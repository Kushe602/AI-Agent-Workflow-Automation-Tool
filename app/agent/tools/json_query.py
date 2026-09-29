"""Extract a value from a JSON document by key path — pure parsing, no eval.

The path is dot-separated with optional bracket indices: ``a.b[0].c`` and
``a.b.0.c`` are equivalent. List positions accept negative indices. Input size and
path depth are bounded so a huge document or path can't be used to exhaust memory.
"""
import json
import re

from app.agent.tools.base import Tool, ToolContext

_MAX_JSON_CHARS = 200_000
_MAX_PATH_TOKENS = 100
_BRACKET_RE = re.compile(r"\[(-?\d+)\]")
_PART_RE = re.compile(r"^([^\[\]]*)((?:\[-?\d+\])*)$")


def _tokenize(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    for part in path.split("."):
        if not part:
            continue
        match = _PART_RE.match(part)
        if match is None:
            raise ValueError(f"malformed path segment: {part!r}")
        key, brackets = match.group(1), match.group(2)
        if key:
            tokens.append(key)
        for idx in _BRACKET_RE.findall(brackets):
            tokens.append(int(idx))
    return tokens


def query(document: str, path: str) -> object:
    """Return the value at ``path`` within the JSON ``document``."""
    if len(document) > _MAX_JSON_CHARS:
        raise ValueError(f"JSON exceeds the {_MAX_JSON_CHARS}-character limit")
    try:
        data: object = json.loads(document)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    tokens = _tokenize(path)
    if not tokens:
        raise ValueError("no path provided")
    if len(tokens) > _MAX_PATH_TOKENS:
        raise ValueError("path is too deep")

    current = data
    walked: list[str] = []
    for token in tokens:
        walked.append(str(token))
        here = ".".join(walked)
        if isinstance(current, list):
            try:
                index = int(token)
            except (TypeError, ValueError):
                raise ValueError(f"expected a list index at {here}") from None
            if not -len(current) <= index < len(current):
                raise ValueError(f"list index out of range at {here}")
            current = current[index]
        elif isinstance(current, dict):
            key = str(token)
            if key not in current:
                raise ValueError(f"key not found at {here}")
            current = current[key]
        else:
            raise ValueError(f"cannot index into a scalar at {here}")
    return current


async def _run(tool_input: dict, ctx: ToolContext) -> str:
    document = str(tool_input.get("json", "")).strip()
    path = str(tool_input.get("path", "")).strip()
    if not document:
        return "Error: no json provided."
    if not path:
        return "Error: no path provided."
    try:
        result = query(document, path)
    except ValueError as exc:
        return f"Error: {exc}"
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)


json_query_tool = Tool(
    name="json_query",
    description=(
        "Extract a value from a JSON document by key path. The path is dot-separated "
        "with optional list indices, e.g. 'user.name' or 'items[0].id'. Returns the "
        "value found, serialized as JSON."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "json": {"type": "string", "description": "The JSON document to query."},
            "path": {
                "type": "string",
                "description": "Dot/bracket key path, e.g. 'a.b[0].c'.",
            },
        },
        "required": ["json", "path"],
    },
    handler=_run,
)
