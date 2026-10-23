"""Finite row selection and owned List/FeatureCollection reducer results."""
from __future__ import annotations

from . import collecting_reducer_values as values
from .ir import fail


def _scan_records(translator, input_count: int, records) -> None:
    if type(records) is not list or len(records) > values.MAX_COLLECTING_ROWS:
        fail("Collecting reducers require at most 1000 input rows")
    # Reserve all row-shape checks and the imminent field walk before a cell.
    values._charge(translator, 1 + len(records) * (1 + input_count),
                   "Collecting reducer record scan")
    for row in records:
        if type(row) is not list or len(row) != input_count:
            fail(f"Collecting reducer records must contain exactly {input_count} inputs")
    wire = [2 + 2 * max(0, len(records) - 1)]
    for row in records:
        if input_count > 1:
            values._wire_add(wire, 2 + 2 * (input_count - 1),
                             "Collecting reducer input rows")
        for value in row:
            values._scan_value(translator, value, wire, set())


def _retained_records(translator, records, input_count: int, num_optional: int):
    required = input_count - num_optional
    values._charge(translator, len(records) * (1 + required),
                   "Collecting reducer null-field selection")
    return [row for row in records if all(value is not None for value in row[:required])]


def _scan_output_value(translator, value, wire) -> int:
    return values._scan_value(translator, value, wire, set())


def _list_result(translator, leaf, rows):
    wire = [0]
    # The one-key envelope covers Collection.reduceColumns as well as List.reduce.
    values._wire_add(wire, 4, "Reducer.toList output envelope")
    values._text(translator, "list", wire, "Reducer.toList output name")
    values._wire_add(wire, 2 + 2 * max(0, len(rows) - 1),
                     "Reducer.toList output list")
    copies = 1 + len(rows)
    copy_work = 0
    for row in rows:
        if leaf.tuple_size is None:
            copy_work += _scan_output_value(translator, row[0], wire)
        else:
            values._wire_add(wire, 2 + 2 * max(0, len(row) - 1),
                             "Reducer.toList output tuple")
            copies += 1 + len(row)
            for value in row:
                copy_work += _scan_output_value(translator, value, wire)
    values._charge(translator, copies + copy_work, "Reducer.toList owned output copy")
    if leaf.tuple_size is None:
        output = [values._copy_value(row[0]) for row in rows]
    else:
        output = [[values._copy_value(value) for value in row] for row in rows]
    return [("list", output)]


def _collection_result(translator, leaf, rows):
    names = leaf.property_names
    wire = [0]
    values._wire_add(wire, 4, "Reducer.toCollection output envelope")
    values._text(translator, "collection", wire, "Reducer.toCollection output name")
    # FeatureCollection object with `type` and `features` properties.
    values._wire_add(wire, 2 + 2 * 2 + 2, "Reducer.toCollection output object")
    values._text(translator, "type", wire, "Reducer.toCollection output field")
    values._text(translator, "features", wire, "Reducer.toCollection output field")
    values._text(translator, "FeatureCollection", wire, "Reducer.toCollection output type")
    values._wire_add(wire, 2 + 2 * max(0, len(rows) - 1),
                     "Reducer.toCollection feature list")

    # Charge construction before allocating result dictionaries or feature rows.
    construction_work = 1 + len(rows) * (1 + len(names) + 4)
    copy_work = 0
    for name in names:
        for _ in rows:
            values._text(translator, name, wire,
                         "Reducer.toCollection repeated property name")

    for row in rows:
        # Three feature fields, two comma-spaces, three colon-spaces, and braces.
        values._wire_add(wire, 2 + 2 * 3 + 2 * 2,
                         "Reducer.toCollection feature")
        for key in ("type", "geometry", "properties"):
            values._text(translator, key, wire, "Reducer.toCollection feature field")
        values._text(translator, "Feature", wire, "Reducer.toCollection feature type")
        values._wire_add(wire, 4, "Reducer.toCollection null geometry")
        # Property object: braces, colon-space per item, comma-space separators.
        values._wire_add(wire, 2 + 2 * len(names) + 2 * max(0, len(names) - 1),
                         "Reducer.toCollection properties")
        for value in row:
            copy_work += _scan_output_value(translator, value, wire)

    values._charge(translator, construction_work,
                   "Reducer.toCollection owned output construction")
    values._charge(translator, copy_work,
                   "Reducer.toCollection owned output copy")
    features = []
    for row in rows:
        properties = {
            name: values._copy_value(value)
            for name, value in zip(names, row)
        }
        features.append({"type": "Feature", "geometry": None, "properties": properties})
    return [("collection", {"type": "FeatureCollection", "features": features})]


def reduce_records(translator, leaf, input_count: int, outputs, records):
    """Scan every row, filter required nulls, and construct a detached result."""
    if input_count > values.MAX_COLLECTING_INPUTS or len(outputs) != 1:
        fail("Collecting reducer descriptor has invalid arity or outputs")
    _scan_records(translator, input_count, records)
    rows = _retained_records(translator, records, input_count, leaf.num_optional)
    if leaf.name == "Reducer.toList":
        result = _list_result(translator, leaf, rows)
    else:
        result = _collection_result(translator, leaf, rows)
    if len(result) != len(outputs):
        fail("Collecting reducer produced an unexpected output count")
    return result
