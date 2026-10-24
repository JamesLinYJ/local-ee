"""Bounded ordered band merging, explicit constant binding and name suffixes."""
from __future__ import annotations

from dataclasses import replace

from .array_core import charge_array
from .constant_bands import bind_source_bands
from .ir import Pixel, as_image, fail


MAX_BANDS = 10_000


def _scan(translator, image):
    if type(image.bands) is not list or len(image.bands) > MAX_BANDS:
        fail("Image.addBands supports at most10000 bands per input")
    charge_array(translator, 2 * len(image.bands) + 1)
    names = set()
    for entry in image.bands:
        if (type(entry) is not tuple or len(entry) != 2
                or type(entry[0]) is not str or not isinstance(entry[1], Pixel)):
            fail("Image.addBands requires named scalar Pixel bands")
        name = entry[0]
        charge_array(translator, 2 * len(name) + 2)
        if name in names:
            fail("Image.addBands input band names must be unique")
        names.add(name)


def _owned_result(translator, image, bands):
    if type(image.props) is not dict:
        fail("Image.addBands requires Image properties")
    from .owned_metadata_values import owned_metadata_copy

    props = owned_metadata_copy(translator, image.props, "Image.addBands properties")
    if image.footprint is None:
        footprint = None
    else:
        # Preserve the source edge model while accepting tuple coordinates
        # emitted by Shapely. Raw catalog mappings use the existing local
        # planar policy; typed GeometryValue sidecars remain authoritative.
        from .spatial_filters import _own_catalog_geometry

        footprint = _own_catalog_geometry(translator, image.footprint)
    return replace(image, bands=bands, props=props, footprint=footprint)


def _source_footprint(translator, image):
    """Build a bounded planar footprint without retaining any source Pixels."""
    from .geometry_binary import invoke_geometry_binary
    from .geometry_consumers import reject_spherical_edges
    from .geometry_preflight import _charge, measure_geometry
    from .spatial_filters import _own_catalog_geometry

    source = image.source
    if source is None:
        return None
    if (type(source.cid) is not str or not source.cid
            or type(source.ids) is not tuple or not source.ids
            or len(source.ids) > 1000):
        fail("Image.addBands cannot derive a finite first footprint from an empty source")

    source_work = 1 + len(source.cid) + len(source.ids)
    for item_id in source.ids:
        if type(item_id) is not str or not item_id:
            fail("Image.addBands first source requires nonempty string image IDs")
        source_work += len(item_id)
    _charge(translator, source_work, "Image.addBands first-footprint source scan")
    wanted = set(source.ids)
    if len(wanted) != len(source.ids):
        fail("Image.addBands first source has duplicate image IDs")
    rows = translator.items.get(source.cid)
    if type(rows) is not list:
        fail("Image.addBands requires catalog footprints for the first image")
    _charge(
        translator, len(rows) + len(wanted) + 1,
        "Image.addBands first-footprint item lookup",
    )
    row_id_work = 0
    for row in rows:
        if type(row) is dict:
            item_id = row.get("id")
            if type(item_id) is str:
                row_id_work += len(item_id)
    _charge(translator, row_id_work, "Image.addBands first-footprint item IDs")
    by_id = {}
    for row in rows:
        if type(row) is not dict:
            continue
        iid = row.get("id")
        if type(iid) is str and iid in wanted:
            if iid in by_id:
                fail("Image.addBands first source has duplicate catalog item ids")
            by_id[iid] = row
    if len(by_id) != len(wanted):
        fail("Image.addBands cannot resolve every first-source footprint")

    footprint = None
    for iid in source.ids:
        raw = by_id[iid].get("geometry")
        if not isinstance(raw, dict):
            fail("Image.addBands requires a declared first-source footprint")
        geometry = _own_catalog_geometry(translator, raw)
        reject_spherical_edges(translator, geometry, "Image.addBands first footprint")
        cost = measure_geometry(geometry)
        _charge(
            translator, cost.nodes + cost.positions,
            "Image.addBands first-footprint geometry scan",
        )
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            fail("Image.addBands first footprint must be planar Polygon or MultiPolygon")
        if footprint is None:
            footprint = geometry
        else:
            footprint = invoke_geometry_binary(translator, "Geometry.union", {
                "left": footprint, "right": geometry, "proj": "EPSG:4326",
            })
            if footprint.get("type") not in {"Polygon", "MultiPolygon"}:
                fail("Image.addBands first footprint union must be Polygon or MultiPolygon")
    return footprint


def _first_footprint(translator, image):
    """Return the first Image's effective planar footprint for empty merges."""
    from .geometry_binary import invoke_geometry_binary
    from .geometry_preflight import _charge, measure_geometry
    from .geometry_topology import geometry_edge_models
    from .spatial_filters import _own_catalog_geometry

    if image.footprint_is_absolute and image.footprint is None:
        fail("Image.addBands absolute first footprint has no geometry")
    if image.footprint is not None:
        if not isinstance(image.footprint, dict):
            fail("Image.addBands first footprint must be a GeoJSON geometry")
        footprint = _own_catalog_geometry(translator, image.footprint)
        cost = measure_geometry(footprint)
        _charge(
            translator, cost.nodes + cost.positions,
            "Image.addBands first-footprint geometry scan",
        )
        if any(model is True for model in geometry_edge_models(footprint)):
            fail("Image.addBands first footprint spherical geometry edges require a spherical raster/reprojection adapter")
        if footprint.get("type") not in {"Polygon", "MultiPolygon"}:
            fail("Image.addBands first footprint must be Polygon or MultiPolygon")
        if image.source is not None and not image.footprint_is_absolute:
            base = _source_footprint(translator, image)
            if base is None:
                fail("Image.addBands cannot resolve the first image source footprint")
            footprint = invoke_geometry_binary(translator, "Geometry.intersection", {
                "left": base, "right": footprint, "proj": "EPSG:4326",
            })
        return footprint
    return _source_footprint(translator, image)


def _clip_to_first_footprint(translator, bands, footprint, science_raster):
    if footprint is None:
        return bands
    from .spatial_filters import _own_catalog_geometry

    output = []
    for (name, pixel), has_science_raster in zip(bands, science_raster):
        mask = _own_catalog_geometry(translator, footprint) if has_science_raster else None
        output.append((name, Pixel("clip", (pixel, mask)) if mask is not None else pixel))
    return output


def _science_raster_bands(translator, bands):
    """Preflight the science-value lineage, excluding weight-only raster paths."""
    from .constant_mask_lineage import scan_mask_lineage

    result = []
    for _, pixel in bands:
        result.append(scan_mask_lineage(pixel, translator).science_raster)
    return result


def add_bands(translator, arguments):
    translator.allowed(arguments, {"dstImg", "srcImg", "names", "overwrite"})
    if not {"dstImg", "srcImg"} <= arguments.keys():
        fail("Image.addBands requires dstImg and srcImg")
    overwrite = arguments.get("overwrite")
    if overwrite is None:
        overwrite = False
    elif type(overwrite) is not bool:
        fail("Image.addBands overwrite must be a boolean or null")
    image, source = as_image(arguments["dstImg"]), as_image(arguments["srcImg"])
    _scan(translator, image)
    _scan(translator, source)
    names = arguments.get("names")
    if type(names) is list and not names:
        source = replace(source, bands=[])
    elif names is not None:
        source = translator.select(source, names)
    if not source.bands:
        # A selector yielding no bands cannot contribute a hidden grid/source.
        charge_array(translator, len(image.bands) + 1)
        return _owned_result(translator, image, list(image.bands))
    if not overwrite and len(image.bands) + len(source.bands) > MAX_BANDS:
        fail("Image.addBands exceeds10000 output bands")
    if not image.bands:
        science_raster = _science_raster_bands(translator, source.bands)
    else:
        science_raster = []
    if not image.bands and any(science_raster):
        # A zero-band destination contributes no science Pixel to the result.
        # Preserve its first-image envelope and explicitly apply its effective
        # footprint to actual added raster bands. When the accumulator is
        # source-free, the added raster supplies the only usable finite grid.
        first_footprint = _first_footprint(translator, image)
        source = replace(
            source,
            bands=_clip_to_first_footprint(
                translator, source.bands, first_footprint, science_raster,
            ),
        )
        if image.source is None:
            donor_footprint = first_footprint
            if donor_footprint is None:
                donor_footprint = _first_footprint(translator, source)
            image = replace(
                image,
                source=source.source,
                footprint=donor_footprint,
                footprint_is_absolute=(image.footprint_is_absolute
                                       if first_footprint is not None
                                       else source.footprint_is_absolute),
            )
        elif first_footprint is not None:
            image = replace(image, footprint=first_footprint)
    if image.source is None and source.source is not None:
        charge_array(translator, 2 * len(image.bands) + len(source.bands) + 8)
        image = replace(
            image, bands=bind_source_bands(image, source, translator=translator),
            source=source.source, footprint=source.footprint,
            footprint_is_absolute=source.footprint_is_absolute,
        )
    bound = bind_source_bands(source, image, translator=translator)
    charge_array(translator, 2 * len(image.bands) + len(bound) + 2)
    output = list(image.bands)
    positions = {name: index for index, (name, _) in enumerate(output)}
    suffixes = {}
    for base, pixel in bound:
        charge_array(translator, len(base) + 4)
        if overwrite and base in positions:
            output[positions[base]] = (base, pixel)
            continue
        name = base
        if name in positions:
            suffix = suffixes.get(base, 1)
            while True:
                digits = 1 if suffix < 10 else 2 if suffix < 100 else 3 if suffix < 1000 else 5
                charge_array(translator, 2 * (len(base) + digits + 1))
                name = f"{base}_{suffix}"
                suffix += 1
                if name not in positions:
                    break
            suffixes[base] = suffix
        if len(output) >= MAX_BANDS:
            fail("Image.addBands exceeds10000 output bands")
        charge_array(translator, len(name) + 3)
        positions[name] = len(output)
        output.append((name, pixel))
    return _owned_result(translator, replace(image, source=image.source or source.source), output)
