"""Generate one or more random version-4 UUIDs. Bounded count, no eval."""
import uuid

from app.agent.tools.base import Tool, ToolContext

_MAX_COUNT = 100


async def _run(tool_input: dict, ctx: ToolContext) -> str:
    try:
        count = int(tool_input.get("count", 1))
    except (TypeError, ValueError):
        return "Error: count must be an integer."
    if count < 1:
        return "Error: count must be at least 1."
    count = min(count, _MAX_COUNT)
    return "\n".join(str(uuid.uuid4()) for _ in range(count))


uuid_generate_tool = Tool(
    name="uuid_generate",
    description="Generate one or more random version-4 UUIDs (up to 100).",
    input_schema={
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "How many UUIDs to generate (1-100, default 1).",
            },
        },
    },
    handler=_run,
)
