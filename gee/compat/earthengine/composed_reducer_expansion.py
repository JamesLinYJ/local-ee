"""Bounded construction and execution helpers for repeated Reducers."""
from __future__ import annotations

from .ir import fail


def _charge(translator, amount):
    if amount < 0 or translator.steps + amount > 50_000:
        fail("Composed reducer expansion exceeds the shared 50000-step compilation work budget")
    translator.steps += amount


def expansion_count(value, label, maximum):
    """Parse a positive integer without converting unbounded integers to float."""
    if type(value) is int:
        count = value
    elif type(value) is float:
        if not value.is_integer():
            fail(f"{label} must be an integer")
        count = int(value)
    else:
        fail(f"{label} must be an integer")
    if count < 1:
        fail(f"{label} must be at least 1; zero-copy Reducers are unsupported")
    if count > maximum:
        fail(f"{label} exceeds the bounded 32-input reducer arity")
    return count


def for_each_output_work(output_names, child_outputs, max_name_chars):
    """Return output count and scan/creation work without allocating names."""
    output_count = len(output_names) * len(child_outputs)
    work = output_count
    if len(child_outputs) == 1:
        for name in output_names:
            work += len(name)
    else:
        for name in output_names:
            for output in child_outputs:
                output_length = len(name) + 1 + len(output)
                if output_length > max_name_chars:
                    fail("Reducer.forEach output name exceeds the bounded length")
                work += output_length
    return output_count, work


def for_each_output_names(output_names, child_outputs):
    """Derive the closed output tuple after callers have precharged its work."""
    if len(child_outputs) == 1:
        return tuple(output_names)
    return tuple(
        f"{name}_{output}"
        for name in output_names
        for output in child_outputs
    )


def _input_blocks(records, input_width, copies):
    for copy_index in range(copies):
        start = copy_index * input_width
        end = start + input_width
        yield [row[start:end] for row in records]


def evaluate_repeat(translator, records, spec, evaluate_child):
    """Run independent input blocks and return one list per child output."""
    copies = spec.repeat_count
    child = spec.child
    output_count = len(child.outputs)
    # Reserve every row slice, result bucket, and appended output value before
    # creating any blocks or entering the child evaluator.
    _charge(
        translator,
        len(records) * (spec.input_count + copies)
        + output_count * (copies + 1),
    )
    values = [[] for _ in child.outputs]
    for rows in _input_blocks(records, child.input_count, copies):
        reduced = evaluate_child(translator, rows, child)
        if len(reduced) != output_count:
            fail("Reducer.repeat child produced an unexpected output count")
        for index, (_, value) in enumerate(reduced):
            values[index].append(value)
    return list(zip(child.outputs, values))


def evaluate_for_each(translator, records, spec, evaluate_child):
    """Run one child copy per name and apply the derived output-name tuple."""
    copies = len(spec.for_each_names)
    child = spec.child
    child_output_count = len(child.outputs)
    output_count = len(spec.outputs)
    # Reserve all row slices and flattened output entries before evaluation.
    _charge(
        translator,
        len(records) * (spec.input_count + copies) + output_count,
    )
    entries = []
    output_index = 0
    for block in _input_blocks(records, child.input_count, copies):
        reduced = evaluate_child(translator, block, child)
        if len(reduced) != child_output_count:
            fail("Reducer.forEach child produced an unexpected output count")
        for _, value in reduced:
            entries.append((spec.outputs[output_index], value))
            output_index += 1
    if output_index != output_count:
        fail("Reducer.forEach produced an unexpected output count")
    return entries
