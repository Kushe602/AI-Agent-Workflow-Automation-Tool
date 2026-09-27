"""Test fixtures. Environment is configured before any app import so settings,
the async engine, and the fake agent are all wired for an isolated test run.
"""
import os
import pathlib
import tempfile

_TMP = tempfile.mkdtemp(prefix="agentflow-test-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(pathlib.Path(_TMP) / 'test.db').as_posix()}"
os.environ["USE_FAKE_AGENT"] = "1"
os.environ["LLM_API_KEY"] = ""
os.environ["WORKSPACE_ROOT"] = str(pathlib.Path(_TMP) / "workspaces")
os.environ["SECRET_KEY"] = "test-secret-key-0123456789abcdef0123456789"

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import Base, engine
from app.main import app


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client
