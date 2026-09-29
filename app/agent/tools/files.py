"""Sandboxed file tools, scoped to a per-run workspace directory.

All paths are resolved inside ``ctx.workspace``; anything that escapes it (via ``..``
or an absolute path) is refused, so the agent can only touch its own scratch space.
"""
from pathlib import Path

from app.agent.tools.base import Tool, ToolContext

_MAX_READ_CHARS = 20_000
_MAX_WRITE_CHARS = 100_000


def safe_path(workspace: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``workspace``, refusing anything that escapes it.

    Shared by the file tools and the run artifacts browser so both enforce the same
    path-traversal guard. Raises ``ValueError`` for escapes or the workspace root.
    """
    workspace = workspace.resolve()
    candidate = (workspace / rel).resolve()
    if not candidate.is_relative_to(workspace):
        raise ValueError("path escapes the workspace")
    if candidate == workspace:
        raise ValueError("a file path is required, not the workspace root")
    return candidate


def list_workspace(workspace: Path) -> list[dict]:
    """List every file under ``workspace`` as ``{"path", "size"}``, sorted by path."""
    workspace = workspace.resolve()
    if not workspace.exists():
        return []
    return [
        {"path": p.relative_to(workspace).as_posix(), "size": p.stat().st_size}
        for p in sorted(workspace.rglob("*"))
        if p.is_file()
    ]


def _resolve(ctx: ToolContext, rel: str) -> Path:
    workspace = ctx.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return safe_path(workspace, rel)


async def _write(tool_input: dict, ctx: ToolContext) -> str:
    rel = str(tool_input.get("path", "")).strip()
    content = tool_input.get("content", "")
    if not rel:
        return "Error: no path provided."
    if not isinstance(content, str):
        content = str(content)
    if len(content) > _MAX_WRITE_CHARS:
        return f"Error: content exceeds the {_MAX_WRITE_CHARS}-character limit."
    try:
        path = _resolve(ctx, rel)
    except ValueError as exc:
        return f"Error: {exc}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {rel}."


async def _read(tool_input: dict, ctx: ToolContext) -> str:
    rel = str(tool_input.get("path", "")).strip()
    if not rel:
        return "Error: no path provided."
    try:
        path = _resolve(ctx, rel)
    except ValueError as exc:
        return f"Error: {exc}"
    if not path.is_file():
        return f"Error: file not found: {rel}."
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) > _MAX_READ_CHARS:
        return data[:_MAX_READ_CHARS] + "\n... (truncated)"
    return data


async def _list(tool_input: dict, ctx: ToolContext) -> str:
    workspace = ctx.workspace.resolve()
    if not workspace.exists():
        return "(workspace is empty)"
    entries = sorted(
        p.relative_to(workspace).as_posix() + ("/" if p.is_dir() else "")
        for p in workspace.rglob("*")
    )
    return "\n".join(entries) if entries else "(workspace is empty)"


write_file_tool = Tool(
    name="write_file",
    description="Create or overwrite a text file in the run's workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path, e.g. 'notes.txt'."},
            "content": {"type": "string", "description": "The text to write."},
        },
        "required": ["path", "content"],
    },
    handler=_write,
)

read_file_tool = Tool(
    name="read_file",
    description="Read a text file previously written in the run's workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path to read."},
        },
        "required": ["path"],
    },
    handler=_read,
)

list_files_tool = Tool(
    name="list_files",
    description="List all files currently in the run's workspace.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    handler=_list,
)
