"""Independent source/grid reference applies casts and actual footprints."""
from pathlib import Path

import numpy as np

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from test_ee_translate import evaluate_graph


def test_constant_reference_is_valid_over_template_nodata_and_masks_outside_geometry():
    ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json")
    geometry = {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": ["signal"]}}}]
    items = {"sentinel-2-l2a": [{"id": "a", "bbox": [0,0,1,1], "geometry": geometry, "properties": {}}]}
    source = ee.Image("a")
    constant = source.addBands(ee.Image.constant(1/3).rename("c")).select("c").toFloat()
    compiled = compile_expression(ee.serializer.encode(constant, for_cloud_api=False), catalog, items)
    values, names, timed = evaluate_graph(compiled,
        {"a": {"signal": np.array([np.nan, 3])}}, grid=[[0.5,0.5],[1.5,0.5]])
    assert names == ["c"] and timed is False
    # First sample is valid despite missing source data; second is outside the
    # source footprint even though its template sample is valid.
    np.testing.assert_array_equal(values, [[float(np.float32(1/3)), np.nan]])


def test_source_polygon_removes_rows_even_when_sample_is_inside_every_bbox():
    ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json")
    triangle = {"type": "Polygon", "coordinates": [[[0,0],[2,0],[0,2],[0,0]]]}
    square = {"type": "Polygon", "coordinates": [[[0,0],[2,0],[2,2],[0,2],[0,0]]]}
    geometries = {"a": triangle, "b": triangle, "c": square}
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": ["x", "y"]}}}]
    rows = [{"id": name, "bbox": [0,0,2,2], "geometry": geometries[name],
             "properties": {"system:index": name, "system:time_start": index}}
            for index, name in enumerate(geometries)]
    arrays = {name: {"x": np.array([x,x]), "y": np.array([2*x+1,2*x+1])}
              for x, name in enumerate(geometries)}
    fit = ee.ImageCollection("sentinel-2-l2a").reduce(ee.Reducer.linearFit())
    compiled = compile_expression(ee.serializer.encode(fit, for_cloud_api=False), catalog,
                                  {"sentinel-2-l2a": rows})
    values, names, timed = evaluate_graph(compiled, arrays,
        grid=[[0.25,0.25],[1.5,1.5]], source_geometries=geometries)
    assert names == ["scale", "offset"] and timed is False
    # Both centers are strictly inside every bbox. The second lies outside a
    # and b's triangles, leaving just c's one complete row, so it cannot fit.
    np.testing.assert_allclose(values, [[2,np.nan],[1,np.nan]], equal_nan=True)
