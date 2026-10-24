"""Run official Earth Engine Python spatial filters through local fixtures."""
from __future__ import annotations

import json
from pathlib import Path
import sys


REGIONS = {
    "dateline": [[170, -5], [-170, -5], [-170, 5], [170, 5], [170, -5]],
    "polar": [[-135, 78], [-45, 78], [45, 78], [135, 78], [-135, 78]],
    "high_left": [[0, 65], [60, 65], [30, 82], [0, 65]],
    "high_right": [[30, 65], [90, 65], [60, 82], [30, 65]],
}

POINTS = (
    ("dateline_inside", [180, 0]),
    ("dateline_outside", [0, 0]),
    ("polar_inside", [0, 89]),
    ("polar_outside", [0, 50]),
    ("high_left_only", [15, 75]),
    ("high_overlap", [45, 75]),
    ("high_right_only", [75, 75]),
    ("curved_inside", [25, 70]),
    ("curved_planar_only", [25, 66]),
    ("high_below", [45, 60]),
)


def build_workflow(ee):
    """Build independent dateline/polar queries and one high-latitude export."""
    geometries = {
        name: ee.Geometry.Polygon([ring]) for name, ring in REGIONS.items()
    }
    all_points = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point(coordinates), {"point_id": name})
        for name, coordinates in POINTS
    ])
    high_points = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point(coordinates), {"point_id": name})
        for name, coordinates in POINTS if name.startswith(("high_", "curved_"))
    ])
    query_points = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point(coordinates), {"point_id": name})
        for name, coordinates in POINTS
        if name in {"high_overlap", "curved_inside", "curved_planar_only"}
    ])

    high_regions = ee.FeatureCollection([
        ee.Feature(geometries[name], {"region_id": name})
        for name in ("high_left", "high_right")
    ])
    merged = high_regions.geometry()
    merged_null = high_regions.geometry(maxError=None)
    merged_typed = high_regions.geometry(maxError=ee.ErrorMargin(0))
    filters = {
        "field_value_numeric": ee.Filter.intersects(
            leftField=".geo", rightValue=geometries["high_left"], maxError=5,
        ),
        "value_field_typed": ee.Filter.intersects(
            leftValue=geometries["high_left"], rightField=".geo",
            maxError=ee.ErrorMargin(5, "projected"),
        ),
        "field_field_typed": ee.Filter.intersects(
            leftField=".geo", rightField=".geo", maxError=ee.ErrorMargin(5),
        ),
        "value_value_numeric": ee.Filter.intersects(
            leftValue=geometries["high_left"],
            rightValue=geometries["high_right"], maxError=5,
        ),
    }

    selected = query_points.filterBounds(merged)
    filter_results = {
        name: high_points.filter(spatial_filter)
        for name, spatial_filter in filters.items()
    }

    first_match = ee.Feature(selected.first()).set("row_kind", "filter_result")
    region_row = ee.Feature(merged, {"row_kind": "regionGeometry"})
    table = ee.FeatureCollection([first_match, region_row])
    return {
        "dateline_selected": all_points.filterBounds(geometries["dateline"]),
        "polar_selected": all_points.filterBounds(geometries["polar"]),
        "merge_omitted": merged,
        "merge_null": merged_null,
        "merge_typed": merged_typed,
        "filters": filters,
        "filter_results": filter_results,
        "selected": selected,
        "table": table,
    }


def encode_workflow(ee, values):
    encode = lambda value: ee.serializer.encode(value, for_cloud_api=False)
    return {
        "dateline_selected": encode(values["dateline_selected"]),
        "polar_selected": encode(values["polar_selected"]),
        "merge_omitted": encode(values["merge_omitted"]),
        "merge_null": encode(values["merge_null"]),
        "merge_typed": encode(values["merge_typed"]),
        "filters": {name: encode(value) for name, value in values["filters"].items()},
        "filter_results": {
            name: encode(value) for name, value in values["filter_results"].items()
        },
        "selected": encode(values["selected"]),
        "table": encode(values["table"]),
    }


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        encoded = encode_workflow(ee, build_workflow(ee))
        compiled = {}
        for name, wire in encoded.items():
            if name == "filters":
                continue
            if name == "filter_results":
                compiled[name] = {
                    filter_name: compile_expression(filter_wire, [], {})
                    for filter_name, filter_wire in wire.items()
                }
            else:
                compiled[name] = compile_expression(
                    wire, [], {}, for_table_export=name == "table",
                )
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({
        "selected_point_ids": [
            row["properties"]["point_id"]
            for row in compiled["selected"]["value"]["features"]
        ],
        "dateline_point_ids": [
            row["properties"]["point_id"]
            for row in compiled["dateline_selected"]["value"]["features"]
        ],
        "polar_point_ids": [
            row["properties"]["point_id"]
            for row in compiled["polar_selected"]["value"]["features"]
        ],
        "export_rows": len(compiled["table"]["value"]["features"]),
        "offline_attempts": 0,
        "google_runtime_used": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
