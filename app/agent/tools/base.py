"""Tool base types: the context passed to tools and the registry that holds them."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolContext:
    """Per-run context handed to every tool invocation."""

    run_id: str
    workspace: Path


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict, ToolContext], Awaitable[str]]

    @property
    def schema(self) -> dict:
        """The tool definition in the shape the Anthropic API expects."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    async def run(self, tool_input: dict, ctx: ToolContext) -> str:
        return await self.handler(tool_input, ctx)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __iter__(self):
        return iter(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self, names: Iterable[str] | None = None) -> list[dict]:
        """Tool schemas, optionally filtered to (and ordered by) ``names``.

        With ``names=None`` every registered tool is returned; otherwise only the
        named tools that exist, preserving registration order.
        """
        if names is None:
            return [tool.schema for tool in self._tools.values()]
        allowed = set(names)
        return [tool.schema for tool in self._tools.values() if tool.name in allowed]
