"""Trusted bridge checks for one-band EE remapping."""
from __future__ import annotations

import pytest

from engine import ee_process_adapters as adapters
from gee.remap_spec import prepare_remap_spec
from ee_sampling_bridge_helpers import _dry_cube, _metadata
from openeo_driver.errors import ProcessParameterInvalidException


def test_remap_dry_run_changes_only_band_schema_and_preserves_source_trace():
    cube, source, tracer = _dry_cube(bands=("red",))

    result = adapters.local_ee_remap({
        "data": cube,
        "spec": prepare_remap_spec([1, 2], [4, 5], default=0),
    }, env=None)

    assert result.metadata.band_names == ["v"]
    assert result._traces == [source]
    assert result._data_tracer is tracer


def test_remap_actual_cube_forwards_canonical_spec_and_single_band_metadata(monkeypatch):
    from openeo_driver.datacube import DriverDataCube

    cube = DriverDataCube(metadata=_metadata(("source",), temporal=True))
    text = prepare_remap_spec([0, 1.5], [-1, 3], default=8)
    calls = []

    def apply(actual, process_id, arguments, metadata, *, target_type=None):
        calls.append((actual, process_id, arguments, metadata, target_type))
        return "native-result"

    monkeypatch.setattr(adapters, "_apply_native", apply)
    result = adapters.local_ee_remap({"data": cube, "spec": text}, env=None)

    assert result == "native-result"
    assert len(calls) == 1
    actual, process_id, arguments, metadata, target_type = calls[0]
    assert (actual, process_id, arguments, target_type) == (
        cube, "local_ee_remap", {"spec": text}, None,
    )
    assert metadata.band_names == ["v"]
    assert metadata.has_temporal_dimension()


@pytest.mark.parametrize(
    "args,pattern",
    [
        ({"data": None, "spec": "{}", "extra": 1}, "accepts exactly"),
        ({"data": None, "spec": {}}, "canonical JSON text"),
        ({"data": "not-a-cube", "spec": prepare_remap_spec([], [])}, "raster cube"),
    ],
)
def test_remap_rejects_invalid_args_before_native_execution(args, pattern):
    if args["data"] is None:
        from openeo_driver.datacube import DriverDataCube

        args["data"] = DriverDataCube(metadata=_metadata(("red",)))
    with pytest.raises((ValueError, TypeError, ProcessParameterInvalidException), match=pattern):
        adapters.local_ee_remap(args, env=None)


@pytest.mark.parametrize("bands", [(), ("red", "nir")])
def test_remap_requires_exactly_one_explicit_source_band(bands):
    cube, _, _ = _dry_cube(bands=bands)
    with pytest.raises(ValueError, match="exactly one named source band"):
        adapters.local_ee_remap(
            {"data": cube, "spec": prepare_remap_spec([], [])}, env=None
        )


def test_remap_validates_mapping_lengths_before_native_execution():
    cube, _, _ = _dry_cube(bands=("red",))
    with pytest.raises(ValueError, match="equal-length"):
        adapters.local_ee_remap({
            "data": cube,
            "spec": '{"default":null,"from":[],"to":[1],"version":1}',
        }, env=None)


def test_remap_process_is_added_to_both_trusted_registries(monkeypatch):
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
    assert first.get_function("local_ee_remap") is adapters.local_ee_remap
    assert second.get_function("local_ee_remap") is adapters.local_ee_remap
