"""Dynamic, lazy filter and limit operations on sampled feature tables."""
from __future__ import annotations

from ...sample_table_spec import MAX_OPERATIONS, MAX_OPERATION_BYTES
from .ir import Filter, SampledFeatures, fail


MAX_TRANSLATOR_WORK = 50_000
MAX_FILTER_WIRE_DEPTH = 64
MAX_SCHEMA_CACHE_ENTRIES = 64
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
        fail("Sampled FeatureCollection supports at most 16 ordered table operations")
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
        fail("Sampled FeatureCollection supports at most 16 ordered table operations")
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
    elif name == "Collection.randomColumn":
        from .random_column import prepare_random_column

        operation = prepare_random_column(translator, arguments)
        candidate = SampledFeatures(
            image=sampled.image,
            spec=sampled.spec,
            operations=(*operations, operation),
        )
        # Keys are checked against this point in the immutable schema chain,
        # so a later random column can use a column produced earlier.
        validated_sampled_schema(
            candidate, translator, "Collection.randomColumn sample table",
        )
        return candidate
    else:
        fail("Sampled FeatureCollections support filter, unsorted limit, and randomColumn only")

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


def _freeze_schema_value(value):
    """Keep cached decoded JSON immutable and detached from its callers."""
    if type(value) is dict:
        return ("dict", tuple((key, _freeze_schema_value(child))
                              for key, child in value.items()))
    if type(value) is list:
        return ("list", tuple(_freeze_schema_value(child) for child in value))
    return ("value", value)


def _copy_frozen_schema_value(value):
    """Build a fresh ordinary JSON tree from the private immutable snapshot."""
    kind, payload = value
    if kind == "dict":
        return {key: _copy_frozen_schema_value(child) for key, child in payload}
    if kind == "list":
        return [_copy_frozen_schema_value(child) for child in payload]
    return payload


def validated_sampled_schema(sampled, translator, label="Sample table"):
    """Validate the full operation chain and derive the exact output headers."""
    from ...sampling_spec import decode_sampling_spec
    from ...sample_table_schema import sampled_columns

    operations = _current_operations(sampled) if isinstance(sampled, SampledFeatures) else ()
    cache = getattr(translator, "_sampled_schema_cache", None)
    if type(cache) is dict and isinstance(sampled, SampledFeatures):
        # Use the identities of the immutable canonical inputs for a constant-
        # time lookup. The entry retains strong references and checks them
        # below, so an id reuse cannot turn a different schema into a hit.
        key = (id(sampled.spec), id(operations))
        cached = cache.get(key)
        if (cached is not None and cached[0] is sampled.spec
                and cached[1] is operations):
            frozen_origin, columns, header_work = cached[2:]
            # A hit still pays for the immutable-key checks, decoded-origin
            # copy and fresh header-list copy before allocating either value.
            work = 8 + len(operations) + len(sampled.spec) + header_work
            _charge(translator, work, label)
            return _copy_frozen_schema_value(frozen_origin), list(columns), operations

    operations = validate_sampled_operations(sampled, translator, label)
    # Charge the origin and operation text before decoding or allocating the
    # transformed header list. The shared schema helper also enforces its own
    # fixed shape and wire-work limits.
    _charge(translator, 8 + len(sampled.spec) + sum(map(len, operations)), label)
    try:
        origin = decode_sampling_spec(sampled.spec)
        columns = sampled_columns(origin, operations)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"{label} has an invalid transformed schema: {exc}")
    header_work = len(columns) + sum(map(len, columns))
    _charge(translator, header_work + 1, label)
    if type(cache) is dict:
        # Snapshot/freeze work is optional cache overhead; skip insertion when
        # the existing compiler budget cannot pay for it. The first caller
        # receives its fresh decode, while later hits thaw owned copies.
        cache_work = len(sampled.spec) + len(columns)
        if translator.steps + cache_work <= MAX_TRANSLATOR_WORK:
            _charge(translator, cache_work, label)
            if len(cache) >= MAX_SCHEMA_CACHE_ENTRIES:
                cache.pop(next(iter(cache)))
            cache[(id(sampled.spec), id(operations))] = (
                sampled.spec, operations, _freeze_schema_value(origin),
                tuple(columns), header_work,
            )
    return origin, columns, operations


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
