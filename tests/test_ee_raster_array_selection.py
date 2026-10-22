"""Single-array selection retains data while sharing bundle selector rules."""
from copy import deepcopy

import numpy as np
import pytest

from gee.compat.earthengine.array_core import MAX_ARRAY_WORK
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_array_accumulation import (
    compile_raster, compile_value, ee, encode, first_image,
    local, source_array, source_values, valid_samples,
)


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


def array_image(ee):
    return source_array(
        ee, first_image(ee).set("selection_tag", "kept"),
        ["v00", "v05", "v08", "v09"], (2, 2), "samples",
    )


def array_selection_invocation(value, scope=None):
    if scope is None:
        scope = dict(value.get("scope", [])) if isinstance(value, dict) else {}
    if isinstance(value, dict):
        selectors = value.get("arguments", {}).get("bandSelectors")
        if isinstance(selectors, dict) and selectors.get("type") == "ValueRef":
            selectors = scope[selectors["value"]]
        if (value.get("functionName") == "Image.select"
                and selectors == [0]):
            return value
        children = value.values()
    elif isinstance(value, (list, tuple)):
        children = value
    else:
        return None
    for child in children:
        found = array_selection_invocation(child, scope)
        if found is not None:
            return found
    return None


@pytest.mark.parametrize("selector", ["samples", 0])
def test_sdk_single_array_select_preserves_cells_masks_and_metadata(ee, local, selector):
    source = array_image(ee)
    before = deepcopy(local["arrays"])
    selected = source.select([selector], ["chosen"])
    assert compile_value(ee, selected.bandNames(), local)["value"] == ["chosen"]
    assert compile_value(ee, source.bandNames(), local)["value"] == ["samples"]
    result, actual, names = compile_raster(
        ee, selected.arrayFlatten([["r0", "r1"], ["c0", "c1"]]), local,
    )
    expected = source_values(local, ["v00", "v05", "v08", "v09"], (2, 2))
    expected = expected.reshape((5, 4)).T.copy()
    expected[:, ~valid_samples(local, ["v00", "v05", "v08", "v09"])] = np.nan
    np.testing.assert_array_equal(actual, expected)
    assert names == result["bands"] == ["r0_c0", "r0_c1", "r1_c0", "r1_c1"]
    assert result["properties"]["selection_tag"] == "kept"
    assert result["source_item_ids"] == ["accum-scene"]
    for band, values in before["accum-scene"].items():
        np.testing.assert_array_equal(local["arrays"]["accum-scene"][band], values)


@pytest.mark.parametrize("selectors,names", [
    (["sam.*"], None), ([1], None), ([False], None), ([], None),
    ([0, 0], None), ([0], []), ([0], ["a", "b"]), ([0], [""]),
])
def test_single_array_select_rejects_unsupported_selectors_and_renames(ee, local, selectors, names):
    selected = array_image(ee).select(selectors, names)
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, selected.bandNames(), local)


def test_single_array_select_rejects_missing_and_unknown_parameters(ee, local):
    selected = array_image(ee).select([0]).bandNames()
    missing = encode(ee, selected)
    array_selection_invocation(missing)["arguments"].pop("bandSelectors")
    with pytest.raises(UnsupportedEEError, match="requires input and bandSelectors"):
        compile_expression(missing, local["catalog"], local["items"])
    unknown = encode(ee, selected)
    array_selection_invocation(unknown)["arguments"]["unused"] = 1
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(unknown, local["catalog"], local["items"])


def raw_array():
    source = Source("sentinel-2-l2a", ("accum-scene",), ("v00",))
    pixel = Pixel("to_float", (Pixel("band", (source, "v00")),))
    image = Image([], {"original": True}, source)
    return wrap_array_image(image, (1,), (pixel,), const(None), "samples")


def test_single_array_select_retains_exact_ir_provenance_and_nodata_mask():
    array = raw_array()
    selected = Translator([], {}, {}).invoke("Image.select", {
        "input": array, "bandSelectors": [0], "newNames": ["chosen"],
    })
    assert selected.cells is array.cells
    assert selected.mask is array.mask
    assert selected.image is array.image
    assert selected.name == "chosen" and array.name == "samples"


def test_single_array_select_precharges_before_selected_wrapper(monkeypatch):
    import gee.compat.earthengine.raster_array_bands as bands

    def forbidden(*args, **kwargs):
        raise AssertionError("selected wrapper constructed before work preflight")

    array = raw_array()
    monkeypatch.setattr(bands, "replace", forbidden)
    translator = Translator([], {}, {})
    translator.steps = MAX_ARRAY_WORK - 1
    with pytest.raises(UnsupportedEEError, match="work budget"):
        translator.invoke("Image.select", {"input": array, "bandSelectors": [0]})
