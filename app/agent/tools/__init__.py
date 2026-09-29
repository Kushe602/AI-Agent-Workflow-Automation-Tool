"""The tool registry: every tool the agent is allowed to call, in one place."""
from app.agent.tools.base import Tool, ToolContext, ToolRegistry
from app.agent.tools.calculator import calculator_tool
from app.agent.tools.datetime_tool import current_datetime_tool
from app.agent.tools.files import list_files_tool, read_file_tool, write_file_tool
from app.agent.tools.json_query import json_query_tool
from app.agent.tools.text_stats import text_stats_tool
from app.agent.tools.unit_convert import unit_convert_tool
from app.agent.tools.uuid_generate import uuid_generate_tool
from app.agent.tools.web_fetch import web_fetch_tool

registry = ToolRegistry()
for _tool in (
    calculator_tool,
    current_datetime_tool,
    web_fetch_tool,
    write_file_tool,
    read_file_tool,
    list_files_tool,
    json_query_tool,
    text_stats_tool,
    unit_convert_tool,
    uuid_generate_tool,
):
    registry.register(_tool)

__all__ = ["Tool", "ToolContext", "ToolRegistry", "registry"]
