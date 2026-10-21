"""Describe SDK callable signatures and trace explicit upstream API bindings."""
from __future__ import annotations

import ast
from functools import lru_cache
import inspect
import json
import textwrap


def _stable(value):
    if value is inspect.Signature.empty:
        return None
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in sorted(value.items())}
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    # Avoid memory addresses and machine paths in repr(default/annotation).
    module = getattr(value, "__module__", type(value).__module__)
    name = getattr(value, "__qualname__", None)
    if name:
        return f"{module}.{name}"
    if module == "typing" or type(value).__module__ == "types":
        return str(value)
    return {"python_type": f"{type(value).__module__}.{type(value).__qualname__}"}


def parameters(callable_object):
    try:
        signature = inspect.signature(callable_object)
    except (TypeError, ValueError):
        return {"status": "unavailable", "parameters": [], "return_annotation": None}
    result = []
    for name, parameter in signature.parameters.items():
        item = {
            "name": name,
            "kind": parameter.kind.name,
            "annotation": _stable(parameter.annotation),
            "required": parameter.default is inspect.Parameter.empty
            and parameter.kind not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD),
        }
        if parameter.default is not inspect.Parameter.empty:
            item["default"] = _stable(parameter.default)
        result.append(item)
    return {
        "status": "inspected",
        "parameters": result,
        "return_annotation": _stable(signature.return_annotation),
    }


def _attribute(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _attribute(node.value) + "." + node.attr
    return ""


def _algorithm_name(node, type_name):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _algorithm_name(node.left, type_name)
        right = _algorithm_name(node.right, type_name)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.Call) and _attribute(node.func) in {"self.name", "cls.name"}:
        return type_name
    if isinstance(node, ast.JoinedStr):
        parts = [
            _algorithm_name(part.value if isinstance(part, ast.FormattedValue) else part, type_name)
            for part in node.values
        ]
        return "".join(parts) if all(part is not None for part in parts) else None
    return None


@lru_cache(maxsize=8192)
def source_algorithms(function, type_name):
    try:
        source = textwrap.dedent(inspect.getsource(inspect.unwrap(function)))
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError):
        return ()
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        target = _attribute(node.func)
        if not (target.endswith("ApiFunction.call_")
                or target.endswith("ApiFunction.apply_")
                or target.endswith("ApiFunction.lookup")
                or target.endswith("ApiFunction")):
            continue
        name = _algorithm_name(node.args[0], type_name)
        if name is not None:
            found.add(name)
    return tuple(sorted(found))


@lru_cache(maxsize=8192)
def keyword_aliases(function):
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(inspect.unwrap(function))))
    except (OSError, TypeError, SyntaxError):
        return {}
    aliases = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _attribute(node.func).endswith("accept_opt_prefix"):
            continue
        for argument in node.args:
            try:
                item = ast.literal_eval(argument)
            except (ValueError, TypeError):
                continue
            if isinstance(item, str):
                aliases[item] = item.replace("opt_", "", 1)
            elif isinstance(item, tuple) and len(item) == 2 and all(isinstance(v, str) for v in item):
                aliases[item[0]] = item[1]
    return dict(sorted(aliases.items()))


def describe_callable(path, value, algorithms, *, owner=None, constructor=False):
    function = value.__init__ if constructor else getattr(value, "__func__", value)
    attached = getattr(function, "signature", {})
    type_name = owner.__name__ if owner is not None else None
    names = set(source_algorithms(function, type_name)) & algorithms
    if attached.get("name") in algorithms:
        names.add(attached["name"])
    row = {
        "path": path,
        "python_signature": parameters(value),
        "algorithm_names": sorted(names),
        "binding_evidence": (
            "sdk_attached_signature" if attached.get("name") in algorithms else
            "sdk_source_explicit_api_calls" if names else "no_direct_binding_identified"
        ),
    }
    if attached:
        # Dynamic functions expose *args/**kwargs; retain exact named EE args too.
        row["sdk_algorithm_signature"] = json.loads(json.dumps(attached))
    aliases = keyword_aliases(function)
    if aliases:
        row["deprecated_keyword_aliases"] = aliases
    return row


def describe_class(path, cls, algorithms):
    methods = []
    for name in sorted(dir(cls)):
        if name.startswith("_"):
            continue
        value = getattr(cls, name)
        if not callable(value) or isinstance(value, type):
            continue
        row = describe_callable(f"{path}.{name}", value, algorithms, owner=cls)
        descriptor = inspect.getattr_static(cls, name)
        row["binding"] = (
            "static" if isinstance(descriptor, staticmethod) else
            "class" if isinstance(descriptor, classmethod) else "instance"
        )
        row["defined_on"] = getattr(value, "__qualname__", name).split(".")[0]
        methods.append(row)
    return {
        "path": path,
        "module": cls.__module__,
        "constructor": describe_callable(path, cls, algorithms, owner=cls, constructor=True),
        "methods": methods,
    }
