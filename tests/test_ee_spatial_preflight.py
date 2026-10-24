"""Static spatial signatures cannot bypass empty collections or opaque values."""
import json
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_map_preflight import preflight_empty_feature_map
from gee.compat.earthengine.ir import Function, UnsupportedEEError
from gee.compat.earthengine.spatial_filters import SPATIAL_FILTER_ARGUMENTS
from gee.ee_translate import compile_expression


def _invocation(name, arguments):
    return {"type": "Invocation", "functionName": name, "arguments": arguments}


def test_intersects_contract_has_exact_pinned_keyword_names():
    path = Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json"
    signature = next(value for value in json.loads(path.read_text())["algorithms"]
                     if value["name"] == "algorithms/Filter.intersects")
    expected = {value["argumentName"] for value in signature["arguments"]}
    required, optional = SPATIAL_FILTER_ARGUMENTS["Filter.intersects"]
    assert not required
    assert optional == expected


@pytest.mark.parametrize("name,arguments", [
    ("Filter.intersects", {"leftField": ".geo", "rightField": ".geo"}),
    ("Collection.geometry", {"collection": {"type": "ArgumentRef", "value": "f"}}),
    ("ErrorMargin", {"value": 1}),
])
def test_empty_callback_checks_keyword_names_without_evaluating_row(name, arguments):
    translator = Translator([], {}, {})
    body = _invocation(name, arguments)
    function = Function(["f"], body, {})
    preflight_empty_feature_map(translator, function)
    assert translator.steps > 0
    body["arguments"]["unexpected"] = True
    with pytest.raises(UnsupportedEEError, match="unexpected"):
        preflight_empty_feature_map(Translator([], {}, {}), function)


def test_error_margin_opaque_output_requires_an_audited_consumer():
    margin = _invocation("ErrorMargin", {"value": 1})
    with pytest.raises(UnsupportedEEError, match="ErrorMargin output requires"):
        compile_expression(margin, [], {})
    with pytest.raises(UnsupportedEEError):
        compile_expression({"type": "Dictionary", "value": {"margin": margin}}, [], {})


def test_empty_catalog_filter_preflights_literals_and_all_branches():
    from gee.compat.earthengine.collection_ops import invoke_collection
    from gee.compat.earthengine.ir import Collection, Filter, Image, Source

    translator = Translator([], {}, {})
    # The collection has no rows. Its data-independent invalid ROI must still
    # fail before enumeration, even after a branch which would be false.
    source = Source("empty", (), ())
    image = Image([], {}, source)
    collection = Collection(source, image)
    bad = Filter("intersects", {"leftField": ".all", "rightValue": {
        "type": "Point", "coordinates": [181, 0],
    }})
    conjunction = Filter("and", {"filters": [Filter("never", {}), bad]})
    with pytest.raises(UnsupportedEEError, match="longitude|bounds"):
        invoke_collection(translator, "Collection.filter", {
            "collection": collection, "filter": conjunction,
        })
