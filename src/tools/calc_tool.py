from __future__ import annotations

import ast
import operator
from typing import Any

from src.tools.base import ToolContext, ToolResult, ToolSpec, require_str

# Deterministic arithmetic for ledger math (GST, arrears, totals, pro-rata).
# AST-walk evaluator: numbers, + - * / // % **, parentheses, and a small set
# of named functions. No names, no attributes, no eval — nothing else parses.

_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {"round": round, "min": min, "max": max, "abs": abs, "sum": lambda *xs: sum(xs)}
MAX_EXPRESSION_CHARS = 500


def evaluate_expression(expression: str) -> float | int:
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise ValueError(f"Expression exceeds {MAX_EXPRESSION_CHARS} characters.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression: {exc}") from exc
    return _walk(tree.body)


def _walk(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("Only numeric literals are allowed.")
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        return _BINARY_OPS[type(node.op)](_walk(node.left), _walk(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_walk(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS or node.keywords:
            raise ValueError(f"Only these functions are allowed: {sorted(_FUNCTIONS)}.")
        return _FUNCTIONS[node.func.id](*(_walk(arg) for arg in node.args))
    raise ValueError(f"Disallowed syntax: {type(node).__name__}.")


def _calculate(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    expression = require_str(args, "expression")
    try:
        result = evaluate_expression(expression)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        return ToolResult(observation=f"ERROR: {exc}")
    return ToolResult(observation=f"{expression} = {result}")


CALC_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="calculate",
        description=(
            "Deterministic arithmetic. Use for ALL money and date-count math (GST, arrears interest, "
            "totals, pro-rata) instead of computing in your head. Supports + - * / // % **, parentheses, "
            "round/min/max/abs/sum."
        ),
        args={"expression": "numeric expression, e.g. round(1000 * 52 / 12 * 0.1, 2)"},
        run=_calculate,
    ),
]
