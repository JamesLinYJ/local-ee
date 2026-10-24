"""Prepare local synthetic spectra, calibrate bands, and unmix endmember fractions.

The source arrays and STAC records live in a versioned fixture. This script
constructs graphs with the pinned offline Earth Engine Python client; it does
not request a Google asset or use user data.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


SYNTHETIC_VERSION = "local-ee-synthetic-spectral-preparation/v1"
COPY_PROPERTIES = ["system:index", "system:time_start", "workflow"]


def declared_local_data(fixture):
    """Return the fixture's catalog and explicit local STAC item records."""
    stac = fixture["stac"]
    collection = stac["collection"]
    return [collection], {collection["id"]: [scene["item"] for scene in fixture["scenes"]]}


def scene_image(ee, fixture, item_id):
    """Select one fixture item without joining masks across scene keys."""
    return ee.ImageCollection(fixture["stac"]["collection"]["id"]).filter(
        ee.Filter.eq("system:index", item_id)
    ).first()


def build_workflow(ee, image, fixture):
    """Return typed color, calibration, and fixed-endmember graph components."""
    source = ee.Image(image).select(
        fixture["source_band_order"], fixture["prepared_band_order"],
    ).toDouble().set("workflow", SYNTHETIC_VERSION)

    # RGB order is explicit; source storage order is blue, green, red.
    rgb = source.select(["red", "green", "blue"])
    # The pinned client exposes unknown-band algorithm returns as Element;
    # restore the documented Image type before chaining image methods.
    hsv = ee.Image(
        ee.Image(rgb.rgbToHsv()).copyProperties(source, COPY_PROPERTIES)
    )
    round_trip = ee.Image(
        ee.Image(hsv.hsvToRgb())
        .copyProperties(source, COPY_PROPERTIES)
    )

    calibration = fixture["calibration"]
    red_lut = ee.Image(
        ee.Image(source.select("red").interpolate(
            calibration["lut_input"], calibration["lut_output"],
            behavior=calibration["interpolation_behavior"],
        )).rename("red_lut").copyProperties(source, COPY_PROPERTIES)
    )
    green_polynomial = ee.Image(
        ee.Image(source.select("green").polynomial(
            calibration["polynomial_coefficients_ascending"],
        )).rename("green_polynomial").copyProperties(source, COPY_PROPERTIES)
    )

    unmix = fixture["unmix"]
    ordered_spectra = source.select(unmix["input_band_order"])
    fractions = ee.Image(
        ee.Image(ordered_spectra.unmix(
            unmix["endmembers"],
            sumToOne=unmix["flags"]["sumToOne"],
            nonNegative=unmix["flags"]["nonNegative"],
        )).copyProperties(source, COPY_PROPERTIES)
    )
    return {
        "rgb_to_hsv": hsv,
        "rgb_roundtrip": round_trip,
        "red_lut": red_lut,
        "green_polynomial": green_polynomial,
        "unmixed_fractions": fractions,
    }


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    fixture = json.loads(
        (root / "tests/fixtures/ee-spectral-preparation-wave57-v1.json")
        .read_text(encoding="utf-8")
    )
    from scripts.ee_python_api.offline import OfflineGuard
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression

    catalog, items = declared_local_data(fixture)
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=root / "vendor/earthengine-js/algorithms.json",
        )
        summaries = {}
        for scene in fixture["scenes"]:
            outputs = build_workflow(ee, scene_image(ee, fixture, scene["id"]), fixture)
            summaries[scene["id"]] = {
                name: {
                    "bands": compile_expression(
                        ee.serializer.encode(value, for_cloud_api=False),
                        catalog, items,
                    )["bands"],
                }
                for name, value in outputs.items()
            }
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({
        "fixture": fixture["schema"],
        "scenes": summaries,
        "network_attempts": 0,
        "services_used": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
