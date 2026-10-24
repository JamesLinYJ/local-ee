"""Run the official Python SDK's default spherical Geometry/Feature workflow."""
from __future__ import annotations

import json
from pathlib import Path
import sys


OPERATIONS = (
    "contains", "containedIn", "disjoint", "intersects",
    "intersection", "union", "difference", "symmetricDifference",
)
OVERLAYS = ("intersection", "union", "difference", "symmetricDifference")


def geometry(ee, value):
    """Use ordinary numeric WGS84 coordinates and the SDK's spherical default."""
    kind = value["type"]
    if kind == "Polygon":
        if "evenOdd" in value:
            return ee.Geometry.Polygon(value["coordinates"], evenOdd=value["evenOdd"])
        return ee.Geometry.Polygon(value["coordinates"])
    if kind == "LineString":
        return ee.Geometry.LineString(value["coordinates"])
    if kind == "Point":
        return ee.Geometry.Point(value["coordinates"])
    raise ValueError(f"Unsupported fixture geometry: {kind}")


def feature(ee, geometry_value, identity, properties):
    """Make an inline Feature whose SDK-normalized system:index is its ID."""
    return ee.Feature({
        "type": "Feature", "id": identity, "geometry": geometry_value,
        "properties": dict(properties),
    })


def _binary(left, name, right, *, explicit_null_projection=False):
    method = getattr(left, name)
    return method(right, proj=None) if explicit_null_projection else method(right)


def build_workflow(ee, fixture, *, explicit_null_projection=False):
    """Build actual official-SDK calls without projection or geodesic rewrites."""
    regions = {name: geometry(ee, value) for name, value in fixture["regions"].items()}
    left, right = regions["dateline_left"], regions["dateline_right"]
    feature_config = fixture["features"]
    left_feature = feature(
        ee, left, feature_config["left_id"], feature_config["left_properties"],
    )
    right_feature = feature(
        ee, right, feature_config["right_id"], feature_config["right_properties"],
    )
    geometry_binary = {
        name: _binary(left, name, right,
                      explicit_null_projection=explicit_null_projection)
        for name in OPERATIONS
    }
    feature_binary = {
        name: _binary(left_feature, name, right_feature,
                      explicit_null_projection=explicit_null_projection)
        for name in OPERATIONS
    }

    probes = {}
    for name, probe in fixture["probes"].items():
        region_name = {
            "dateline_inside": "dateline_left",
            "dateline_other_side": "dateline_left",
            "polar_cap_inside": "polar_cap",
            "polar_cap_outside": "polar_cap",
            "hole_shell_inside": "with_hole",
            "hole_center_outside": "with_hole",
            "oriented_left_inside": "oriented_left",
            "oriented_reversed_outside": "oriented_reversed",
            "oriented_reversed_complement": "oriented_reversed",
        }[name]
        probes[name] = _binary(
            regions[region_name], "contains", ee.Geometry.Point(probe["point"]),
            explicit_null_projection=explicit_null_projection,
        )

    touch_polygon = regions["touch_polygon"]
    touch_line = regions["touch_line"]
    boundary_point = regions["boundary_point"]
    empty = regions["dateline_left"].intersection(regions["empty_other"])
    boundary = {
        "point_intersects": _binary(
            touch_polygon, "intersects", boundary_point,
            explicit_null_projection=explicit_null_projection,
        ),
        "line_intersects": _binary(
            touch_polygon, "intersects", touch_line,
            explicit_null_projection=explicit_null_projection,
        ),
        "intersection_line": _binary(
            touch_polygon, "intersection", touch_line,
            explicit_null_projection=explicit_null_projection,
        ),
        "intersection_point": _binary(
            touch_polygon, "intersection", boundary_point,
            explicit_null_projection=explicit_null_projection,
        ),
        "point_contains": _binary(
            touch_polygon, "contains", boundary_point,
            explicit_null_projection=explicit_null_projection,
        ),
        "empty_intersection": empty,
    }

    feature_overlays = []
    for name in OVERLAYS:
        identified_left = feature(
            ee, left, f"{feature_config['left_id']}-{name}",
            feature_config["left_properties"],
        )
        feature_overlays.append(_binary(
            identified_left, name, right_feature,
            explicit_null_projection=explicit_null_projection,
        ))

    return {
        "geometry": geometry_binary,
        "feature": feature_binary,
        "probes": probes,
        "boundary": boundary,
        "feature_overlays": ee.FeatureCollection(feature_overlays),
    }


def encode_workflow(ee, values):
    encode = lambda value: ee.serializer.encode(value, for_cloud_api=False)
    return {
        "geometry": {name: encode(value) for name, value in values["geometry"].items()},
        "feature": {name: encode(value) for name, value in values["feature"].items()},
        "probes": {name: encode(value) for name, value in values["probes"].items()},
        "boundary": {name: encode(value) for name, value in values["boundary"].items()},
        "feature_overlays": encode(values["feature_overlays"]),
    }


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    fixture = json.loads(
        (root / "tests/fixtures/ee-spherical-wave61-v1.json").read_text(encoding="utf-8")
    )
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        encoded = encode_workflow(ee, build_workflow(ee, fixture))
        compiled = {
            family: {name: compile_expression(value, [], {})
                     for name, value in outputs.items()}
            for family, outputs in encoded.items()
            if family != "feature_overlays"
        }
        compiled["feature_overlays"] = compile_expression(
            encoded["feature_overlays"], [], {},
        )
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({
        "fixture": fixture["schema"],
        "geometry_methods": sorted(compiled["geometry"]),
        "feature_methods": sorted(compiled["feature"]),
        "probe_results": {name: output["value"] for name, output in compiled["probes"].items()},
        "boundary_types": {
            name: output["value"].get("type") if isinstance(output.get("value"), dict) else output.get("value")
            for name, output in compiled["boundary"].items()
        },
        "feature_overlay_rows": len(compiled["feature_overlays"]["value"]["features"]),
        "offline_attempts": 0,
        "google_runtime_used": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
