"""Sampled row assembly, CSV serialization and typed result reconstruction."""
from __future__ import annotations

import os

import pytest

from ee_sampling_contract_helpers import (
    _feature,
    _read_csv_rows,
    _rewrite_csv,
    _row,
    _sample_text,
    _write_csv,
)
from gee.sampling_spec import (
    MAX_BANDS,
    MAX_BYTES,
    MAX_CELLS,
    MAX_COLUMNS,
    MAX_ROWS,
    decode_sampling_spec,
    sampling_columns,
)
from gee.sampling_values import (
    assemble_sample_features,
    read_sample_csv,
    render_sample_csv,
)


def test_assembled_rows_roundtrip_through_csv_preserving_nested_unicode_copied_types(tmp_path):
    properties = {
        "plot_id": '样地, "北区"\n二号',
        "landcover": 4,
        "rank": 7,
        "active": False,
        "nullable": None,
        "metadata": {"巡查员": "林", "flags": [True, None, {"from_node": "opaque"}]},
    }
    text = _sample_text(
        bands=["red", "nir"],
        properties=list(properties),
        geometries=True,
        features=[_feature(properties)],
    )
    spec = decode_sampling_spec(text)
    rows = [
        _row(col=0, values=[1.25, 2.5]),
        _row(col=1, x=1.5, values=[3.75, 4.0]),
    ]
    assembled = assemble_sample_features(spec, rows)
    csv_text = render_sample_csv(assembled, sampling_columns(spec))
    result_path = _write_csv(tmp_path / "samples.csv", csv_text)

    restored = read_sample_csv(result_path, spec)
    assert restored == assembled
    assert [feature["id"] for feature in restored["features"]] == [
        "f0_r0_c0", "f0_r0_c1",
    ]
    assert "system:index" not in restored["features"][0]["properties"]
    restored_properties = restored["features"][0]["properties"]
    assert type(restored_properties["landcover"]) is int
    assert type(restored_properties["active"]) is bool
    assert restored_properties["nullable"] is None
    assert restored_properties["metadata"]["巡查员"] == "林"
    assert restored["features"][0]["geometry"] == {
        "type": "Point", "coordinates": [0.5, 0.5],
    }


def test_sample_csv_roundtrip_without_geometry_and_empty_result_is_header_only(tmp_path):
    text = _sample_text(properties=["label"], geometries=False)
    spec = decode_sampling_spec(text)
    data = assemble_sample_features(spec, [_row(values=[9.5])])
    rendered = render_sample_csv(data, sampling_columns(spec))
    assert _read_csv_rows(rendered)[1][-1] == ""
    no_geometry = read_sample_csv(_write_csv(tmp_path / "no-geometry.csv", rendered), spec)
    assert no_geometry["features"][0]["geometry"] is None

    empty = assemble_sample_features(spec, [])
    header = render_sample_csv(empty, sampling_columns(spec))
    assert header == ",".join(sampling_columns(spec)) + "\r\n"
    assert read_sample_csv(_write_csv(tmp_path / "empty.csv", header), spec) == {
        "type": "FeatureCollection", "features": [],
    }


def test_sample_csv_columns_guard_rejects_invalid_selectors_as_value_errors(tmp_path):
    spec = decode_sampling_spec(_sample_text(properties=["label"]))
    data = assemble_sample_features(spec, [_row()])
    valid = sampling_columns(spec)
    invalid = [
        ["label", *valid[1:]],
        [*valid, "unknown"],
        ["system:index", "label", "label", "red", ".geo"],
        ["system:index", "label", [], "red", ".geo"],
        ["system:index", "label"],
        ["system:index", "label", "red", ".geo", *[f"c{i}" for i in range(253)]],
    ]
    for selectors in invalid:
        with pytest.raises(ValueError):
            render_sample_csv(data, selectors)


def test_sample_rows_reject_wrong_fields_order_coordinates_and_value_shape():
    spec = decode_sampling_spec(_sample_text(bands=["red", "nir"], geometries=True))
    valid = _row(values=[1.0, 2.0])
    invalid_rows = [
        {**valid, "unexpected": 1},
        {**valid, "feature": True},
        {**valid, "feature": 1},
        {**valid, "row": 2**53 + 1},
        {**valid, "col": -1},
        {**valid, "x": float("nan")},
        {**valid, "y": 91},
        {**valid, "values": [1.0]},
        {**valid, "values": [1.0, float("inf")]},
    ]
    for row in invalid_rows:
        with pytest.raises(ValueError):
            assemble_sample_features(spec, [row])

    first = _row(col=0, values=[1.0, 2.0])
    second = _row(col=1, x=1.5, values=[3.0, 4.0])
    with pytest.raises(ValueError, match="unique and ordered"):
        assemble_sample_features(spec, [second, first])
    with pytest.raises(ValueError, match="unique and ordered"):
        assemble_sample_features(spec, [first, first])


def test_sample_result_row_and_cell_budgets_enforce_exact_limits():
    spec = decode_sampling_spec(_sample_text())
    exact_rows = [
        _row(row=index, values=[float(index)]) for index in range(MAX_ROWS)
    ]
    assert len(assemble_sample_features(spec, exact_rows)["features"]) == MAX_ROWS
    with pytest.raises(ValueError, match="1000 result rows"):
        assemble_sample_features(spec, exact_rows + [_row(row=MAX_ROWS)])

    properties = [f"p{index:03}" for index in range(190)]
    prop_values = {name: 0 for name in properties}
    wide_spec = decode_sampling_spec(_sample_text(
        bands=[f"b{index:02}" for index in range(MAX_BANDS)],
        properties=properties,
        features=[_feature(prop_values)],
    ))
    columns = len(sampling_columns(wide_spec))
    assert columns == MAX_COLUMNS
    exact_cell_rows = [
        _row(row=index, values=[0] * MAX_BANDS)
        for index in range(MAX_CELLS // columns)
    ]
    assert len(assemble_sample_features(wide_spec, exact_cell_rows)["features"]) == MAX_CELLS // columns
    over_cell_rows = exact_cell_rows + [
        _row(row=len(exact_cell_rows), values=[0] * MAX_BANDS)
    ]
    with pytest.raises(ValueError, match="50000 result cells"):
        assemble_sample_features(wide_spec, over_cell_rows)


@pytest.mark.parametrize("change, message", [
    (lambda rows: rows[1].__setitem__(0, "f00_r0_c0"), "identifier"),
    (lambda rows: rows[1].__setitem__(0, "f1_r0_c0"), "feature index"),
    (lambda rows: rows.__setitem__(slice(1, 3), list(reversed(rows[1:3]))), "unique ordered identifiers"),
    (lambda rows: rows[2].__setitem__(0, rows[1][0]), "unique ordered identifiers"),
    (lambda rows: rows[1].__setitem__(1, "changed"), "copied properties differ"),
    (lambda rows: rows[0].__setitem__(1, "not-label"), "columns do not match"),
    (lambda rows: rows[1].append("extra"), "row or shape limits"),
    (lambda rows: rows[1].__setitem__(2, "nan"), "finite numbers"),
])
def test_sample_csv_reader_rechecks_ids_order_properties_shape_and_finite_bands(
    tmp_path, change, message,
):
    spec = decode_sampling_spec(_sample_text(properties=["label"], geometries=False))
    data = assemble_sample_features(spec, [
        _row(col=0, values=[1.0]),
        _row(col=1, x=1.5, values=[2.0]),
    ])
    valid = render_sample_csv(data, sampling_columns(spec))
    corrupted = _rewrite_csv(valid, change)
    path = _write_csv(tmp_path / "corrupted.csv", corrupted)

    with pytest.raises(ValueError, match=message):
        read_sample_csv(path, spec)


def test_sample_csv_reader_rejects_symlink_paths(tmp_path):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW is unavailable on this platform")
    spec = decode_sampling_spec(_sample_text())
    data = assemble_sample_features(spec, [_row()])
    target = _write_csv(tmp_path / "real.csv", render_sample_csv(data, sampling_columns(spec)))
    link = tmp_path / "link.csv"
    link.symlink_to(target)

    with pytest.raises(OSError):
        read_sample_csv(link, spec)


def test_sample_csv_reader_rejects_result_larger_than_one_megabyte(tmp_path):
    spec = decode_sampling_spec(_sample_text())
    data = assemble_sample_features(spec, [_row()])
    valid = render_sample_csv(data, sampling_columns(spec))
    path = _write_csv(tmp_path / "oversized.csv", valid + "x" * (MAX_BYTES + 1))

    with pytest.raises(ValueError, match="bounded regular result file"):
        read_sample_csv(path, spec)
