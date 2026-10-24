"""Bounded bounds contracts; spherical runs use typed mocked envelopes."""
from pathlib import Path
from types import SimpleNamespace
import os
import sys

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.error_margin import ErrorMarginValue
from gee.compat.earthengine.geometry_bounds import (
    GEOMETRY_BOUNDS_ARGUMENTS,
    _RECTANGLE_OUTPUT_WORK,
    _rectangle,
    _bounds_output_work,
    invoke_geometry_bounds,
)
from gee.compat.earthengine.geometry_preflight import MAX_GEOMETRY_WORK
from gee.ee_translate import UnsupportedEEError, compile_expression


ROOT = Path(__file__).resolve().parents[1]


def translator(steps=0):
    result = Translator([], {}, {})
    result.steps = steps
    return result


def planar_polygon(coordinates=None):
    return {
        "type": "Polygon",
        "coordinates": coordinates or [[
            [-5, 40], [5, 40], [5, 50], [-5, 50], [-5, 40],
        ]],
        "geodesic": False,
    }


def geometry_call(value, **options):
    return invoke_geometry_bounds(
        translator(), "Geometry.bounds", {"geometry": value, **options},
    )


def assert_rectangle(value, west, south, east, north):
    assert value["type"] == "Polygon"
    assert value["coordinates"] == [[
        [west, south], [east, south], [east, north],
        [west, north], [west, south],
    ]]
    assert value["geodesic"] is False
    assert value["evenOdd"] is True
    assert "crs" not in value


def mock_native(monkeypatch, envelope):
    from gee.compat.earthengine import spherical_native

    calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda _geometry: True)
    monkeypatch.setattr(
        spherical_native, "run",
        lambda operation, _geometry: calls.append(operation) or envelope,
    )
    return calls


def test_exact_signature_defaults_and_explicit_nulls_share_epsg4326_path():
    assert GEOMETRY_BOUNDS_ARGUMENTS["Geometry.bounds"] == (
        frozenset({"geometry"}), frozenset({"maxError", "proj"}),
    )
    geometry = planar_polygon()
    assert_rectangle(geometry_call(geometry), -5, 40, 5, 50)
    assert_rectangle(geometry_call(geometry, maxError=None, proj=None), -5, 40, 5, 50)
    assert_rectangle(geometry_call(geometry, maxError=1, proj="EPSG:4326"), -5, 40, 5, 50)
    assert_rectangle(geometry_call(
        geometry, maxError=ErrorMarginValue(1.0, "meters"), proj="EPSG:4326",
    ), -5, 40, 5, 50)


@pytest.mark.parametrize("arguments, message", [
    ({}, "requires arguments"),
    ({"geometry": planar_polygon(), "extra": 1}, "Unsupported algorithm arguments"),
    ({"geometry": planar_polygon(), "proj": "EPSG:3857"}, "other projections"),
    ({"geometry": planar_polygon(), "proj": 4326}, "other projections"),
    ({"geometry": planar_polygon(), "maxError": True}, "static ErrorMargin"),
])
def test_argument_errors_are_explicit(arguments, message):
    with pytest.raises(UnsupportedEEError, match=message):
        invoke_geometry_bounds(translator(), "Geometry.bounds", arguments)


def test_planar_bounds_use_true_coordinate_extrema_without_native_s2(monkeypatch):
    from gee.compat.earthengine import spherical_native

    monkeypatch.setattr(
        spherical_native, "run",
        lambda *_args, **_kwargs: pytest.fail("planar bounds must not use S2"),
    )
    geometry = planar_polygon([[[-4, 42], [3, 41], [1, 49], [-4, 42]]])
    assert_rectangle(geometry_call(geometry), -4, 41, 3, 49)


def test_geodesic_bounds_use_native_component_envelope_not_vertex_extrema(monkeypatch):
    from gee.compat.earthengine.spherical_envelope import Envelope

    calls = mock_native(monkeypatch, Envelope(
        False, False, False, -12.5, 70.0, 12.5, 88.0,
    ))
    geometry = {
        "type": "Polygon",
        "coordinates": [[[-10, 80], [10, 80], [0, 82], [-10, 80]]],
    }
    result = geometry_call(geometry)
    assert_rectangle(result, -12.5, 70.0, 12.5, 88.0)
    assert calls == ["bounds"]


def test_full_longitude_polar_envelope_becomes_finite_planar_rectangle(monkeypatch):
    from gee.compat.earthengine.spherical_envelope import Envelope

    calls = mock_native(monkeypatch, Envelope(
        False, True, False, -180.0, 80.0, 180.0, 90.0,
    ))
    geometry = {
        "type": "Polygon",
        "coordinates": [[[-135, 80], [-45, 80], [45, 80],
                         [135, 80], [-135, 80]]],
    }
    result = geometry_call(geometry)
    assert_rectangle(result, -180.0, 80.0, 180.0, 90.0)
    assert calls == ["bounds"]


def test_fixed_rectangle_reservation_matches_the_ordinary_decoder_and_mapper():
    from gee.compat.earthengine.geometry_preflight import measure_geometry
    from gee.compat.earthengine.geometry_values import decode_geometry_bounded

    template = {
        "type": "Polygon",
        "coordinates": [[
            [-1.0, -1.0], [1.0, -1.0], [1.0, 1.0],
            [-1.0, 1.0], [-1.0, -1.0],
        ]],
        "geodesic": False,
    }
    raw_cost = measure_geometry(template)
    assert (raw_cost.nodes, raw_cost.positions, raw_cost.geometries,
            raw_cost.ring_closures) == (27, 5, 1, 1)
    decode_budget = SimpleNamespace(steps=0)
    decoded = decode_geometry_bounded(decode_budget, template)
    decoded_cost = measure_geometry(decoded)
    assert decode_budget.steps == 27 + 5 + 3 * 1
    assert (decoded_cost.nodes, decoded_cost.positions,
            decoded_cost.geometries, decoded_cost.ring_closures) == (61, 5, 1, 1)

    budget = SimpleNamespace(steps=0)
    _rectangle(budget, (-1.0, -1.0, 1.0, 1.0), "bounds test")
    assert _RECTANGLE_OUTPUT_WORK == 136
    assert budget.steps == _RECTANGLE_OUTPUT_WORK
    assert _bounds_output_work(include_envelope=False) == 136
    assert _bounds_output_work(include_envelope=True) == 136 + 8 + 3


@pytest.mark.parametrize("envelope, message", [
    ((True, False, False, 0.0, 0.0, 0.0, 0.0), "empty bounds"),
    ((False, False, True, 170.0, -5.0, -170.0, 5.0), "wrapped-longitude"),
    ((False, False, False, 1.0, 3.0, 1.0, 3.0), "degenerate"),
    ((False, False, False, -180.0, -80.0, 180.0, 80.0),
     "full longitude without its flag"),
    ((False, False, False, 0.0, 80.0, 1.0, 90.0),
     "pole-touching envelope without full longitude"),
    ((False, False, False, 0.0, -90.0, 1.0, 80.0),
     "pole-touching envelope without full longitude"),
])
def test_empty_wrapped_and_degenerate_envelopes_remain_explicit_gaps(
        monkeypatch, envelope, message):
    from gee.compat.earthengine.spherical_envelope import Envelope

    calls = mock_native(monkeypatch, Envelope(*envelope))
    geometry = {
        "type": "LineString", "coordinates": [[0, 0], [1, 1]],
    }
    with pytest.raises(UnsupportedEEError, match=message):
        geometry_call(geometry)
    assert calls == ["bounds"]


def test_s2_output_is_reserved_before_native_and_exact_remaining_budget_succeeds(
        monkeypatch):
    from gee.compat.earthengine import spherical_native
    from gee.compat.earthengine.spherical_envelope import Envelope

    geometry = {
        "type": "Polygon",
        "coordinates": [[[-10, 80], [10, 80], [0, 82], [-10, 80]]],
    }
    envelope = Envelope(False, False, False, -12.5, 70.0, 12.5, 88.0)

    # The native result validation is exactly the eight record values plus
    # checks of its three boolean flags; the rectangle charge is measured by
    # running the ordinary bounded output path on its structural template.
    planar_output = _bounds_output_work(include_envelope=False)
    spherical_output = _bounds_output_work(include_envelope=True)
    assert spherical_output == planar_output + 8 + 3

    baseline = translator()
    native_steps = []
    monkeypatch.setattr(spherical_native, "validate", lambda _geometry: True)
    monkeypatch.setattr(
        spherical_native, "run",
        lambda operation, _geometry: native_steps.append(baseline.steps) or envelope,
    )
    assert_rectangle(invoke_geometry_bounds(
        baseline, "Geometry.bounds", {"geometry": geometry},
    ), -12.5, 70.0, 12.5, 88.0)
    assert native_steps == [baseline.steps]
    boundary = baseline.steps
    assert 0 < boundary < MAX_GEOMETRY_WORK

    exact = translator(MAX_GEOMETRY_WORK - boundary)
    exact_native_steps = []
    monkeypatch.setattr(
        spherical_native, "run",
        lambda operation, _geometry: exact_native_steps.append(exact.steps) or envelope,
    )
    assert_rectangle(invoke_geometry_bounds(
        exact, "Geometry.bounds", {"geometry": geometry},
    ), -12.5, 70.0, 12.5, 88.0)
    assert exact_native_steps == [MAX_GEOMETRY_WORK]
    assert exact.steps == MAX_GEOMETRY_WORK

    # The reviewed start reached the native boundary with no output allowance.
    # It now fails while reserving the complete output, before native execution.
    near_cap = translator(49_393)
    near_cap_calls = []
    monkeypatch.setattr(
        spherical_native, "run",
        lambda operation, _geometry: near_cap_calls.append(operation) or envelope,
    )
    with pytest.raises(UnsupportedEEError, match="complete output reservation"):
        invoke_geometry_bounds(
            near_cap, "Geometry.bounds", {"geometry": geometry},
        )
    assert near_cap.steps == MAX_GEOMETRY_WORK
    assert near_cap_calls == []


def test_actual_native_geometry_bounds_uses_selected_artifact(monkeypatch):
    artifact_name = os.environ.get("LOCAL_EE_TEST_S2_BOUNDS_ARTIFACT")
    from gee.compat.earthengine import spherical_native
    from gee.compat.earthengine.spherical_envelope import Envelope

    artifact = (Path(artifact_name).expanduser() if artifact_name is not None
                else spherical_native.ARTIFACT_DIR)
    if not artifact.is_absolute():
        artifact = Path.cwd() / artifact
    library = "liblocal_ee_s2.dylib" if sys.platform == "darwin" else "liblocal_ee_s2.so"
    manifest, library_path = artifact / "manifest.json", artifact / library
    if (artifact.is_symlink() or manifest.is_symlink()
            or library_path.is_symlink()):
        pytest.fail("S2 bounds artifact paths must not be symlinks")
    if artifact_name is None and not artifact.exists():
        pytest.skip("canonical S2 adapter artifact is unavailable")
    if not artifact.is_dir():
        pytest.fail("S2 bounds artifact is not a physical directory")
    if artifact_name is None and (not manifest.exists() or not library_path.exists()):
        pytest.skip("canonical S2 adapter artifact is unavailable")
    if not manifest.is_file() or not library_path.is_file():
        pytest.fail("S2 bounds artifact is not a complete physical artifact directory")

    if spherical_native._LOADED is not None:
        loaded_library = next((path for path in spherical_native._LOADED[0]
                               if path.name == library), None)
        if loaded_library is None or loaded_library.parent != artifact:
            pytest.fail("run actual S2 bounds checks in a fresh process for the selected artifact")
    monkeypatch.setattr(spherical_native, "ARTIFACT_DIR", artifact)

    source = {"type": "LineString", "coordinates": [[0, 80], [90, 80]]}
    work = translator()
    native_calls = []
    native_run = spherical_native.run

    def observed_run(operation, geometry):
        result = native_run(operation, geometry)
        native_calls.append((operation, work.steps, result))
        return result

    monkeypatch.setattr(spherical_native, "run", observed_run)
    result = invoke_geometry_bounds(
        work, "Geometry.bounds", {"geometry": source},
    )
    assert [operation for operation, _steps, _result in native_calls] == [
        "validate", "bounds",
    ]
    _operation, bounds_steps, envelope = native_calls[-1]
    assert bounds_steps == work.steps
    assert type(envelope) is Envelope
    assert envelope.north > 80.0
    assert envelope.north < 84.0
    assert_rectangle(result, envelope.west, envelope.south,
                     envelope.east, envelope.north)


def test_mixed_edge_models_reject_before_native_bounds(monkeypatch):
    from gee.compat.earthengine import spherical_native

    calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda _geometry: True)
    monkeypatch.setattr(
        spherical_native, "run",
        lambda operation, _geometry: calls.append(operation) or True,
    )
    mixed = {
        "type": "GeometryCollection",
        "geometries": [
            {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            {"type": "LineString", "coordinates": [[2, 2], [3, 3]],
             "geodesic": False},
        ],
    }
    with pytest.raises(UnsupportedEEError, match="mixed geodesic edge models"):
        geometry_call(mixed)
    assert calls == []


def test_geometry_input_is_freshly_revalidated_and_cycles_depth_and_work_stay_bounded():
    source = planar_polygon()
    first = geometry_call(source)
    first["coordinates"][0][0][0] = -99
    assert source["coordinates"][0][0][0] == -5

    t = translator()
    from gee.compat.earthengine.geometry_values import decode_geometry_bounded

    decoded = decode_geometry_bounded(t, source)
    decoded["coordinates"][0][0][0] = -8
    decoded["coordinates"][0][-1][0] = -8
    assert_rectangle(invoke_geometry_bounds(
        t, "Geometry.bounds", {"geometry": decoded},
    ), -8, 40, 5, 50)

    cyclic = {"type": "GeometryCollection", "geometries": []}
    cyclic["geometries"].append(cyclic)
    with pytest.raises(UnsupportedEEError, match="cycle"):
        geometry_call(cyclic)

    deeply_nested = {"type": "Point", "coordinates": [1, 1]}
    for _ in range(17):
        deeply_nested = {"type": "GeometryCollection", "geometries": [deeply_nested]}
    with pytest.raises(UnsupportedEEError, match="16 levels"):
        geometry_call(deeply_nested)

    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_geometry_bounds(
            translator(49_999), "Geometry.bounds", {"geometry": source},
        )


def test_literal_planar_image_geometry_bounds_controls_are_offline_and_stable():
    from gee.ee_python_client import configure_local_ee
    from scripts.ee_python_api.offline import OfflineGuard

    catalog = [{"id": "sentinel-2-l2a",
                "cube:dimensions": {"bands": {"values": ["B1"]}}}]
    footprint = planar_polygon([[[-4, 35], [3, 35], [3, 48], [-4, 48], [-4, 35]]])
    items = {"sentinel-2-l2a": [{
        "id": "bounds-planar-control", "bbox": [-4, 35, 3, 48], "geometry": footprint,
        "properties": {"system:index": "bounds-planar-control"},
    }]}

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        image = ee.Image("bounds-planar-control")
        values = (
            image.geometry().bounds(),
            image.geometry(proj=ee.Projection("EPSG:4326"), geodesics=False).bounds(
                proj=ee.Projection("EPSG:4326"),
            ),
        )
        wires = [ee.serializer.encode(value, for_cloud_api=False) for value in values]
        results = [compile_expression(wire, catalog, items)["value"] for wire in wires]
        assert guard.evidence()["attempt_count"] == 0

    for result in results:
        assert_rectangle(result, -4, 35, 3, 48)
