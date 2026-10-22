"""Generated Feature.id values are visible to sampled Feature filters only."""
from __future__ import annotations

import pytest

from engine import ee_process_adapters as adapters
from engine.ee_sampling_result import SampledFeatureTable
from gee.compat.earthengine.ir import Filter
from gee.sample_table_spec import prepare_sample_filter
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from gee.sampling_values import render_sample_csv
from ee_sampling_bridge_helpers import _spec


def _table(*, include_invalid=False):
    sample_spec = _spec()
    columns = sampling_columns(decode_sampling_spec(sample_spec))
    identifiers = ["f0_r0_c0", "f0_r0_c1", "f0_r0_c2"]
    if include_invalid:
        identifiers.append("f999_r0_c0")
    features = [{
        "type": "Feature", "id": identifier,
        "geometry": {"type": "Point", "coordinates": [index + .5, 2.5]},
        "properties": {
            "plot_id": f"plot-{index}", "landcover": index % 2,
            "red": index + 1, "nir": index + 2,
        },
    } for index, identifier in enumerate(identifiers)]
    table = SampledFeatureTable(
        {"type": "FeatureCollection", "features": features}, columns,
    )
    table.sample_spec = sample_spec
    table.sample_spec_verified = True
    table.sample_operations = ()
    table.sample_operation_work = 0
    return table


@pytest.mark.parametrize(
    "predicate,expected,include_invalid",
    [
        (Filter("equals", {"leftField": "system:index", "rightValue": "f0_r0_c1"}),
         ["f0_r0_c1"], False),
        (Filter("notNull", {"properties": ["system:index"]}),
         ["f0_r0_c0", "f0_r0_c1", "f0_r0_c2"], True),
        (Filter("lessThan", {"leftField": "system:index", "rightValue": "f0_r0_c2"}),
         ["f0_r0_c0", "f0_r0_c1"], False),
        (Filter("stringContains", {"leftField": "system:index", "rightValue": "_c1"}),
         ["f0_r0_c1"], False),
    ],
)
def test_filter_predicates_see_only_valid_generated_system_index(predicate, expected, include_invalid):
    table = _table(include_invalid=include_invalid)
    original = table.data
    operation = prepare_sample_filter(predicate)

    result = adapters.local_ee_sample_table_op(
        {"data": table, "spec": operation}, env=None
    )

    rows = result.data["features"]
    assert [feature["id"] for feature in rows] == expected
    assert all("system:index" not in feature["properties"] for feature in rows)
    assert table.data == original
    csv_rows = render_sample_csv(result.data, result.columns).splitlines()
    assert csv_rows[0].startswith("system:index,")
    assert [line.split(",", 1)[0] for line in csv_rows[1:]] == expected
