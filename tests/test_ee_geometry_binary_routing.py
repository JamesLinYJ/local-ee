"""Empty maps validate official binary signatures without inventing a row."""
from __future__ import annotations

import copy

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_map_preflight import preflight_empty_feature_map
from gee.compat.earthengine.ir import Function, UnsupportedEEError


METHODS = (
    "contains", "containedIn", "disjoint", "intersects", "intersection",
    "union", "difference", "symmetricDifference",
)


def function(name):
    return Function(["row"], {
        "type": "Invocation", "functionName": name,
        "arguments": {
            "left": {"type": "ArgumentRef", "value": "row"},
            "right": {"type": "ArgumentRef", "value": "row"},
            "proj": {"type": "Invocation", "functionName": "Projection",
                     "arguments": {"crs": "EPSG:4326"}},
        },
    }, {})


@pytest.mark.parametrize("family", ["Geometry", "Feature"])
@pytest.mark.parametrize("method", METHODS)
def test_empty_map_accepts_only_supported_keyword_structure(family, method):
    callback = function(f"{family}.{method}")
    original = copy.deepcopy(callback.body)
    translator = Translator([], {}, {})
    preflight_empty_feature_map(translator, callback)
    assert callback.body == original
    assert translator.steps > 0
    assert translator.scope == {}

    callback.body["arguments"]["unexpected"] = True
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        preflight_empty_feature_map(Translator([], {}, {}), callback)

    callback.body["arguments"].pop("unexpected")
    callback.body["arguments"].pop("right")
    with pytest.raises(UnsupportedEEError, match="missing required arguments"):
        preflight_empty_feature_map(Translator([], {}, {}), callback)
