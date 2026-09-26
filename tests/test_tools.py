"""Unit tests for the agent's tools: calculator safety, file sandboxing, SSRF guards."""
from pathlib import Path

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.calculator import CalculatorError, calculator_tool, evaluate
from app.agent.tools.files import list_files_tool, read_file_tool, write_file_tool
from app.agent.tools.web_fetch import web_fetch_tool


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(run_id="test", workspace=tmp_path / "ws")


def test_calculator_evaluates_expressions():
    assert evaluate("2 + 3 * 4") == 14
    assert evaluate("(2 + 3) * 4") == 20
    assert evaluate("2 ** 10") == 1024
    assert evaluate("17 % 5") == 2
    assert evaluate("7 // 2") == 3


def test_calculator_rejects_names_and_calls():
    with pytest.raises(CalculatorError):
        evaluate("__import__('os').system('echo hi')")
    with pytest.raises(CalculatorError):
        evaluate("pow(2, 3)")


def test_calculator_rejects_huge_exponent():
    with pytest.raises(CalculatorError):
        evaluate("10 ** 1000")


async def test_calculator_tool_run(tmp_path):
    ctx = _ctx(tmp_path)
    assert await calculator_tool.run({"expression": "21 * 2"}, ctx) == "42"
    assert "division by zero" in await calculator_tool.run({"expression": "1/0"}, ctx)
    assert "Error" in await calculator_tool.run({"expression": "a + 1"}, ctx)


async def test_file_tools_roundtrip(tmp_path):
    ctx = _ctx(tmp_path)
    assert "Wrote" in await write_file_tool.run(
        {"path": "notes/hello.txt", "content": "hi there"}, ctx
    )
    assert await read_file_tool.run({"path": "notes/hello.txt"}, ctx) == "hi there"
    assert "notes/hello.txt" in await list_files_tool.run({}, ctx)


async def test_file_tools_block_traversal(tmp_path):
    ctx = _ctx(tmp_path)
    assert "escapes the workspace" in await write_file_tool.run(
        {"path": "../escape.txt", "content": "x"}, ctx
    )
    assert "Error" in await read_file_tool.run({"path": "../../etc/passwd"}, ctx)


async def test_web_fetch_blocks_non_http(tmp_path):
    ctx = _ctx(tmp_path)
    assert "http and https" in await web_fetch_tool.run({"url": "ftp://example.com"}, ctx)


async def test_web_fetch_blocks_local_addresses(tmp_path):
    ctx = _ctx(tmp_path)
    for url in (
        "http://127.0.0.1/",
        "http://localhost:8000/",
        "http://169.254.169.254/latest/meta-data/",
    ):
        assert "Error" in await web_fetch_tool.run({"url": url}, ctx)
