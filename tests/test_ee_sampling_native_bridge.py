"""Native sampler forwarding, grid validation and bounded response parsing."""
from __future__ import annotations

import json
import sys
import types

import pytest

from engine import ee_process_adapters as adapters
from engine import ee_sampling
from engine.ee_sampling_result import SampledFeatureTable
from gee.sampling_spec import decode_sampling_spec, prepare_sampling_spec
from ee_sampling_bridge_helpers import _actual_cube, _fixture, _native_row, _spec


def test_native_sampling_forwards_only_wkts_and_uses_one_max_level(monkeypatch):
    spec = _spec()
    calls = []
    cube = _actual_cube(monkeypatch)

    def invoke(input_cube, level, bands, decoded_spec):
        calls.append((input_cube, level, bands, decoded_spec))
        return json.dumps([_native_row(0, 0, 0, [0.25, 1.5])], separators=(",", ":"))

    monkeypatch.setattr(ee_sampling, "_invoke_native_sampler", invoke)
    table = adapters.local_ee_sample_regions({"data": cube, "spec": spec}, env=None)

    assert type(table) is SampledFeatureTable
    assert table.format == "CSV"
    assert cube.level_calls == 1
    assert calls[0][0] is cube and calls[0][1] is cube.level
    assert calls[0][2] == ["red", "nir"]
    assert calls[0][3]["bands"] == ["red", "nir"]
    feature = table.data["features"][0]
    assert feature["id"] == "f0_r0_c0"
    assert feature["properties"]["red"] == 0.25
    assert feature["properties"]["nir"] == 1.5


def test_actual_grid_crs_and_meter_scale_are_checked_before_sampling(monkeypatch):
    geographic_spec = _spec(grid={"scale": 10, "crs": None})
    geographic_cube = _actual_cube(monkeypatch, crs="EPSG:4326")
    monkeypatch.setattr(
        ee_sampling,
        "_invoke_native_sampler",
        lambda *args: pytest.fail("The native sampler must not run for a geographic meter scale"),
    )
    with pytest.raises(ValueError, match="meter scale on a geographic grid"):
        adapters.local_ee_sample_regions(
            {"data": geographic_cube, "spec": geographic_spec}, env=None
        )
    assert geographic_cube.level_calls == 1

    projected_spec = _spec(grid={"scale": 10, "crs": "EPSG:32631"})
    projected_cube = _actual_cube(monkeypatch, crs="EPSG:3857")
    with pytest.raises(ValueError, match="does not match its declared CRS"):
        adapters.local_ee_sample_regions(
            {"data": projected_cube, "spec": projected_spec}, env=None
        )


@pytest.mark.parametrize(
    "cube_options,error",
    [
        ({"cell_size": 30}, "does not match actual raster cell size"),
        ({"crs": "EPSG:2263"}, "projected meter CRS"),
        ({"layout": False}, "actual raster layout metadata"),
    ],
)
def test_meter_scale_matches_actual_projected_layout_before_sampling(monkeypatch, cube_options, error):
    spec = _spec(grid={"scale": 10, "crs": None})
    cube = _actual_cube(monkeypatch, **cube_options)
    monkeypatch.setattr(
        ee_sampling,
        "_invoke_native_sampler",
        lambda *args: pytest.fail("The native sampler must not run for an unverifiable grid"),
    )

    with pytest.raises(ValueError, match=error):
        adapters.local_ee_sample_regions({"data": cube, "spec": spec}, env=None)


def test_meter_scale_accepts_the_matching_actual_layout(monkeypatch):
    spec = _spec(grid={"scale": 10, "crs": "EPSG:3857"})
    cube = _actual_cube(monkeypatch, cell_size=10)
    monkeypatch.setattr(
        ee_sampling,
        "_invoke_native_sampler",
        lambda *args: json.dumps([_native_row(0, 0, 0, [0.25, 1.5])], separators=(",", ":")),
    )

    table = adapters.local_ee_sample_regions({"data": cube, "spec": spec}, env=None)

    assert type(table) is SampledFeatureTable
    assert cube.level_calls == 1


def test_native_spi_receives_wrapped_max_level_source_names_and_ordered_wkt(monkeypatch):
    spec_text = _spec(features=[{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [1, 2]},
        "properties": {"plot_id": "p", "landcover": 0},
    }])
    from gee.sampling_spec import decode_sampling_spec

    spec = decode_sampling_spec(spec_text)
    observations = {}

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
            observations["wrapped"] = cube
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

    level = types.SimpleNamespace(srdd=types.SimpleNamespace(rdd=lambda: "max-rdd"))
    assert ee_sampling._invoke_native_sampler(object(), level, ["red", "nir"], spec) == "[]"
    assert observations["rdd"] == "max-rdd"
    assert observations["band_names"] == ["red", "nir"]
    assert observations["process_id"] == "local_ee_sample_regions"
    assert observations["arguments"]["regions"] == ["POINT (1 2)"]


@pytest.mark.parametrize(
    "text,error",
    [
        ('{"feature":0,"feature":0}', "duplicate JSON keys"),
        ("NaN", "invalid number"),
        ('[{"feature":0,"row":0,"col":0,"x":0,"y":0,"values":[9007199254740993,1]}]',
         "exact Float64 domain"),
        ("{}", "row array"),
    ],
)
def test_native_row_parser_rejects_malformed_json(text, error):
    with pytest.raises(ValueError, match=error):
        ee_sampling._parse_native_rows(text)


@pytest.mark.parametrize(
    "row,error",
    [
        (_native_row(True, 0, 0, [1, 2]), "feature index"),
        (_native_row(99, 0, 0, [1, 2]), "feature index"),
        (_native_row(0, 0, 0, [1]), "declared bands"),
        (_native_row(0, 0, 0, [float("inf"), 2]), "invalid number"),
        (_native_row(0, 0, 0, [1, 2], x=181), "WGS84"),
    ],
)
def test_shared_row_assembler_rejects_invalid_shape_types_and_values(row, error):
    from gee.sampling_values import assemble_sample_features

    spec = decode_sampling_spec(_spec())
    with pytest.raises(ValueError, match=error):
        rows = ee_sampling._parse_native_rows(json.dumps([row]))
        assemble_sample_features(spec, rows)


def test_native_response_and_shared_assembler_enforce_row_cell_and_byte_budgets():
    from gee.sampling_values import assemble_sample_features

    spec = decode_sampling_spec(_spec())
    too_many = [_native_row(0, i, 0, [1, 2]) for i in range(1001)]
    with pytest.raises(ValueError, match="1000 rows"):
        ee_sampling._parse_native_rows(json.dumps(too_many))

    wide = prepare_sampling_spec(
        {"type": "FeatureCollection", "features": _fixture()["training_features"]},
        bands=[f"b{index}" for index in range(64)],
        properties=[f"p{index}" for index in range(190)],
    )
    wide_spec = decode_sampling_spec(wide)
    crowded = [_native_row(0, i, 0, [1] * 64) for i in range(200)]
    with pytest.raises(ValueError, match="50000 result cells"):
        assemble_sample_features(wide_spec, crowded)
    with pytest.raises(ValueError, match="1000000-byte limit"):
        ee_sampling._parse_native_rows(" " * (ee_sampling.MAX_SAMPLE_JSON_BYTES + 1))
