"""Shared Jinja2 templates and a small JSON filter for rendering tool payloads."""
import json
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _fromjson(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


templates.env.filters["fromjson"] = _fromjson
