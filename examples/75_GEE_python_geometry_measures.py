"""Compute finite geometry metrics through the offline official EE client."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def build_workflow(ee):
    """Keep default metre metrics separate from explicit planar degree metrics."""
    polygon = ee.Geometry.Polygon([[[0, 0], [90, 0], [0, 90], [0, 0]]])
    line = ee.Geometry.LineString([[0, 0], [90, 0]])
    projection = ee.Projection("EPSG:4326")
    planar = ee.Geometry.Polygon(
        [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]],
        proj=projection, geodesic=False,
    )
    features = ee.FeatureCollection([
        ee.Feature(polygon, {"name": "octant"}),
        ee.Feature(line, {"name": "equator"}),
    ])

    def measure(feature):
        return feature.set({
            "area_m2": feature.area(),
            "length_m": feature.length(),
            "perimeter_m": feature.perimeter(),
        })

    return {
        "area_m2": polygon.area(),
        "length_m": line.length(),
        "perimeter_m": polygon.perimeter(),
        "centroid": polygon.centroid(),
        "planar_area_deg2": planar.area(proj=projection),
        "measured_features": features.map(measure),
    }


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:1/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        compiled = {
            name: compile_expression(
                ee.serializer.encode(expression, for_cloud_api=False), [], {},
            )
            for name, expression in build_workflow(ee).items()
        }
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({"compiled": compiled, "offline": guard.evidence(),
                      "google_runtime_used": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
