"""Pinned official Python and JavaScript mask-weight calls stay offline."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from gee.ee_python_client import configure_local_ee
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-mask-weights-wave64-v1.json"
GENERATOR = ROOT / "scripts/ee_mask_weights_fixtures.cjs"
NODE = shutil.which("node") or str(
    ROOT / ".native/toolchains/node-v24.22.1-darwin-arm64/bin/node"
)


def _invocations(value):
    if type(value) is dict:
        if value.get("type") == "Invocation":
            yield value
        for child in value.values():
            yield from _invocations(child)
    elif type(value) in (list, tuple):
        for child in value:
            yield from _invocations(child)


def _final_invocation(value):
    if value.get("type") == "CompoundValue":
        scope = dict(value["scope"])
        return scope[value["value"]["value"]]
    assert value.get("type") == "Invocation"
    return value


def _python_values(ee):
    collection = ee.ImageCollection("sentinel-2-l2a")
    scene = ee.Image(collection.first())
    source = scene.select(["red", "nir"]).toDouble()
    one_weight = ee.Image.constant(0.25).rename("weight")
    reversed_weights = ee.Image.constant([0.25, 0.75]).rename(["nir", "red"])
    weighted = source.updateMask(one_weight)
    stacked = weighted.updateMask(
        ee.Image.constant([0.75, 0.5]).rename(["red", "nir"]),
    )
    weighted_input_mask = scene.select("SCL").eq(4).updateMask(one_weight)
    mapped_mask_getter = collection.map(
        lambda image: image.select("nir").updateMask(ee.Image.constant(0.25)).mask(),
    )
    return {
        "updateFractionalBroadcast": weighted,
        "updateFractionalByOrder": source.updateMask(reversed_weights),
        "stackedReplacementUpdate": stacked,
        "maskGetter": weighted.mask(),
        "maskGetterNullDefault": weighted.mask(mask=None),
        "weightedMaskInput": source.select("red").updateMask(weighted_input_mask).mask(),
        "maskGetterByOrder": source.updateMask(reversed_weights).mask(),
        "stackedMaskGetter": stacked.mask(),
        "selectCarriesWeights": weighted.select("nir"),
        "selectMaskGetter": weighted.select("nir").mask(),
        "renameCarriesWeights": weighted.rename(["R", "N"]),
        "renameMaskGetter": weighted.rename(["R", "N"]).mask(),
        "addBandsCarriesWeights": scene.select("blue").addBands(
            weighted.rename(["R", "N"]),
        ),
        "addBandsMaskGetter": scene.select("blue").addBands(
            weighted.rename(["R", "N"]),
        ).mask(),
        "binaryUpdateCompatibility": scene.select("nir").updateMask(
            scene.select("SCL").neq(9),
        ),
        "weightedArithmetic": weighted.select("red").multiply(2),
        "weightedUnmask": weighted.unmask(0),
        "weightedMapMaskGetter": mapped_mask_getter,
        "mappedMaskGetterMean": mapped_mask_getter.mean(),
        "mappedMaskGetterToBands": mapped_mask_getter.toBands(),
        "weightedCollectionMean": collection.map(
            lambda image: image.select("nir").updateMask(ee.Image.constant(0.25)),
        ).mean(),
    }


@pytest.fixture(scope="module")
def python_sdk():
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        assert ee.__version__ == "1.7.49"
        values = _python_values(ee)
        encoded = {
            name: ee.serializer.encode(value, for_cloud_api=False)
            for name, value in values.items()
        }
        yield ee, values, encoded
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture(scope="module")
def javascript_fixture():
    if not Path(NODE).is_file():
        pytest.skip("Node is required to exercise the pinned JavaScript SDK")
    result = subprocess.run(
        [NODE, str(GENERATOR)], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    generated = json.loads(result.stdout)
    saved = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert generated == saved
    return generated


def test_both_official_sdks_are_pinned_and_javascript_network_tripwire_stays_quiet(
        python_sdk, javascript_fixture):
    _ee, _values, _encoded = python_sdk
    assert javascript_fixture["sdk"] == "1.7.49"
    assert javascript_fixture["source_commit"] == "e189e4b89e785019ea5642ea8e80cb644749cd4a"
    assert javascript_fixture["tripwire_attempts"] == 0
    assert javascript_fixture["sdk_expressions"]


def test_python_sdk_serializes_official_fractional_update_and_mask_getter(python_sdk):
    _ee, values, encoded = python_sdk
    update = _final_invocation(encoded["updateFractionalBroadcast"])
    assert update["functionName"] == "Image.updateMask"
    assert set(update["arguments"]) == {"image", "mask"}
    getter = _final_invocation(encoded["maskGetter"])
    assert getter["functionName"] == "Image.mask"
    assert set(getter["arguments"]) == {"image"}
    # The official Python binding accepts both the no-argument default and
    # explicit mask=None form; both serialize as the official getter overload.
    assert encoded["maskGetterNullDefault"] == encoded["maskGetter"]
    assert values["maskGetter"] is not None


def test_python_and_javascript_serialize_the_same_official_graphs_except_null_elision(
        python_sdk, javascript_fixture):
    _ee, _values, encoded = python_sdk
    for name, python_expression in encoded.items():
        # Python uses tuples for scope pairs in memory, while JSON from the JS
        # fixture uses arrays. Round-trip through JSON to compare the wire.
        python_wire = json.loads(json.dumps(python_expression))
        js_wire = javascript_fixture["sdk_expressions"][name]
        if name == "maskGetterNullDefault":
            python_call = _final_invocation(python_wire)
            js_call = _final_invocation(js_wire)
            assert python_call["functionName"] == js_call["functionName"] == "Image.mask"
            assert python_call["arguments"] == {"image": js_call["arguments"]["image"]}
            assert js_call["arguments"]["mask"] is None
        else:
            assert python_wire == js_wire, name


def test_fixed_js_fixture_covers_preservation_routes_and_unsupported_consumers(
        javascript_fixture):
    expressions = javascript_fixture["sdk_expressions"]
    expected = {
        "updateFractionalBroadcast", "updateFractionalByOrder", "stackedReplacementUpdate",
        "maskGetter", "maskGetterNullDefault", "maskGetterByOrder", "stackedMaskGetter",
        "weightedMaskInput",
        "selectCarriesWeights", "selectMaskGetter", "renameCarriesWeights", "renameMaskGetter",
        "addBandsCarriesWeights", "addBandsMaskGetter", "binaryUpdateCompatibility",
        "weightedArithmetic", "weightedUnmask", "weightedMapMaskGetter",
        "mappedMaskGetterMean", "mappedMaskGetterToBands", "weightedCollectionMean",
    }
    assert set(expressions) == expected
    names = {key: [row["functionName"] for row in _invocations(value)]
             for key, value in expressions.items()}
    assert names["updateFractionalBroadcast"][-1] == "Image.updateMask"
    assert names["stackedReplacementUpdate"].count("Image.updateMask") == 2
    assert _final_invocation(expressions["stackedReplacementUpdate"])["functionName"] == "Image.updateMask"
    assert names["maskGetter"][-1] == "Image.mask"
    assert names["maskGetterNullDefault"][-1] == "Image.mask"
    assert names["weightedMaskInput"][-1] == "Image.mask"
    assert names["selectCarriesWeights"][-1] == "Image.select"
    assert names["selectMaskGetter"][-1] == "Image.mask"
    assert names["renameCarriesWeights"][-1] == "Image.rename"
    assert names["renameMaskGetter"][-1] == "Image.mask"
    assert names["addBandsCarriesWeights"][-1] == "Image.addBands"
    assert names["addBandsMaskGetter"][-1] == "Image.mask"
    assert names["binaryUpdateCompatibility"][-1] == "Image.updateMask"
    assert names["weightedArithmetic"][-1] == "Image.multiply"
    assert names["weightedUnmask"][-1] == "Image.unmask"
    assert "Image.mask" in names["weightedMapMaskGetter"]
    assert names["weightedMapMaskGetter"][-1] == "Collection.map"
    assert names["mappedMaskGetterMean"][-1] == "reduce.mean"
    assert names["mappedMaskGetterToBands"][-1] == "ImageCollection.toBands"
    assert names["weightedCollectionMean"][-1] == "reduce.mean"

