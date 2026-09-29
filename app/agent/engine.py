"""The agent loop: drive the model, run tools, and persist + stream every step.

``run_agent`` runs as a background task with its own DB session. For each turn it
streams assistant text, and if the model requests tools it runs them (each with a
timeout), feeds the results back, and loops — until the model answers, a stop is
requested, or the iteration cap is hit. Every step is written to the database and
published to the broker so live SSE subscribers and later page loads agree.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.agent.events import broker
from app.agent.models import ToolUse, Turn, get_model
from app.agent.tools import registry
from app.agent.tools.base import ToolContext
from app.config import settings
from app.database import SessionLocal
from app.models import Run, Step, _uuid

_EVICT_AFTER_SECONDS = 30
_background: set[asyncio.Task] = set()


def start_run(run_id: str) -> None:
    """Launch the agent loop for a run as a tracked background task."""
    task = asyncio.create_task(run_agent(run_id))
    _background.add(task)
    task.add_done_callback(_background.discard)


def _make_on_text(run_id: str, step_id: str, idx: int, state: dict):
    async def on_text(delta: str) -> None:
        if not state["open"]:
            state["open"] = True
            await broker.publish(
                run_id,
                {"event": "step_open", "id": step_id, "idx": idx, "type": "text"},
            )
        await broker.publish(run_id, {"event": "delta", "id": step_id, "text": delta})

    return on_text


async def _persist_step(
    db, run_id: str, idx: int, type_: str, name: str | None, content: str, tool_input: str | None
) -> None:
    db.add(
        Step(
            run_id=run_id,
            idx=idx,
            type=type_,
            name=name,
            content=content or "",
            tool_input=tool_input,
        )
    )
    await db.commit()


async def _run_tool(tool_use: ToolUse, ctx: ToolContext) -> str:
    tool = registry.get(tool_use.name)
    if tool is None:
        return f"Error: unknown tool '{tool_use.name}'."
    try:
        return await asyncio.wait_for(
            tool.run(tool_use.input, ctx), timeout=settings.tool_timeout_seconds
        )
    except TimeoutError:
        return f"Error: tool '{tool_use.name}' timed out after {settings.tool_timeout_seconds}s."
    except Exception as exc:  # tool failures are fed back to the model, not fatal
        return f"Error: {type(exc).__name__}: {exc}"


async def _finish(db, run: Run, run_id: str, status: str, error: str | None) -> None:
    run.status = status
    run.error = error
    await db.commit()
    await broker.publish(run_id, {"event": "status", "status": status})
    await broker.publish(run_id, {"event": "done", "status": status, "error": error})
    broker.close(run_id)
    asyncio.get_running_loop().call_later(_EVICT_AFTER_SECONDS, broker.evict, run_id)


def enabled_tool_names(run: Run) -> list[str] | None:
    """The tools enabled for this run, or ``None`` when every tool is enabled.

    ``Run.tools`` holds a JSON array chosen at creation time; unknown names are
    dropped and an empty/blank/invalid value means "all tools".
    """
    if not run.tools:
        return None
    try:
        selected = json.loads(run.tools)
    except (ValueError, TypeError):
        return None
    if not isinstance(selected, list):
        return None
    wanted = {name for name in selected if isinstance(name, str)}
    valid = [name for name in registry.names() if name in wanted]
    return valid or None


async def run_agent(run_id: str) -> None:
    async with SessionLocal() as db:
        run = await db.get(Run, run_id)
        if run is None:
            return

        run.status = "running"
        run.model = settings.llm_model if settings.agent_enabled else "fake"
        await db.commit()
        await broker.publish(run_id, {"event": "status", "status": "running"})

        model = get_model()
        ctx = ToolContext(run_id=run_id, workspace=Path(settings.workspace_root) / run_id)
        enabled = enabled_tool_names(run)  # None => every tool is enabled
        enabled_set = set(enabled) if enabled is not None else None
        tool_schemas = registry.schemas(enabled)
        messages: list[dict] = [{"role": "user", "content": run.goal}]
        idx = 0

        try:
            for _iteration in range(settings.max_iterations):
                if broker.is_stopped(run_id):
                    await _finish(db, run, run_id, "cancelled", None)
                    return

                step_id = _uuid()
                state = {"open": False}
                on_text = _make_on_text(run_id, step_id, idx, state)
                turn: Turn = await model.stream_turn(messages, tool_schemas, on_text)

                step_type = "thinking" if turn.tool_uses else "final"
                if turn.text.strip() or state["open"]:
                    await _persist_step(db, run_id, idx, step_type, None, turn.text, None)
                    if not state["open"]:
                        await broker.publish(
                            run_id,
                            {"event": "step_open", "id": step_id, "idx": idx, "type": "text"},
                        )
                        await broker.publish(
                            run_id, {"event": "delta", "id": step_id, "text": turn.text}
                        )
                    await broker.publish(
                        run_id,
                        {
                            "event": "step_close",
                            "id": step_id,
                            "idx": idx,
                            "type": step_type,
                            "content": turn.text,
                        },
                    )
                    idx += 1

                if not turn.tool_uses:
                    await _finish(db, run, run_id, "succeeded", None)
                    return

                assistant_content: list[dict] = []
                if turn.text.strip():
                    assistant_content.append({"type": "text", "text": turn.text})
                for tool_use in turn.tool_uses:
                    assistant_content.append(
                        {
                            "type": "tool_use",
                            "id": tool_use.id,
                            "name": tool_use.name,
                            "input": tool_use.input,
                        }
                    )
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results: list[dict] = []
                for tool_use in turn.tool_uses:
                    if broker.is_stopped(run_id):
                        await _finish(db, run, run_id, "cancelled", None)
                        return
                    input_json = json.dumps(tool_use.input, ensure_ascii=False)
                    await _persist_step(db, run_id, idx, "tool_call", tool_use.name, "", input_json)
                    await broker.publish(
                        run_id,
                        {
                            "event": "step",
                            "idx": idx,
                            "type": "tool_call",
                            "name": tool_use.name,
                            "content": "",
                            "tool_input": input_json,
                        },
                    )
                    idx += 1

                    if enabled_set is not None and tool_use.name not in enabled_set:
                        result = f"Error: tool '{tool_use.name}' is not enabled for this run."
                    else:
                        result = await _run_tool(tool_use, ctx)
                    await _persist_step(db, run_id, idx, "tool_result", tool_use.name, result, None)
                    await broker.publish(
                        run_id,
                        {
                            "event": "step",
                            "idx": idx,
                            "type": "tool_result",
                            "name": tool_use.name,
                            "content": result,
                            "tool_input": None,
                        },
                    )
                    idx += 1
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": result,
                        }
                    )

                messages.append({"role": "user", "content": tool_results})

            await _finish(
                db,
                run,
                run_id,
                "failed",
                f"Reached the maximum of {settings.max_iterations} iterations "
                "without producing a final answer.",
            )
        except Exception as exc:  # surface any engine/model error as a failed run
            detail = f"{type(exc).__name__}: {exc}"
            await _persist_step(db, run_id, idx, "error", None, detail, None)
            await broker.publish(
                run_id,
                {"event": "step", "idx": idx, "type": "error", "name": None, "content": detail},
            )
            await _finish(db, run, run_id, "failed", detail)
