"""Finite collection-linking contracts; method names do not imply completeness."""

COLLECTION_LINK_LIMITS = {
    "Image.linkCollection": [
        "Concrete finite local Images and at most1000 secondary frames. The pinned "
        "Python ImageCollection.linkCollection helper lowers through per-item map. "
        "A flat finite scalar match property defaults to system:index; duplicate "
        "secondary keys reject instead of arbitrary selection. Selected named bands "
        "and properties overwrite; unmatched bands are fully masked and properties "
        "null. Unselected primary metadata, actual source identity and footprint "
        "remain. Single-name strings or literal lists accepted; null/[] select "
        "nothing by local policy, without a Google equivalence claim. Real source "
        "grid/asset, time and footprint evidence is required for raster mixing; "
        "unsupported cross-lineage alignment rejects. Shared50000-work/500-node/1MB "
        "limits remain. Explicitly ingested QA data only; no automatic Google "
        "cloud-probability loading. Synthetic sample graphs are separate from "
        "native Spark, physical export, deployed and Google same-data acceptance."
    ],
    "ImageCollection.combine": [
        "Bounded inner join of concrete local collections by actual system:index, "
        "at most1000 frames per input, primary order/identity retained. Duplicate "
        "keys reject; no matches return an empty collection. Adds secondary bands "
        "with existing collision suffix rules, or replaces bands in place when "
        "overwrite=true. Fresh grid/asset, temporal and compatible-footprint proof "
        "before raster mixing; no implicit resampling or time broadcast. Shared "
        "compiler, graph and public materialization limits unchanged. This local "
        "finite slice is not full metadata, arbitrary duplicate or Google parity."
    ],
}
