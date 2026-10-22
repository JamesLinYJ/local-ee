"""Exact bounded wire representation for raster minimum-distance models."""
from __future__ import annotations

from fractions import Fraction
import math
import re
import sys

from .ir import fail
from .minimum_distance import require_trained


VERSION = 1
MAX_SCHEMA_BANDS = 8
MAX_CLASSES = 64
MAX_LABEL = 63
MAX_FRACTION_CHARS = 700
MAX_FRACTION_BITS = 2200
MAX_CENTER_MAGNITUDE = Fraction.from_float(sys.float_info.max)

_WIRE_KEYS = frozenset({"version", "metric", "schema", "labels", "centers"})
_METRICS = frozenset({"euclidean", "manhattan", "cosine"})
_INTEGER = re.compile(r"(?:0|-?[1-9][0-9]*)\Z")
_POSITIVE = re.compile(r"[1-9][0-9]*\Z")


def _shape(classifier):
    classifier = require_trained(classifier)
    schema, labels, centers = classifier.schema, classifier.labels, classifier.centers
    if (not isinstance(schema, tuple) or not 1 <= len(schema) <= MAX_SCHEMA_BANDS
            or any(type(name) is not str or not name or "." in name for name in schema)
            or len(set(schema)) != len(schema)):
        fail("Raster classifier schema must contain 1..8 unique flat band names")
    if (not isinstance(labels, tuple) or not 1 <= len(labels) <= MAX_CLASSES
            or any(type(label) is not int or not 0 <= label <= MAX_LABEL for label in labels)
            or tuple(sorted(set(labels))) != labels):
        fail("Raster classifier labels must be sorted unique integers from 0 through 63")
    if not isinstance(centers, tuple) or len(centers) != len(labels):
        fail("Raster classifier centers must match its class labels")
    for center in centers:
        if not isinstance(center, tuple) or len(center) != len(schema):
            fail("Raster classifier center dimensions must match its schema")
        for value in center:
            _fraction_parts(value)
        if classifier.metric == "cosine" and not any(center):
            fail("Raster cosine classification rejects a zero-norm class center")
    return classifier, schema, labels, centers


def _fraction_parts(value):
    if type(value) is not Fraction:
        fail("Raster classifier centers must contain exact rational values")
    numerator, denominator = value.numerator, value.denominator
    if (abs(numerator).bit_length() > MAX_FRACTION_BITS
            or denominator.bit_length() > MAX_FRACTION_BITS
            or abs(value) > MAX_CENTER_MAGNITUDE):
        fail("Raster classifier center exceeds the exact finite Float64 wire limits")
    return numerator, denominator


def _decimal_bound(value, signed=False):
    """Upper bound the ASCII decimal width without formatting the integer."""
    bits = abs(value).bit_length()
    if not bits:
        return 1
    digits = (bits * 30103) // 100000 + 1
    return digits + int(signed and value < 0)


def model_serialization_work(classifier):
    """Return a conservative precharge for the bounded classifier wire copy."""
    _, schema, labels, centers = _shape(classifier)
    work = 8 + sum(2 + len(name) for name in schema) + len(labels)
    for center in centers:
        work += 2 + len(center)
        for value in center:
            numerator, denominator = _fraction_parts(value)
            work += 2 + _decimal_bound(numerator, signed=True)
            work += _decimal_bound(denominator)
    return work


def encode_model(classifier) -> dict:
    """Encode a trained StaticMinimumDistance without numeric quantization.

    The caller must precharge ``model_serialization_work`` before invoking
    this bounded copy and decimal formatting operation.
    """
    classifier, schema, labels, centers = _shape(classifier)
    return {
        "version": VERSION,
        "metric": classifier.metric,
        "schema": list(schema),
        "labels": list(labels),
        "centers": [
            [[str(numerator), str(denominator)]
             for numerator, denominator in map(_fraction_parts, center)]
            for center in centers
        ],
    }


def model_validation_work(model):
    """Return a conservative precharge for validating an untrusted wire model."""
    if type(model) is not dict or set(model) != _WIRE_KEYS:
        fail("Raster classifier model must contain exactly the version, metric, schema, labels and centers fields")
    schema, labels, centers = model.get("schema"), model.get("labels"), model.get("centers")
    if type(schema) is not list or type(labels) is not list or type(centers) is not list:
        fail("Raster classifier model schema, labels and centers must be lists")
    work = 8 + len(schema) + len(labels) + len(centers)
    for name in schema:
        if type(name) is str:
            work += len(name)
    for row in centers:
        if type(row) is list:
            work += len(row)
            for pair in row:
                if type(pair) is list:
                    work += len(pair)
                    for component in pair:
                        if type(component) is str:
                            work += len(component)
    return work


def _parse_fraction(value):
    if type(value) is not list or len(value) != 2:
        fail("Raster classifier center values must be numerator/denominator string pairs")
    numerator_text, denominator_text = value
    if (type(numerator_text) is not str or type(denominator_text) is not str
            or len(numerator_text) > MAX_FRACTION_CHARS
            or len(denominator_text) > MAX_FRACTION_CHARS
            or not _INTEGER.fullmatch(numerator_text)
            or not _POSITIVE.fullmatch(denominator_text)):
        fail("Raster classifier center fractions must use canonical bounded decimal strings")
    numerator, denominator = int(numerator_text), int(denominator_text)
    if (abs(numerator).bit_length() > MAX_FRACTION_BITS
            or denominator.bit_length() > MAX_FRACTION_BITS):
        fail("Raster classifier center fraction exceeds the 2200-bit limit")
    if math.gcd(abs(numerator), denominator) != 1:
        fail("Raster classifier center fractions must be reduced")
    value = Fraction(numerator, denominator)
    if abs(value) > MAX_CENTER_MAGNITUDE:
        fail("Raster classifier center exceeds the exact finite Float64 range")
    return value


def validate_model(model) -> dict:
    """Strictly validate and return the original version-1 wire dictionary.

    Callers must precharge ``model_validation_work`` before validation.
    """
    if type(model) is not dict or set(model) != _WIRE_KEYS:
        fail("Raster classifier model must contain exactly the version, metric, schema, labels and centers fields")
    if type(model["version"]) is not int or model["version"] != VERSION:
        fail("Unsupported raster classifier model version")
    if type(model["metric"]) is not str or model["metric"] not in _METRICS:
        fail("Raster classifier metric must be euclidean, manhattan or cosine")

    schema, labels, centers = model["schema"], model["labels"], model["centers"]
    if (type(schema) is not list or not 1 <= len(schema) <= MAX_SCHEMA_BANDS
            or any(type(name) is not str or not name or "." in name for name in schema)
            or len(set(schema)) != len(schema)):
        fail("Raster classifier schema must contain 1..8 unique flat band names")
    if (type(labels) is not list or not 1 <= len(labels) <= MAX_CLASSES
            or any(type(label) is not int or not 0 <= label <= MAX_LABEL for label in labels)
            or labels != sorted(set(labels))):
        fail("Raster classifier labels must be sorted unique integers from 0 through 63")
    if type(centers) is not list or len(centers) != len(labels):
        fail("Raster classifier centers must match its class labels")
    for row in centers:
        if type(row) is not list or len(row) != len(schema):
            fail("Raster classifier center dimensions must match its schema")
        parsed = [_parse_fraction(value) for value in row]
        if model["metric"] == "cosine" and not any(parsed):
            fail("Raster cosine classification rejects a zero-norm class center")
    return model
