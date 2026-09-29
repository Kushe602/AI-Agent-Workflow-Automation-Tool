"""Model abstraction over an OpenAI-compatible chat model, plus a deterministic
offline fake.

Both models expose the same ``stream_turn`` coroutine: it streams assistant text via
the ``on_text`` callback as it arrives and returns a :class:`Turn` describing the full
assistant message (text plus any tool-use requests). The engine works in one internal
format (Anthropic-style content blocks); :class:`OpenAIModel` translates that to and
from the OpenAI Chat Completions wire format, so any OpenAI-compatible provider drives
the same loop without changing the engine.
"""
from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.agent.prompts import SYSTEM_PROMPT
from app.config import settings

OnText = Callable[[str], Awaitable[None]]


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict


@dataclass
class Turn:
    text: str
    tool_uses: list[ToolUse]
    stop_reason: str


class BaseModel:
    async def stream_turn(
        self, messages: list[dict], tools: list[dict], on_text: OnText
    ) -> Turn:
        raise NotImplementedError


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """Anthropic-style tool schemas -> OpenAI function-tool schemas."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for tool in tools
    ]


def _parse_args(raw: str) -> dict:
    """Parse streamed tool-call argument JSON into a dict, defensively."""
    raw = raw.strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """Anthropic-style content-block messages -> OpenAI chat messages: the system
    prompt leads, tool_use -> assistant tool_calls, tool_result -> role="tool"."""
    out: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for message in messages:
        role = message["role"]
        content = message["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text = "".join(
                block["text"]
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            tool_calls = [
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {})),
                    },
                }
                for block in content
                if isinstance(block, dict) and block.get("type") == "tool_use"
            ]
            msg: dict = {"role": "assistant", "content": text or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
        else:
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": str(block.get("content", "")),
                        }
                    )
                elif block.get("type") == "text":
                    out.append({"role": "user", "content": block.get("text", "")})
    return out


class OpenAIModel(BaseModel):
    """Real tool-using turns via any OpenAI-compatible Chat Completions API."""

    def __init__(self) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key, base_url=settings.llm_base_url
        )

    async def stream_turn(
        self, messages: list[dict], tools: list[dict], on_text: OnText
    ) -> Turn:
        stream = await self._client.chat.completions.create(
            model=settings.llm_model,
            max_tokens=settings.max_tokens,
            messages=_to_openai_messages(messages),
            tools=_to_openai_tools(tools) or None,
            stream=True,
        )
        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        stop_reason = ""
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.delta.content:
                text_parts.append(choice.delta.content)
                await on_text(choice.delta.content)
            for tc in choice.delta.tool_calls or []:
                slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments
            if choice.finish_reason:
                stop_reason = choice.finish_reason
        tool_uses = [
            ToolUse(
                id=slot["id"] or f"call_{i}",
                name=slot["name"],
                input=_parse_args(slot["args"]),
            )
            for i, slot in sorted(calls.items())
        ]
        return Turn(
            text="".join(text_parts),
            tool_uses=tool_uses,
            stop_reason="tool_use" if tool_uses else (stop_reason or "end_turn"),
        )


class FakeModel(BaseModel):
    """Deterministic, offline stand-in that still exercises the full tool loop.

    On the first turn it picks a tool based on the goal; after a tool result comes
    back it produces a final answer that references the result. This lets the whole
    engine, persistence and streaming path run in tests and demos with no API key.
    """

    _MATH_RE = re.compile(r"[-+*/().\d\s%]+")
    _URL_RE = re.compile(r"https?://\S+")
    _UNIT_RE = re.compile(
        r"convert\s+(-?\d+(?:\.\d+)?)\s*([a-zA-Z°]+)\s+(?:to|into)\s+([a-zA-Z°]+)",
        re.IGNORECASE,
    )
    _COUNT_RE = re.compile(r"(\d+)\s+(?:uuid|guid)")
    _JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
    _JSON_PATH_RE = re.compile(r"[A-Za-z_]\w*(?:(?:\.\w+)|(?:\[\d+\]))+")

    async def stream_turn(
        self, messages: list[dict], tools: list[dict], on_text: OnText
    ) -> Turn:
        used_tool = any(
            isinstance(message.get("content"), list)
            and any(
                isinstance(block, dict) and block.get("type") == "tool_result"
                for block in message["content"]
            )
            for message in messages
        )
        goal = self._first_user_text(messages)
        if not used_tool:
            available = {tool.get("name") for tool in tools}
            tool_use = self._pick_tool(goal, available)
            if tool_use is not None:
                plan = (
                    f"Plan: I'll use the {tool_use.name} tool to make progress, "
                    "then report the result."
                )
                await self._emit(on_text, plan)
                return Turn(text=plan, tool_uses=[tool_use], stop_reason="tool_use")

        answer = self._final_answer(messages, goal)
        await self._emit(on_text, answer)
        return Turn(text=answer, tool_uses=[], stop_reason="end_turn")

    def _pick_tool(self, goal: str, available: set) -> ToolUse | None:
        """Choose a tool for the goal, but only one the run actually enabled."""
        candidate = self._candidate(goal)
        if candidate is not None and candidate.name in available:
            return candidate
        return None

    def _candidate(self, goal: str) -> ToolUse | None:
        low = goal.lower()
        url_match = self._URL_RE.search(goal)
        if url_match or any(k in low for k in ("fetch", "http", "website", "url")):
            url = url_match.group(0).rstrip(".,)") if url_match else "https://example.com"
            return ToolUse(id="fake_web", name="web_fetch", input={"url": url})
        if any(k in low for k in ("time", "date", "today", "now", "clock")):
            return ToolUse(id="fake_dt", name="current_datetime", input={})
        if "uuid" in low or "guid" in low:
            count_match = self._COUNT_RE.search(low)
            count = max(1, min(int(count_match.group(1)), 100)) if count_match else 1
            return ToolUse(id="fake_uuid", name="uuid_generate", input={"count": count})
        unit_match = self._UNIT_RE.search(goal)
        if unit_match:
            value, from_unit, to_unit = unit_match.groups()
            return ToolUse(
                id="fake_unit",
                name="unit_convert",
                input={"value": float(value), "from": from_unit, "to": to_unit},
            )
        if ("word" in low and "count" in low) or any(
            k in low for k in ("text stat", "statistics", "word frequency")
        ):
            return ToolUse(id="fake_stats", name="text_stats", input={"text": goal})
        if "json" in low:
            block = self._JSON_BLOCK_RE.search(goal)
            path = self._JSON_PATH_RE.search(goal)
            if block and path:
                return ToolUse(
                    id="fake_json",
                    name="json_query",
                    input={"json": block.group(0), "path": path.group(0)},
                )
        if any(k in low for k in ("file", "save", "write", "note")):
            return ToolUse(
                id="fake_file",
                name="write_file",
                input={"path": "note.txt", "content": goal},
            )
        for expr in sorted(
            (match.group(0).strip() for match in self._MATH_RE.finditer(goal)),
            key=len,
            reverse=True,
        ):
            if any(ch.isdigit() for ch in expr) and any(op in expr for op in "+-*/%"):
                return ToolUse(id="fake_calc", name="calculator", input={"expression": expr})
        return None

    def _final_answer(self, messages: list[dict], goal: str) -> str:
        last_result = self._last_tool_result(messages)
        if last_result is not None:
            return f"Done. The tool returned: {last_result}"
        return f"Here is my answer to your request: {goal}"

    @staticmethod
    def _first_user_text(messages: list[dict]) -> str:
        for message in messages:
            if message["role"] == "user":
                content = message["content"]
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    if parts:
                        return " ".join(parts)
        return ""

    @staticmethod
    def _last_tool_result(messages: list[dict]) -> str | None:
        for message in reversed(messages):
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        return str(block.get("content", ""))
        return None

    @staticmethod
    async def _emit(on_text: OnText, text: str) -> None:
        # Emit in small chunks so token-streaming code paths are exercised.
        for start in range(0, len(text), 8):
            await on_text(text[start : start + 8])


def get_model() -> BaseModel:
    if settings.agent_enabled:
        return OpenAIModel()
    return FakeModel()
