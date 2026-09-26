"""Model abstraction over Anthropic Claude, plus a deterministic offline fake.

Both models expose the same ``stream_turn`` coroutine: it streams assistant text via
the ``on_text`` callback as it arrives and returns a :class:`Turn` describing the full
assistant message (text plus any tool-use requests). The engine stays provider-agnostic.
"""
from __future__ import annotations

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


class ClaudeModel(BaseModel):
    """Real tool-using turns via the Anthropic streaming Messages API."""

    def __init__(self) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def stream_turn(
        self, messages: list[dict], tools: list[dict], on_text: OnText
    ) -> Turn:
        async with self._client.messages.stream(
            model=settings.chat_model,
            max_tokens=settings.max_tokens,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        ) as stream:
            async for delta in stream.text_stream:
                await on_text(delta)
            final = await stream.get_final_message()

        text = "".join(
            block.text for block in final.content if getattr(block, "type", None) == "text"
        )
        tool_uses = [
            ToolUse(id=block.id, name=block.name, input=dict(block.input))
            for block in final.content
            if getattr(block, "type", None) == "tool_use"
        ]
        return Turn(text=text, tool_uses=tool_uses, stop_reason=final.stop_reason or "")


class FakeModel(BaseModel):
    """Deterministic, offline stand-in that still exercises the full tool loop.

    On the first turn it picks a tool based on the goal; after a tool result comes
    back it produces a final answer that references the result. This lets the whole
    engine, persistence and streaming path run in tests and demos with no API key.
    """

    _MATH_RE = re.compile(r"[-+*/().\d\s%]+")
    _URL_RE = re.compile(r"https?://\S+")

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
            tool_use = self._pick_tool(goal)
            if tool_use is not None:
                text = "On it — let me use a tool to help with that."
                await self._emit(on_text, text)
                return Turn(text=text, tool_uses=[tool_use], stop_reason="tool_use")

        answer = self._final_answer(messages, goal)
        await self._emit(on_text, answer)
        return Turn(text=answer, tool_uses=[], stop_reason="end_turn")

    def _pick_tool(self, goal: str) -> ToolUse | None:
        low = goal.lower()
        url_match = self._URL_RE.search(goal)
        if url_match or any(k in low for k in ("fetch", "http", "website", "url")):
            url = url_match.group(0).rstrip(".,)") if url_match else "https://example.com"
            return ToolUse(id="fake_web", name="web_fetch", input={"url": url})
        if any(k in low for k in ("time", "date", "today", "now", "clock")):
            return ToolUse(id="fake_dt", name="current_datetime", input={})
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
        return ClaudeModel()
    return FakeModel()
