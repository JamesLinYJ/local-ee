"""Runtime filter/limit bridges for typed sampled-feature tables."""
from __future__ import annotations

import types

import pytest

from engine import ee_process_adapters as adapters
from engine.ee_sampling_result import PendingSampledTable, SampledFeatureTable
from gee.compat.earthengine.ir import Filter
from gee.sample_table_spec import prepare_sample_filter, prepare_sample_limit
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from ee_sampling_bridge_helpers import _dry_cube, _spec, _training_spec


def _features():
    rows = [(None, 0, 1), (0, 2, 3), (1, 4, 5)]
    return [{
        "type": "Feature",
        "id": f"f0_r0_c{index}",
        "geometry": {"type": "Point", "coordinates": [index + .5, 2.5]},
        "properties": {
            "plot_id": f"plot-{index}", "landcover": label,
            "red": red, "nir": nir,
        },
    } for index, (label, red, nir) in enumerate(rows)]


def _actual_table(*, operation_work=0, features=None):
    sample_spec = _spec()
    decoded = decode_sampling_spec(sample_spec)
    table = SampledFeatureTable(
        {"type": "FeatureCollection", "features": _features() if features is None else features},
        sampling_columns(decoded),
    )
    table.sample_spec = sample_spec
    table.sample_spec_verified = True
    table.sample_operations = ()
    table.sample_operation_work = operation_work
    table.traces = (object(),)
    table.data_tracer = object()
    return table


def test_filter_skips_unknown_keeps_order_and_returns_a_new_owned_table():
    table = _actual_table()
    original = table.data
    filt = prepare_sample_filter(Filter("lessThan", {
        "leftField": "landcover", "rightValue": 1,
    }))

    result = adapters.local_ee_sample_table_op(
        {"data": table, "spec": filt}, env=None
    )

    assert type(result) is SampledFeatureTable
    assert result is not table
    assert [feature["id"] for feature in result.data["features"]] == ["f0_r0_c1"]
    assert result.data["features"][0]["geometry"] == original["features"][1]["geometry"]
    assert result.data["features"][0]["properties"] == original["features"][1]["properties"]
    assert table.data == original
    assert result.columns == table.columns
    assert result.sample_spec == table.sample_spec
    assert result.sample_spec_verified is True
    assert result.sample_operations == (filt,)
    assert result.sample_operation_work > 0
    assert result.traces == table.traces
    assert result.data_tracer is table.data_tracer


@pytest.mark.parametrize("count,expected", [(None, 3), (0, 0), (2, 2)])
def test_limit_preserves_native_order_and_zero_is_empty(count, expected):
    table = _actual_table()
    result = adapters.local_ee_sample_table_op(
        {"data": table, "spec": prepare_sample_limit(count)}, env=None
    )
    assert [feature["id"] for feature in result.data["features"]] == [
        feature["id"] for feature in table.data["features"][:expected]
    ]
    assert result.sample_spec == table.sample_spec


def test_actual_filter_then_limit_stays_trainable_as_the_same_table_type():
    table = _actual_table(features=_features()[1:])
    filtered = adapters.local_ee_sample_table_op({
        "data": table,
        "spec": prepare_sample_filter(Filter("greaterThan", {
            "leftField": "red", "rightValue": 0,
        })),
    }, env=None)
    result = adapters.local_ee_sample_table_op({
        "data": filtered, "spec": prepare_sample_limit(2),
    }, env=None)

    assert type(result) is SampledFeatureTable
    assert [feature["id"] for feature in result.data["features"]] == [
        "f0_r0_c1", "f0_r0_c2",
    ]
    assert len(result.sample_operations) == 2
    model = adapters.local_ee_train_minimum_distance(
        {"data": result, "spec": _training_spec()}, env=None
    )
    assert model["schema"] == ["red", "nir"]
    assert model["labels"] == [0, 1]


def test_pending_chain_is_save_result_compatible_and_keeps_source_traces():
    from openeo_driver.processgraph.evaluator import convert_node
    from openeo_driver.processgraph.process_implementations.io import save_result
    from openeo_driver.processgraph.registry import ENV_DRY_RUN_TRACER, ENV_SAVE_RESULT
    from openeo_driver.processes import ProcessRegistry
    from openeo_driver.utils import EvalEnv

    registry = ProcessRegistry(argument_names=["args", "env"])
    registry.add_hidden(adapters.local_ee_sample_regions)
    registry.add_hidden(adapters.local_ee_sample_table_op)
    registry.add_hidden(save_result)
    backend = types.SimpleNamespace(
        processing=types.SimpleNamespace(get_process_registry=lambda api_version: registry),
        summarize_exception=lambda error: None,
    )
    training, source, tracer = _dry_cube()
    saved_results = []
    env = EvalEnv({
        "backend_implementation": backend,
        "version": "1.2.0", "openeo_api_version": "1.2.0", "node_caching": False,
        ENV_DRY_RUN_TRACER: tracer, ENV_SAVE_RESULT: saved_results,
    })
    filter_text = prepare_sample_filter(Filter("greaterThan", {
        "leftField": "red", "rightValue": 0,
    }))
    limit_text = prepare_sample_limit(0)
    sample = {
        "process_id": "local_ee_sample_regions",
        "arguments": {"data": training, "spec": _spec()},
    }
    filtered = {
        "process_id": "local_ee_sample_table_op",
        "arguments": {"data": sample, "spec": filter_text},
    }
    limited = {
        "process_id": "local_ee_sample_table_op",
        "arguments": {"data": filtered, "spec": limit_text},
    }
    graph = {"process_id": "save_result", "arguments": {"data": limited, "format": "CSV"}}

    result = convert_node(graph, env=env)

    assert isinstance(result, PendingSampledTable)
    assert result is saved_results[0]
    assert result.format == "CSV"
    assert result.columns == tuple(sampling_columns(decode_sampling_spec(_spec())))
    assert result.sample_spec == _spec()
    assert result.sample_operations == (filter_text, limit_text)
    assert result.traces == (source,)
    assert result.data_tracer is tracer
    assert not hasattr(result, "data")
    with pytest.raises(ValueError, match="cannot be written"):
        result.write_assets("/tmp/out")


def test_operations_require_verified_origin_and_matching_declared_columns():
    table = _actual_table()
    del table.sample_spec_verified
    with pytest.raises(ValueError, match="original sampling specification"):
        adapters.local_ee_sample_table_op(
            {"data": table, "spec": prepare_sample_limit(1)}, env=None
        )
    table = _actual_table()
    table._columns = ("wrong",)
    with pytest.raises(ValueError, match="columns differ"):
        adapters.local_ee_sample_table_op(
            {"data": table, "spec": prepare_sample_limit(1)}, env=None
        )


@pytest.mark.parametrize(
    "args,pattern",
    [
        ({"data": None, "spec": "{}", "extra": 1}, "accepts exactly"),
        ({"data": None, "spec": {}}, "canonical JSON text"),
        ({"data": {"type": "FeatureCollection", "features": []},
          "spec": prepare_sample_limit(1)}, "actual or pending sampled table"),
    ],
)
def test_operations_recheck_argument_shape_and_table_type(args, pattern):
    if args["data"] is None:
        args["data"] = _actual_table()
    with pytest.raises((ValueError, TypeError), match=pattern):
        adapters.local_ee_sample_table_op(args, env=None)


def test_operations_enforce_chain_and_cumulative_work_budgets():
    table = _actual_table()
    table.sample_operations = (prepare_sample_limit(1),) * 16
    with pytest.raises(ValueError, match="16 operations"):
        adapters.local_ee_sample_table_op(
            {"data": table, "spec": prepare_sample_limit(1)}, env=None
        )

    table = _actual_table(operation_work=50_000)
    filt = prepare_sample_filter(Filter("equals", {
        "leftField": "plot_id", "rightValue": "plot-0",
    }))
    with pytest.raises(ValueError, match="work budget"):
        adapters.local_ee_sample_table_op({"data": table, "spec": filt}, env=None)


def test_training_continues_operation_work_instead_of_resetting_budget():
    table = _actual_table(operation_work=50_000, features=_features()[1:])
    with pytest.raises(ValueError, match="work budget"):
        adapters.local_ee_train_minimum_distance(
            {"data": table, "spec": _training_spec()}, env=None
        )


def test_sample_table_operations_are_registered_in_both_trusted_registries(monkeypatch):
    class Registry:
        def __init__(self):
            self.handlers = {}

        def contains(self, name):
            return name in self.handlers

        def get_function(self, name):
            return self.handlers[name]

        def add_hidden(self, handler):
            self.handlers[handler.__name__] = handler

    import openeo_driver.processgraph.registry as registries

    first, second = Registry(), Registry()
    monkeypatch.setattr(registries, "process_registry_100", first)
    monkeypatch.setattr(registries, "process_registry_2xx", second)
    adapters.register_local_ee_processes()
    assert first.get_function("local_ee_sample_table_op") is adapters.local_ee_sample_table_op
    assert second.get_function("local_ee_sample_table_op") is adapters.local_ee_sample_table_op
