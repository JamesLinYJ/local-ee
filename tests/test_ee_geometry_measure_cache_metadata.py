"""Feature preflight reuse requires complete fresh content and detached output."""
from copy import deepcopy

import numpy as np
import pytest

from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_geometry_measures import invoke_feature_geometry_measures
from gee.compat.earthengine.feature_structure import invoke_feature_structure
from gee.compat.earthengine.geometry_measures import invoke_geometry_measures
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.ee_translate import UnsupportedEEError


def feature(number=1, identity="kept"):
    return {"type": "Feature", "id": identity,
            "geometry": {"type": "Point", "coordinates": [number, 2]},
            "properties": {"system:index": identity, "nested": {"values": [number]}}}


def identity(t, value):
    return invoke_feature_structure(t, "Feature.id", {"element": value})


def centroid(t, value):
    return invoke_feature_geometry_measures(t, "Feature.centroid", {"feature": value})


def test_only_complete_equal_features_skip_repeated_public_formatting(monkeypatch):
    from gee.compat.earthengine import feature_preflight_cache

    old = feature_preflight_cache.preflight_owned_metadata_value
    calls = []

    def count(*args, **kwargs):
        calls.append(True)
        return old(*args, **kwargs)

    monkeypatch.setattr(feature_preflight_cache, "preflight_owned_metadata_value", count)
    t, source = Translator([], {}, {}), feature()
    assert identity(t, source) == identity(t, deepcopy(source)) == "kept"
    assert len(calls) == 1
    source["extension"] = {"unknown": ["retained"]}
    assert identity(t, source) == "kept"
    source["geometry"]["coordinates"][0] = 3
    assert centroid(t, source)["geometry"]["coordinates"] == [3, 2]
    assert len(calls) == 3


def test_centroid_cache_hits_keep_bidirectional_property_and_geometry_ownership():
    t, source = Translator([], {}, {}), feature()
    first, second = centroid(t, source), centroid(t, source)
    first["properties"]["nested"]["values"].append(99)
    first["geometry"]["coordinates"][0] = 77
    first["geometry"].geometry_metadata["crs"] = "changed"
    source["properties"]["nested"]["values"].append(5)
    assert second["properties"]["nested"]["values"] == [1]
    assert second["geometry"]["coordinates"] == [1, 2]
    third = centroid(t, source)
    assert third["properties"]["nested"]["values"] == [1, 5]
    assert third["geometry"].geometry_metadata["crs"] == "EPSG:4326"


@pytest.mark.parametrize("bad", ["key", "string", "geometry_inf", "unknown_nan", "entries", "cycle"])
def test_warm_feature_preflight_retains_all_historical_metadata_rejections(bad):
    t, source = Translator([], {}, {}), feature()
    assert identity(t, source) == "kept"
    if bad == "key":
        source["properties"]["k" * 50_001] = 1
    elif bad == "string":
        source["properties"]["value"] = "v" * 1_000_001
    elif bad == "geometry_inf":
        source["geometry"]["coordinates"][0] = float("inf")
    elif bad == "unknown_nan":
        source["extension"] = float("nan")
    elif bad == "entries":
        source["properties"]["nested"] = [0] * 10_001
    else:
        source["properties"]["cycle"] = source["properties"]
    with pytest.raises(UnsupportedEEError):
        identity(t, source)


def test_feature_sidecar_proof_is_metadata_only_and_retains_original_id_domain():
    t, source = Translator([], {}, {}), feature()
    source["geometry"] = GeometryValue(source["geometry"], {"unknown": "metadata"})
    assert identity(t, source) == identity(t, source) == "kept"
    with pytest.raises(UnsupportedEEError, match="metadata"):
        centroid(t, source)
    source["geometry"].geometry_metadata["unknown"] = float("inf")
    with pytest.raises(UnsupportedEEError, match="finite"):
        identity(t, source)


def test_typed_array_metadata_keeps_original_preflight_and_fresh_copies(monkeypatch):
    from gee.compat.earthengine import feature_preflight_cache

    old = feature_preflight_cache.preflight_owned_metadata_value
    calls = []

    def count(*args, **kwargs):
        calls.append(True)
        return old(*args, **kwargs)

    monkeypatch.setattr(feature_preflight_cache, "preflight_owned_metadata_value", count)
    t, source = Translator([], {}, {}), feature()
    source["properties"]["array"] = StaticArray(np.array([1.0, 2.0]))
    first, second = centroid(t, source), centroid(t, source)
    assert len(calls) == 2
    assert t._feature_preflight_cache.entries == 0
    assert first["properties"]["array"] is not second["properties"]["array"]
    assert not np.shares_memory(first["properties"]["array"].data,
                                source["properties"]["array"].data)


def test_duplicate_id_candidate_bucket_is_bounded_and_never_decides_equality():
    from gee.compat.earthengine.feature_preflight_cache import MAX_BUCKET_ENTRIES

    t = Translator([], {}, {})
    for value in range(1, 8):
        result = centroid(t, feature(value))
        assert result["geometry"]["coordinates"] == [value, 2]
        assert result["properties"]["nested"]["values"] == [value]
    assert max(map(len, t._feature_preflight_cache.buckets.values())) == MAX_BUCKET_ENTRIES


def test_geometry_hash_collisions_still_compare_complete_snapshots(monkeypatch):
    from gee.compat.earthengine import geometry_measure_cache

    monkeypatch.setattr(geometry_measure_cache, "hash", lambda _value: 17, raising=False)
    t = Translator([], {}, {})
    for value in (1, 9, 1):
        result = invoke_geometry_measures(t, "Geometry.centroid", {
            "geometry": {"type": "Point", "coordinates": [value, 2]},
        })
        assert result["coordinates"] == [value, 2]
    assert t._geometry_measure_cache.entries == 2


def test_geometry_and_feature_caches_share_finite_total_entry_and_size_caps():
    t = Translator([], {}, {})
    for value in range(40):
        source = feature(value, f"row-{value}")
        assert identity(t, source) == f"row-{value}"
        assert centroid(t, source)["geometry"]["coordinates"] == [value, 2]
    caches = (t._feature_preflight_cache, t._geometry_measure_cache)
    assert all(cache.entries > 0 for cache in caches)
    assert sum(cache.entries for cache in caches) == 64
    assert sum(cache.retained_bytes for cache in caches) <= 1_000_000
    assert t.steps <= 50_000
