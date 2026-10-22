"""Engine bridge regressions for randomColumn and real Image.sample metadata.

The RF calls in this file use an explicitly named Python proxy fixture. They
exercise the trusted bridge contracts, not a live JVM or Spark runtime.
"""
from __future__ import annotations

import hashlib
import math
import struct

import pytest

from engine import ee_process_adapters as adapters
from engine.ee_sampling_result import PendingSampledTable, SampledFeatureTable
from gee.image_sampling_spec import prepare_image_sample_spec
from gee.random_column_spec import (
    decode_random_column_spec,
    prepare_random_column_spec,
)
from gee.random_column_values import random_value
from gee.sampling_spec import (
    decode_sampling_spec,
    encode_spec,
    prepare_sampling_spec,
    sampling_columns,
)
from gee.sampling_values import assemble_sample_features


def _v1_table(*, region_properties=None, values=None):
    first = {"class": 0, "plot": "shared"}
    second = {"class": 1, "plot": "shared"}
    if region_properties is not None:
        first, second = region_properties
    regions = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {
            "type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        }, "properties": first},
        {"type": "Feature", "geometry": {
            "type": "Polygon", "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]],
        }, "properties": second},
    ]}
    text = prepare_sampling_spec(regions, ["red", "nir"], properties=list(first))
    spec = decode_sampling_spec(text)
    row_values = values or [[1.25, 2.5], [8.5, 9.25]]
    rows = [{
        "feature": index, "row": 0, "col": index,
        "x": index + 0.5, "y": 0.5, "values": row_values[index],
    } for index in range(2)]
    table = SampledFeatureTable(assemble_sample_features(spec, rows), sampling_columns(spec))
    _set_lineage(table, text)
    return table


def _v2_table(*, metadata=None):
    region = {"type": "Polygon", "coordinates": [
        [[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]],
    ]}
    text = prepare_image_sample_spec(region, ["class", "red"], geometries=True)
    spec = decode_sampling_spec(text)
    rows = [
        {"feature": 0, "row": 0, "col": 0, "x": 0.5, "y": 0.5, "values": [0, 1.25]},
        {"feature": 0, "row": 0, "col": 1, "x": 1.5, "y": 0.5, "values": [1, 8.5]},
    ]
    data = assemble_sample_features(spec, rows)
    if metadata is not None:
        data["properties"] = metadata
    table = SampledFeatureTable(data, sampling_columns(spec))
    _set_lineage(table, text)
    return table


def _set_lineage(table, sample_spec):
    table.sample_spec = sample_spec
    table.sample_spec_verified = True
    table.sample_operations = ()
    table.sample_operation_work = 0
    table.traces = (object(),)
    table.data_tracer = object()


def _independent_uniform(feature, spec):
    """Small independent oracle for the documented typed SHA-256 frame."""
    raw = bytearray(b"local-ee/randomColumn/sha256-rowkeys-v1\0")
    raw.extend(spec["seed"].to_bytes(8, "big", signed=True))
    raw.extend(len(spec["row_keys"]).to_bytes(4, "big"))
    for key in spec["row_keys"]:
        if key in feature["properties"]:
            value = feature["properties"][key]
        else:
            value = feature["id"]
        if type(value) is str:
            tag, payload = b"s", value.encode("utf-8")
        elif type(value) is bool:
            tag, payload = b"b", bytes([int(value)])
        else:
            number = float(value)
            tag, payload = b"n", struct.pack(">d", 0.0 if number == 0 else number)
        raw.extend(tag)
        raw.extend(len(payload).to_bytes(4, "big"))
        raw.extend(payload)
    digest = hashlib.sha256(raw).digest()
    return (int.from_bytes(digest[:8], "big") >> 11) * (2.0 ** -53)


def test_random_column_uses_typed_stable_row_keys_and_preserves_owned_table():
    table = _v1_table()
    original = table.data
    random_text = prepare_random_column_spec("split", seed=-19, row_keys=["plot"])
    random_spec = decode_random_column_spec(random_text)

    result = adapters.local_ee_sample_table_op({"data": table, "spec": random_text}, env=None)

    rows = result.data["features"]
    assert rows[0]["properties"]["split"] == _independent_uniform(original["features"][0], random_spec)
    assert rows[0]["properties"]["split"] == rows[1]["properties"]["split"]
    assert result.columns == [*table.columns[:-1], "split", ".geo"]
    assert result.sample_spec == table.sample_spec
    assert result.sample_spec_verified is True
    assert result.sample_operations == (random_text,)
    assert result.sample_operation_work > 0
    assert result.traces == table.traces
    assert result.data_tracer is table.data_tracer
    assert table.data == original
    assert rows[0]["id"] == original["features"][0]["id"]
    assert rows[0]["geometry"] == original["features"][0]["geometry"]
    assert rows[0]["properties"]["class"] == original["features"][0]["properties"]["class"]


def test_random_column_overwrite_keeps_header_position_and_chains_can_use_derived_keys():
    table = _v1_table()
    original_columns = table.columns
    overwrite = prepare_random_column_spec("red", seed=4, row_keys=["plot"])
    replaced = adapters.local_ee_sample_table_op({"data": table, "spec": overwrite}, env=None)
    assert replaced.columns == original_columns
    assert replaced.sample_operations == (overwrite,)
    assert all(type(row["properties"]["red"]) is float for row in replaced.data["features"])

    first = prepare_random_column_spec("split", seed=4, row_keys=["system:index"])
    second = prepare_random_column_spec("split2", seed=8, row_keys=["split"])
    once = adapters.local_ee_sample_table_op({"data": table, "spec": first}, env=None)
    twice = adapters.local_ee_sample_table_op({"data": once, "spec": second}, env=None)
    assert twice.columns == [*table.columns[:-1], "split", "split2", ".geo"]
    assert twice.sample_operations == (first, second)
    values = [row["properties"]["split2"] for row in twice.data["features"]]
    assert all(math.isfinite(value) for value in values)
    assert values[0] != values[1]


def test_random_column_rejects_reserved_or_missing_schema_keys_before_copy(monkeypatch):
    table = _v1_table()
    for name in ("system:index", ".geo"):
        with pytest.raises(ValueError, match="reserved"):
            prepare_random_column_spec(name)

    monkeypatch.setattr(SampledFeatureTable, "data", property(
        lambda _table: pytest.fail("invalid randomColumn must reject before copying rows"),
    ))
    with pytest.raises(ValueError, match="rowKeys must exist"):
        adapters.local_ee_sample_table_op({
            "data": table,
            "spec": prepare_random_column_spec("split", row_keys=["missing"]),
        }, env=None)


@pytest.mark.parametrize("key", [None, ["mutable"], {"nested": 1}])
def test_random_column_rejects_null_or_container_row_keys_without_mutating_input(key):
    table = _v1_table(region_properties=(
        {"class": 0, "plot": key}, {"class": 1, "plot": key},
    ))
    original = table.data
    with pytest.raises(ValueError, match="row keys"):
        adapters.local_ee_sample_table_op({
            "data": table,
            "spec": prepare_random_column_spec("split", row_keys=["plot"]),
        }, env=None)
    assert table.data == original


def test_random_column_rejects_new_column_when_declared_schema_is_full(monkeypatch):
    from gee.sampling_values import assemble_sample_features

    copied = {f"property_{index}": index for index in range(253)}
    regions = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": {
            "type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        }, "properties": copied,
    }]}
    text = prepare_sampling_spec(regions, ["red"], properties=list(copied))
    origin = decode_sampling_spec(text)
    row = {"feature": 0, "row": 0, "col": 0, "x": 0.5, "y": 0.5, "values": [1]}
    table = SampledFeatureTable(
        assemble_sample_features(origin, [row]), sampling_columns(origin),
    )
    _set_lineage(table, text)
    assert len(table.columns) == 256
    monkeypatch.setattr(SampledFeatureTable, "data", property(
        lambda _table: pytest.fail("schema overflow must reject before copying rows"),
    ))
    with pytest.raises(ValueError, match="exceeds256 columns"):
        adapters.local_ee_sample_table_op({
            "data": table, "spec": prepare_random_column_spec("extra"),
        }, env=None)


def test_random_column_obeys_table_work_budget_before_reading_rows(monkeypatch):
    table = _v1_table()
    table.sample_operation_work = 50_000
    monkeypatch.setattr(SampledFeatureTable, "data", property(
        lambda _table: pytest.fail("over-budget randomColumn must reject before copying rows"),
    ))
    with pytest.raises(ValueError, match="50000-step work budget"):
        adapters.local_ee_sample_table_op({
            "data": table, "spec": prepare_random_column_spec("split"),
        }, env=None)


def test_random_column_pending_schema_adds_columns_without_materializing_or_hashing(monkeypatch):
    actual = _v2_table()
    origin = decode_sampling_spec(actual.sample_spec)
    pending = PendingSampledTable(
        columns=tuple(sampling_columns(origin)), sample_spec=actual.sample_spec,
        traces=(object(),), data_tracer=object(),
    )
    pending.sample_spec_verified = True
    pending.sample_operations = ()
    pending.sample_operation_work = 0
    monkeypatch.setattr(
        "gee.random_column_values.apply_random_column",
        lambda *_args, **_kwargs: pytest.fail("pending table must not hash or fabricate rows"),
    )
    operation = prepare_random_column_spec("split", row_keys=["system:index"])

    result = adapters.local_ee_sample_table_op({"data": pending, "spec": operation}, env=None)

    assert type(result) is PendingSampledTable
    assert result.columns == (*pending.columns[:-1], "split", ".geo")
    assert result.sample_operations == (operation,)
    assert result.sample_operation_work > 0
    assert not hasattr(result, "data")


def test_random_column_numeric_row_keys_normalize_int_float_but_keep_bool_typed():
    spec = decode_random_column_spec(prepare_random_column_spec(row_keys=["key"]))
    integer = {"type": "Feature", "properties": {"key": 7}}
    floating = {"type": "Feature", "properties": {"key": 7.0}}
    boolean = {"type": "Feature", "properties": {"key": True}}
    assert random_value(integer, spec) == random_value(floating, spec)
    assert random_value(boolean, spec) != random_value(integer, spec)
    for invalid in (None, [], {}, float("inf"), 2**53 + 1):
        with pytest.raises(ValueError, match="row keys"):
            random_value({"properties": {"key": invalid}}, spec)


def test_random_column_accepts_sixteen_completed_operations_in_consumers(monkeypatch):
    from ee_smile_rf_engine_helpers import install_factory, spec as rf_spec
    from gee.sample_table_spec import prepare_sample_limit

    table = _v1_table()
    limit = prepare_sample_limit(None)
    for _ in range(16):
        table = adapters.local_ee_sample_table_op({"data": table, "spec": limit}, env=None)
    assert len(table.sample_operations) == 16
    calls = install_factory(monkeypatch)
    model = adapters.local_ee_train_smile_rf_samples({
        "data": table,
        "spec": rf_spec(schema=("red", "nir"), class_property="class"),
    }, env=None)
    assert model.schema == ("red", "nir")
    assert len(calls) == 1


def test_image_sample_v2_band_order_metadata_is_validated_and_random_schema_reaches_rf(monkeypatch):
    from ee_smile_rf_engine_helpers import install_factory, spec as rf_spec
    from engine import ee_rf_validation, ee_rf_validation_runtime
    from gee.rf_validation_spec import prepare_classify_spec, prepare_matrix_spec
    from engine.ee_json_result import RuntimeFeatureTable

    table = _v2_table()
    operation = prepare_random_column_spec("split", seed=42, row_keys=["system:index"])
    table = adapters.local_ee_sample_table_op({"data": table, "spec": operation}, env=None)
    training_spec = rf_spec(schema=("split",), class_property="class")
    calls = install_factory(monkeypatch)

    model = adapters.local_ee_train_smile_rf_samples(
        {"data": table, "spec": training_spec}, env=None,
    )

    assert len(calls) == 1
    assert table.data["properties"] == {"band_order": ["class", "red"]}
    headers = [*table.columns[:-1], "prediction", ".geo"]
    classify_spec = prepare_classify_spec("prediction", headers)
    monkeypatch.setattr(
        ee_rf_validation_runtime, "_predict_jvm_rows",
        lambda _model, _rows: encode_spec({"version": 1, "predictions": [0, 1]}),
    )
    classified = ee_rf_validation.local_ee_smile_rf_classify_samples({
        "data": table, "spec": classify_spec, "model": model,
    }, env=None)
    assert type(classified) is RuntimeFeatureTable
    assert classified.columns == headers
    assert classified.data["properties"] == {"band_order": ["class", "red"]}
    matrix = ee_rf_validation.local_ee_error_matrix({
        "data": classified,
        "spec": prepare_matrix_spec("class", "prediction", [0, 1]),
    }, env=None)
    assert matrix._value.order == (0, 1)
    assert matrix._value.matrix.data.tolist() == [[1, 0], [0, 1]]


@pytest.mark.parametrize("metadata", [
    {"band_order": ["red", "class"]},
    {"band_order": ["class", "red"], "invented": [1]},
    {"band_order": "class,red"},
])
def test_rf_rejects_unproven_image_sample_metadata_before_java(monkeypatch, metadata):
    from ee_smile_rf_engine_helpers import install_factory, spec as rf_spec

    table = _v2_table(metadata=metadata)
    calls = install_factory(monkeypatch)
    with pytest.raises(ValueError, match="band_order|FeatureCollection fields"):
        adapters.local_ee_train_smile_rf_samples({
            "data": table,
            "spec": rf_spec(schema=("red",), class_property="class"),
        }, env=None)
    assert calls == []


def test_minimum_distance_training_reads_transformed_sample_columns():
    from ee_sampling_bridge_helpers import _training_spec

    table = _v1_table()
    operation = prepare_random_column_spec("split", row_keys=["system:index"])
    table = adapters.local_ee_sample_table_op({"data": table, "spec": operation}, env=None)
    model = adapters.local_ee_train_minimum_distance({
        "data": table, "spec": _training_spec(schema=["split"], class_property="class"),
    }, env=None)
    assert model["schema"] == ["split"]


def test_v1_sample_feature_collection_without_collection_metadata_remains_valid(monkeypatch):
    from ee_smile_rf_engine_helpers import install_factory, spec as rf_spec

    table = _v1_table()
    assert "properties" not in table.data
    calls = install_factory(monkeypatch)
    model = adapters.local_ee_train_smile_rf_samples({
        "data": table,
        "spec": rf_spec(schema=("red", "nir"), class_property="class"),
    }, env=None)
    assert model.schema == ("red", "nir")
    assert len(calls) == 1
