"""End-to-end tests of the agent loop using the deterministic fake model."""
import json
import re

from sqlalchemy import select

from app.agent.engine import run_agent
from app.agent.events import broker
from app.database import SessionLocal
from app.models import Run, Step, User, _uuid


async def _make_run(goal: str, tools: list[str] | None = None) -> str:
    async with SessionLocal() as db:
        user = User(email=f"agent-{_uuid()}@test.dev", hashed_password="x")
        db.add(user)
        await db.commit()
        run = Run(owner_id=user.id, goal=goal, tools=json.dumps(tools) if tools else None)
        db.add(run)
        await db.commit()
        return run.id


async def _steps(run_id: str) -> list[Step]:
    async with SessionLocal() as db:
        result = await db.execute(select(Step).where(Step.run_id == run_id).order_by(Step.idx))
        return list(result.scalars().all())


async def test_agent_runs_calculator_end_to_end():
    run_id = await _make_run("What is 21 * 2?")
    await run_agent(run_id)

    async with SessionLocal() as db:
        run = await db.get(Run, run_id)
    assert run.status == "succeeded"

    steps = await _steps(run_id)
    types = [s.type for s in steps]
    assert "tool_call" in types
    assert "tool_result" in types
    assert types[-1] == "final"

    call = next(s for s in steps if s.type == "tool_call")
    assert call.name == "calculator"
    assert json.loads(call.tool_input)["expression"] == "21 * 2"

    result = next(s for s in steps if s.type == "tool_result")
    assert "42" in result.content
    assert "42" in steps[-1].content


async def test_agent_answers_without_tools():
    run_id = await _make_run("Please introduce yourself briefly")
    await run_agent(run_id)

    async with SessionLocal() as db:
        run = await db.get(Run, run_id)
    assert run.status == "succeeded"
    assert [s.type for s in await _steps(run_id)] == ["final"]


async def test_agent_uses_new_tool_end_to_end():
    run_id = await _make_run("Please generate a uuid for me")
    await run_agent(run_id)

    async with SessionLocal() as db:
        run = await db.get(Run, run_id)
    assert run.status == "succeeded"

    steps = await _steps(run_id)
    call = next(s for s in steps if s.type == "tool_call")
    assert call.name == "uuid_generate"

    result = next(s for s in steps if s.type == "tool_result")
    assert re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}", result.content)
    assert steps[-1].type == "final"


async def test_tool_selection_allows_the_chosen_tool():
    run_id = await _make_run("What is 21 * 2?", tools=["calculator"])
    await run_agent(run_id)

    steps = await _steps(run_id)
    assert any(s.type == "tool_call" and s.name == "calculator" for s in steps)
    assert "42" in steps[-1].content


async def test_tool_selection_hides_unselected_tools():
    # A math goal would normally call the calculator, but it is not enabled here,
    # so the fake model is never offered it and answers directly instead.
    run_id = await _make_run("What is 21 * 2?", tools=["current_datetime"])
    await run_agent(run_id)

    async with SessionLocal() as db:
        run = await db.get(Run, run_id)
    assert run.status == "succeeded"

    steps = await _steps(run_id)
    assert all(s.name != "calculator" for s in steps)
    assert [s.type for s in steps] == ["final"]


async def test_agent_can_be_cancelled():
    run_id = await _make_run("What is 21 * 2?")
    broker.request_stop(run_id)
    await run_agent(run_id)

    async with SessionLocal() as db:
        run = await db.get(Run, run_id)
    assert run.status == "cancelled"
    assert await _steps(run_id) == []
