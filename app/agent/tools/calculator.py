"""Safe arithmetic calculator built on the AST — never uses eval()."""
import ast
import operator
from collections.abc import Callable

from app.agent.tools.base import Tool, ToolContext

_BIN_OPS: dict[type, Callable] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type, Callable] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculatorError(ValueError):
    """Raised for unsupported or unsafe expressions."""


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalculatorError("only numeric literals are allowed")
        return node.value
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise CalculatorError(f"unsupported operator: {type(node.op).__name__}")
        left, right = _eval(node.left), _eval(node.right)
        if type(node.op) is ast.Pow and (abs(right) > 100 or abs(left) > 1_000_000):
            raise CalculatorError("exponent out of the allowed range")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise CalculatorError("unsupported unary operator")
        return op(_eval(node.operand))
    raise CalculatorError("unsupported expression")


def evaluate(expression: str) -> float:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"invalid syntax: {exc.msg}") from exc
    return _eval(tree.body)


async def _run(tool_input: dict, ctx: ToolContext) -> str:
    expression = str(tool_input.get("expression", "")).strip()
    if not expression:
        return "Error: no expression provided."
    try:
        result = evaluate(expression)
    except CalculatorError as exc:
        return f"Error: {exc}"
    except ZeroDivisionError:
        return "Error: division by zero."
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)


calculator_tool = Tool(
    name="calculator",
    description=(
        "Evaluate an arithmetic expression using +, -, *, /, //, %, ** and "
        "parentheses. Returns the numeric result."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The arithmetic expression, e.g. '2 * (3 + 4)'.",
            }
        },
        "required": ["expression"],
    },
    handler=_run,
)
