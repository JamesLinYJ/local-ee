"""Bounded runtime training bridge for the pinned Smile random forest."""
from __future__ import annotations

from .ee_sampling_result import PendingSampledTable, SampledFeatureTable


MAX_RF_RUNTIME_WORK = 150_000
MAX_RF_PRIOR_OPERATION_WORK = 50_000
MAX_RF_WIRE_SCAN_BYTES = 3_000_000
MAX_RF_ROWS_JSON_BYTES = 1_000_000


class _RuntimeWork:
    """RF object/copy/operation meter, seeded by bounded table-operation work."""

    def __init__(self, steps=0):
        if type(steps) is not int or not 0 <= steps <= MAX_RF_RUNTIME_WORK:
            raise ValueError("Smile RF training exceeds the 150000-step object-work budget")
        self.steps = steps

    def charge(self, amount):
        if type(amount) is not int or amount < 0 or self.steps + amount > MAX_RF_RUNTIME_WORK:
            raise ValueError("Smile RF training exceeds the 150000-step object-work budget")
        self.steps += amount


class _WireScan:
    """Cumulative bytes scanned or canonicalized by the Python RF bridge."""

    def __init__(self):
        self.bytes_scanned = 0

    def charge(self, amount):
        if (type(amount) is not int or amount < 0
                or self.bytes_scanned + amount > MAX_RF_WIRE_SCAN_BYTES):
            raise ValueError("Smile RF training exceeds the 3000000-byte wire-scan budget")
        self.bytes_scanned += amount


def _utf8_size(text, maximum, label):
    if type(text) is not str or len(text) > maximum:
        raise ValueError(f"{label} exceeds its bounded UTF-8 limit")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8") from exc
    if size > maximum:
        raise ValueError(f"{label} exceeds its bounded UTF-8 limit")
    return size


def _spec(text, wire_budget=None):
    from gee.smile_rf_spec import MAX_SPEC_BYTES, decode_rf_spec

    size = _utf8_size(text, MAX_SPEC_BYTES, "Smile RF specification")
    if wire_budget is not None:
        # _parse loads the JSON tree and re-encodes it to enforce canonical
        # form. Reserve both byte scans before entering the decoder.
        wire_budget.charge(size * 2)
    return decode_rf_spec(text)


def _dry_run_tracer(env):
    if env is None:
        return None
    from openeo_driver.processgraph.registry import ENV_DRY_RUN_TRACER

    getter = getattr(env, "get", None)
    return getter(ENV_DRY_RUN_TRACER) if callable(getter) else None


def _pending(spec_text, decoded, *, traces=(), data_tracer=None):
    from .ee_smile_rf import PendingSmileRfModel

    return PendingSmileRfModel(
        schema=tuple(decoded["schema"]),
        class_property=decoded["class_property"],
        traces=tuple(traces),
        data_tracer=data_tracer,
        spec=spec_text,
    )


def _train(spec_text, rows_text, decoded, rows):
    from .ee_smile_rf import _train_jvm_model, _trained_model

    java_model = _train_jvm_model(spec_text, rows_text)
    labels = {row[0] for row in rows["rows"]}
    return _trained_model(
        decoded["schema"], decoded["class_property"], spec_text, java_model,
        training_row_count=len(rows["rows"]), class_count=len(labels),
    )


def local_ee_train_smile_rf_rows(args, env):
    """Validate literal rows, then train only in an actual batch/JVM runtime."""
    from .ee_process_adapters import _checked_args
    from gee.smile_rf_spec import decode_rf_rows, training_work_bound

    args = _checked_args(args, "local_ee_train_smile_rf_rows", {"rows", "spec"})
    budget = _RuntimeWork()
    wire_budget = _WireScan()
    decoded = _spec(args["spec"], wire_budget)
    rows_text = args["rows"]
    row_bytes = _utf8_size(rows_text, MAX_RF_ROWS_JSON_BYTES, "Smile RF rows")
    # The bounded parser reads and canonicalizes the input text. Keep those
    # byte scans independent from object shape work, with the one-MB wire cap
    # still applied above.
    wire_budget.charge(row_bytes * 3)
    # Reserve the maximum bounded decoded matrix shape before parsing it.
    # MAX_ROWS and schema width make this a small fixed upper bound.
    from gee.smile_rf_spec import MAX_ROWS

    budget.charge(MAX_ROWS * (len(decoded["schema"]) + 1))
    rows = decode_rf_rows(rows_text, decoded)
    # decode_rf_rows establishes the conservative tree/row bound before it
    # traverses row contents; keep an explicit bridge-level contract check too.
    training_work_bound(decoded, len(rows["rows"]))
    tracer = _dry_run_tracer(env)
    if tracer is not None:
        return _pending(args["spec"], decoded, data_tracer=tracer)
    return _train(args["spec"], rows_text, decoded, rows)


def _table_columns(table):
    columns = (getattr(table, "columns", None)
               if type(table) is PendingSampledTable else getattr(table, "_columns", None))
    if (type(columns) is not tuple or not columns
            or any(type(name) is not str for name in columns)
            or len(set(columns)) != len(columns)):
        raise ValueError("Smile RF training requires a validated sampled-table schema")
    return columns


def _table_schema(table, budget):
    """Rebuild trusted sample columns from their immutable origin and ops."""
    columns = _table_columns(table)
    operations = getattr(table, "sample_operations", ())
    verified = getattr(table, "sample_spec_verified", False)
    has_sample_metadata = any(hasattr(table, name) for name in (
        "sample_spec", "sample_spec_verified", "sample_operations",
    ))
    if type(table) is SampledFeatureTable and not has_sample_metadata:
        # Legacy trusted tables constructed directly by the engine/test bridge
        # predate sampler lineage. Keep their declared schema without inventing
        # an origin; the caller separately enforces the inherited 50000 cap.
        return columns, None
    if (type(table) is PendingSampledTable
            and not hasattr(table, "sample_spec_verified")
            and not hasattr(table, "sample_operations")):
        # Existing schema-only pending objects may be constructed directly for
        # dry-run bridge callers. Their supplied columns are usable, but the
        # unverified spec cannot authorize any table transformation.
        return columns, None
    if (type(table) is SampledFeatureTable and hasattr(table, "sample_spec")
            and verified is not True):
        raise ValueError("Actual sampled table carries an unverified origin specification")
    if not has_sample_metadata:
        raise ValueError("Pending Smile RF samples require a verified origin specification")
    if verified is not True or type(operations) is not tuple:
        raise ValueError("Sampled table requires a verified origin and operation chain")

    from .ee_sample_table_ops import _SampleOperationContext, _table_state

    audit = _SampleOperationContext(0)
    _, _, origin_spec, _ = _table_state(table, audit)
    budget.charge(audit.steps)
    return columns, origin_spec


def _check_training_columns(columns, decoded):
    missing = {decoded["class_property"], *decoded["schema"]} - set(columns)
    if missing:
        raise ValueError(f"Smile RF sample table is missing training field {sorted(missing)[0]!r}")


def _class_label(value):
    from gee.smile_rf_spec import MAX_CLASSES

    import math

    if type(value) is int:
        number = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        number = int(value)
    else:
        raise ValueError("Smile RF class labels must be finite integer values from 0 through 63")
    if not 0 <= number < MAX_CLASSES:
        raise ValueError("Smile RF class labels must be finite integer values from 0 through 63")
    return number


def _feature_rows(data, row_count, decoded, budget, origin_spec=None):
    from .ee_sample_table_ops import validate_sample_collection_metadata

    validate_sample_collection_metadata(data, origin_spec, budget.charge)
    if (data["type"] != "FeatureCollection"
            or type(data.get("features")) is not list or len(data["features"]) != row_count):
        raise ValueError("Smile RF requires the actual sampled FeatureCollection")
    schema = decoded["schema"]
    budget.charge(row_count * (len(schema) + 1))
    rows = []
    for feature in data["features"]:
        if (type(feature) is not dict
                or set(feature) != {"type", "id", "geometry", "properties"}
                or feature["type"] != "Feature" or type(feature["properties"]) is not dict):
            raise ValueError("Smile RF sample table contains an invalid Feature")
        properties = feature["properties"]
        if decoded["class_property"] not in properties:
            raise ValueError(f"Smile RF sample is missing class property {decoded['class_property']!r}")
        label = _class_label(properties[decoded["class_property"]])
        values = []
        for name in schema:
            if name not in properties:
                raise ValueError(f"Smile RF sample is missing input property {name!r}")
            values.append(properties[name])
        rows.append([label, values])
    return rows


def _rf_wire_upper_bound(row_count, input_count):
    """Bound canonical rows JSON without allocating or inspecting row values.

    Float repr is at most 25 ASCII characters; labels are 0..63. The fixed
    JSON punctuation and commas are included, so this safely reserves both
    serialization and decoder passes before those allocate a wire string/tree.
    """
    prefix = len('{"rows":[')
    suffix = len('],"version":1}')
    row_size = 26 * input_count + 6
    return prefix + row_count * row_size + max(0, row_count - 1) + suffix


def _sample_prior_work(table):
    from .ee_sample_table_ops import MAX_SAMPLE_TABLE_WORK

    prior_work = getattr(table, "sample_operation_work", 0)
    if (type(prior_work) is not int
            or not 0 <= prior_work <= min(MAX_SAMPLE_TABLE_WORK, MAX_RF_PRIOR_OPERATION_WORK)):
        raise ValueError("Sample table operation work must be an integer from 0 through 50000")
    return prior_work


def local_ee_train_smile_rf_samples(args, env):
    """Train from the exact actual sampled table or carry only a pending schema."""
    from .ee_process_adapters import _checked_args
    from gee.smile_rf_spec import (
        MAX_ROWS, decode_rf_rows, prepare_rf_rows, training_work_bound,
    )

    args = _checked_args(args, "local_ee_train_smile_rf_samples", {"data", "spec"})
    table = args["data"]
    if type(table) not in (SampledFeatureTable, PendingSampledTable):
        raise ValueError("Smile RF sample training requires a trusted sampled table")
    prior_work = _sample_prior_work(table)
    budget = _RuntimeWork(prior_work)
    wire_budget = _WireScan()
    decoded = _spec(args["spec"], wire_budget)
    columns, origin_spec = _table_schema(table, budget)
    _check_training_columns(columns, decoded)
    tracer = _dry_run_tracer(env)

    if type(table) is PendingSampledTable:
        if tracer is None or table.data_tracer is not tracer:
            raise ValueError("Pending Smile RF samples require their original dry-run tracer")
        return _pending(
            args["spec"], decoded, traces=table.traces, data_tracer=tracer,
        )

    row_count = table.row_count
    if type(row_count) is not int or not 2 <= row_count <= MAX_ROWS:
        raise ValueError("Smile RF sample training requires 2..1000 actual rows")
    training_work_bound(decoded, row_count)
    if tracer is not None:
        return _pending(
            args["spec"], decoded,
            traces=tuple(getattr(table, "traces", ())), data_tracer=tracer,
        )

    # SampledFeatureTable.data returns a deep copy. Charge its full declared
    # row/column shape before asking the property for that copy.
    copy_work = getattr(table, "data_copy_work", None)
    if type(copy_work) is not int or copy_work < 0:
        raise ValueError("Smile RF sample table is missing validated copy-work metadata")
    budget.charge(row_count * len(columns) + copy_work)
    data = table.data
    rows = _feature_rows(data, row_count, decoded, budget, origin_spec)

    row_cells = row_count * (len(decoded["schema"]) + 1)
    wire_upper = _rf_wire_upper_bound(row_count, len(decoded["schema"]))
    # Reserve the conservative byte bound and row shape independently before
    # prepare_rf_rows allocates its canonical JSON representation.
    budget.charge(row_cells)
    wire_budget.charge(wire_upper)
    rows_text = prepare_rf_rows(rows, decoded)
    if len(rows_text) > wire_upper:
        raise RuntimeError("Smile RF canonical rows exceeded the reserved wire bound")
    budget.charge(row_cells)
    wire_budget.charge(2 * wire_upper)
    decoded_rows = decode_rf_rows(rows_text, decoded)
    return _train(args["spec"], rows_text, decoded, decoded_rows)
