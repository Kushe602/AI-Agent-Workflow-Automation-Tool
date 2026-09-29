"""Unit tests for the agent's tools: calculator safety, file sandboxing, SSRF guards."""
import re
from pathlib import Path

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.calculator import CalculatorError, calculator_tool, evaluate
from app.agent.tools.files import list_files_tool, list_workspace, read_file_tool, write_file_tool
from app.agent.tools.json_query import json_query_tool
from app.agent.tools.text_stats import text_stats_tool
from app.agent.tools.unit_convert import convert, unit_convert_tool
from app.agent.tools.uuid_generate import uuid_generate_tool
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


_DOC = '{"user": {"name": "Ada", "tags": ["x", "y"]}, "items": [10, 20, 30]}'


async def test_json_query_extracts_by_path(tmp_path):
    ctx = _ctx(tmp_path)
    assert await json_query_tool.run({"json": _DOC, "path": "user.name"}, ctx) == "Ada"
    assert await json_query_tool.run({"json": _DOC, "path": "user.tags[1]"}, ctx) == "y"
    # Bare numeric segments index into lists too, and negative indices work.
    assert await json_query_tool.run({"json": _DOC, "path": "items.0"}, ctx) == "10"
    assert await json_query_tool.run({"json": _DOC, "path": "items[-1]"}, ctx) == "30"


async def test_json_query_reports_errors(tmp_path):
    ctx = _ctx(tmp_path)
    assert "invalid JSON" in await json_query_tool.run({"json": "{oops", "path": "a"}, ctx)
    assert "key not found" in await json_query_tool.run({"json": _DOC, "path": "user.age"}, ctx)
    assert "out of range" in await json_query_tool.run({"json": _DOC, "path": "items[9]"}, ctx)
    assert "no path" in await json_query_tool.run({"json": _DOC, "path": ""}, ctx)


async def test_text_stats_counts_words_and_top(tmp_path):
    ctx = _ctx(tmp_path)
    out = await text_stats_tool.run(
        {"text": "the cat sat on the mat the cat", "top_n": 2}, ctx
    )
    assert "words: 8" in out
    assert "unique words: 5" in out
    assert "the (3)" in out and "cat (2)" in out
    assert "Error" in await text_stats_tool.run({"text": "   "}, ctx)


def test_unit_convert_math():
    assert round(convert(100, "km", "mi"), 4) == 62.1371
    assert convert(1, "kg", "g") == 1000
    assert convert(100, "C", "F") == 212
    assert convert(0, "C", "K") == 273.15


async def test_unit_convert_tool_and_errors(tmp_path):
    ctx = _ctx(tmp_path)
    out = await unit_convert_tool.run({"value": 1, "from": "kg", "to": "g"}, ctx)
    assert out == "1 kg = 1000 g"
    assert "cannot convert" in await unit_convert_tool.run(
        {"value": 1, "from": "kg", "to": "m"}, ctx
    )
    assert "unknown unit" in await unit_convert_tool.run(
        {"value": 1, "from": "kg", "to": "blorp"}, ctx
    )
    assert "must be a number" in await unit_convert_tool.run(
        {"value": "abc", "from": "kg", "to": "g"}, ctx
    )


async def test_uuid_generate_count_and_format(tmp_path):
    ctx = _ctx(tmp_path)
    out = await uuid_generate_tool.run({"count": 3}, ctx)
    lines = out.splitlines()
    assert len(lines) == 3
    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    assert all(uuid_re.match(line) for line in lines)
    assert "at least 1" in await uuid_generate_tool.run({"count": 0}, ctx)


async def test_list_workspace_reports_files(tmp_path):
    ctx = _ctx(tmp_path)
    await write_file_tool.run({"path": "a/b.txt", "content": "hello"}, ctx)
    files = list_workspace(ctx.workspace)
    assert files == [{"path": "a/b.txt", "size": 5}]
