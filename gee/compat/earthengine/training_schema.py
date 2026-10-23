"""Resolve omitted classifier schemas only from declared FeatureCollection metadata."""
from __future__ import annotations

from ...image_sampling_spec import sample_collection_properties
from .array_core import charge_array
from .ir import SampledFeatures, fail


MAX_INPUT_PROPERTIES = 8
MAX_PROPERTY_NAME_LENGTH = 256
_RESERVED_PROPERTIES = frozenset({"system:index", ".geo"})


def _copy_declared_band_order(translator, value):
    if type(value) is not list:
        fail("Automatic inputProperties requires a declared band_order list")
    if not 1 <= len(value) <= MAX_INPUT_PROPERTIES:
        fail(
            "Automatic inputProperties requires 1..8 declared band_order names"
        )

    # Charge the bounded reference scan before examining any item. The list is
    # at most eight entries, and each accepted name is at most 256 codepoints.
    charge_array(translator, len(value))
    names = []
    total_length = 0
    for name in value:
        if type(name) is not str or not name:
            fail("Automatic band_order names must be nonempty UTF-8 strings")
        length = len(name)
        if length > MAX_PROPERTY_NAME_LENGTH:
            fail("Automatic band_order names must be at most 256 codepoints")
        charge_array(translator, length)
        for character in name:
            codepoint = ord(character)
            if character == "\0" or character == ".":
                fail("Automatic band_order names must be flat and contain no NUL")
            if 0xD800 <= codepoint <= 0xDFFF:
                fail("Automatic band_order names must be valid UTF-8")
        if name in _RESERVED_PROPERTIES:
            fail(f"Automatic band_order cannot contain reserved property {name!r}")

        # Equality may inspect every codepoint in each preceding name.
        charge_array(translator, sum(map(len, names)))
        if name in names:
            fail("Automatic band_order names must be unique")
        names.append(name)
        total_length += length

    # Return an owned list, never the metadata's mutable list. Charge its
    # bounded reference/string copy before allocating it.
    charge_array(translator, len(value) + total_length)
    return list(value)


def resolve_input_properties(translator, features, explicit):
    """Return explicit inputProperties unchanged or a declared automatic schema."""
    if explicit is not None:
        return explicit

    if isinstance(features, SampledFeatures):
        from .sampled_feature_ops import validated_sampled_schema

        try:
            origin, _columns, _operations = validated_sampled_schema(
                features, translator, "Classifier.train sample table",
            )
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"Classifier.train requires a valid server-side sample table: {exc}")

        # Charge the collection-level metadata dict and band-list copy before
        # sample_collection_properties allocates either one.
        bands = origin.get("bands")
        if type(bands) is not list:
            fail("Classifier.train sample origin has malformed band metadata")
        charge_array(translator, 1 + len(bands))
        metadata = sample_collection_properties(origin)
        band_order = metadata.get("band_order")
        if band_order is None:
            fail(
                "SampleRegions v1 has no declared band_order; Classifier.train "
                "requires inputProperties unless the collection has v2 metadata"
            )
        return _copy_declared_band_order(translator, band_order)

    if type(features) is not dict or features.get("type") != "FeatureCollection":
        fail("Automatic inputProperties requires an actual FeatureCollection dictionary")
    metadata = features.get("properties", {})
    if type(metadata) is not dict:
        fail("Automatic FeatureCollection properties metadata must be a dictionary")
    band_order = metadata.get("band_order")
    if band_order is None:
        fail(
            "Classifier.train requires inputProperties or declared "
            "FeatureCollection properties.band_order metadata"
        )
    return _copy_declared_band_order(translator, band_order)
