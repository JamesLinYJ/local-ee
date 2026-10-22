"""Canonical sampling specifications, geometry declarations and bounds."""
from __future__ import annotations

import json

import pytest

from ee_sampling_contract_helpers import (
    _encode_sample_object,
    _feature,
    _sample_object,
    _sample_text,
)
from gee.sampling_spec import (
    MAX_BANDS,
    MAX_BYTES,
    MAX_COLUMNS,
    MAX_ROWS,
    decode_sampling_spec,
    decode_training_spec,
    encode_spec,
    sampling_columns,
)


def test_sampling_spec_is_canonical_and_default_properties_preserve_first_seen_order():
    features = [
        _feature({
            "system:index": "original-0",
            "system:time_start": 10,
            "plot_id": "样地一",
            "quality": 3,
            "nested": {"notes": [True, None]},
        }),
        _feature({"plot_id": "样地二", "source": "tile-b"}, identifier="region-1"),
    ]
    text = _sample_text(features=features, bands=("nir", "red"))
    spec = decode_sampling_spec(text)

    assert text == encode_spec(json.loads(text))
    assert spec["properties"] == ["plot_id", "quality", "nested", "source"]
    assert set(spec["regions"]["features"][0]["properties"]) == set(spec["properties"])
    assert set(spec["regions"]["features"][1]["properties"]) == set(spec["properties"])
    assert spec["regions"]["features"][1]["properties"]["quality"] is None
    assert "system:index" not in spec["properties"]
    assert "system:time_start" not in spec["properties"]
    assert sampling_columns(spec) == [
        "system:index", "plot_id", "quality", "nested", "source", "nir", "red", ".geo",
    ]

    empty_copy = decode_sampling_spec(_sample_text(features=features, properties=[]))
    assert empty_copy["properties"] == []
    assert all(feature["properties"] == {} for feature in empty_copy["regions"]["features"])
    assert sampling_columns(empty_copy) == ["system:index", "red", ".geo"]


@pytest.mark.parametrize("text, message", [
    (_sample_text() + " ", "canonical"),
    (_sample_text()[:-1] + ',"version":1}', "Duplicate specification key"),
    (_sample_text().replace('"scale":null', '"scale":NaN'), "finite JSON"),
])
def test_sampling_spec_parser_requires_exact_canonical_finite_json(text, message):
    with pytest.raises(ValueError, match=message):
        decode_sampling_spec(text)


def test_sampling_and_training_spec_parser_enforces_utf8_byte_budget():
    with pytest.raises(ValueError, match="bounded"):
        decode_sampling_spec(" " * (MAX_BYTES + 1))
    with pytest.raises(ValueError, match="1 MB"):
        encode_spec({"payload": "x" * MAX_BYTES})

    text = encode_spec({
        "version": 1,
        "metric": "euclidean",
        "class_property": "label",
        "schema": ["red"],
    })
    with pytest.raises(ValueError, match="bounded"):
        decode_training_spec(" " * (MAX_BYTES + 1))
    assert decode_training_spec(text)["schema"] == ["red"]


@pytest.mark.parametrize("mutation, message", [
    (lambda obj: obj.update(version=True), "version"),
    (lambda obj: obj.update(extra=True), "fields or version"),
    (lambda obj: obj.update(bands=[]), "Sampling bands"),
    (lambda obj: obj.update(bands=[f"b{index}" for index in range(MAX_BANDS + 1)]), "Sampling bands"),
    (lambda obj: obj.update(bands=["red", "red"]), "Sampling bands"),
    (lambda obj: obj.update(bands=["red.nir"]), "Sampling bands"),
    (lambda obj: obj.update(bands=["system:index"]), "collide"),
    (lambda obj: obj.update(properties=["red"]), "collide"),
    (lambda obj: obj.update(properties=[".geo"]), "Copied properties"),
    (lambda obj: obj.update(properties=["system:index"]), "collide"),
    (lambda obj: obj.update(geometries=1), "boolean"),
])
def test_sampling_spec_rejects_bad_versions_names_collisions_and_types(mutation, message):
    spec = _sample_object()
    mutation(spec)
    with pytest.raises(ValueError, match=message):
        decode_sampling_spec(_encode_sample_object(spec))


@pytest.mark.parametrize("grid", [
    {"scale": True, "crs": None},
    {"scale": 0, "crs": None},
    {"scale": -1, "crs": None},
    {"scale": float("nan"), "crs": None},
    {"scale": float("inf"), "crs": None},
    {"scale": None, "crs": "EPSG:3857"},
    {"scale": 10, "crs": "EPSG:4326"},
    {"scale": 10, "crs": "EPSG:9999999"},
    {"scale": 10},
])
def test_sampling_grid_requires_positive_finite_meter_scale_and_supported_projection(grid):
    spec = _sample_object()
    spec["grid"] = grid
    with pytest.raises(ValueError):
        decode_sampling_spec(_encode_sample_object(spec))


def test_sampling_grid_accepts_scale_without_projection_or_projected_epsg():
    assert decode_sampling_spec(_sample_text(grid={"scale": 10, "crs": None}))[
        "grid"
    ] == {"scale": 10, "crs": None}
    assert decode_sampling_spec(_sample_text(grid={"scale": 30.5, "crs": "EPSG:3857"}))[
        "grid"
    ] == {"scale": 30.5, "crs": "EPSG:3857"}


@pytest.mark.parametrize("geometry", [
    None,
    {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
    {"type": "MultiPoint", "coordinates": []},
    {"type": "Point", "coordinates": [181, 0]},
    {"type": "Point", "coordinates": [0, float("inf")]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]},
])
def test_sampling_regions_reject_unsupported_empty_out_of_range_or_invalid_geometry(geometry):
    spec = _sample_object()
    spec["regions"]["features"][0]["geometry"] = geometry
    with pytest.raises(ValueError):
        decode_sampling_spec(_encode_sample_object(spec))


@pytest.mark.parametrize("geometry", [
    {"type": "Point", "coordinates": [1, 1]},
    {"type": "MultiPoint", "coordinates": [[0, 0], [1, 1]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
    {"type": "MultiPolygon", "coordinates": [[[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]]},
])
def test_sampling_regions_accept_the_four_declared_geometry_kinds(geometry):
    spec = _sample_object()
    spec["regions"]["features"][0]["geometry"] = geometry
    assert decode_sampling_spec(_encode_sample_object(spec))["regions"]["features"][0]["geometry"] == geometry


def test_sampling_regions_reject_feature_property_shape_mismatch_and_extra_fields():
    spec = _sample_object()
    spec["regions"]["features"][0]["properties"]["other"] = 2
    with pytest.raises(ValueError, match="exactly their declared"):
        decode_sampling_spec(_encode_sample_object(spec))

    spec = _sample_object()
    spec["regions"]["features"][0]["bbox"] = [0, 0, 1, 1]
    with pytest.raises(ValueError, match="Unsupported sampling feature field"):
        decode_sampling_spec(_encode_sample_object(spec))


def test_sampling_coordinate_and_source_feature_row_budgets_accept_boundary_and_reject_overflow():
    thousand = [_feature({}, identifier=f"r{index}") for index in range(MAX_ROWS)]
    spec = decode_sampling_spec(_sample_text(features=thousand, properties=[]))
    assert len(spec["regions"]["features"]) == MAX_ROWS

    too_many_rows = thousand + [_feature({}, identifier="r-over")]
    with pytest.raises(ValueError, match="1000"):
        decode_sampling_spec(_sample_text(features=too_many_rows, properties=[]))

    many_positions = []
    for feature_index in range(910):
        latitude = -4 + feature_index * 0.008
        coordinates = [
            [feature_index * 0.0001 + point_index * 0.001,
             latitude + point_index * 0.00001]
            for point_index in range(12)
        ]
        many_positions.append(_feature(
            {},
            {"type": "MultiPoint", "coordinates": coordinates},
            identifier=f"multipoint-{feature_index}",
        ))
    with pytest.raises(ValueError, match="10000 coordinate positions"):
        decode_sampling_spec(_sample_text(features=many_positions, properties=[]))


def test_sampling_column_and_input_cell_budgets_have_a_checked_boundary():
    properties = [f"p{index:03}" for index in range(190)]
    props = {name: index for index, name in enumerate(properties)}
    features = [_feature(props)]
    at_limit = decode_sampling_spec(_sample_text(
        bands=[f"b{index:02}" for index in range(MAX_BANDS)],
        properties=properties,
        features=features,
    ))
    assert len(sampling_columns(at_limit)) == MAX_COLUMNS

    over_limit = _sample_object(
        bands=[f"b{index:02}" for index in range(MAX_BANDS)],
        properties=properties,
        features=features,
    )
    over_limit["properties"].append("p190")
    over_limit["regions"]["features"][0]["properties"]["p190"] = 190
    with pytest.raises(ValueError, match="Copied properties"):
        decode_sampling_spec(_encode_sample_object(over_limit))

    fifty_columns = [f"p{index:02}" for index in range(49)]
    wide_properties = {name: 1 for name in fifty_columns}
    many_rows = [_feature(wide_properties, identifier=f"r{index}") for index in range(1000)]
    with pytest.raises(ValueError, match="50000 row-by-default-column cells"):
        decode_sampling_spec(_sample_text(
            bands=["red"], properties=fifty_columns, features=many_rows,
        ))
