"""End-to-end tests of the agent loop using the deterministic fake model."""
import json

from sqlalchemy import select

from app.agent.engine import run_agent
from app.database import SessionLocal
from app.models import Run, Step, User


async def _make_run(goal: str) -> str:
    async with SessionLocal() as db:
        user = User(email="agent@test.dev", hashed_password="x")
        db.add(user)
        await db.commit()
        run = Run(owner_id=user.id, goal=goal)
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
