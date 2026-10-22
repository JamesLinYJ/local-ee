"""Actual file roundtrips for new/overwritten columns, independent of pixel IO."""
import copy

import pytest

from ee_sampling_contract_helpers import POINT, _row, _sample_text, _write_csv
from gee.image_sampling_spec import prepare_image_sample_spec
from gee.random_column_spec import decode_random_column_spec, prepare_random_column_spec
from gee.random_column_values import apply_random_column
from gee.sample_table_schema import sampled_columns
from gee.sampling_spec import decode_sampling_spec
from gee.sampling_values import assemble_sample_features, read_sample_csv, render_sample_csv
from gee.services.ee_sample_results import read_result, result_context


def rows_and_spec(version=2):
    text = (prepare_image_sample_spec(POINT, ["nir", "red"], drop_nulls=False)
            if version == 2 else _sample_text(bands=["nir", "red"], properties=["label"]))
    spec = decode_sampling_spec(text)
    data = assemble_sample_features(spec, [_row(values=[2.25, 1.0000000000000002])])
    return text, spec, data


@pytest.mark.parametrize("version", [1, 2])
def test_new_and_overwritten_real_csv_columns_follow_full_lineage(tmp_path, version):
    _, origin, data = rows_and_spec(version)
    operations = [prepare_random_column_spec("split"),
                  prepare_random_column_spec("red", distribution="normal", row_keys=["split"])]
    if version == 1:
        operations.append(prepare_random_column_spec("label", row_keys=["nir"]))
    original = copy.deepcopy(data)
    for text in operations:
        data = {**data, "features": apply_random_column(data["features"], decode_random_column_spec(text))}
    path = _write_csv(tmp_path / "actual.csv", render_sample_csv(data, sampled_columns(origin, operations)))
    restored = read_sample_csv(path, origin, operations)
    assert restored == data
    assert restored["features"][0]["properties"]["red"] != original["features"][0]["properties"]["red"]
    if version == 1:
        assert type(restored["features"][0]["properties"]["label"]) is float
    else:
        assert restored["properties"] == {"band_order": ["nir", "red"]}
    with pytest.raises(ValueError, match="columns"):
        read_sample_csv(path, origin)


@pytest.mark.parametrize("cell", ["", "NaN", "Infinity", "-0.01", "1", "1.01", "true"])
def test_uniform_csv_cells_are_real_nonempty_finite_values_in_domain(tmp_path, cell):
    _, origin, _ = rows_and_spec()
    operations = [prepare_random_column_spec()]
    text = f"system:index,nir,red,random,.geo\r\nf0_r0_c0,1,2,{cell},\r\n"
    with pytest.raises(ValueError):
        read_sample_csv(_write_csv(tmp_path / "bad.csv", text), origin, operations)


def test_nullable_original_pixels_and_empty_normal_tables_keep_metadata(tmp_path):
    text, origin, _ = rows_and_spec()
    operation = prepare_random_column_spec("normal", distribution="normal")
    csv = "system:index,nir,red,normal,.geo\r\nf0_r0_c0,,2,-3.125,\r\n"
    restored = read_sample_csv(_write_csv(tmp_path / "nullable.csv", csv), origin, [operation])
    assert restored["features"][0]["properties"] == {"nir": None, "red": 2, "normal": -3.125}
    empty = assemble_sample_features(origin, [])
    headers = sampled_columns(origin, [operation])
    path = _write_csv(tmp_path / "empty.csv", render_sample_csv(empty, headers))
    assert read_sample_csv(path, origin, [operation]) == empty
    context = result_context({"sample_spec": text, "sample_operations": [operation]})
    assert context["sample_operations"] == [operation]


def test_owned_reader_uses_context_chain_and_rejects_undeclared_csv(tmp_path):
    text, origin, data = rows_and_spec()
    operation = prepare_random_column_spec()
    data = {**data, "features": apply_random_column(data["features"], decode_random_column_spec(operation))}
    context = {"protocol": "earthengine", **result_context({
        "sample_spec": text, "sample_operations": [operation]})}
    row = {"id": "0046cf2a-a26c-43a5-a4eb-65f328c0fb5c", "context": context,
           "assets": {"sample.csv": {}}}
    folder = tmp_path / "jobs" / row["id"] / "out"
    folder.mkdir(parents=True)
    _write_csv(folder / "sample.csv", render_sample_csv(data, sampled_columns(origin, [operation])))
    assert read_result(tmp_path, row) == data
    row["context"].pop("sample_operations")
    with pytest.raises(ValueError, match="columns"):
        read_result(tmp_path, row)
    with pytest.raises(ValueError, match="rowKeys"):
        result_context({"sample_spec": text, "sample_operations": [
            prepare_random_column_spec(row_keys=["missing"])]})
