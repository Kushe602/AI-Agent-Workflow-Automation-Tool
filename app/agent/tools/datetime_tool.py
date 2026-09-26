"""Report the current UTC date and time."""
from datetime import UTC, datetime

from app.agent.tools.base import Tool, ToolContext


async def _run(tool_input: dict, ctx: ToolContext) -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


current_datetime_tool = Tool(
    name="current_datetime",
    description="Get the current date and time in UTC, as an ISO 8601 string.",
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    handler=_run,
)
