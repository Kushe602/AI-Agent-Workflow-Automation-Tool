"""Agent runs: create a run, watch it stream live over SSE, stop it, browse the
files it wrote, export it to Markdown, and view history."""
import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request, Response, status
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.engine import enabled_tool_names, start_run
from app.agent.events import broker
from app.agent.tools import registry
from app.agent.tools.files import list_workspace, safe_path
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Run, Step, User
from app.web import templates

router = APIRouter(tags=["runs"])
_TERMINAL = {"succeeded", "failed", "cancelled"}
_KEEPALIVE_SECONDS = 15.0


def _workspace(run_id: str) -> Path:
    return Path(settings.workspace_root) / run_id


def _sse(event: dict) -> str:
    name = event.get("event", "message")
    return f"event: {name}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _owned_run(db: AsyncSession, run_id: str, user_id: str) -> Run | None:
    run = await db.get(Run, run_id)
    if run is None or run.owner_id != user_id:
        return None
    return run


async def _steps(db: AsyncSession, run_id: str) -> list[Step]:
    result = await db.execute(select(Step).where(Step.run_id == run_id).order_by(Step.idx))
    return list(result.scalars().all())


_STEP_HEADINGS = {"thinking": "Reasoning", "final": "Final answer", "error": "Error"}


def _pretty_json(raw: str | None) -> str:
    if not raw:
        return "{}"
    try:
        return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except (ValueError, TypeError):
        return raw


def _run_to_markdown(run: Run, steps: list[Step]) -> str:
    """Render a run and all of its steps as a self-contained Markdown document."""
    tools = enabled_tool_names(run)
    lines = [
        "# AgentFlow run",
        "",
        f"- **Goal:** {run.goal}",
        f"- **Status:** {run.status}",
        f"- **Model:** {run.model or 'n/a'}",
        f"- **Tools enabled:** {'all' if tools is None else ', '.join(tools)}",
        f"- **Created:** {run.created_at:%Y-%m-%d %H:%M:%S} UTC",
    ]
    if run.error:
        lines.append(f"- **Error:** {run.error}")
    lines += ["", "## Steps"]
    if not steps:
        lines += ["", "_No steps were recorded._"]
    for step in steps:
        lines.append("")
        if step.type == "tool_call":
            lines += [f"### Tool call — `{step.name}`", "", "```json"]
            lines += [_pretty_json(step.tool_input), "```"]
        elif step.type == "tool_result":
            lines += [f"### Result — `{step.name}`", "", "```", step.content, "```"]
        else:
            heading = _STEP_HEADINGS.get(step.type, step.type.title())
            lines += [f"### {heading}", "", step.content or "_(empty)_"]
    return "\n".join(lines) + "\n"


@router.post("/runs")
async def create_run(
    goal: str = Form(...),
    tools: list[str] = Form(default=[]),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    goal = goal.strip()
    if not goal:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    # Keep only known tools, in registry order; an empty selection means "all tools".
    selected = [name for name in registry.names() if name in set(tools)]
    tools_json = json.dumps(selected) if selected else None
    run = Run(owner_id=user.id, goal=goal, status="pending", tools=tools_json)
    db.add(run)
    await db.commit()
    start_run(run.id)
    return RedirectResponse(f"/runs/{run.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(
    request: Request,
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _owned_run(db, run_id, user.id)
    if run is None:
        return templates.TemplateResponse(
            request, "not_found.html", {}, status_code=status.HTTP_404_NOT_FOUND
        )
    steps = await _steps(db, run_id)
    live = run.status not in _TERMINAL
    enabled = enabled_tool_names(run)
    return templates.TemplateResponse(
        request,
        "run.html",
        {
            "run": run,
            "steps": steps,
            "live": live,
            "files": list_workspace(_workspace(run_id)),
            "enabled_tools": enabled if enabled is not None else registry.names(),
            "all_tools_enabled": enabled is None,
        },
    )


@router.get("/runs/{run_id}/stream")
async def run_stream(
    request: Request,
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _owned_run(db, run_id, user.id)
    if run is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    # If the run has already finished and its live channel was evicted, replay the
    # persisted steps and close — this handles reconnects and page reloads.
    if run.status in _TERMINAL and not broker.has_channel(run_id):
        steps = await _steps(db, run_id)

        async def replay():
            for step in steps:
                yield _sse(
                    {
                        "event": "step",
                        "idx": step.idx,
                        "type": step.type,
                        "name": step.name,
                        "content": step.content,
                        "tool_input": step.tool_input,
                    }
                )
            yield _sse({"event": "status", "status": run.status})
            yield _sse({"event": "done", "status": run.status, "error": run.error})

        return StreamingResponse(replay(), media_type="text/event-stream")

    async def live():
        past, queue = broker.subscribe(run_id)
        try:
            for event in past:
                yield _sse(event)
            if any(event.get("event") == "done" for event in past):
                return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _sse(event)
                if event.get("event") == "done":
                    return
        finally:
            broker.unsubscribe(run_id, queue)

    return StreamingResponse(
        live(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/stop")
async def stop_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await _owned_run(db, run_id, user.id)
    if run is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    broker.request_stop(run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/runs/{run_id}/files")
async def run_files(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """JSON listing of the files the agent wrote in this run's workspace."""
    run = await _owned_run(db, run_id, user.id)
    if run is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    return {"files": list_workspace(_workspace(run_id))}


@router.get("/runs/{run_id}/files/raw")
async def run_file_raw(
    run_id: str,
    path: str = Query(..., min_length=1),
    download: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """View or download a single workspace file. Path-traversal safe."""
    run = await _owned_run(db, run_id, user.id)
    if run is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    try:
        resolved = safe_path(_workspace(run_id), path)
    except ValueError:
        return PlainTextResponse("Invalid path.", status_code=status.HTTP_400_BAD_REQUEST)
    if not resolved.is_file():
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(
        resolved,
        filename=resolved.name,
        media_type="application/octet-stream" if download else "text/plain; charset=utf-8",
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/runs/{run_id}/export.md")
async def export_run_markdown(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download the whole run — goal, every step, and the final answer — as Markdown."""
    run = await _owned_run(db, run_id, user.id)
    if run is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    steps = await _steps(db, run_id)
    return PlainTextResponse(
        _run_to_markdown(run, steps),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="agentflow-run-{run_id[:8]}.md"'
        },
    )
