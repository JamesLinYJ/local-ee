"""Contracts for the dimension-changing trusted local EE process specs."""
import pytest

from gee import graph
from gee.backend import Processes
from gee.local_processes import EE_BAND_REDUCERS


def _graph(process_id, arguments):
    return {
        "load": {"process_id": "load_collection", "arguments": {"id": "sample"}},
        "local": {"process_id": process_id, "arguments": arguments, "result": True},
    }


@pytest.mark.parametrize(
    "process_id,arguments",
    [
        ("local_ee_drop_single_time", {"data": {"from_node": "load"}}),
        (
            "local_ee_reduce_bands",
            {"data": {"from_node": "load"}, "reducer": "median"},
        ),
    ],
)
def test_dimension_changing_processes_accept_only_canonical_cube_refs(process_id, arguments):
    graph.validate(_graph(process_id, arguments))


@pytest.mark.parametrize("reducer", sorted(EE_BAND_REDUCERS))
def test_every_shared_scalar_reducer_has_a_valid_public_contract(reducer):
    from engine.ee_process_adapters import EE_BAND_REDUCERS as engine_reducers

    assert engine_reducers == EE_BAND_REDUCERS
    graph.validate(_graph("local_ee_reduce_bands", {
        "data": {"from_node": "load"}, "reducer": reducer,
    }))


@pytest.mark.parametrize(
    "process_id,arguments",
    [
        ("local_ee_drop_single_time", {"data": {"from_node": "load"}, "axis": "t"}),
        ("local_ee_drop_single_time", {"data": "/tmp/input.tif"}),
        (
            "local_ee_reduce_bands",
            {"data": {"from_node": "load"}, "reducer": "mean", "callback": {"process_graph": {}}},
        ),
        ("local_ee_reduce_bands", {"data": {"from_node": "load"}, "reducer": "not_a_reducer"}),
        ("local_ee_reduce_bands", {"data": {"from_node": "load"}, "reducer": {"from_node": "load"}}),
    ],
)
def test_dimension_changing_processes_reject_unsupported_arguments(process_id, arguments):
    with pytest.raises(ValueError):
        graph.validate(_graph(process_id, arguments))


def test_dimension_changing_process_specs_advertise_the_native_contract():
    registry = Processes().get_process_registry("1.2.0")
    drop = registry.get_spec("local_ee_drop_single_time")
    reduce = registry.get_spec("local_ee_reduce_bands")

    assert [parameter["name"] for parameter in drop["parameters"]] == ["data"]
    assert [parameter["name"] for parameter in reduce["parameters"]] == ["data", "reducer"]
    assert set(reduce["parameters"][1]["schema"]["enum"]) == EE_BAND_REDUCERS
    assert drop["returns"]["schema"]["subtype"] == "raster-cube"
