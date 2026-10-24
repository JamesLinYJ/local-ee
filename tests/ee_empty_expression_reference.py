"""Independent finite Float64 references for the Wave67 expression workflow."""
from __future__ import annotations

from fractions import Fraction
import json
import hashlib
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-empty-expression-wave67-v1.json"


def load_fixture():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if fixture.get("schema") != "local-ee-empty-expression-wave67/v1":
        raise ValueError("unexpected Wave67 empty-expression fixture schema")
    frozen_keys = (
        "schema", "fixture_id", "input_only", "source_id", "source_bands",
        "source_values", "grid", "region", "mask_transitions", "provenance",
    )
    canonical = json.dumps(
        {key: fixture[key] for key in frozen_keys}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    if (fixture.get("input_only") is not True
            or fixture.get("frozen_before_local_compile") is not True
            or fixture.get("provenance", {}).get("production_results_included") is not False
            or fixture.get("frozen_input_sha256") != hashlib.sha256(canonical).hexdigest()):
        raise ValueError("Wave67 original input fixture failed its frozen-input hash")
    return fixture

def _number(value):
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Wave67 reference inputs must be finite or NoData")
    return number


def _exact(left, right, operation):
    left, right = _number(left), _number(right)
    if left is None or right is None:
        return None
    a, b = Fraction.from_float(left), Fraction.from_float(right)
    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "divide":
        if b == 0:
            return 0.0  # Existing local Float64 division policy.
        result = a / b
    else:
        raise ValueError(f"unsupported reference operation: {operation}")
    return float(result)


def _series(values, operation=None, right=None):
    if operation is None:
        return [_number(value) for value in values]
    return [_exact(value, right[index] if isinstance(right, list) else right, operation)
            for index, value in enumerate(values)]


def expected_expression_outputs(fixture):
    bands = fixture["source_values"]
    red, nir = bands["red"], bands["nir"]
    added = _series(nir, "add", red)
    numerator = _series(nir, "subtract", red)
    denominator = _series(nir, "add", red)
    unweighted_nd = [_exact(top, bottom, "divide")
                     for top, bottom in zip(numerator, denominator)]
    normalized = []
    for red_value, nir_value, value in zip(red, nir, unweighted_nd):
        no_data = red_value is None or nir_value is None
        negative = not no_data and (red_value < 0 or nir_value < 0)
        zero_sum = (not no_data and Fraction.from_float(float(red_value))
                    + Fraction.from_float(float(nir_value)) == 0)
        normalized.append(None if no_data or negative or zero_sum else value)
    assigned = [_exact(value, 2.0, "add") for value in red]
    zero_masked = [None] * len(red)
    zero_weights = [0.0] * len(red)
    return {
        "named_sum": {"values": added, "weights": [0.0 if v is None else 1.0 for v in added]},
        "dot_red": {"values": _series(red), "weights": [0.0 if v is None else 1.0 for v in red]},
        "index_red": {"values": _series(red), "weights": [0.0 if v is None else 1.0 for v in red]},
        "index_nir": {"values": _series(nir), "weights": [0.0 if v is None else 1.0 for v in nir]},
        "assigned": {"values": assigned, "weights": [0.0 if v is None else 1.0 for v in assigned]},
        "unweighted_nd": {"values": unweighted_nd,
                          "weights": [0.0 if v is None else 1.0 for v in unweighted_nd]},
        "normalized_difference": {"values": normalized,
                                  "weights": [0.0 if v is None else 1.0 for v in normalized]},
        "default_call": {"values": zero_masked, "weights": zero_weights},
        "default_index": {"values": zero_masked, "weights": zero_weights},
        "default_name": {"values": zero_masked, "weights": zero_weights},
        "default_index_plus_red": {"values": zero_masked, "weights": zero_weights},
    }


def expected_mask_transition_outputs(fixture):
    cases = fixture["mask_transitions"]
    values, weights, updated_values, updated_weights = [], [], [], []
    for raw, old, new in zip(cases["science"], cases["old_weights"], cases["new_weights"]):
        raw = _number(raw)
        old = _number(old)
        new = _number(new)
        if old is None or not 0 <= old <= 1 or new is None or not 0 <= new <= 1:
            raise ValueError("Wave67 local mask policy requires finite weights in [0,1]")
        old_effective = old if raw is not None and old > 0 else 0.0
        filled = raw if old_effective > 0 else 0.0
        values.append(filled if new > 0 else None)
        weights.append(new)
        updated_weight = new if old_effective > 0 else 0.0
        updated_values.append(raw if raw is not None and updated_weight > 0 else None)
        updated_weights.append(updated_weight)
    return {
        "setter_values": values,
        "setter_weights": weights,
        "update_mask_values": updated_values,
        "update_mask_weights": updated_weights,
    }


def expected_fractional_hidden_recovery(fixture):
    """Local policy for red.updateMask(.25).updateMask(0).mask(1)."""
    values = []
    weights = []
    for raw in fixture["source_values"]["red"]:
        raw = _number(raw)
        original_weight = 0.25 if raw is not None else 0.0
        hidden_weight = 0.0 if original_weight > 0 else 0.0
        filled = raw if hidden_weight > 0 else 0.0
        replacement_weight = 1.0
        values.append(filled if replacement_weight > 0 else None)
        weights.append(replacement_weight)
    return {"values": values, "weights": weights}
