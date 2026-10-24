"""Bounded metadata and raster behavior for Image.linkCollection/combine."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.image_collection_link import invoke_collection_link
from gee.compat.earthengine.image_collection_link_common import frames
from gee.compat.earthengine.image_collection_link_grid import _time_start
from gee.compat.earthengine.ir import Image, ImageSequence, Pixel, Source, rebind
from gee.ee_translate import UnsupportedEEError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-collection-link-wave58-v1.json"


def local_state(data=None):
    data = json.loads(FIXTURE.read_text()) if data is None else data
    rows = [deepcopy(scene["item"]) for scene in data["scenes"]]
    translator = Translator(data["catalog"], {"sentinel-2-l2a": rows}, {})
    collection = translator.load("sentinel-2-l2a")
    by_id = {
        item_id: translator.first(rebind(collection, [item_id]))
        for item_id in (item["id"] for item in rows)
    }
    return translator, rows, by_id


def invoke(translator, algorithm, **arguments):
    return invoke_collection_link(translator, algorithm, arguments)


def test_link_collection_adds_string_or_list_bands_and_masks_a_missing_match():
    translator, _rows, by_id = local_state()
    linked = invoke(
        translator, "Image.linkCollection", input=by_id["p-a"],
        imageCollection=ImageSequence([by_id["q-a"], by_id["q-c"]]),
        linkedBands="qa",
    )
    assert [name for name, _ in linked.bands] == ["red", "nir", "qa"]
    assert linked.source.ids == ("p-a",)
    assert linked.props["side"] == "primary"

    missing = invoke(
        Translator(json.loads(FIXTURE.read_text())["catalog"], {
            "sentinel-2-l2a": [deepcopy(row) for row in _rows]
        }, {}),
        "Image.linkCollection", input=by_id["p-b"],
        imageCollection=ImageSequence([by_id["q-a"], by_id["q-c"]]),
        linkedBands=["qa"],
    )
    masked = dict(missing.bands)["qa"]
    assert masked.op == "if"
    assert masked.args[0] == Pixel("constant", (False,), True)
    assert masked.args[2] == Pixel("constant", (None,))


def test_link_collection_copies_nested_properties_and_explicit_system_metadata():
    translator, _rows, by_id = local_state()
    primary = deepcopy(by_id["p-a"])
    primary.props["pair_key"] = 7
    candidate = deepcopy(by_id["q-a"])
    candidate.props.update({
        "pair_key": 7,
        "system:index": "qa-a",
        "system:time_start": 1704067200099,
    })
    version = candidate.props["qa_version"]
    result = invoke(
        translator, "Image.linkCollection", input=primary,
        imageCollection=ImageSequence([candidate]), linkedProperties=[
            "qa_version", "system:index", "system:time_start",
        ], matchPropertyName="pair_key",
    )
    assert result.props["qa_version"] == version
    assert result.props["qa_version"] is not version
    assert result.props["system:index"] == "qa-a"
    assert result.props["system:time_start"] == 1704067200099
    assert result.source.ids == ("p-a",)
    assert result.props["side"] == "primary"

    missing = invoke(
        translator, "Image.linkCollection", input=primary,
        imageCollection=ImageSequence([]), linkedProperties="qa_version",
        matchPropertyName="pair_key",
    )
    assert missing.props["qa_version"] is None
    assert missing.source.ids == ("p-a",)


@pytest.mark.parametrize("selector", [None, []])
def test_null_and_empty_selectors_are_local_no_selection(selector):
    translator, _rows, by_id = local_state()
    candidates = ImageSequence([by_id["q-a"], by_id["q-c"]])
    result = invoke(
        translator, "Image.linkCollection", input=by_id["p-a"],
        imageCollection=candidates, linkedBands=selector,
        linkedProperties=selector,
    )
    assert result is by_id["p-a"]


def test_link_collection_properties_only_bands_only_and_neither():
    translator, _rows, by_id = local_state()
    candidates = ImageSequence([by_id["q-a"]])
    properties_only = invoke(
        translator, "Image.linkCollection", input=by_id["p-a"],
        imageCollection=candidates, linkedProperties="qa_version",
    )
    assert properties_only.bands is by_id["p-a"].bands
    assert properties_only.props["qa_version"] == {"major": 1, "tags": ["synthetic"]}

    bands_only = invoke(
        translator, "Image.linkCollection", input=by_id["p-a"],
        imageCollection=candidates, linkedBands=["qa"],
    )
    assert [name for name, _ in bands_only.bands] == ["red", "nir", "qa"]
    assert bands_only.props is by_id["p-a"].props

    neither = invoke(
        translator, "Image.linkCollection", input=by_id["p-a"],
        imageCollection=candidates,
    )
    assert neither is by_id["p-a"]


def test_link_collection_rejects_ambiguous_or_invalid_match_values_and_missing_bands():
    translator, _rows, by_id = local_state()
    duplicate = deepcopy(by_id["q-c"])
    duplicate.props["system:index"] = "a"
    candidates = ImageSequence([by_id["q-a"], duplicate])
    with pytest.raises(UnsupportedEEError, match="duplicate match keys"):
        invoke(
            translator, "Image.linkCollection", input=by_id["p-a"],
            imageCollection=candidates, linkedProperties="qa_version",
        )

    with pytest.raises(UnsupportedEEError, match="missing from a matching image"):
        invoke(
            translator, "Image.linkCollection", input=by_id["p-a"],
            imageCollection=ImageSequence([by_id["q-a"]]),
            linkedBands="not_a_band",
        )
    with pytest.raises(UnsupportedEEError, match="flat property key"):
        invoke(
            translator, "Image.linkCollection", input=by_id["p-a"],
            imageCollection=ImageSequence([by_id["q-a"]]),
            linkedProperties="nested.key",
        )
    with pytest.raises(UnsupportedEEError, match="flat scalar"):
        invoke(
            translator, "Image.linkCollection", input=by_id["p-a"],
            imageCollection=ImageSequence([by_id["q-a"]]),
            linkedProperties="qa_version", matchPropertyName="qa_version",
        )


def test_combine_is_inner_primary_ordered_and_uses_add_bands_overwrite_default():
    translator, _rows, by_id = local_state()
    primary = ImageSequence([by_id["p-c"], by_id["p-a"], by_id["p-b"]])
    secondary = ImageSequence([by_id["q-a"], by_id["q-c"]])

    kept = invoke(
        translator, "ImageCollection.combine", primary=primary,
        secondary=secondary,
    )
    assert [image.source.ids[0] for image in kept.images] == ["p-c", "p-a"]
    assert [name for name, _ in kept.images[0].bands] == [
        "red", "nir", "qa", "red_1", "nir_1", "qa_1",
    ]
    assert kept.images[0].props["side"] == "primary"

    replaced = invoke(
        translator, "ImageCollection.combine", primary=primary,
        secondary=secondary, overwrite=True,
    )
    assert [name for name, _ in replaced.images[0].bands] == ["red", "nir", "qa"]
    assert replaced.images[0].props["side"] == "primary"


def test_combine_rejects_duplicate_ids_and_matches_by_index_not_timestamp():
    translator, rows, by_id = local_state()
    p_c = next(row for row in rows if row["id"] == "p-c")
    q_c = next(row for row in rows if row["id"] == "q-c")
    tied_time = by_id["p-a"].props["system:time_start"]
    p_c["properties"]["system:time_start"] = tied_time
    q_c["properties"]["system:time_start"] = tied_time
    same_time_primary = deepcopy(by_id["p-c"])
    same_time_primary.props["system:time_start"] = tied_time
    by_id["q-c"].props["system:time_start"] = tied_time
    primary = ImageSequence([by_id["p-a"], same_time_primary])
    secondary = ImageSequence([by_id["q-a"], by_id["q-c"]])
    result = invoke(
        translator, "ImageCollection.combine", primary=primary,
        secondary=secondary,
    )
    assert [image.source.ids[0] for image in result.images] == ["p-a", "p-c"]
    # Equal timestamps do not collapse different system:index values.
    assert result.images[0].bands[-1][1] is not result.images[1].bands[-1][1]

    with pytest.raises(UnsupportedEEError, match="duplicate match keys"):
        invoke(
            translator, "ImageCollection.combine",
            primary=ImageSequence([by_id["p-a"], deepcopy(by_id["p-a"])]),
            secondary=secondary,
        )
    duplicate = deepcopy(by_id["q-c"])
    duplicate.props["system:index"] = "a"
    with pytest.raises(UnsupportedEEError, match="duplicate match keys"):
        invoke(
            translator, "ImageCollection.combine", primary=ImageSequence([by_id["p-a"]]),
            secondary=ImageSequence([by_id["q-a"], duplicate]),
        )


def _one_band_image(cid, item, band):
    source = Source(cid, (item["id"],), (band,))
    pixel = Pixel("reduce_t", (Pixel("band", (source, band)), "first"))
    return Image([(band, pixel)], dict(item["properties"]), source)


def test_pair_grid_proof_accepts_distinct_cids_only_with_actual_matching_evidence():
    data = json.loads(FIXTURE.read_text())
    rows = {scene["id"]: deepcopy(scene["item"]) for scene in data["scenes"]}
    translator = Translator(data["catalog"], {
        "primary-v1": [rows["p-a"]], "quality-v1": [rows["q-a"]],
    }, {})
    primary = _one_band_image("primary-v1", rows["p-a"], "red")
    quality = _one_band_image("quality-v1", rows["q-a"], "qa")
    result = invoke(
        translator, "Image.linkCollection", input=primary,
        imageCollection=ImageSequence([quality]), linkedBands="qa",
    )
    assert result.source == primary.source
    assert [name for name, _ in result.bands] == ["red", "qa"]

    shifted = deepcopy(rows["q-a"])
    shifted["assets"]["qa"]["proj:transform"][2] += .5
    bad_quality = _one_band_image("quality-v1", shifted, "qa")
    bad_translator = Translator(data["catalog"], {
        "primary-v1": [rows["p-a"]], "quality-v1": [shifted],
    }, {})
    with pytest.raises(UnsupportedEEError, match="affine evidence conflict"):
        invoke(
            bad_translator, "Image.linkCollection", input=primary,
            imageCollection=ImageSequence([bad_quality]), linkedBands="qa",
        )


def test_collection_materialization_precharges_metadata_before_legacy_copy_paths():
    translator, _rows, _by_id = local_state()
    collection = translator.load("sentinel-2-l2a")
    translator.steps = 49_900
    base_property_calls = []
    translator._base_properties = lambda *args: base_property_calls.append(args) or {}
    translator.member = lambda *_args: pytest.fail(
        "indexed materialization must not perform a linear catalogue member scan"
    )

    with pytest.raises(UnsupportedEEError, match="50000-step compilation work budget"):
        frames(translator, collection, "link materialization budget probe")
    assert not base_property_calls


def test_timestamp_proof_precharges_actual_properties_before_base_copy():
    translator, rows, _by_id = local_state()
    translator.steps = 49_990
    base_property_calls = []
    translator._base_properties = lambda *args: base_property_calls.append(args) or {}

    with pytest.raises(UnsupportedEEError, match="50000-step compilation work budget"):
        _time_start(translator, rows[0], "sentinel-2-l2a", "timestamp budget probe")
    assert not base_property_calls
