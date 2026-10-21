"""Pinned SDK printf forms, independent expected strings and resource errors."""
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.number_format import format_number
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("number,pattern,expected", [
    (3.14159265, "%.2f", "3.14"), (42, "%05d", "00042"),
    (3.5, "value=%+08.2f units", "value=+0003.50 units"),
    (-3.5, "%08.2f", "-0003.50"), (42, "%-5d!", "42   !"),
    (2.675, "%.2f", "2.68"), (2.685, "%.2f", "2.69"),
    (-0.005, "%.2f", "-0.01"), (-0.0, "%.2f", "-0.00"), (-0.0, "%d", "0"), (-0.0, "%+d", "+0"),
    (1, "%f", "1.000000"), (1.5, "% .0f", " 2"),
    (17, None, "17"), (1.5, "%8s", "     1.5"), (12345, "%.3s", "123"),
])
def test_sdk_number_format_supported_forms(number, pattern, expected):
    ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
    expression = ee.serializer.encode(ee.Number(number).format(pattern), for_cloud_api=False)
    assert compile_expression(expression, [], {})["value"] == expected


@pytest.mark.parametrize("number,pattern", [
    (3, ""), (3, "%f %d"), (3, "%%"), (3, "%e"), (3, "%x"),
    (3, "%,d"), (3, "%#f"), (3, "%(f"), (3, "%++d"), (3, "%+ d"),
    (3, "%-05d"), (3, "%0d"), (3, "%-d"), (3, "%.2d"), (1.5, "%d"),
    (3, "%1001d"), (3, "%.1001f"), (3, "%99999999999999999999999d"), (3, "%٥d"),
    (3, "x" * 10001 + "%d"), (3, "%+s"), (1e20, "%s"),
    (float("nan"), "%f"), (float("inf"), "%f"), (True, "%d"), (2**64, "%d"),
])
def test_unimplemented_or_malformed_forms_reject_without_dropping_flags(number, pattern):
    with pytest.raises(UnsupportedEEError):
        format_number(Translator([], {}, None), {"number": number, "pattern": pattern})


def test_format_work_budget_and_unknown_options():
    translator = Translator([], {}, None)
    translator.steps = 49999
    with pytest.raises(UnsupportedEEError, match="budget"):
        format_number(translator, {"number": 42, "pattern": "%05d"})
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        format_number(Translator([], {}, None), {"number": 3, "locale": "US"})
