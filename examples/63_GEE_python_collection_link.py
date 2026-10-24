"""Link explicitly loaded local QA bands and combine matching observations.

The accompanying fixture declares synthetic source grids, metadata and masks.
Replace the collection and filters with your own ingested observations; this
script does not load a Google cloud-probability dataset.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


def declared_local_data(fixture):
    return fixture["catalog"], {
        "sentinel-2-l2a": [scene["item"] for scene in fixture["scenes"]],
    }


def build_workflow(ee, fixture):
    base = ee.ImageCollection(fixture["catalog"][0]["id"])
    primary = base.filter(ee.Filter.eq("side", "primary")).select(["red", "nir"])
    quality = base.filter(ee.Filter.eq("side", "qa"))
    # The official collection helper maps Image.linkCollection over the input.
    linked = primary.linkCollection(quality, ["qa"], ["qa_version"])
    first = ee.Image(linked.filter(ee.Filter.eq("system:index", "a")).first())
    missing = ee.Image(linked.filter(ee.Filter.eq("system:index", "b")).first())
    last = ee.Image(linked.filter(ee.Filter.eq("system:index", "c")).first())
    custom = ee.Image(primary.first()).linkCollection(
        quality, ["qa"], ["qa_version"], "scene",
    )
    extra = quality.select(["nir", "qa"])
    keep = primary.combine(extra, overwrite=False)
    overwrite = primary.combine(extra, overwrite=True)
    return {
        "linked_collection": linked,
        "linked_a": first,
        "linked_b": missing,
        "linked_c": last,
        "custom_key_a": custom,
        "clear_a": first.select(["red", "nir"]).updateMask(first.select("qa").lt(50)),
        "keep_collection": keep,
        "keep_a": ee.Image(keep.first()),
        "overwrite_a": ee.Image(overwrite.first()),
        "version_a": first.get("qa_version"),
        "version_b": missing.get("qa_version"),
        "primary_index_after_link": first.get("system:index"),
        "primary_actual_id_after_link": first.id(),
    }


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.offline import OfflineGuard

    fixture = json.loads((root / "tests/fixtures/ee-collection-link-wave58-v1.json").read_text())
    catalog, items = declared_local_data(fixture)
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        results = {
            key: compile_expression(
                ee.serializer.encode(value, for_cloud_api=False), catalog, items,
            ) for key, value in build_workflow(ee, fixture).items()
        }
    print(json.dumps({
        "fixture": fixture["schema"],
        "outputs": {key: {field: value[field] for field in ("kind", "bands", "value")
                          if field in value} for key, value in results.items()},
        "network_attempts": guard.evidence()["attempt_count"],
        "services_used": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
