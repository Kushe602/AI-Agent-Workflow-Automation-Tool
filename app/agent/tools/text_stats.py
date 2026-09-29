"""Compute simple statistics for a block of text: character, word and line counts
plus the most frequent words. Pure counting, bounded input, no eval.
"""
import re
from collections import Counter

from app.agent.tools.base import Tool, ToolContext

_MAX_CHARS = 100_000
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _run_sync(text: str, top_n: int) -> str:
    words = _WORD_RE.findall(text.lower())
    counts = Counter(words)
    lines = ["Statistics:"]
    lines.append(f"- characters: {len(text)}")
    lines.append(f"- words: {len(words)}")
    lines.append(f"- unique words: {len(counts)}")
    lines.append(f"- lines: {len(text.splitlines())}")
    if counts:
        top = ", ".join(f"{word} ({n})" for word, n in counts.most_common(top_n))
        lines.append(f"- top {min(top_n, len(counts))} words: {top}")
    return "\n".join(lines)


async def _run(tool_input: dict, ctx: ToolContext) -> str:
    text = tool_input.get("text", "")
    if not isinstance(text, str):
        text = str(text)
    if not text.strip():
        return "Error: no text provided."
    if len(text) > _MAX_CHARS:
        return f"Error: text exceeds the {_MAX_CHARS}-character limit."
    try:
        top_n = int(tool_input.get("top_n", 5))
    except (TypeError, ValueError):
        top_n = 5
    top_n = max(1, min(top_n, 50))
    return _run_sync(text, top_n)


text_stats_tool = Tool(
    name="text_stats",
    description=(
        "Analyze a block of text and report character, word, unique-word and line "
        "counts plus the most frequent words."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to analyze."},
            "top_n": {
                "type": "integer",
                "description": "How many of the most frequent words to list (1-50, default 5).",
            },
        },
        "required": ["text"],
    },
    handler=_run,
)
