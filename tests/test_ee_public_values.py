"""Public result bounds and typed metadata composition, without leaking IR."""
import json

import pytest

from gee.compat.earthengine.array_values import ARRAY_FUNCTIONS, StaticArray
from gee.compat.earthengine.capabilities import SUPPORTED_FUNCTIONS, get_capabilities
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, UnsupportedEEError
from gee.compat.earthengine.join_ops import JOIN_FUNCTIONS
from gee.compat.earthengine.public_values import public_result


def test_typed_array_metadata_remains_computable_until_public_output():
    translator = Translator([], {}, None)
    matrix = translator.invoke("Array", {"values": [[1, 2], [3, 4]]})
    image = Image([("red", Pixel("constant", (7,)))], {"system:index": "primary"})
    tagged = translator.invoke("Element.set", {"object": image, "key": "matrix", "value": matrix})
    extracted = translator.invoke("Element.get", {"object": tagged, "property": "matrix"})
    assert isinstance(extracted, StaticArray)
    assert translator.invoke("Array.get", {"array": extracted, "position": [1, 0]}) == 3
    result = public_result({"properties": tagged.props})
    assert result["properties"]["matrix"] == [[1, 2], [3, 4]]
    json.dumps(result, allow_nan=False)


def test_joined_images_have_metadata_descriptions_without_pixel_ir():
    matched = Image([("nir", Pixel("constant", (4,)))], {"system:index": "secondary"})
    primary = Image([], {"system:index": "primary", "matches": [matched]})
    public = public_result({"value": primary})
    match = public["value"]["properties"]["matches"][0]
    assert match == {"type": "Image", "id": "secondary", "properties": {"system:index": "secondary"}, "bands": [{"id": "nir"}]}
    assert "Pixel" not in json.dumps(public)


def test_response_budget_applies_to_all_shared_matches_together():
    matched = Image([], {"description": "x" * 2000})
    with pytest.raises(UnsupportedEEError, match="1 MB"):
        public_result({"matches": [matched] * 600})
    with pytest.raises(UnsupportedEEError, match="materialization limits"):
        public_result([list(range(500))] * 101)


def test_recursive_metadata_stops_before_unbounded_materialization():
    image = Image([], {})
    image.props["cycle"] = image
    with pytest.raises(UnsupportedEEError, match="materialization limits"):
        public_result(image)


def test_large_shared_strings_reject_without_allocating_full_encoded_response():
    import tracemalloc

    value = {"strings": ["x" * 100_000] * 200}
    tracemalloc.start()
    try:
        with pytest.raises(UnsupportedEEError, match="1 MB"):
            public_result(value)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2_000_000


@pytest.mark.parametrize("text", ['"', "\\", "\n", "\x00", "中文", "\U0001f30d"])
def test_escaped_strings_and_dictionary_keys_count_toward_output_budget(text):
    repetitions = 500_000 // (len(json.dumps(text)) - 2) + 1
    value = {text * repetitions: text * repetitions}
    assert len(json.dumps(value)) > 1_000_000
    with pytest.raises(UnsupportedEEError, match="1 MB"):
        public_result(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1: "invalid key"}, Pixel("constant", (1,))])
def test_invalid_public_values_reject(value):
    with pytest.raises(UnsupportedEEError):
        public_result({"nested": value})


def test_capability_inventory_covers_the_implemented_static_array_and_join_slice():
    assert ARRAY_FUNCTIONS <= SUPPORTED_FUNCTIONS
    assert JOIN_FUNCTIONS <= SUPPORTED_FUNCTIONS
    assert "Filter.notNull" in SUPPORTED_FUNCTIONS
    assert "Reducer.linearRegression" in SUPPORTED_FUNCTIONS
    restrictions = get_capabilities()["restrictions"]
    assert any("inline FeatureCollection.reduceColumns and List.reduce" in item
               and "general raster linearRegression" in item for item in restrictions)
    assert "List.reduce" in SUPPORTED_FUNCTIONS
    assert "Classifier.smileRandomForest" not in SUPPORTED_FUNCTIONS
