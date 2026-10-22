"""Strict exact-rational wire contract for native raster classifiers."""
from copy import deepcopy
from fractions import Fraction

import pytest

from gee.compat.earthengine.classifier_model import (
    encode_model,
    model_serialization_work,
    model_validation_work,
    validate_model,
)
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.minimum_distance import StaticMinimumDistance


def classifier(metric="euclidean", centers=None):
    centers = ((Fraction(1, 3), Fraction(-7, 5)),
               (Fraction(9, 10), Fraction(11, 13))) if centers is None else centers
    return StaticMinimumDistance(
        metric=metric,
        schema=("red", "nir"),
        labels=(2, 7),
        centers=centers,
        training_rows=((2, (Fraction(1), Fraction(2))),),
    )


def valid_wire():
    return encode_model(classifier())


def test_wire_round_trip_preserves_exact_centers_and_has_only_v1_fields():
    source = classifier()
    wire = encode_model(source)

    assert set(wire) == {"version", "metric", "schema", "labels", "centers"}
    assert wire == {
        "version": 1,
        "metric": "euclidean",
        "schema": ["red", "nir"],
        "labels": [2, 7],
        "centers": [[ ["1", "3"], ["-7", "5"] ],
                    [ ["9", "10"], ["11", "13"] ]],
    }
    assert validate_model(wire) is wire
    assert model_serialization_work(source) > 0
    assert model_validation_work(wire) > 0


@pytest.mark.parametrize("change", [
    lambda m: m.update(extra=1),
    lambda m: m.update(version=True),
    lambda m: m.update(version=2),
    lambda m: m.update(metric="mahalanobis"),
    lambda m: m.update(schema=["red", "red"]),
    lambda m: m.update(schema=["red.name"]),
    lambda m: m.update(schema=[]),
    lambda m: m.update(labels=[2, True]),
    lambda m: m.update(labels=[7, 2]),
    lambda m: m.update(labels=[64]),
    lambda m: m.update(centers=[]),
    lambda m: m["centers"][0].__setitem__(1, ["01", "3"]),
    lambda m: m["centers"][0].__setitem__(1, ["+1", "3"]),
    lambda m: m["centers"][0].__setitem__(1, ["2", "4"]),
    lambda m: m["centers"][0].__setitem__(1, ["0", "2"]),
    lambda m: m["centers"][0].__setitem__(1, ["1", "0"]),
    lambda m: m["centers"][0].__setitem__(1, ["1" * 701, "1"]),
    lambda m: m["centers"][0].__setitem__(1, [str(1 << 2200), "1"]),
    lambda m: (m.update(metric="cosine"), m["centers"][0].__setitem__(0, ["0", "1"]),
               m["centers"][0].__setitem__(1, ["0", "1"])),
])
def test_wire_rejects_unknown_noncanonical_or_unsupported_models(change):
    model = deepcopy(valid_wire())
    change(model)
    with pytest.raises(UnsupportedEEError):
        validate_model(model)


def test_wire_rejects_center_outside_float64_range_and_untrained_classifier():
    outside = classifier(centers=((Fraction(1 << 1024), Fraction(0)),
                                  (Fraction(1), Fraction(1))))
    with pytest.raises(UnsupportedEEError, match="finite Float64"):
        encode_model(outside)

    untrained = StaticMinimumDistance(metric="euclidean")
    with pytest.raises(UnsupportedEEError, match="must be trained"):
        encode_model(untrained)


def test_cosine_wire_rejects_zero_center_even_though_training_ir_can_retain_it():
    zero_center = classifier(
        metric="cosine",
        centers=((Fraction(0), Fraction(0)), (Fraction(1), Fraction(0))),
    )
    with pytest.raises(UnsupportedEEError, match="zero-norm class center"):
        encode_model(zero_center)
