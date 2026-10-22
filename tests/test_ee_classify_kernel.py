"""Opt-in actual GeoTrellis tile kernel versus independent rational/Decimal norms."""
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import random
import struct
import subprocess
import sys

import pytest

from scripts.build_integer_adapter import ROOT, _engine_paths, build, sha256


pytestmark = pytest.mark.skipif(
    os.environ.get("LOCAL_EE_RUN_CLASSIFIER_KERNEL_TEST") != "1",
    reason="opt-in trusted JVM tile-kernel probe; no full native/Spark batch acceptance",
)


def wire(metric, centers):
    return {"version": 1, "metric": metric,
            "schema": [f"b{i}" for i in range(len(centers[0]))],
            "labels": list(range(len(centers))),
            "centers": [[[str(x.numerator), str(x.denominator)] for x in center]
                        for center in centers]}


def reference(metric, query, centers):
    """Direct squared/L1 distance or Decimal norm+sqrt, no production ranking."""
    query = [Fraction.from_float(x) for x in query]
    if metric != "cosine":
        scores = [sum(((q - c) ** 2 if metric == "euclidean" else abs(q - c)
                       for q, c in zip(query, center)), Fraction(0)) for center in centers]
    else:
        with localcontext() as context:
            context.prec = 1600

            def decimal(x):
                return Decimal(x.numerator) / Decimal(x.denominator)

            q = [decimal(x) for x in query]
            qnorm = sum(x * x for x in q).sqrt()
            if not qnorm:
                raise ValueError("zero query")
            scores = []
            for center in centers:
                c = [decimal(x) for x in center]
                norm = sum(x * x for x in c).sqrt()
                if not norm:
                    raise ValueError("zero center")
                scores.append(-sum(a * b for a, b in zip(q, c)) / (qnorm * norm))
    best = min(scores)
    if scores.count(best) != 1:
        raise ValueError("equal nearest classes")
    return scores.index(best)


def cases():
    predictions = []

    def append(metric, centers, query, labels=None, input_type="float64"):
        row = {"model": wire(metric, centers),
               "query": [None if x is None else ("Infinity" if x == math.inf else
                         "-Infinity" if x == -math.inf else float(x).hex()) for x in query],
               "expected": None, "reject": False, "input_type": input_type}
        if labels is not None:
            row["model"]["labels"] = labels
        if input_type == "float32":
            query = [None if x is None else struct.unpack("!f", struct.pack("!f", x))[0]
                     for x in query]
        try:
            if any(x is not None and not math.isfinite(x) for x in query):
                raise ValueError("infinity")
            if not any(x is None for x in query):
                row["expected"] = row["model"]["labels"][reference(metric, query, centers)]
        except ValueError:
            row["reject"] = True
        predictions.append(row)

    standard = [[Fraction(3), Fraction(0)], [Fraction(2), Fraction(2)],
                [Fraction(1, 3), Fraction(1, 2)]]
    randomizer = random.Random(23023)
    for metric in ("euclidean", "manhattan", "cosine"):
        for query in ([.25, .25], [2., 2.], [8., 3.6], [6., 0.], [-2., -2.], [0., 4.],
                      [None, 1.], [1., None], [None, None], [math.inf, 1.],
                      [-math.inf, 1.], [None, math.inf]):
            append(metric, standard, query)
        for _ in range(24):
            centers = [[Fraction(randomizer.randint(-20, 20), randomizer.randint(1, 13))
                        for _ in range(3)] for _ in range(4)]
            append(metric, centers, [randomizer.uniform(-30, 30) for _ in range(3)])
        for scale in (sys.float_info.max, math.ulp(0.0), 1e-300):
            exact = Fraction.from_float(scale)
            append(metric, [[exact, Fraction(0)], [Fraction(0), exact]], [scale, scale / 2])
        # A real 1/3 center, signed directions, extreme mixed magnitudes and ties.
        append(metric, standard, [math.nextafter(1 / 3, 0), .5])
        append(metric, [[Fraction(-1), Fraction(0)], [Fraction(-1), Fraction(-1)]], [1., 0.])
        append(metric, [[Fraction(0), Fraction(1)], [Fraction(2), Fraction(1)]], [1., 1.])
        append(metric, [[Fraction(1), Fraction(0)], [Fraction(2), Fraction(0)]], [0., 0.])
        append(metric, standard, [sys.float_info.max, math.ulp(0.)])
        append(metric, [[Fraction(1), Fraction(0)], [Fraction(0), Fraction(1)]],
               [0., 1.], labels=[0, 63])
        precise = [[Fraction(16777216), Fraction(1)], [Fraction(16777217), Fraction(1)]]
        for input_type in ("float32", "float64"):
            append(metric, precise, [16777217., 1.], input_type=input_type)
    template = wire("euclidean", standard)
    invalid = []
    for key, value in (("version", True), ("version", 1.0), ("version", 2),
                       ("metric", "mahalanobis"), ("schema", ["b0", "b0"]),
                       ("labels", [2, 1, 0]), ("labels", [False, 1, 2])):
        invalid.append(template | {key: value})
    for pair in (["01", "1"], ["+1", "1"], ["-0", "1"], ["2", "4"],
                 ["0", "2"], ["1", "0"], ["1" * 701, "1"], [str(1 << 2200), "1"]):
        value = deepcopy(template)
        value["centers"][0][0] = pair
        invalid.append(value)
    invalid.append(wire("cosine", [[Fraction(0), Fraction(0)], [Fraction(1), Fraction(1)]]))
    binary64 = []
    for value in (0., -0., .1, -.1, math.ulp(0.), -math.ulp(0.),
                  sys.float_info.min, sys.float_info.max, -sys.float_info.max):
        exact = Fraction.from_float(value)
        binary64.append({"input": value.hex(), "numerator": str(exact.numerator),
                         "denominator": str(exact.denominator)})
    return {"predictions": predictions, "invalid_models": invalid, "binary64": binary64}


def test_actual_native_tile_kernel_matches_independent_reference(tmp_path):
    jar = tmp_path / "classifier-adapter.jar"
    manifest = build(jar)
    java, _, compiler, runtime, _ = _engine_paths()
    classes = tmp_path / "classes"
    classes.mkdir()
    source = ROOT / "tests/fixtures/ee-classifier-kernel-probe.scala"
    classpath = os.pathsep.join(map(str, [jar, *runtime]))
    compile_command = [str(java), "-cp", os.pathsep.join(map(str, compiler)),
                       "scala.tools.nsc.Main", "-classpath", classpath,
                       "-d", str(classes), str(source)]
    compiled = subprocess.run(compile_command, capture_output=True, text=True, timeout=120)
    assert compiled.returncode == 0, compiled.stderr
    fixture = cases()
    from gee.compat.earthengine.classifier_model import validate_model

    for row in fixture["predictions"]:
        validate_model(row["model"])
    for invalid in fixture["invalid_models"]:
        with pytest.raises(ValueError):
            validate_model(invalid)
    inputs = tmp_path / "cases.json"
    inputs.write_text(json.dumps(fixture, allow_nan=False))
    result = subprocess.run([str(java), "-cp", str(classes) + os.pathsep + classpath,
                             "ClassifierKernelProbe", str(inputs)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    expected = (f"CLASSIFIER_KERNEL_OK predictions={len(fixture['predictions'])} "
                f"invalid-models={len(fixture['invalid_models'])} binary64={len(fixture['binary64'])}")
    assert expected in result.stdout
    audit_dir = os.environ.get("GEE_AUDIT_DIR")
    if audit_dir:
        target = Path(audit_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "classifier-kernel-cases.json").write_text(json.dumps(fixture, indent=2) + "\n")
        (target / "classifier-kernel.json").write_text(json.dumps({
            "scope": "Trusted standalone GeoTrellis tile kernel, no SparkContext or sandbox task",
            "stdout": result.stdout, "stderr": result.stderr,
            "case_counts": {key: len(value) for key, value in fixture.items()},
            "source_sha256": sha256(source), "manifest": manifest,
            "limitations": ["No full Spark cube, NativeClient/Seatbelt, service, browser or Google acceptance"],
        }, indent=2) + "\n")
