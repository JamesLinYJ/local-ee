"""Independent precision/mask controls for structural Double conditionals."""
from copy import deepcopy
import json

import numpy as np
import pytest

from ee_float64_graph_reference import evaluate_float64_graph
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Image, Pixel, const
from gee.compat.earthengine.pixel_selection_graph import select_float64
from gee.ee_translate import UnsupportedEEError
from test_ee_double_array_solve import (
    _compile_raster, _encode, _first_image, ee, local, offline_only,
)


def _data(local, **bands):
    values = local["arrays"][local["item_id"]]
    for name, samples in bands.items():
        values[name] = np.asarray(samples, dtype=np.float64)


def _direct(ee, local, build):
    translator = Translator(local["catalog"], local["items"], {})
    image = translator.evaluate(_encode(ee, _first_image(ee).select(["y0", "y1", "y2"]).toDouble()))
    graph = Graph(translator)
    pixel = build(*(pixel for _, pixel in image.bands))
    output = Image([("chosen", pixel)], dict(image.props), image.source)
    reference, timed = graph.image(output)
    result = {"process_graph": graph.finish(reference)}
    actual, names, has_time = evaluate_float64_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries=local["geometries"],
    )
    assert has_time is False and timed is False and names == ["chosen"]
    return result, actual[0]


def test_public_where_preserves_double_values_masks_names_and_properties(ee, local):
    _data(local,
          y0=[16777217, -1e308, np.nan, 1.25, 5e-324, 3],
          y1=[1, 0, 1, np.nan, 1, 1],
          y2=[16777219, 1e308, 4, 8, np.nan, 9])
    image = _first_image(ee).set("selection_tag", "preserved")
    output = image.select("y0").toDouble().where(
        image.select("y1").toDouble(), image.select("y2").toDouble(),
    )
    result, actual, names = _compile_raster(ee, output, local)
    np.testing.assert_array_equal(actual, [[16777219, -1e308, np.nan, 1.25, 5e-324, np.nan]])
    assert names == ["y0"] and result["properties"]["selection_tag"] == "preserved"
    assert result["source_item_ids"] == [local["item_id"]]
    assert any(node["process_id"] == "local_ee_integer_values"
               and json.loads(node["arguments"]["spec"])["op"] == "where_select"
               for node in result["process_graph"].values())


@pytest.mark.parametrize("double_input", [False, True])
def test_public_where_promotes_mixed_inputs_without_restoring_float32_bits(ee, local, double_input):
    _data(local, y0=[16777217] * 6, y1=[1, 0, 1, 0, 1, 0], y2=[16777219] * 6)
    image = _first_image(ee)
    left, right = image.select("y0"), image.select("y2")
    left = left.toDouble() if double_input else left.toFloat()
    right = right.toFloat() if double_input else right.toDouble()
    _, actual, _ = _compile_raster(ee, left.where(image.select("y1"), right), local)
    replacement = float(np.float32(16777219)) if double_input else 16777219
    original = 16777217 if double_input else float(np.float32(16777217))
    np.testing.assert_array_equal(actual, [[replacement, original, replacement, original, replacement, np.nan]])


def test_direct_numeric_double_condition_preserves_subnormal_truth_and_missing(ee, local):
    _data(local, y0=[5e-324, -5e-324, 0, -0., np.nan, 1],
          y1=[1e308, -1e308, 2, 2, 2, 2], y2=[3, 3, 16777217, -16777219, 3, 3])
    _, actual = _direct(ee, local, lambda test, yes, no: Pixel("if", (test, yes, no)))
    np.testing.assert_array_equal(actual, [1e308, -1e308, 16777217, -16777219, np.nan, np.nan])


def test_unselected_missing_branch_does_not_mask_selected_values(ee, local):
    _data(local, y0=[1, 0, 1, 0, np.nan, 1],
          y1=[16777217, np.nan, np.nan, 4, 4, 4],
          y2=[np.nan, 16777219, 3, np.nan, 3, 3])
    _, actual = _direct(ee, local, lambda test, yes, no: Pixel("if", (test, yes, no)))
    np.testing.assert_array_equal(actual, [16777217, 16777219, np.nan, np.nan, np.nan, np.nan])


def test_both_signed_zeros_are_copied_without_arithmetic(ee, local):
    _data(local, y0=[1, 0, 1, 0, 1, 0], y1=[-0., 0., 0., 0., -0., 0.], y2=[0., -0., -0., 0., 0., 0.])
    _, actual = _direct(ee, local, lambda test, yes, no: Pixel("if", (test, yes, no)))
    np.testing.assert_array_equal(actual[:5], np.zeros(5))
    np.testing.assert_array_equal(np.signbit(actual[:5]), [True, True, False, False, True])


def test_source_free_literal_branch_has_independent_mask_and_no_precision_loss(ee, local):
    _data(local, y0=[1, 0, 1, 0, np.nan, 1], y2=[np.nan, 8, np.nan, 9, 10, 11])
    _, actual = _direct(ee, local, lambda test, _yes, no: Pixel("if", (test, const(16777219), no)))
    np.testing.assert_array_equal(actual, [16777219, 8, 16777219, 9, np.nan, np.nan])


def test_source_free_null_accept_branch_does_not_fall_back(ee, local):
    _data(local, y0=[1, 0, 1, 0, np.nan, 1], y2=[1, 2, 3, 4, 5, 6])
    _, actual = _direct(ee, local, lambda test, _yes, no: Pixel("if", (test, const(None), no)))
    np.testing.assert_array_equal(actual, [np.nan, 2, np.nan, 4, np.nan, np.nan])


def test_large_finite_replacement_is_an_exact_native_wire_constant(ee, local):
    image = _first_image(ee)
    _data(local, y1=[1, 1, 1, 1, 1, 1])
    result, actual, _ = _compile_raster(
        ee, image.select("y0").toDouble().where(image.select("y1"), 1e30), local,
    )
    np.testing.assert_array_equal(actual, [[1e30] * 5 + [np.nan]])
    assert not any(node["process_id"] == "local_ee_constant_on_grid"
                   for node in result["process_graph"].values())
    with pytest.raises(UnsupportedEEError, match="within.*2\\^53"):
        _compile_raster(ee, image.select("y0").toDouble().where(image.select("y1"), 2**53 + 1), local)


@pytest.mark.parametrize("args", [(), (const(1),), (const(1), const(2), 3)])
def test_invalid_selection_operands_reject_before_graph_nodes(local, args):
    graph = Graph(Translator(local["catalog"], local["items"], {}))
    with pytest.raises(UnsupportedEEError, match="exactly three Pixel"):
        select_float64(graph, Pixel("if", args))
    assert graph.graph == {}


def test_selection_reservation_rejects_before_scanning_or_building_graph(local):
    translator = Translator(local["catalog"], local["items"], {})
    translator.steps = 49_953
    graph = Graph(translator)
    with pytest.raises(UnsupportedEEError, match="50000-step work budget"):
        select_float64(graph, Pixel("if", (const(1), const(2), const(3))))
    assert not graph.graph and translator.steps == 49_953


def test_warm_expression_facts_cannot_authorize_changed_grid(ee, local):
    first = local["items"]["sentinel-2-l2a"][0]
    first["properties"].update({"proj:code": "EPSG:32649", "proj:transform": [10, 0, 0, 0, -10, 0]})
    other = deepcopy(first)
    other["id"] = "other-observation"
    other["properties"].update({"system:index": other["id"], "system:time_start": 2000})
    local["items"]["sentinel-2-l2a"].append(other)
    translator = Translator(local["catalog"], local["items"], {})
    collection = ee.ImageCollection("sentinel-2-l2a")
    a = translator.evaluate(_encode(ee, collection.first().select("y0").toDouble()))
    b = Translator(local["catalog"], local["items"], {}).evaluate(
        _encode(ee, collection.sort("system:time_start", False).first().select("y0").toDouble()),
    )
    left, right = a.bands[0][1], b.bands[0][1]
    pixel = Pixel("if", (Pixel("gt", (left, const(0)), True), left, right))
    select_float64(Graph(translator), pixel)
    other["properties"]["proj:transform"] = [10, 0, 5, 0, -10, 0]
    graph = Graph(translator)
    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        select_float64(graph, pixel)
    assert not graph.graph
