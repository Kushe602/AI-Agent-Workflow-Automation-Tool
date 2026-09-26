"""The tool registry: every tool the agent is allowed to call, in one place."""
from app.agent.tools.base import Tool, ToolContext, ToolRegistry
from app.agent.tools.calculator import calculator_tool
from app.agent.tools.datetime_tool import current_datetime_tool
from app.agent.tools.files import list_files_tool, read_file_tool, write_file_tool
from app.agent.tools.web_fetch import web_fetch_tool

registry = ToolRegistry()
for _tool in (
    calculator_tool,
    current_datetime_tool,
    web_fetch_tool,
    write_file_tool,
    read_file_tool,
    list_files_tool,
):
    registry.register(_tool)

__all__ = ["Tool", "ToolContext", "ToolRegistry", "registry"]
