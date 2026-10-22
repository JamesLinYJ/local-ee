"""Nullable actual-row and physical CSV roundtrips, separate from pixel execution."""
from __future__ import annotations

import pytest

from ee_sampling_contract_helpers import POINT, _row, _sample_text, _write_csv
from gee.image_sampling_spec import prepare_image_sample_spec
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from gee.sampling_values import assemble_sample_features, read_sample_csv, render_sample_csv
from gee.services.ee_sample_results import read_result, result_context


def image_spec(**options):
    return decode_sampling_spec(prepare_image_sample_spec(POINT, ["nir", "red"], **options))


@pytest.mark.parametrize("geometries", [True, False])
def test_actual_values_and_nulls_survive_csv_without_fabrication(tmp_path, geometries):
    spec = image_spec(drop_nulls=False, geometries=geometries)
    rows = [_row(values=[None, 1.0000000000000002]),
            _row(col=1, x=1.5, values=[-3.25, None]),
            _row(col=2, x=2.5, values=[None, None])]
    data = assemble_sample_features(spec, rows)
    assert data["properties"] == {"band_order": ["nir", "red"]}
    assert data["features"][0]["properties"] == {"nir": None, "red": 1.0000000000000002}
    assert data["features"][0]["geometry"] == (POINT if geometries else None)
    text = render_sample_csv(data, sampling_columns(spec))
    path = _write_csv(tmp_path / "nullable.csv", text)
    assert read_sample_csv(path, spec) == data
    data["features"][0]["properties"]["red"] = 12345
    assert read_sample_csv(path, spec)["features"][0]["properties"]["red"] == 1.0000000000000002


@pytest.mark.parametrize("spec", [
    image_spec(), decode_sampling_spec(_sample_text(bands=["nir", "red"])),
])
def test_default_and_v1_results_never_accept_null_cells(tmp_path, spec):
    with pytest.raises(ValueError, match="finite numbers"):
        assemble_sample_features(spec, [_row(values=[None, 2])])
    text = "system:index,nir,red,.geo\r\nf0_r0_c0,,2,\r\n"
    with pytest.raises(ValueError):
        read_sample_csv(_write_csv(tmp_path / "bad.csv", text), spec)


@pytest.mark.parametrize("values", [[True, None], [float("inf"), None],
                                   [float("nan"), None], ["2", None]])
def test_nullable_rows_still_reject_non_numeric_non_null_values(values):
    with pytest.raises(ValueError):
        assemble_sample_features(image_spec(drop_nulls=False), [_row(values=values)])


def test_empty_results_retain_only_declared_metadata(tmp_path):
    spec = image_spec(num_pixels=0, drop_nulls=False)
    data = assemble_sample_features(spec, [])
    assert data == {"type": "FeatureCollection", "features": [],
                    "properties": {"band_order": ["nir", "red"]}}
    path = _write_csv(tmp_path / "empty.csv", render_sample_csv(data, sampling_columns(spec)))
    assert read_sample_csv(path, spec) == data


def test_result_reader_uses_owned_physical_file_and_spec_metadata(tmp_path):
    spec = image_spec(drop_nulls=False)
    text = prepare_image_sample_spec(POINT, ["nir", "red"], drop_nulls=False)
    context = {"protocol": "earthengine", **result_context({"sample_spec": text})}
    row = {"id": "44e3e0b7-89c7-4ea2-92e2-67fa74cd5cab", "context": context,
           "assets": {"openEO.csv": {}}}
    folder = tmp_path / "jobs" / row["id"] / "out"
    folder.mkdir(parents=True)
    data = assemble_sample_features(spec, [_row(values=[None, 2.125])])
    target = _write_csv(folder / "openEO.csv", render_sample_csv(data, sampling_columns(spec)))
    assert read_result(tmp_path, row) == data
    target.unlink()
    outside = _write_csv(tmp_path / "other.csv", "system:index,nir,red,.geo\r\n")
    target.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        read_result(tmp_path, row)
