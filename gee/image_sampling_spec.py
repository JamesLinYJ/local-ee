"""Canonical Image.sample options and the local, grid-stable random reference.

The compiler records these options; only the raster engine selects pixels.
The seeded hash is a local reproducibility contract, not Google's sampler RNG.
"""
from __future__ import annotations

import math

from .sampling_spec import MAX_ROWS, SAMPLE_KEYS, _check_regions_spec, _parse, encode_spec


ALGORITHM = "splitmix64-grid-v1"
_OPTION_KEYS = {"algorithm", "factor", "num_pixels", "seed", "drop_nulls"}
_MASK64 = (1 << 64) - 1


def is_image_sample(spec):
    return type(spec) is dict and type(spec.get("version")) is int and spec["version"] == 2


def allows_null_samples(spec):
    return is_image_sample(spec) and spec["image_sample"]["drop_nulls"] is False


def sample_collection_properties(spec):
    return {"band_order": spec["bands"].copy()} if is_image_sample(spec) else {}


def _integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"Image.sample {label} must be an integer in {minimum}..{maximum}")
    return value


def _sdk_integer(value, minimum, maximum, label):
    # Official SDK serialization can represent integral parameters as floats.
    if type(value) is float and math.isfinite(value) and value.is_integer():
        value = int(value)
    return _integer(value, minimum, maximum, label)


def _options(options):
    if type(options) is not dict or set(options) != _OPTION_KEYS:
        raise ValueError("Unexpected Image.sample option fields")
    if type(options["algorithm"]) is not str or options["algorithm"] != ALGORITHM:
        raise ValueError("Unsupported Image.sample random algorithm")
    factor, count = options["factor"], options["num_pixels"]
    if factor is not None:
        try:
            valid = type(factor) in (int, float) and math.isfinite(factor) and 0 < factor <= 1
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("Image.sample factor must be finite in (0, 1]")
    if count is not None:
        _integer(count, 0, MAX_ROWS, "numPixels")
    if factor is not None and count is not None:
        raise ValueError("Image.sample factor and numPixels are mutually exclusive")
    _integer(options["seed"], -(2**31), 2**31 - 1, "seed")
    if type(options["drop_nulls"]) is not bool:
        raise ValueError("Image.sample dropNulls must be a boolean")


def validate_image_sample_spec(spec):
    if (not is_image_sample(spec) or set(spec) != SAMPLE_KEYS | {"image_sample"}):
        raise ValueError("Unsupported Image.sample specification fields or version")
    # Keep direct callers bounded too; this checks JSON size without decoding it again.
    encode_spec(spec)
    common = {key: spec[key] for key in SAMPLE_KEYS}
    common["version"] = 1
    _check_regions_spec(common)
    features = spec["regions"]["features"]
    if (len(features) != 1 or spec["properties"] != []
            or set(features[0]) != {"type", "geometry", "properties"}
            or features[0]["properties"] != {}):
        raise ValueError("Image.sample requires exactly one region and no copied properties")
    _options(spec["image_sample"])
    return spec


def decode_image_sample_spec(text):
    return validate_image_sample_spec(_parse(text))


def prepare_image_sample_spec(region, bands, *, grid=None, factor=None,
                              num_pixels=None, seed=0, drop_nulls=True, geometries=False):
    options = {
        "algorithm": ALGORITHM, "factor": factor,
        "num_pixels": None if num_pixels is None else _sdk_integer(num_pixels, 0, MAX_ROWS, "numPixels"),
        "seed": _sdk_integer(seed, -(2**31), 2**31 - 1, "seed"),
        "drop_nulls": drop_nulls,
    }
    spec = {
        "version": 2,
        "regions": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": region, "properties": {}}
        ]},
        "bands": bands.copy() if type(bands) is list else bands,
        "properties": [], "geometries": geometries,
        "grid": {"scale": None, "crs": None} if grid is None else grid,
        "image_sample": options,
    }
    validate_image_sample_spec(spec)
    return encode_spec(spec)


def _mix(value):
    value &= _MASK64
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK64
    return value ^ (value >> 31)


def grid_random(seed, col, row):
    """Independent Python reference over global cell indices; never generates rows."""
    _integer(seed, -(2**31), 2**31 - 1, "seed")
    _integer(col, 0, 2**53, "grid column")
    _integer(row, 0, 2**53, "grid row")
    value = _mix((seed & _MASK64) ^ _mix(col + 0x9E3779B97F4A7C15)
                 ^ _mix(row + 0xD1B54A32D192ED03))
    return (value >> 11) * (2.0 ** -53)
