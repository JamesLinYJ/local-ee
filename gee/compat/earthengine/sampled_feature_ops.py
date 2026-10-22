"""Dynamic, lazy filter and limit operations on sampled feature tables."""
from __future__ import annotations

from ...sample_table_spec import MAX_OPERATIONS, MAX_OPERATION_BYTES
from .ir import Filter, SampledFeatures, fail


MAX_TRANSLATOR_WORK = 50_000
MAX_FILTER_WIRE_DEPTH = 64
_SAMPLE_TABLE_PROCESS = "local_ee_sample_table_op"


def _charge(translator, work, label="Sampled FeatureCollection operation"):
    if work < 0 or translator.steps + work > MAX_TRANSLATOR_WORK:
        fail(f"{label} exceeds the 50000-step compilation work budget")
    translator.steps += work


def _filter_work(filt):
    """Measure a normalized filter tree before canonical JSON serialization."""
    pending = [(filt, 0, False)]
    active = set()
    work = 0
    while pending:
        value, depth, leaving = pending.pop()
        if leaving:
            active.remove(id(value))
            continue
        work += 1
        if work > MAX_TRANSLATOR_WORK or depth > MAX_FILTER_WIRE_DEPTH:
            fail("Sampled FeatureCollection filter exceeds its bounded structure")
        if isinstance(value, Filter):
            if id(value) in active:
                fail("Sampled FeatureCollection filter cannot contain cycles")
            active.add(id(value))
            pending.append((value, depth, True))
            work += len(value.name) + 1
            pending.append((value.args, depth + 1, False))
        elif type(value) is dict:
            if id(value) in active:
                fail("Sampled FeatureCollection filter cannot contain cycles")
            active.add(id(value))
            pending.append((value, depth, True))
            work += len(value)
            for key, child in value.items():
                if not isinstance(key, str):
                    fail("Sampled FeatureCollection filter arguments need string keys")
                work += len(key)
                pending.append((child, depth + 1, False))
        elif type(value) in (list, tuple):
            if id(value) in active:
                fail("Sampled FeatureCollection filter cannot contain cycles")
            active.add(id(value))
            pending.append((value, depth, True))
            work += len(value)
            pending.extend((child, depth + 1, False) for child in value)
        elif isinstance(value, str):
            work += len(value)
        elif value is None or type(value) in (bool, int, float):
            pass
        else:
            fail("Sampled FeatureCollection filters support scalar values only")
    return work


def _current_operations(sampled):
    operations = sampled.operations
    if type(operations) is not tuple or len(operations) > MAX_OPERATIONS:
        fail("Sampled FeatureCollection supports at most 16 filter/limit operations")
    if any(type(operation) is not str for operation in operations):
        fail("Sampled FeatureCollection contains a malformed operation spec")
    return operations


def invoke_sampled_feature_operation(translator, name, arguments):
    """Append one canonical operation without materializing sample rows."""
    from ...sample_table_spec import prepare_sample_filter, prepare_sample_limit

    sampled = arguments.get("collection")
    if not isinstance(sampled, SampledFeatures):
        fail("Sampled FeatureCollection operation requires lazy sampleRegions output")
    operations = _current_operations(sampled)
    if len(operations) >= MAX_OPERATIONS:
        fail("Sampled FeatureCollection supports at most 16 filter/limit operations")
    _charge(translator, 32 + sum(6 * len(spec) for spec in operations))

    if name == "Collection.filter":
        translator.allowed(arguments, {"collection", "filter"})
        filt = arguments.get("filter")
        if not isinstance(filt, Filter):
            fail("Sampled FeatureCollection.filter requires a serialized ee.Filter")
        _charge(translator, 6 * _filter_work(filt))
        try:
            operation = prepare_sample_filter(filt)
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"Unsupported sampled FeatureCollection filter: {exc}")
    elif name == "Collection.limit":
        translator.allowed(arguments, {"collection", "limit", "key", "ascending"})
        key = arguments.get("key")
        if key is not None:
            fail("Sampled FeatureCollection.limit does not support sorting")
        ascending = arguments.get("ascending", True)
        if type(ascending) is not bool:
            fail("Collection ascending must be a boolean")
        count = arguments.get("limit")
        if count is not None and (type(count) is not int or not 0 <= count <= 1000):
            fail("Sampled FeatureCollection limit must be null or an integer from 0 to 1000")
        _charge(translator, 128)
        try:
            operation = prepare_sample_limit(count)
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"Unsupported sampled FeatureCollection limit: {exc}")
    else:
        fail("Sampled FeatureCollections support filter and unsorted limit only")

    if type(operation) is not str:
        fail("Sampled FeatureCollection operation encoder returned a malformed spec")
    _charge(translator, 6 * len(operation) + 8)
    return SampledFeatures(
        image=sampled.image,
        spec=sampled.spec,
        operations=(*operations, operation),
    )


def validate_sampled_operations(sampled, translator, label="Sample table"):
    """Validate and precharge the immutable operation chain before graph edits."""
    from ...sample_table_spec import (
        decode_sample_operation,
        decode_sample_predicate,
    )

    if not isinstance(sampled, SampledFeatures):
        fail(f"{label} has a malformed sample-table IR")
    operations = _current_operations(sampled)
    # Six bytes per code point is a conservative bound for UTF-8 plus JSON
    # escaping. Charge before decoding or constructing intermediate objects.
    _charge(translator, 8 + sum(6 * len(operation) for operation in operations), label)
    for text in operations:
        if len(text) > MAX_OPERATION_BYTES:
            fail(f"{label} operation exceeds 16384 bytes")
        try:
            operation = decode_sample_operation(text)
            if operation["operation"] == "filter":
                predicate = decode_sample_predicate(operation["predicate"])
                if not isinstance(predicate, Filter):
                    fail(f"{label} contains a malformed decoded filter")
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"{label} has an invalid operation spec: {exc}")
    return operations


def sampled_table_known_empty(sampled):
    """Report only emptiness proved by a literal region list or limit(0)."""
    from ...sample_table_spec import decode_sample_operation
    from ...sampling_spec import decode_sampling_spec
    from ...image_sampling_spec import is_image_sample

    spec = decode_sampling_spec(sampled.spec)
    if not spec["regions"]["features"]:
        return True
    if is_image_sample(spec) and spec["image_sample"]["num_pixels"] == 0:
        return True
    for text in _current_operations(sampled):
        operation = decode_sample_operation(text)
        if operation["operation"] == "limit" and operation["count"] == 0:
            return True
    return False


def emit_sampled_operations(graph, table_ref, operations):
    """Lower opaque specs as table metadata, retaining exact data references."""
    for operation in operations:
        table_ref = graph.node(_SAMPLE_TABLE_PROCESS, data=table_ref, spec=operation)
    return table_ref
