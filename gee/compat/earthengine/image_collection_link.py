"""Finite Image.linkCollection and ImageCollection.combine support.

These operations use explicit bounded frames only. Band mixing requires fresh
source-grid, timestamp, and footprint proofs; metadata-only linking does not
invent a raster grid or alter the primary source identity.
"""
from __future__ import annotations

from dataclasses import replace

from .constant_bands import bind_source_bands, destination_template
from .image_collection_link_common import (
    COLLECTION_LINK_FUNCTIONS,
    _MAX_BANDS,
    arguments,
    band_names,
    charge,
    frames,
    index,
    match_value,
    names,
    property_key,
    property_updates,
    validate_properties,
)
from .image_collection_link_grid import (
    _pixel_cost,
    require_pair_alignment,
)
from .ir import Image, ImageSequence, Pixel, const, fail


def _add_linked_bands(translator, primary, secondary, selected, label, *, overwrite):
    if not selected:
        return primary
    band_names(translator, primary, label + " primary")
    band_names(translator, secondary, label + " linked")
    charge(translator, 1 + len(secondary.bands), label + " linked band index")
    secondary_bands = dict(secondary.bands)
    charge(translator, 1 + len(selected), label + " selected band copy")
    linked = []
    for name in selected:
        if name not in secondary_bands:
            fail(f"{label} requested band is missing from a matching image: {name}")
        linked.append((name, secondary_bands[name]))
    if not primary.source or not primary.source.ids:
        fail(f"{label} requires a finite primary raster grid")
    if destination_template(primary) is None:
        fail(f"{label} requires an actual primary raster band to supply its grid")

    charge(translator, 1 + len(primary.bands), label + " primary band binding")
    charge(translator, 1 + len(linked), label + " linked band binding")
    primary_bands = bind_source_bands(primary, primary)
    linked_image = replace(secondary, bands=linked)
    linked_bands = bind_source_bands(linked_image, primary)
    if overwrite:
        charge(translator, 1 + len(primary_bands), label + " overwrite band index")
        primary_names = {name for name, _ in primary_bands}
        additions = 0
        for selected_name in selected:
            charge(translator, 1 + len(selected_name), label + " overwrite band scan")
            if selected_name not in primary_names:
                additions += 1
        output_count = len(primary_bands) + additions
    else:
        output_count = len(primary_bands) + len(linked_bands)
    if output_count > _MAX_BANDS:
        fail(f"{label} output exceeds 10000 bands")
    charge(
        translator, 1 + len(primary_bands) + len(linked_bands),
        label + " band pair materialization",
    )
    paired_pixels = ([pixel for _, pixel in primary_bands]
                     + [pixel for _, pixel in linked_bands])
    _pixel_cost(translator, paired_pixels, label)
    require_pair_alignment(
        translator,
        primary,
        secondary,
        paired_pixels,
        label,
    )

    charge(translator, 1 + len(primary_bands), label + " output copy")
    output = list(primary_bands)
    charge(translator, 1 + len(output), label + " output band index")
    positions = {name: index for index, (name, _) in enumerate(output)}
    for name, pixel in linked_bands:
        if name in positions and overwrite:
            output[positions[name]] = (name, pixel)
        else:
            base, suffix = name, 1
            while name in positions:
                charge(translator, 1 + len(name), label + " collision suffix")
                suffix_text = str(suffix)
                charge(translator, len(base) + 1 + len(suffix_text), label + " collision name")
                name = f"{base}_{suffix_text}"
                suffix += 1
            charge(translator, 1, label + " output band index")
            positions[name] = len(output)
            output.append((name, pixel))
    if len(output) > _MAX_BANDS:
        fail(f"{label} output exceeds 10000 bands")
    return replace(primary, bands=output)


def _link_image(translator, values):
    name = "Image.linkCollection"
    arguments(
        translator, name, values,
        {"input", "imageCollection"},
        {"linkedBands", "linkedProperties", "matchPropertyName"},
    )
    primary = values["input"]
    if not isinstance(primary, Image) or type(primary.props) is not dict:
        fail("Image.linkCollection input must be a concrete Image")
    validate_properties(translator, primary, name + " input")
    candidates = frames(translator, values["imageCollection"], name)
    linked_bands = names(translator, values.get("linkedBands"), name + " linkedBands")
    linked_properties = tuple(
        property_key(translator, key, name + " linkedProperties")
        for key in names(
            translator, values.get("linkedProperties"), name + " linkedProperties",
        )
    )
    match_name = property_key(
        translator, values.get("matchPropertyName", "system:index"),
        name + " matchPropertyName",
    )
    if not linked_bands and not linked_properties:
        return primary

    candidates_by_key = index(
        translator, candidates, match_name, name + " imageCollection",
        system_index=match_name == "system:index",
    )
    primary_key = match_value(
        translator, primary, match_name, name + " input",
        system_index=match_name == "system:index",
    )
    match = candidates_by_key.get(primary_key) if primary_key is not None else None

    result = primary
    if linked_bands:
        if match is None:
            template = destination_template(primary)
            if template is None:
                fail(f"{name} unmatched bands require a finite primary raster grid")
            # The false branch selects no pixels. Including a real primary
            # template binds the all-NoData output to the exact primary grid.
            charge(translator, len(linked_bands), name + " masked band construction")
            masked_bands = [
                (band, Pixel("if", (const(False), template, const(None))))
                for band in linked_bands
            ]
            masked = Image(masked_bands, {})
            result = _add_linked_bands(
                translator, primary, masked, linked_bands, name, overwrite=True,
            )
        else:
            result = _add_linked_bands(
                translator, primary, match, linked_bands, name, overwrite=True,
            )
    if linked_properties:
        result = replace(
            result,
            props=property_updates(
                translator, primary, match, linked_properties, name,
            ),
        )
    return result


def _combine(translator, values):
    name = "ImageCollection.combine"
    arguments(translator, name, values, {"primary", "secondary"}, {"overwrite"})
    overwrite = values.get("overwrite", False)
    if type(overwrite) is not bool:
        fail("ImageCollection.combine overwrite must be a boolean")
    primary = frames(translator, values["primary"], name + " primary")
    secondary = frames(translator, values["secondary"], name + " secondary")
    secondary_by_id = index(
        translator, secondary, "system:index", name + " secondary",
        system_index=True,
    )
    # Index the primary too: duplicate system:index values make EE's inner
    # match ambiguous in this finite adapter, even if only one pair survives.
    primary_by_id = index(
        translator, primary, "system:index", name + " primary",
        system_index=True,
    )
    del primary_by_id

    output = []
    charge(translator, 1 + len(primary), name + " output scan")
    for image in primary:
        key = match_value(
            translator, image, "system:index", name + " primary",
            system_index=True,
        )
        match = secondary_by_id.get(key) if key is not None else None
        if match is None:
            continue
        charge(translator, 1, name + " pair materialization")
        output.append(_add_linked_bands(
            translator, image, match,
            band_names(translator, match, name + " matching secondary"),
            name, overwrite=overwrite,
        ))
    return ImageSequence(output)


def invoke_collection_link(translator, name, values):
    """Handle the pinned Image.linkCollection and ImageCollection.combine APIs."""
    if name == "Image.linkCollection":
        return _link_image(translator, values)
    if name == "ImageCollection.combine":
        return _combine(translator, values)
    fail(f"Unsupported Earth Engine algorithm: {name}")
