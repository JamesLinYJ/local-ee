"""Closed reducer plans limited to Image.reduceNeighborhood consumers."""
from __future__ import annotations

from dataclasses import dataclass

from .ir import Reducer, fail


_MAX_WORK = 50_000
_MAX_OUTPUTS = 256
_MAX_NAME_CHARS = 10_000
_OPERATIONS = frozenset({
    "sum", "mean", "count", "min", "max", "variance", "stdDev",
    "sampleVariance", "sampleStdDev", "product", "median", "mode",
})
_UNWEIGHTED_ALIASES = {"sd": "sampleStdDev"}


@dataclass(frozen=True, slots=True)
class NeighborhoodUnweighted:
    """Opaque Reducer.unweighted result accepted only by neighborhood lowering."""

    plan: tuple[tuple[str, str], ...]


def _charge(translator, amount: int, label: str) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or type(amount) is not int or amount < 0
            or steps + amount > _MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _contains_quantile(spec) -> bool:
    """Do a bounded type-only walk before selecting the mode-aware planner."""
    from .composed_reducer_spec import ReducerSpec
    from .quantile_reducer_spec import QuantileReducerLeaf

    stack = [(spec, 0)]
    visited = set()
    while stack:
        node, depth = stack.pop()
        if type(node) is not ReducerSpec or depth > 16 or len(visited) >= 64:
            return False
        identity = id(node)
        if identity in visited:
            continue
        visited.add(identity)
        if node.kind == "leaf":
            if type(node.leaf) is QuantileReducerLeaf:
                return True
        elif node.kind == "combine":
            stack.append((node.right, depth + 1))
            stack.append((node.left, depth + 1))
        elif node.kind in {"setOutputs", "group", "repeat", "forEach"}:
            stack.append((node.child, depth + 1))
    return False


def _mode_aware_plan(translator, spec):
    """Plan numeric leaves plus the existing default mode leaf in a full tree."""
    from .composed_reducer_spec import ScalarReducerLeaf, validate_reducer_spec
    from .finite_reducer_leaves import FiniteReducerLeaf
    from .quantile_reducer_spec import QuantileReducerLeaf

    validate_reducer_spec(spec, translator)

    def leaf_operations(node):
        if type(node.leaf) is ScalarReducerLeaf:
            name = node.leaf.name
            operation = _UNWEIGHTED_ALIASES.get(name, name)
            if name not in {"sum", "mean", "min", "max", "count", "median", "sd"}:
                fail(f"reduceNeighborhood does not support numeric reducer {name}")
            return (operation,)
        if type(node.leaf) is FiniteReducerLeaf:
            mapping = {
                "minMax": ("min", "max"),
                "product": ("product",),
                "stdDev": ("stdDev",),
                "variance": ("variance",),
                "sampleVariance": ("sampleVariance",),
            }
            operations = mapping.get(node.leaf.name)
            if operations is None:
                fail(f"reduceNeighborhood does not support finite reducer {node.leaf.name}")
            return operations
        if type(node.leaf) is QuantileReducerLeaf:
            leaf = node.leaf
            if (leaf.name != "Reducer.mode" or leaf.max_raw is not None
                    or leaf.percentiles != () or leaf.outputs != ("mode",)):
                fail("reduceNeighborhood supports only the default Reducer.mode leaf")
            return ("mode",)
        fail("reduceNeighborhood requires supported scalar numeric reducer leaves")

    def visit(node):
        _charge(translator, 1, "Neighborhood reducer plan")
        if node.kind == "leaf":
            if node.input_count != 1:
                fail("reduceNeighborhood requires one input per reducer leaf")
            return leaf_operations(node)
        if node.kind == "combine":
            if node.shared_inputs is not True:
                fail("reduceNeighborhood Reducer.combine requires sharedInputs=true")
            left = visit(node.left)
            right = visit(node.right)
            operations = left + right
            if len(operations) != len(node.outputs):
                fail("reduceNeighborhood Reducer.combine has an invalid output plan")
            return operations
        if node.kind == "setOutputs":
            child = visit(node.child)
            selection = node.output_selection
            if type(selection) is not tuple or len(selection) != len(child):
                fail("reduceNeighborhood Reducer.setOutputs has an invalid output plan")
            return tuple(operation for operation, name in zip(child, selection)
                         if name is not None and name != "")
        fail(f"reduceNeighborhood does not support reducer descriptor {node.kind}")

    operations = visit(spec)
    if (not 1 <= len(operations) <= _MAX_OUTPUTS
            or len(spec.outputs) != len(operations)):
        fail("reduceNeighborhood requires 1 to 256 numeric reducer outputs")
    _charge(translator, len(spec.outputs) + sum(len(name) for name in spec.outputs),
            "Neighborhood reducer output plan")
    return tuple(zip(spec.outputs, operations))


def _validate_unweighted_plan(translator, plan):
    if type(plan) is not tuple or not 1 <= len(plan) <= _MAX_OUTPUTS:
        fail("Expected a validated neighborhood-only unweighted Reducer")
    work = len(plan)
    for pair in plan:
        if (type(pair) is not tuple or len(pair) != 2
                or type(pair[0]) is not str or not pair[0]
                or len(pair[0]) > _MAX_NAME_CHARS
                or type(pair[1]) is not str or pair[1] not in _OPERATIONS):
            fail("Neighborhood unweighted Reducer has an invalid output plan")
        work += 1 + len(pair[0])
    _charge(translator, work, "Neighborhood unweighted reducer plan")
    seen = set()
    for pair in plan:
        if pair[0] in seen:
            fail("Neighborhood unweighted Reducer output names must be unique")
        seen.add(pair[0])
    return plan


def resolve_neighborhood_reducer(translator, reducer):
    """Return output/operation pairs and whether all support weights are one."""
    if type(reducer) is NeighborhoodUnweighted:
        return _validate_unweighted_plan(translator, reducer.plan), True

    from .composed_reducer_spec import ReducerSpec
    from .numeric_reducer_plan import numeric_outputs

    direct_unweighted = False
    numeric_reducer = reducer
    if type(reducer) is Reducer:
        if type(reducer.name) is not str or type(reducer.unweighted) is not bool:
            fail("Legacy neighborhood Reducer has invalid fields")
        direct_unweighted = reducer.unweighted
        if direct_unweighted:
            # Keep the shared numeric planner strict. Only this private
            # neighborhood consumer interprets the legacy flag as unit support.
            numeric_reducer = Reducer(reducer.name, False)
    if (type(numeric_reducer) is ReducerSpec
            and _contains_quantile(numeric_reducer)):
        plan = _mode_aware_plan(translator, numeric_reducer)
    else:
        plan = numeric_outputs(translator, numeric_reducer)

    normalized = []
    for output, operation in plan:
        operation = _UNWEIGHTED_ALIASES.get(operation, operation)
        if operation not in _OPERATIONS:
            fail(f"reduceNeighborhood does not support reducer operation {operation}")
        normalized.append((output, operation))
    if not 1 <= len(normalized) <= _MAX_OUTPUTS:
        fail("reduceNeighborhood requires 1 to 256 numeric reducer outputs")
    return tuple(normalized), direct_unweighted


def invoke_neighborhood_unweighted(translator, arguments):
    """Build a reducer wrapper whose unweighted policy is neighborhood-only."""
    translator.allowed(arguments, {"reducer"})
    if "reducer" not in arguments:
        fail("Reducer.unweighted requires a reducer")
    if type(arguments["reducer"]) is NeighborhoodUnweighted:
        fail("Reducer.unweighted cannot be nested")
    plan, _ = resolve_neighborhood_reducer(translator, arguments["reducer"])
    return NeighborhoodUnweighted(plan)
