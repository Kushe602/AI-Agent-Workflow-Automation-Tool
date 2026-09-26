"""Agent runs: create a run, watch it stream live over SSE, stop it, view history."""
import asyncio
import json

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.engine import start_run
from app.agent.events import broker
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Run, Step, User
from app.web import templates

router = APIRouter(tags=["runs"])
_TERMINAL = {"succeeded", "failed", "stopped"}
_KEEPALIVE_SECONDS = 15.0


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


@router.post("/runs")
async def create_run(
    goal: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    goal = goal.strip()
    if not goal:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    run = Run(owner_id=user.id, goal=goal, status="pending")
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
    return templates.TemplateResponse(
        request, "run.html", {"run": run, "steps": steps, "live": live}
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
