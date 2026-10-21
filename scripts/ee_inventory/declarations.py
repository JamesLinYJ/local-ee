"""Read the declared handler names without importing the application."""
from __future__ import annotations

import ast
from pathlib import Path

def _expand_handler_expression(node: ast.AST, symbols: dict[str, set[str]] | None = None) -> set[str]:
    """Evaluate the simple literal/generator expression used for handlers."""
    symbols = symbols or {}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "frozenset" and len(node.args) == 1:
        return _expand_handler_expression(node.args[0], symbols)
    if isinstance(node, ast.Name) and node.id in symbols:
        return set(symbols[node.id])
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Set):
        return set().union(*(_expand_handler_expression(item, symbols) for item in node.elts)) if node.elts else set()
    if isinstance(node, ast.Tuple):
        return set().union(*(_expand_handler_expression(item, symbols) for item in node.elts)) if node.elts else set()
    if isinstance(node, ast.Starred):
        return _expand_handler_expression(node.value, symbols)
    if isinstance(node, ast.GeneratorExp) and len(node.generators) == 1:
        generator = node.generators[0]
        if not isinstance(generator.target, ast.Name) or not isinstance(generator.iter, (ast.Tuple, ast.List)):
            raise ValueError("Unsupported handler generator expression")
        values: set[str] = set()
        for item in generator.iter.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                raise ValueError("Handler generator must enumerate string literals")
            if isinstance(node.elt, ast.BinOp) and isinstance(node.elt.op, ast.Add):
                if isinstance(node.elt.left, ast.Constant) and isinstance(node.elt.left.value, str) and isinstance(node.elt.right, ast.Name) and node.elt.right.id == generator.target.id:
                    values.add(node.elt.left.value + item.value)
                    continue
            raise ValueError("Unsupported handler generator template")
        return values
    raise ValueError(f"Unsupported handler inventory syntax: {type(node).__name__}")


def read_declared_handlers(source: Path) -> set[str]:
    declaration = source.parent / "compat/earthengine/capabilities.py"
    if not declaration.exists(): declaration = source
    tree = ast.parse(declaration.read_text(encoding="utf-8"), filename=str(declaration.name))
    date_tree = ast.parse(source.with_name("ee_dates.py").read_text(encoding="utf-8"), filename="gee/ee_dates.py")
    integer_tree = ast.parse(source.with_name("ee_integer.py").read_text(encoding="utf-8"), filename="gee/ee_integer.py")
    symbols: dict[str, set[str]] = {}
    for module_tree, symbol_name in (
        (date_tree, "SUPPORTED_DATE_FUNCTIONS"),
        (integer_tree, "SUPPORTED_INTEGER_FUNCTIONS"),
    ):
        for statement in module_tree.body:
            if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == symbol_name for target in statement.targets
            ):
                symbols[symbol_name] = _expand_handler_expression(statement.value)
                break
        else:
            raise ValueError(f"{symbol_name} declaration was not found")
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "SUPPORTED_FUNCTIONS" for target in statement.targets):
            continue
        value = statement.value
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Sub):
            handlers = _expand_handler_expression(value.left, symbols) - _expand_handler_expression(value.right, symbols)
        else:
            handlers = _expand_handler_expression(value, symbols)
        return handlers
    raise ValueError("SUPPORTED_FUNCTIONS declaration was not found")
