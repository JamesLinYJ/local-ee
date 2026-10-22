"""V2 Image.sample bridge protocol, grid checks and nullable real-row assembly."""
from __future__ import annotations

import json
import sys
import types

import pytest

from engine import ee_process_adapters as adapters
from engine import ee_sampling
from engine.ee_sampling_result import PendingSampledTable, SampledFeatureTable
from gee.image_sampling_spec import prepare_image_sample_spec
from gee.sampling_spec import decode_sampling_spec, encode_spec
from ee_sampling_bridge_helpers import _actual_cube, _dry_cube, _native_row, _spec


def _image_spec(**options):
    return prepare_image_sample_spec(
        {"type": "Polygon", "coordinates": [[
            [0, 30], [40, 30], [40, 0], [0, 0], [0, 30],
        ]]},
        ["red", "nir"], geometries=True, **options,
    )


def _mock_jvm(monkeypatch, observations):
    class Wrapped:
        def openEOMetadata(self):
            return self

        def setBandNames(self, names):
            observations["band_names"] = names

    class Processes:
        def wrapCube(self, rdd):
            observations["rdd"] = rdd
            return Wrapped()

    class Registry:
        @staticmethod
        def invoke(cube, process_id, arguments):
            observations["process_id"] = process_id
            observations["arguments"] = arguments
            return "[]"

    processes = Processes()
    jvm = types.SimpleNamespace(org=types.SimpleNamespace(
        openeo=types.SimpleNamespace(
            geotrellis=types.SimpleNamespace(OpenEOProcesses=lambda: processes),
            geotrelliscommon=types.SimpleNamespace(CubeProcessRegistry=Registry),
        )
    ))
    package = types.ModuleType("openeogeotrellis")
    package.__path__ = []
    utils = types.ModuleType("openeogeotrellis.utils")
    utils.get_jvm = lambda: jvm
    monkeypatch.setitem(sys.modules, "openeogeotrellis", package)
    monkeypatch.setitem(sys.modules, "openeogeotrellis.utils", utils)


def test_v2_native_protocol_passes_one_wkt_and_canonical_options(monkeypatch):
    text = _image_spec(factor=0.25, seed=-7, drop_nulls=False)
    spec = decode_sampling_spec(text)
    observations = {}
    _mock_jvm(monkeypatch, observations)
    level = types.SimpleNamespace(srdd=types.SimpleNamespace(rdd=lambda: "max-image-rdd"))

    assert ee_sampling._invoke_native_sampler(object(), level, ["red", "nir"], spec) == "[]"

    assert observations["rdd"] == "max-image-rdd"
    assert observations["band_names"] == ["red", "nir"]
    assert observations["process_id"] == "local_ee_image_sample"
    assert set(observations["arguments"]) == {"regions", "options"}
    assert observations["arguments"]["regions"] == [
        "POLYGON ((0 30, 40 30, 40 0, 0 0, 0 30))"
    ]
    assert observations["arguments"]["options"] == encode_spec(spec["image_sample"])


def test_v1_native_protocol_keeps_the_existing_sample_regions_process(monkeypatch):
    spec = decode_sampling_spec(_spec())
    observations = {}
    _mock_jvm(monkeypatch, observations)
    level = types.SimpleNamespace(srdd=types.SimpleNamespace(rdd=lambda: "legacy-max-level-rdd"))

    assert ee_sampling._invoke_native_sampler(object(), level, ["red", "nir"], spec) == "[]"

    assert observations["rdd"] == "legacy-max-level-rdd"
    assert observations["process_id"] == "local_ee_sample_regions"
    assert set(observations["arguments"]) == {"regions"}


def test_actual_v2_bridge_assembles_nullable_rows_and_declared_band_order(monkeypatch):
    text = _image_spec(drop_nulls=False)
    spec = decode_sampling_spec(text)
    cube = _actual_cube(monkeypatch, cell_size=10)
    row = _native_row(0, 0, 0, [None, 1.0000000000000002], x=5, y=25)
    monkeypatch.setattr(ee_sampling, "_invoke_native_sampler", lambda *args: json.dumps([row]))

    result = adapters.local_ee_sample_regions({"data": cube, "spec": text}, env=None)

    assert type(result) is SampledFeatureTable
    assert cube.level_calls == 1
    assert result.data["properties"] == {"band_order": ["red", "nir"]}
    feature = result.data["features"][0]
    assert feature["id"] == "f0_r0_c0"
    assert feature["properties"] == {"red": None, "nir": 1.0000000000000002}
    assert feature["geometry"] == {"type": "Point", "coordinates": [5.0, 25.0]}


def test_v2_scale_is_checked_against_the_actual_grid_before_jvm(monkeypatch):
    text = _image_spec(grid={"scale": 10, "crs": "EPSG:3857"})
    cube = _actual_cube(monkeypatch, cell_size=30)
    monkeypatch.setattr(ee_sampling, "_invoke_native_sampler", lambda *args: pytest.fail(
        "the native process must not run when the requested grid differs"
    ))

    with pytest.raises(ValueError, match="does not match actual raster cell size"):
        adapters.local_ee_sample_regions({"data": cube, "spec": text}, env=None)


def test_v2_dry_run_retains_schema_and_trace_without_jvm_rows(monkeypatch):
    text = _image_spec(drop_nulls=False)
    cube, source, _ = _dry_cube()
    monkeypatch.setattr(ee_sampling, "_invoke_native_sampler", lambda *args: pytest.fail(
        "dry-run must not start a JVM or fabricate sample rows"
    ))

    result = adapters.local_ee_sample_regions({"data": cube, "spec": text}, env=None)

    assert type(result) is PendingSampledTable
    assert result.columns == ("system:index", "red", "nir", ".geo")
    assert result.sample_spec == text
    assert result.traces == (source,)
