"""SDK formula builders and artifact gates for Wave71 measure workflows."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

from ee_measures_references import (
    FIXTURE,
    ROOT,
    WGS84,
    load_fixture,
    planar_reference,
    spherical_arc_angle,
    spherical_centroid_coordinates,
    spherical_centroid_vector,
    spherical_triangle_area,
    verify_frozen_wgs84_reference,
)

METHOD_FOR_OPERATION = {11: "area", 12: "length", 13: "perimeter"}
PLANAR_GEOMETRYCOLLECTION_FIXTURE = ROOT / (
    "tests/fixtures/ee-geometry-measures-wave71-planar-geometrycollection-v1.json"
)
FEATURE_ONLY_WORKFLOW_FIXTURE = ROOT / (
    "tests/fixtures/ee-geometry-measures-wave71-feature-only-workflows-v1.json"
)


def load_geometrycollection_workflow_fixture(fixture=None):
    """Add the separately versioned GeometryCollection route to a base fixture."""
    base = deepcopy(fixture if fixture is not None else load_fixture())
    raw = PLANAR_GEOMETRYCOLLECTION_FIXTURE.read_bytes()
    variant = json.loads(raw)
    source_path = ROOT / variant["source_fixture"]["path"]
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if source_hash != variant["source_fixture"]["sha256"]:
        raise AssertionError("Additive GeometryCollection fixture source hash changed")

    case = variant["case"]
    source_geometry = base["cases"][case["source_case"]]["geometry"]
    geometry = case["geometry"]
    component_coordinates = [
        child["coordinates"] for child in geometry["geometries"]
    ]
    if (geometry["type"] != "GeometryCollection"
            or component_coordinates != source_geometry["coordinates"]
            or any(child.get("geodesic") is not False
                   for child in geometry["geometries"])):
        raise AssertionError("GeometryCollection components differ from the frozen MultiPolygon")
    base["cases"][case["name"]] = {
        key: value for key, value in case.items()
        if key not in {"name", "source_case"}
    }
    base["physical_workflow_v3"] = variant["physical_workflow_v3"]
    base["geometrycollection_addendum"] = variant
    return base


def load_feature_only_workflows_fixture(fixture=None):
    """Add lower-cost v4 physical workflows without changing earlier fixtures."""
    base = load_geometrycollection_workflow_fixture(fixture)
    raw = FEATURE_ONLY_WORKFLOW_FIXTURE.read_bytes()
    variant = json.loads(raw)
    for source in variant["source_fixtures"]:
        source_path = ROOT / source["path"]
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != source["sha256"]:
            raise AssertionError("Feature-only workflow fixture source hash changed")
    base["physical_workflows_v4"] = variant["physical_workflows_v4"]
    base["feature_only_workflow_addendum"] = variant
    return base


def require_exact_measure_artifact(monkeypatch):
    """Skip only when the designated exact-source native artifact is absent."""
    import pytest

    from gee.compat.earthengine import spherical_native

    override = os.environ.get("LOCAL_EE_TEST_S2_MEASURES_ARTIFACT")
    artifact = Path(override).expanduser() if override else spherical_native.ARTIFACT_DIR
    if not artifact.is_absolute():
        artifact = Path.cwd() / artifact
    library = ("liblocal_ee_s2.dylib" if sys.platform == "darwin"
               else "liblocal_ee_s2.so")
    if not artifact.exists():
        pytest.skip("designated exact-source S2 measure artifact is absent")
    if artifact.is_symlink() or not artifact.is_dir():
        pytest.fail("designated S2 measure artifact must be a physical directory")
    if not (artifact / "manifest.json").exists() or not (artifact / library).exists():
        pytest.fail("designated S2 measure artifact directory is incomplete")
    if (artifact / "manifest.json").is_symlink() or (artifact / library).is_symlink():
        pytest.fail("designated S2 measure artifact files must be physical files")
    if spherical_native._LOADED is not None:
        loaded = next((path for path in spherical_native._LOADED[0]
                       if path.name == library), None)
        if loaded is None or loaded.parent != artifact:
            pytest.fail("Run measure workflow tests in a fresh process for this artifact")
    monkeypatch.setattr(spherical_native, "ARTIFACT_DIR", artifact)
    # The integrity loader checks all source and library hashes. A present but
    # stale artifact therefore fails here rather than being treated as absent.
    spherical_native._load()
    return artifact


def metric_output_collection(ee, fixture=None):
    """Preserve the original v1 mixed-route formula as a gap/control record."""
    fixture = fixture or load_fixture()
    projection = ee.Projection("EPSG:4326")
    source_features = []
    for rank, name in enumerate(fixture["workflow"]["input_features"]):
        geometry = fixture["cases"][name]["geometry"]
        source_features.append(ee.Feature({
            "type": "Feature",
            "id": f"wave71-{name}",
            "properties": {"label": name, "source_rank": rank},
            "geometry": geometry,
        }))

    def add_metrics(feature):
        geometry = feature.geometry()
        feature_centroid = feature.centroid()
        projected_feature_centroid = feature.centroid(proj=projection)
        values = {
            "system:index": feature.id(),
            "feature_id": feature.id(),
            "geometry_area_default": geometry.area(),
            "feature_area_default": feature.area(),
            "geometry_area_null": geometry.area(maxError=None, proj=None),
            "feature_area_null": feature.area(maxError=None, proj=None),
            "geometry_area_epsg4326": geometry.area(proj=projection),
            "feature_area_epsg4326": feature.area(proj=projection),
            "geometry_length_default": geometry.length(),
            "feature_length_default": feature.length(),
            "geometry_length_null": geometry.length(maxError=None, proj=None),
            "feature_length_null": feature.length(maxError=None, proj=None),
            "geometry_length_epsg4326": geometry.length(proj=projection),
            "feature_length_epsg4326": feature.length(proj=projection),
            "geometry_perimeter_default": geometry.perimeter(),
            "feature_perimeter_default": feature.perimeter(),
            "geometry_perimeter_null": geometry.perimeter(maxError=None, proj=None),
            "feature_perimeter_null": feature.perimeter(maxError=None, proj=None),
            "geometry_perimeter_epsg4326": geometry.perimeter(proj=projection),
            "feature_perimeter_epsg4326": feature.perimeter(proj=projection),
            "geometry_centroid_default": geometry.centroid().coordinates(),
            "feature_centroid_default": feature_centroid.geometry().coordinates(),
            "geometry_centroid_epsg4326": geometry.centroid(proj=projection).coordinates(),
            "feature_centroid_epsg4326": projected_feature_centroid.geometry().coordinates(),
        }
        return projected_feature_centroid.set(values)

    return ee.FeatureCollection(source_features).map(add_metrics)


def expected_feature_id(name):
    return f"wave71-{name}"


def physical_measurement_collection(ee, fixture, route):
    """Build one route-homogeneous map workflow for actual worker export.

    The historical ``workflow`` deliberately remains the original six-row
    mixed-route formula. Physical v2 variants split that formula because one
    geometry cannot be transformed between the currently supported default
    WGS84 great-circle and explicit planar EPSG:4326 measurement paths.
    """
    variants = fixture["physical_workflow_v2"]
    if route in variants:
        config = variants[route]
    elif (route == fixture.get("physical_workflow_v3", {}).get("route")):
        config = fixture["physical_workflow_v3"]
    else:
        config = next((candidate for candidate in fixture.get(
            "physical_workflows_v4", {}).values()
            if candidate.get("route") == route), None)
        if config is None:
            raise ValueError(f"Unknown physical measurement route: {route}")
    projection = ee.Projection("EPSG:4326")
    source_features = []
    for rank, name in enumerate(config["input_features"]):
        geometry = deepcopy(fixture["cases"][name]["geometry"])
        if (route.startswith("explicit_epsg4326_planar")
                and geometry.get("type") not in {"Point", "MultiPoint"}):
            # Declare the planar edge model when constructing the input. This
            # never transforms a geodesic input into a planar one. Point
            # constructors have no edge-model argument and Points have no
            # edges whose model needs to be declared.
            geometry["geodesic"] = False
        source_features.append(ee.Feature({
            "type": "Feature",
            "id": expected_feature_id(name),
            "properties": {"label": name, "source_rank": rank},
            "geometry": geometry,
        }))

    def add_metrics(feature):
        geometry = feature.geometry()
        values = {
            "system:index": feature.id(),
            "feature_id": feature.id(),
        }
        if route.startswith("default_wgs84"):
            if config.get("metric_owner") == "Feature":
                for method in ("area", "length", "perimeter"):
                    values[f"feature_{method}_default"] = getattr(feature, method)()
                feature_centroid = feature.centroid()
                values["feature_centroid_default"] = (
                    feature_centroid.geometry().coordinates()
                )
                return feature_centroid.set(values)
            for method in ("area", "length", "perimeter"):
                values[f"geometry_{method}_default"] = getattr(geometry, method)()
                values[f"feature_{method}_default"] = getattr(feature, method)()
                values[f"geometry_{method}_null"] = getattr(geometry, method)(
                    maxError=None, proj=None,
                )
                values[f"feature_{method}_null"] = getattr(feature, method)(
                    maxError=None, proj=None,
                )
            geometry_centroid = geometry.centroid()
            feature_centroid = feature.centroid()
            values["geometry_centroid_default"] = geometry_centroid.coordinates()
            values["feature_centroid_default"] = feature_centroid.geometry().coordinates()
            return feature_centroid.set(values)

        if route.startswith("explicit_epsg4326_planar"):
            if config.get("metric_owner") == "Feature":
                for method in ("area", "length", "perimeter"):
                    values[f"feature_{method}_epsg4326"] = getattr(feature, method)(
                        proj=projection,
                    )
                feature_centroid = feature.centroid(proj=projection)
                values["feature_centroid_epsg4326"] = (
                    feature_centroid.geometry().coordinates()
                )
                return feature_centroid.set(values)
            for method in ("area", "length", "perimeter"):
                values[f"geometry_{method}_epsg4326"] = getattr(geometry, method)(
                    proj=projection,
                )
                values[f"feature_{method}_epsg4326"] = getattr(feature, method)(
                    proj=projection,
                )
            geometry_centroid = geometry.centroid(proj=projection)
            feature_centroid = feature.centroid(proj=projection)
            values["geometry_centroid_epsg4326"] = geometry_centroid.coordinates()
            values["feature_centroid_epsg4326"] = feature_centroid.geometry().coordinates()
            return feature_centroid.set(values)

        raise ValueError(f"Unknown physical measurement route: {route}")

    return ee.FeatureCollection(source_features).map(add_metrics)
