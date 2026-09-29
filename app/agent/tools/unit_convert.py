"""Convert a value between units of length, mass or temperature.

Length and mass convert through a base unit via fixed factors; temperature uses the
standard affine formulas. Units must belong to the same category. No eval.
"""
from app.agent.tools.base import Tool, ToolContext

# Aliases -> canonical code, and canonical code -> factor to the category base unit.
_LENGTH = {  # base: metre
    "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
    "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0, "kilometre": 1000.0,
    "kilometres": 1000.0,
    "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01,
    "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001,
    "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
    "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
    "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
    "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
}
_MASS = {  # base: gram
    "g": 1.0, "gram": 1.0, "grams": 1.0,
    "kg": 1000.0, "kilogram": 1000.0, "kilograms": 1000.0,
    "mg": 0.001, "milligram": 0.001, "milligrams": 0.001,
    "lb": 453.59237, "lbs": 453.59237, "pound": 453.59237, "pounds": 453.59237,
    "oz": 28.349523125, "ounce": 28.349523125, "ounces": 28.349523125,
}
_TEMPERATURE = {
    "c": "c", "celsius": "c", "centigrade": "c",
    "f": "f", "fahrenheit": "f",
    "k": "k", "kelvin": "k",
}


def _category(unit: str) -> str | None:
    if unit in _LENGTH:
        return "length"
    if unit in _MASS:
        return "mass"
    if unit in _TEMPERATURE:
        return "temperature"
    return None


def _to_celsius(value: float, unit: str) -> float:
    if unit == "c":
        return value
    if unit == "f":
        return (value - 32.0) * 5.0 / 9.0
    return value - 273.15  # kelvin


def _from_celsius(celsius: float, unit: str) -> float:
    if unit == "c":
        return celsius
    if unit == "f":
        return celsius * 9.0 / 5.0 + 32.0
    return celsius + 273.15  # kelvin


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert ``value`` from ``from_unit`` to ``to_unit`` within one category."""
    src, dst = from_unit.strip().lower(), to_unit.strip().lower()
    src_cat, dst_cat = _category(src), _category(dst)
    if src_cat is None:
        raise ValueError(f"unknown unit: {from_unit!r}")
    if dst_cat is None:
        raise ValueError(f"unknown unit: {to_unit!r}")
    if src_cat != dst_cat:
        raise ValueError(f"cannot convert {src_cat} to {dst_cat}")
    if src_cat == "temperature":
        return _from_celsius(_to_celsius(value, _TEMPERATURE[src]), _TEMPERATURE[dst])
    table = _LENGTH if src_cat == "length" else _MASS
    return value * table[src] / table[dst]


def _format(number: float) -> str:
    rounded = round(number, 6)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"


async def _run(tool_input: dict, ctx: ToolContext) -> str:
    raw_value = tool_input.get("value")
    from_unit = str(tool_input.get("from", "")).strip()
    to_unit = str(tool_input.get("to", "")).strip()
    if raw_value is None or from_unit == "" or to_unit == "":
        return "Error: value, from and to are all required."
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return f"Error: value must be a number, got {raw_value!r}."
    try:
        result = convert(value, from_unit, to_unit)
    except ValueError as exc:
        return f"Error: {exc}"
    return f"{_format(value)} {from_unit} = {_format(result)} {to_unit}"


unit_convert_tool = Tool(
    name="unit_convert",
    description=(
        "Convert a numeric value between units of length (m, km, cm, mm, mi, yd, ft, "
        "in), mass (g, kg, mg, lb, oz) or temperature (C, F, K). The two units must be "
        "in the same category."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "value": {"type": "number", "description": "The quantity to convert."},
            "from": {"type": "string", "description": "The unit to convert from, e.g. 'km'."},
            "to": {"type": "string", "description": "The unit to convert to, e.g. 'mi'."},
        },
        "required": ["value", "from", "to"],
    },
    handler=_run,
)
