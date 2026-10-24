"""Actual native tile probe binding for spectral workflow sample graphs."""
from __future__ import annotations

from fractions import Fraction
import json
import os
from pathlib import Path
import time

import numpy as np

from ee_spectral_preparation_workflow_helpers import (
    AUDIT_ROOT,
    FIXTURE_PATH,
    ROOT,
    numpy_arrays,
)


def native_manifest_path():
    configured = os.environ.get("GEE_NATIVE_ADAPTER_MANIFEST")
    if configured:
        return Path(configured).expanduser()
    return ROOT.parent.parent / "work/gee-python-wave57/native/local-ee-integer-adapter.jar.manifest.json"


def run_native_probe(fixture):
    manifest = native_manifest_path()
    if not manifest.is_file():
        import pytest
        pytest.skip(f"Native unmix manifest is not available: {manifest}")
    from scripts.probe_unmix_native import run_probe

    return run_probe(manifest, FIXTURE_PATH)


def persist_native_report(report):
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    fixture_hash = report["fixture_sha256"][:12]
    target = AUDIT_ROOT / f"spectral-native-{fixture_hash}-{time.time_ns()}.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def consume_native_unmix_result(compiled, scene, fixture, case_result):
    """Evaluate a compiled sample graph using actual GeoTrellis tile values."""
    from ee_float64_graph_reference import float64_values_handler
    from test_ee_translate import evaluate_graph

    item_id = scene["id"]
    native_spec = next(
        node["arguments"]["spec"]
        for node in compiled["process_graph"].values()
        if node["process_id"] == "local_ee_unmix"
    )
    probe_case = next(
        row for row in fixture["native_probe"]["cases"]
        if row["label"] == item_id
    )
    assert native_spec == probe_case["spec"]
    assert case_result["band_names"] == ["unmix0", "unmix1", "unmix2"]
    native = np.asarray([
        [np.nan if text == "NaN" else float(text) for text in band]
        for band in case_result["actual_bands"]
    ], dtype=np.float64)
    assert native.shape == (3, len(fixture["stac"]["grid"]["pixel_centers"]))
    input_bands = np.stack([numpy_arrays(scene)[name]
                            for name in fixture["source_band_order"]])

    def native_handler(arguments, values):
        assert set(arguments) == {"data", "spec"}
        assert arguments["spec"] == native_spec
        reference = arguments["data"]
        assert set(reference) == {"from_node"}
        source_cube, names, timed = values[reference["from_node"]]
        # The SDK preparation graph renames selected physical bands to the
        # native wire contract's positional inputs before compiling unmix.
        assert names == [f"band{index}" for index in range(len(input_bands))]
        source = source_cube[0] if timed else source_cube
        np.testing.assert_allclose(source, input_bands, rtol=0, atol=0, equal_nan=True)
        actual = native[None, :, :] if timed else native
        return actual, ["unmix0", "unmix1", "unmix2"], timed

    handlers = {"local_ee_integer_values": float64_values_handler,
                "local_ee_unmix": native_handler}
    values, names, timed = evaluate_graph(
        compiled, {item_id: numpy_arrays(scene)},
        grid=np.asarray(fixture["stac"]["grid"]["pixel_centers"], dtype=np.float64),
        source_geometries={item_id: scene["item"]["geometry"]},
        process_handlers=handlers,
    )
    sample_values = values[0] if timed else values
    assert names == fixture["unmix"]["component_band_order"]
    np.testing.assert_allclose(sample_values, native, rtol=0, atol=0, equal_nan=True)
    expected = np.asarray([
        [np.nan if text is None else float(Fraction(text)) for text in row]
        for row in zip(*scene["true_fractions"])
    ], dtype=np.float64)
    np.testing.assert_allclose(sample_values, expected, rtol=0, atol=2e-12, equal_nan=True)
    return sample_values
