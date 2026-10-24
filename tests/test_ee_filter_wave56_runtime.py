"""Wave56 filter execution through sampled and classified table consumers."""
from __future__ import annotations

import json

import pytest

from engine import ee_process_adapters as adapters
from engine.ee_json_result import RuntimeFeatureTable, attach_classification_origin
from engine.ee_sampling_result import SampledFeatureTable
from gee.compat.earthengine.ir import Filter
from gee.sample_table_spec import decode_sample_operation, prepare_sample_filter
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from gee.rf_validation_spec import prepare_classify_spec
from ee_sampling_bridge_helpers import _spec

def _sample_table(*, empty=False, null_geometry=False):
    from pathlib import Path

    source = json.loads(Path(__file__).with_name("fixtures").joinpath(
        "ee-sampling-training-v1.json").read_text())
    features = [] if empty else [
        {
            "type": "Feature", "id": f"f0_r0_c{index}",
            "geometry": (None if null_geometry and index == 1 else {
                "type": "Point", "coordinates": [index + .5, 2.5],
            }),
            "properties": {
                "plot_id": tag, "landcover": index,
                "red": index + 1, "nir": index + 2,
            },
        }
        for index, tag in enumerate(("plot-east", "road-north", "plot-west"))
    ]
    sample_spec = _spec()
    table = SampledFeatureTable(
        {"type": "FeatureCollection", "features": features},
        sampling_columns(decode_sampling_spec(sample_spec)),
    )
    table.sample_spec = sample_spec
    table.sample_spec_verified = True
    table.sample_operations = ()
    table.sample_operation_work = 0
    return table


def test_sampled_table_consumes_string_filters_and_preserves_ids_geometry_and_properties():
    table = _sample_table()
    original = table.data
    spec = prepare_sample_filter(Filter("stringStartsWith", {
        "leftField": "plot_id", "rightValue": "plot-",
    }))
    result = adapters.local_ee_sample_table_op({"data": table, "spec": spec}, env=None)

    assert [row["id"] for row in result.data["features"]] == ["f0_r0_c0", "f0_r0_c2"]
    assert result.data["features"][0]["geometry"] == original["features"][0]["geometry"]
    assert result.data["features"][0]["properties"] == original["features"][0]["properties"]
    assert table.data == original
    assert result.sample_operations == (spec,)


def _runtime_table(*, empty=False, null_geometry=False):
    headers = ["system:index", "plot_id", "truth", "reflectance", "prediction", ".geo"]
    features = [] if empty else [
        {
            "type": "Feature", "id": f"classified-{index}",
            "geometry": (None if null_geometry and index == 1 else {
                "type": "Point", "coordinates": [index + .25, 5.5],
            }),
            "properties": {
                "plot_id": tag, "truth": index % 2,
                "reflectance": index + .5, "prediction": index % 2,
            },
        }
        for index, tag in enumerate(("field-east-a", "road-north", "field-west-b"))
    ]
    table = RuntimeFeatureTable({
        "type": "FeatureCollection", "properties": {"band_order": ["reflectance"]},
        "features": features,
    }, headers)
    attach_classification_origin(table, prepare_classify_spec("prediction", headers))
    return table


def test_classified_runtime_table_consumes_string_filters_on_actual_rows():
    table = _runtime_table()
    original = table.data
    spec = prepare_sample_filter(Filter("stringEndsWith", {
        "leftField": "plot_id", "rightValue": "b",
    }))
    result = adapters.local_ee_runtime_table_op({"data": table, "spec": spec}, env=None)

    assert [row["id"] for row in result.data["features"]] == ["classified-2"]
    assert result.data["features"][0]["geometry"] == original["features"][2]["geometry"]
    assert result.data["properties"] == original["properties"]
    assert table.data == original
    assert result.runtime_operations == (spec,)


def test_has_geometry_runs_on_actual_sampled_and_classified_rows():
    predicate = prepare_sample_filter(Filter("hasGeometry", {}))
    sampled = _sample_table(null_geometry=True)
    sampled_result = adapters.local_ee_sample_table_op(
        {"data": sampled, "spec": predicate}, env=None,
    )
    assert [feature["id"] for feature in sampled_result.data["features"]] == [
        "f0_r0_c0", "f0_r0_c2",
    ]

    classified = _runtime_table(null_geometry=True)
    classified_result = adapters.local_ee_runtime_table_op(
        {"data": classified, "spec": predicate}, env=None,
    )
    assert [feature["id"] for feature in classified_result.data["features"]] == [
        "classified-0", "classified-2",
    ]


@pytest.mark.parametrize("runtime", [False, True])
@pytest.mark.parametrize("predicate", [
    {"name": "hasType", "arguments": {
        "leftField": "landcover", "rightValue": "Integer",
    }},
    {"name": "stringStartsWith", "arguments": {
        "leftField": "plot_id", "rightValue": 7,
    }},
    {"name": "greaterThan", "arguments": {
        "leftField": "plot_id", "rightValue": True,
    }},
    {"name": "stringContains", "arguments": {
        "leftField": "plot_id", "rightValue": 7,
    }},
])
def test_unsupported_or_mistyped_filters_reject_before_empty_table_bypass(runtime, predicate):
    from gee.sampling_spec import encode_spec

    wire = encode_spec({
        "version": 1, "operation": "filter", "predicate": predicate,
    })
    table = _runtime_table(empty=True) if runtime else _sample_table(empty=True)
    operation = adapters.local_ee_runtime_table_op if runtime else adapters.local_ee_sample_table_op
    with pytest.raises((ValueError, TypeError), match="Unsupported|hasType|string|filter"):
        operation({"data": table, "spec": wire}, env=None)


def test_sample_filter_aliases_are_stored_as_canonical_ir_data():
    text = prepare_sample_filter(Filter("gte", {
        "leftField": "cloud_cover", "rightValue": 10,
    }))
    operation = decode_sample_operation(text)
    assert operation["predicate"] == {
        "name": "not", "arguments": {"filter": {
            "name": "lessThan", "arguments": {
                "leftField": "cloud_cover", "rightValue": 10,
            },
        }},
    }
