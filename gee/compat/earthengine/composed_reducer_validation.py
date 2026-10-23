"""Bounded structural validation for closed reducer descriptors."""
from __future__ import annotations

from .composed_reducer_spec import (
    MAX_REDUCER_DEPTH,
    MAX_REDUCER_INPUTS,
    MAX_REDUCER_NAME_CHARS,
    MAX_REDUCER_NODES,
    MAX_REDUCER_OUTPUTS,
    ReducerSpec,
    ScalarReducerLeaf,
    _SCALAR_OUTPUTS,
    _charge,
)
from .composed_reducer_expansion import for_each_output_names, for_each_output_work
from .ir import fail
from .table_reducers import TableReducer
from .finite_reducer_leaves import FiniteReducerLeaf, validate_finite_leaf
from .statistical_reducer_leaves import is_statistical_leaf, validate_statistical_leaf


def validate_tree(spec, translator=None):
    """Precharge and validate every descriptor occurrence and derived name."""
    if type(spec) is not ReducerSpec:
        fail("Expected a closed composed Reducer")
    active = set()
    nodes = [0]

    def visit(node, depth):
        if type(node) is not ReducerSpec:
            fail("Composed Reducer contains an unsupported descriptor node")
        identity = id(node)
        if identity in active:
            fail("Composed Reducer descriptors cannot contain cycles")
        if depth > MAX_REDUCER_DEPTH:
            fail("Composed Reducer exceeds depth 16")
        nodes[0] += 1
        if nodes[0] > MAX_REDUCER_NODES:
            fail("Composed Reducer exceeds 64 descriptor nodes")
        if translator is not None:
            _charge(translator, 1)

        if (type(node.kind) is not str or type(node.input_count) is not int
                or not 0 <= node.input_count <= MAX_REDUCER_INPUTS
                or type(node.outputs) is not tuple
                or len(node.outputs) > MAX_REDUCER_OUTPUTS):
            fail("Composed Reducer has invalid input or output arity")
        if translator is not None:
            # Charge a bounded tuple walk before inspecting its contents, then
            # charge every name's characters before hashing or concatenating.
            _charge(translator, 1 + len(node.kind) + len(node.outputs))
        if len(node.kind) > MAX_REDUCER_NAME_CHARS:
            fail("Composed Reducer descriptor kind is too long")
        output_chars = 0
        for output in node.outputs:
            if type(output) is not str or len(output) > MAX_REDUCER_NAME_CHARS:
                fail("Composed Reducer has invalid output names")
            output_chars += len(output)
        if translator is not None:
            _charge(translator, output_chars)

        active.add(identity)
        try:
            if node.kind == "leaf":
                if (node.child is not None or node.left is not None or node.right is not None
                        or node.shared_inputs is not False or node.output_prefix != ""
                        or type(node.group_field) is not int or node.group_field != 0
                        or node.group_name != "group" or node.output_selection is not None
                        or node.repeat_count is not None or node.for_each_names is not None):
                    fail("Composed Reducer leaf has invalid descriptor fields")
                if type(node.leaf) is ScalarReducerLeaf:
                    name = node.leaf.name
                    if type(name) is not str or len(name) > MAX_REDUCER_NAME_CHARS:
                        fail("Composed Reducer scalar leaf has invalid fields")
                    if translator is not None:
                        _charge(translator, 1 + len(name))
                    if (name not in _SCALAR_OUTPUTS
                            or node.input_count != 1
                            or node.outputs != (_SCALAR_OUTPUTS[name],)):
                        fail("Composed Reducer scalar leaf has invalid arity or outputs")
                elif type(node.leaf) is FiniteReducerLeaf:
                    validate_finite_leaf(translator, node.leaf, node.input_count, node.outputs)
                elif is_statistical_leaf(node.leaf):
                    validate_statistical_leaf(translator, node.leaf, node.input_count, node.outputs)
                elif type(node.leaf) is TableReducer:
                    leaf = node.leaf
                    if (type(leaf.name) is not str or type(leaf.num_x) is not int
                            or type(leaf.num_y) is not int):
                        fail("Composed Reducer regression leaf has invalid fields")
                    if len(leaf.name) > MAX_REDUCER_NAME_CHARS:
                        fail("Composed Reducer regression leaf name is too long")
                    if translator is not None:
                        _charge(translator, 1 + len(leaf.name))
                    if leaf.name == "linearFit":
                        if (leaf.num_x, leaf.num_y) != (1, 1):
                            fail("Composed Reducer linearFit leaf has invalid arity")
                        expected = ("scale", "offset")
                    elif leaf.name == "linearRegression":
                        if leaf.num_x < 1 or leaf.num_y < 1:
                            fail("Composed Reducer regression leaf has invalid arity")
                        expected = ("coefficients", "residuals")
                    else:
                        fail(f"Composed reducers do not support table reducer {leaf.name}")
                    if (not 1 <= leaf.input_count <= MAX_REDUCER_INPUTS
                            or node.input_count != leaf.input_count or node.outputs != expected):
                        fail("Composed Reducer regression leaf has invalid outputs")
                else:
                    fail("Composed Reducer leaf is not a detached supported reducer")
                return 1

            if node.kind == "combine":
                if (type(node.left) is not ReducerSpec or type(node.right) is not ReducerSpec
                        or node.child is not None or node.leaf is not None
                        or type(node.shared_inputs) is not bool
                        or type(node.output_prefix) is not str
                        or len(node.output_prefix) > MAX_REDUCER_NAME_CHARS
                        or type(node.group_field) is not int or node.group_field != 0
                        or node.group_name != "group" or node.output_selection is not None
                        or node.repeat_count is not None or node.for_each_names is not None):
                    fail("Composed Reducer combine node is invalid")
                if len(node.output_prefix) > MAX_REDUCER_NAME_CHARS:
                    fail("Composed Reducer output prefix is too long")
                if translator is not None:
                    _charge(translator, 1 + len(node.output_prefix))
                left_nodes = visit(node.left, depth + 1)
                right_nodes = visit(node.right, depth + 1)
                logical_nodes = 1 + left_nodes + right_nodes
                if logical_nodes > MAX_REDUCER_NODES:
                    fail("Composed Reducer exceeds 64 logical descriptor nodes")
                expected_inputs = (node.left.input_count if node.shared_inputs else
                                   node.left.input_count + node.right.input_count)
                expected_count = len(node.left.outputs) + len(node.right.outputs)
                if (expected_inputs != node.input_count or expected_inputs > MAX_REDUCER_INPUTS
                        or expected_count != len(node.outputs)
                        or expected_count > MAX_REDUCER_OUTPUTS
                        or (node.shared_inputs and node.left.input_count != node.right.input_count)):
                    fail("Composed Reducer combine node has invalid input or output arity")
                concat_work = expected_count
                for output in node.right.outputs:
                    if len(node.output_prefix) + len(output) > MAX_REDUCER_NAME_CHARS:
                        fail("Composed Reducer output name exceeds the bounded length")
                    concat_work += len(node.output_prefix) + len(output)
                if translator is not None:
                    # All prefix/name concatenation work is charged before any
                    # derived output strings or tuples are allocated.
                    _charge(translator, concat_work)
                expected_names = node.left.outputs + tuple(
                    node.output_prefix + output for output in node.right.outputs
                )
                if node.outputs != expected_names:
                    fail("Composed Reducer combine outputs do not match their children")
                return logical_nodes

            if node.kind in {"group", "setOutputs"}:
                if (type(node.child) is not ReducerSpec or node.left is not None
                        or node.right is not None or node.leaf is not None
                        or node.shared_inputs is not False
                        or node.output_prefix != "" or node.repeat_count is not None
                        or node.for_each_names is not None):
                    fail("Composed Reducer wrapper node is invalid")
                if node.kind == "group":
                    if (type(node.group_field) is not int or type(node.group_name) is not str
                            or len(node.group_name) > MAX_REDUCER_NAME_CHARS
                            or node.output_selection is not None):
                        fail("Composed Reducer group node has invalid fields")
                    if translator is not None:
                        _charge(translator, 1 + len(node.group_name))
                    child_nodes = visit(node.child, depth + 1)
                    logical_nodes = 1 + child_nodes
                    if logical_nodes > MAX_REDUCER_NODES:
                        fail("Composed Reducer exceeds 64 logical descriptor nodes")
                    if (not 0 <= node.group_field < node.input_count
                            or node.input_count != node.child.input_count + 1
                            or node.outputs != ("groups",)):
                        fail("Composed Reducer group node is invalid")
                    return logical_nodes

                if (type(node.group_field) is not int or node.group_field != 0
                        or node.group_name != "group"
                        or type(node.output_selection) is not tuple
                        or len(node.output_selection) > MAX_REDUCER_OUTPUTS):
                    fail("Composed Reducer output selection is invalid")
                if translator is not None:
                    _charge(translator, len(node.output_selection))
                selection_chars = 0
                for output in node.output_selection:
                    if output is not None:
                        if type(output) is not str or len(output) > MAX_REDUCER_NAME_CHARS:
                            fail("Composed Reducer output selection is invalid")
                        selection_chars += len(output)
                if translator is not None:
                    _charge(translator, selection_chars)
                child_nodes = visit(node.child, depth + 1)
                logical_nodes = 1 + child_nodes
                if logical_nodes > MAX_REDUCER_NODES:
                    fail("Composed Reducer exceeds 64 logical descriptor nodes")
                if (len(node.output_selection) != len(node.child.outputs)
                        or node.input_count != node.child.input_count):
                    fail("Composed Reducer output selection is invalid")
                selection_work = len(node.output_selection)
                if translator is not None:
                    _charge(translator, selection_work)
                expected_names = tuple(item for item in node.output_selection if item)
                if node.outputs != expected_names:
                    fail("Composed Reducer output selection does not match its names")
                return logical_nodes

            if node.kind in {"repeat", "forEach"}:
                if (type(node.child) is not ReducerSpec or node.left is not None
                        or node.right is not None or node.leaf is not None
                        or node.shared_inputs is not False or node.output_prefix != ""
                        or type(node.group_field) is not int or node.group_field != 0
                        or node.group_name != "group" or node.output_selection is not None):
                    fail("Composed Reducer expansion node has invalid unused fields")
                if node.kind == "repeat":
                    if (type(node.repeat_count) is not int
                            or not 1 <= node.repeat_count <= MAX_REDUCER_INPUTS
                            or node.for_each_names is not None):
                        fail("Reducer.repeat descriptor has invalid copy count")
                    copies = node.repeat_count
                    output_names = None
                else:
                    if (node.repeat_count is not None
                            or type(node.for_each_names) is not tuple
                            or not 1 <= len(node.for_each_names) <= MAX_REDUCER_INPUTS):
                        fail("Reducer.forEach descriptor has invalid output names")
                    copies = len(node.for_each_names)
                    if translator is not None:
                        _charge(translator, copies)
                    name_chars = 0
                    for name in node.for_each_names:
                        if type(name) is not str or len(name) > MAX_REDUCER_NAME_CHARS:
                            fail("Reducer.forEach descriptor has invalid output names")
                        name_chars += len(name)
                    if translator is not None:
                        _charge(translator, name_chars)
                    output_names = node.for_each_names

                child_nodes = visit(node.child, depth + 1)
                logical_nodes = 1 + copies * child_nodes
                if logical_nodes > MAX_REDUCER_NODES:
                    fail("Composed Reducer expansion exceeds 64 logical descriptor nodes")
                if translator is not None:
                    # The stored child is traversed once above; charge each
                    # additional logical copy before repeated names or rows
                    # can be built from it.
                    _charge(translator, child_nodes * (copies - 1))
                expected_inputs = node.child.input_count * copies
                if expected_inputs > MAX_REDUCER_INPUTS or node.input_count != expected_inputs:
                    fail("Composed Reducer expansion has invalid input arity")

                if node.kind == "repeat":
                    if node.outputs != node.child.outputs:
                        fail("Reducer.repeat outputs do not match its child")
                    repeated_name_work = copies * len(node.child.outputs)
                    repeated_name_work += copies * sum(len(name) for name in node.child.outputs)
                    if translator is not None:
                        _charge(translator, repeated_name_work)
                else:
                    expected_count = copies * len(node.child.outputs)
                    if expected_count > MAX_REDUCER_OUTPUTS or len(node.outputs) != expected_count:
                        fail("Reducer.forEach has invalid output arity")
                    _, output_work = for_each_output_work(
                        output_names, node.child.outputs, MAX_REDUCER_NAME_CHARS,
                    )
                    if translator is not None:
                        _charge(translator, output_work)
                    expected_names = for_each_output_names(output_names, node.child.outputs)
                    if node.outputs != expected_names:
                        fail("Reducer.forEach outputs do not match its child and names")
                return logical_nodes

            fail("Composed Reducer contains an unknown descriptor kind")
        finally:
            active.remove(identity)

    return visit(spec, 1)
