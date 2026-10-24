"""Compile the bounded default-geodesic Image.clip subset."""
from __future__ import annotations

import hashlib
from dataclasses import replace

from .ir import ClipFootprintIdentity, Image, Pixel, fail


MAX_CLIP_WORK = 50_000
MAX_CLIP_BANDS = 10_000
_FRACTIONAL_OPS = frozenset({"clip_coverage", "with_mask"})


def _charge(translator, amount, label):
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or amount < 0 or amount > MAX_CLIP_WORK
            or steps + amount > MAX_CLIP_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _scan_existing_clip_state(translator, image):
    """Find existing masks/clips before geometry or band copies."""
    if type(image.bands) is not list or len(image.bands) > MAX_CLIP_BANDS:
        fail("Image.clip requires at most10000 named bands")
    work = 2 + 3 * len(image.bands)
    for name, pixel in image.bands:
        if type(name) is not str or not isinstance(pixel, Pixel):
            fail("Image.clip requires named scalar Pixel bands")
        work += len(name)
    _charge(translator, work, "Image.clip input band scan")

    seen, active, operations = {}, set(), set()

    def visit(value, depth):
        if not isinstance(value, (Pixel, tuple, list)):
            return 0
        if depth > 96:
            fail("Image.clip input Pixel graph exceeds depth96")
        identity = id(value)
        if identity in active:
            fail("Image.clip input Pixel graph contains a cycle")
        height = seen.get(identity)
        if height is not None:
            _charge(translator, 1, "Image.clip input Pixel revisit")
            if depth + height - 1 > 96:
                fail("Image.clip input Pixel graph exceeds depth96")
            return height
        if isinstance(value, Pixel):
            if type(value.op) is not str or type(value.args) is not tuple:
                fail("Image.clip input contains a malformed Pixel node")
            _charge(translator, 1 + len(value.op) + len(value.args),
                    "Image.clip input Pixel scan")
            if value.op in {"clip", *_FRACTIONAL_OPS}:
                operations.add(value.op)
            children = value.args
        else:
            _charge(translator, 1 + len(value), "Image.clip input container scan")
            children = value
        active.add(identity)
        child_height = max(
            (visit(child, depth + 1) for child in children), default=0,
        )
        active.remove(identity)
        height = 1 + child_height
        if depth + height - 1 > 96:
            fail("Image.clip input Pixel graph exceeds depth96")
        seen[identity] = height
        return height

    for _name, pixel in image.bands:
        visit(pixel, 1)
    return operations


def _polygon_counts(geometry):
    if geometry["type"] == "Polygon":
        polygons = [geometry["coordinates"]]
    else:
        polygons = geometry["coordinates"]
    polygon_count = len(polygons)
    ring_count = sum(len(polygon) for polygon in polygons)
    position_count = sum(len(ring) for polygon in polygons for ring in polygon)
    extra_closures = sum(
        bool(ring) and ring[-1] != ring[0]
        for polygon in polygons for ring in polygon
    )
    return polygon_count, ring_count, position_count, position_count + extra_closures


def _clip_coverage_spec(translator, geometry):
    from ...clip_coverage_spec import (
        MAX_POLYGONS,
        MAX_POSITIONS,
        MAX_RINGS,
        MAX_SPEC_BYTES,
        prepare_clip_coverage_spec,
    )
    from .geometry_preflight import _charge as geometry_charge, measure_geometry
    from .spherical_preflight import native_work
    from . import spherical_native

    # The geometry has already had a fresh bounded decode/topology validation.
    # Measure and pay for this second, independent policy/copy walk as well.
    cost = measure_geometry(geometry)
    geometry_charge(
        translator, cost.nodes + cost.positions,
        "Image.clip polygon model and coordinate scan",
    )
    polygon_count, ring_count, position_count, canonical_positions = _polygon_counts(geometry)
    if not 1 <= polygon_count <= MAX_POLYGONS:
        fail("Image.clip supports 1..1000 polygons")
    if not 1 <= ring_count <= MAX_RINGS:
        fail("Image.clip supports 1..1000 total rings")
    if not 1 <= canonical_positions <= MAX_POSITIONS:
        fail("Image.clip exceeds 10000 closed coordinate positions")

    longitudes = []
    latitudes = []
    for polygon in geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]:
        for ring in polygon:
            for longitude, latitude in ring:
                longitudes.append(longitude)
                latitudes.append(latitude)
    if max(longitudes) - min(longitudes) >= 180:
        fail("Image.clip rejects global longitude spans of 180 degrees or more")
    if any(not -90 < latitude < 90 for latitude in latitudes):
        fail("Image.clip rejects polar or pole-touching geodesic polygons")

    # S2 bounds distinguish valid short arcs from wrapped/polar regions that a
    # coordinate envelope cannot identify. Charge its complete bounded native
    # model before the call; the numeric policy is still enforced by the ABI.
    from types import SimpleNamespace

    from .geometry_bounds import _ENVELOPE_RECORD_WORK
    from .geometry_preflight import MAX_GEOMETRY_WORK

    closed_positions = cost.positions + cost.ring_closures
    bounds_work = 1 + cost.nodes + 4 * closed_positions + native_work(geometry)
    geometry_charge(
        translator, bounds_work + _ENVELOPE_RECORD_WORK,
        "Image.clip S2 bounds and envelope validation",
    )
    envelope = spherical_native.run("bounds", geometry)
    from .geometry_bounds import _validate_envelope

    envelope_budget = SimpleNamespace(
        steps=MAX_GEOMETRY_WORK - _ENVELOPE_RECORD_WORK,
    )
    _validate_envelope(envelope_budget, envelope)
    if envelope_budget.steps != MAX_GEOMETRY_WORK:
        fail("Image.clip S2 envelope validation did not consume its prepaid work")
    if envelope.full_longitude:
        fail("Image.clip rejects full-longitude geodesic polygons")
    if envelope.south <= -90 or envelope.north >= 90:
        fail("Image.clip rejects polar or pole-touching geodesic polygons")

    # Reserve the worst-case Float64 JSON spellings, delimiters and per-ring
    # closure before allocating the canonical nested lists or JSON string.
    copy_bound = 96 + 64 * canonical_positions + 4 * ring_count + 4 * polygon_count
    if copy_bound > MAX_SPEC_BYTES:
        fail("Image.clip canonical geometry exceeds the 1000000-byte wire limit")
    geometry_charge(translator, copy_bound,
                    "Image.clip canonical specification copy")
    try:
        spec = prepare_clip_coverage_spec(geometry)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Image.clip geometry cannot be encoded for local coverage: {exc}")
    if len(spec.encode("utf-8")) > copy_bound:
        fail("Image.clip canonical geometry exceeded its reserved specification bound")
    return spec


def _planar_clip(translator, image, geometry):
    from shapely.geometry import mapping, shape

    from .geometry_preflight import precharge_geometry_copy
    from .geometry_public import public_geometry_mapping
    from .geometry_regions import _strip_inferred_even_odd
    from .geometry_consumers import reject_spherical_edges

    reject_spherical_edges(translator, geometry, "Image.clip", default_geodesic=True)
    precharge_geometry_copy(
        translator, geometry, "Image.clip public mapping",
        additional_geometry_walks=1,
    )
    geometry_mapping = public_geometry_mapping(geometry)
    _strip_inferred_even_odd(geometry_mapping, geometry)
    if image.footprint:
        from .geometry_regions import own_ee_region

        _, base = own_ee_region(
            translator, image.footprint, "Image.clip", strip_inferred_even_odd=True,
        )
        footprint = mapping(shape(base).intersection(shape(geometry_mapping)))
        from .geometry_topology import _has_edges

        if _has_edges(footprint):
            footprint["geodesic"] = False
    else:
        footprint = geometry_mapping
    _charge(translator, 2 + 3 * len(image.bands), "Image.clip planar Pixel output")
    bands = [(name, Pixel("clip", (pixel, geometry_mapping)))
             for name, pixel in image.bands]
    return replace(
        image, bands=bands, footprint=footprint,
        clip_footprint=None,
    )


def _normalize_empty_constructor_band(translator, image):
    """Keep the SDK's no-argument Image null placeholder out of mask IR.

    The official `ee.Image()` constructor lowers to one source-free, fully
    masked zero placeholder. Its exact finite mask-IR shape is equivalent to
    NoData and used by the historical planar empty-accumulator path. Collapse
    only that exact constructor value before an explicit planar clip; real
    or fractional masks remain forbidden in the old clip branch.
    """
    if (image.source is not None or type(image.bands) is not list
            or len(image.bands) != 1):
        return image
    zero = Pixel("constant", (0,))
    source_validity = Pixel("mask_validity", (zero,))
    set_value = Pixel("mask_set_value", (zero, source_validity))
    zero_weight = Pixel("mask_update", (
        Pixel("mask_validity", (set_value,)), zero,
    ))
    placeholder = Pixel("with_mask", (set_value, zero_weight))
    name, pixel = image.bands[0]
    if type(name) is not str or pixel != placeholder:
        return image
    _charge(translator, 4 + len(name), "Image.clip empty Image placeholder normalization")
    return replace(image, bands=[(name, Pixel("constant", (None,)))])


def invoke_image_clip(translator, arguments):
    """Lower explicit planar clips historically and the safe geodesic subset locally."""
    from .geometry_regions import _unwrap_feature_region
    from .geometry_values import _geometry_metadata, decode_geometry_bounded
    from .spherical_wire import FullSphere

    translator.allowed(arguments, {"input", "geometry"})
    if not {"input", "geometry"} <= arguments.keys():
        fail("Image.clip requires input and geometry")
    from .ir import as_image

    image = as_image(arguments["input"])
    if image.clip_footprint is not None:
        fail("Image.clip rejects repeated composition while the geodesic clip footprint is pending")
    existing_operations = _scan_existing_clip_state(translator, image)

    raw_geometry = _unwrap_feature_region(translator, arguments["geometry"], "Image.clip")
    if isinstance(raw_geometry, FullSphere):
        fail("Image.clip does not support full-sphere geometries")
    if not isinstance(raw_geometry, dict) or raw_geometry.get("type") not in {
            "Polygon", "MultiPolygon"}:
        fail("Image.clip supports Polygon/MultiPolygon only")
    geometry = decode_geometry_bounded(translator, raw_geometry)
    metadata = _geometry_metadata(geometry)
    if metadata.get("crs") != "EPSG:4326":
        fail("Image.clip supports EPSG:4326 only")
    if metadata.get("geodesic") is False:
        image = _normalize_empty_constructor_band(translator, image)
        existing_operations = _scan_existing_clip_state(translator, image)
        if existing_operations & _FRACTIONAL_OPS:
            fail("Explicit planar Image.clip rejects an existing fractional mask carrier")
        return _planar_clip(translator, image, geometry)
    if metadata.get("geodesic") is not True or metadata.get("evenOdd") is not True:
        fail("Image.clip supports only geodesic Polygon/MultiPolygon with evenOdd=true")
    if existing_operations:
        fail("Default geodesic Image.clip rejects repeated clips and existing fractional mask carriers")

    spec = _clip_coverage_spec(translator, geometry)
    # Allocate independent Float64 weights on each band's real input grid;
    # the scientific value and its source lineage stay as the raw first arg.
    _charge(translator, 4 + 4 * len(image.bands),
            "Image.clip weighted Pixel output")
    bands = [
        (name, Pixel("with_mask", (
            pixel, Pixel("clip_coverage", (pixel, spec)),
        )))
        for name, pixel in image.bands
    ]
    _charge(translator, len(spec), "Image.clip ROI identity fingerprint")
    identity = ClipFootprintIdentity(
        spec, hashlib.sha256(spec.encode("ascii")).digest(),
    )
    translator.warn(
        "Default geodesic Image.clip uses local projected-cell area fractions with a bounded "
        "great-circle approximation; Google boundary quantization and clipped-footprint "
        "parity are unverified. The source footprint remains conservative support metadata."
    )
    return replace(image, bands=bands, clip_footprint=identity)


__all__ = ["invoke_image_clip"]
