"""Finite local coefficient images: phase, scientific transforms and QA setup.

Use an existing two-band coefficient Image with bands cosine and sine. This
example builds lazy images; actual tasks require the matching native adapter.
"""
import math


def build_workflow(ee, coefficients):
    coefficients = coefficients.toFloat()
    cosine = coefficients.select("cosine")
    sine = coefficients.select("sine")
    phase = cosine.atan2(sine).rename("phase")
    phase_turn = phase.unitScale(-math.pi, math.pi).rename("phase_turn")
    # Deferred constant math is computed on the real coefficient grid.
    gamma_one = ee.Image.constant(1).gamma().rename("gamma_one")
    with_constant = phase.addBands(gamma_one)
    qa_bits = ee.Array([1, 2, 4, 8]).bitwiseAnd(ee.Array([5, 5, 5, 5]))
    return {
        "phase": phase,
        "phase_turn": phase_turn,
        "phase_and_gamma": with_constant,
        "bounded_asin": sine.clamp(-1, 1).asin().rename("bounded_asin"),
        "qa_bits": qa_bits,
        "qa_count": qa_bits.bitCount(),
        "dot": ee.Array([3, 4]).dotProduct(ee.Array([3, 4])),
        "identity": ee.Array.identity(2),
        "padded": ee.Array([1, 2]).pad([4], -1),
        "qa_value": ee.Number.parse("101", 2).bitwise_and(4),
    }
