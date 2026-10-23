"""Finite Date calendar semantics for the pinned Earth Engine API."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from gee.compat.earthengine import date_calendar, date_calendar_parse
from gee.compat.earthengine.date_calendar import (
    SUPPORTED_DATE_CALENDAR_FUNCTIONS,
    invoke_date_calendar,
)
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.ee_translate import compile_expression


ROOT = Path(__file__).resolve().parents[1]
EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def _epoch_ms(value: dt.datetime) -> float:
    elapsed = value.astimezone(dt.timezone.utc) - EPOCH
    return elapsed.days * 86_400_000 + elapsed.seconds * 1000 + elapsed.microseconds / 1000


def _invoke(name, **arguments):
    return invoke_date_calendar(Translator([], {}, None), name, arguments)


def test_pinned_function_set_and_direct_handler_route():
    assert SUPPORTED_DATE_CALENDAR_FUNCTIONS == frozenset({
        "Date.parse", "Date.update", "Date.getRange", "Date.unitRatio",
    })
    translator = Translator([], {}, None)
    assert translator.invoke("Date.unitRatio", {
        "numerator": "day", "denominator": "minute",
    }) == 1440


def test_parse_numeric_joda_subset_and_utc_zone_tokens():
    value = _invoke(
        "Date.parse", format="yyyy-MM-dd HH:mm:ss.SSS",
        date="2020-2-29 07:15:31.240",
    )
    expected = dt.datetime(2020, 2, 29, 7, 15, 31, 240_000, tzinfo=dt.timezone.utc)
    assert value == _epoch_ms(expected)

    quoted = _invoke(
        "Date.parse", format="yyyy-MM-dd 'at' HH:mm:ss.SSSZZZ",
        date="2020-02-29 at 07:15:31.240UTC",
    )
    assert quoted == value


@pytest.mark.parametrize(("pattern", "value"), [
    ("yyyy", "2020"), ("M", "12"), ("MM", "2"), ("d", "31"),
    ("HH", "23"), ("m", "59"), ("ss", "59"), ("D", "366"),
])
def test_parse_variable_width_fields_have_calendar_specific_digit_caps(pattern, value):
    assert isinstance(_invoke("Date.parse", format=pattern, date=value), float)


@pytest.mark.parametrize(("pattern", "value"), [
    ("yyyy", "02020"), ("M", "123"), ("MM", "123"),
    ("d", "123"), ("HH", "123"), ("m", "123"), ("ss", "123"),
    ("D", "1234"),
])
def test_parse_rejects_numeric_fields_wider_than_calendar_limits(pattern, value):
    with pytest.raises(UnsupportedEEError):
        _invoke("Date.parse", format=pattern, date=value)


def test_parse_adversarial_digit_literals_use_bounded_numeric_groups():
    regex, _ = date_calendar_parse._compile_pattern(
        date_calendar_parse._pattern_parts("yyyy")
    )
    assert regex.pattern == r"([0-9]{1,4})"

    pattern = "yyyy" + "1" * 196
    assert len(pattern) == 200
    assert _invoke("Date.parse", format=pattern, date="1" * 200) == _epoch_ms(
        dt.datetime(1111, 1, 1, tzinfo=dt.timezone.utc)
    )
    with pytest.raises(UnsupportedEEError):
        _invoke("Date.parse", format=pattern, date="1" * 199 + "2")


def test_parse_rejects_ambiguous_adjacent_unpadded_fields():
    with pytest.raises(UnsupportedEEError, match="ambiguous"):
        _invoke("Date.parse", format="yyyyMdd", date="2020215")
    assert _invoke("Date.parse", format="yyyyMMdd", date="20200229") == _epoch_ms(
        dt.datetime(2020, 2, 29, tzinfo=dt.timezone.utc)
    )


def test_parse_ordinal_dates_and_documented_missing_field_defaults():
    assert _invoke("Date.parse", format="yyyy-DDD", date="2020-060") == _epoch_ms(
        dt.datetime(2020, 2, 29, tzinfo=dt.timezone.utc)
    )
    assert _invoke("Date.parse", format="MM-dd", date="02-29") == _epoch_ms(
        dt.datetime(2000, 2, 29, tzinfo=dt.timezone.utc)
    )
    assert _invoke("Date.parse", format="HH:mm", date="07:15") == _epoch_ms(
        dt.datetime(1970, 1, 1, 7, 15, tzinfo=dt.timezone.utc)
    )


def test_parse_two_digit_year_uses_explicit_reproducible_pivot():
    translator = Translator([], {}, None)
    assert invoke_date_calendar(translator, "Date.parse", {
        "format": "yy-MM-dd", "date": "49-01-01",
    }) == _epoch_ms(dt.datetime(2049, 1, 1, tzinfo=dt.timezone.utc))
    assert invoke_date_calendar(translator, "Date.parse", {
        "format": "yy-MM-dd", "date": "50-01-01",
    }) == _epoch_ms(dt.datetime(1950, 1, 1, tzinfo=dt.timezone.utc))
    assert any("fixed 1950..2049 pivot" in warning for warning in translator.warnings)


@pytest.mark.parametrize(("pattern", "value"), [
    ("yyyy-MM-dd", "2021-02-29"),
    ("yyyy-MM-dd", "0000-01-01"),
    ("yyyy-DDD", "2021-366"),
    ("yyyy-MM-dd", "2021-13-01"),
    ("yyyy-MM-dd", "2021-01-01junk"),
    ("yyyy-MM-dd HH:mm:ss", "2021-01-01 24:00:00"),
    ("yyyy-MM-dd HH:mm:ss", "2021-01-01 00:00:60"),
    ("yyyy-MM-ddX", "2021-01-01X"),
    ("yyyy-MM-dd 'broken", "2021-01-01 broken"),
    ("yyyy-DDD-MM", "2020-060-02"),
])
def test_parse_rejects_invalid_calendar_values_and_unsupported_patterns(pattern, value):
    with pytest.raises(UnsupportedEEError):
        _invoke("Date.parse", format=pattern, date=value)


@pytest.mark.parametrize("arguments", [
    {"format": "yyyy-MM-dd", "date": "2020-01-01", "timeZone": "Asia/Shanghai"},
    {"format": "yyyy-MM-dd ZZZ", "date": "2020-01-01America/Los_Angeles"},
    {"format": "yyyy-MM-dd ZZ", "date": "2020-01-01+05:00"},
    {"format": "MMM dd, yyyy", "date": "Feb 29, 2020"},
])
def test_parse_never_drops_zone_or_unsupported_text_fields(arguments):
    with pytest.raises(UnsupportedEEError):
        _invoke("Date.parse", **arguments)


def test_update_sets_components_and_preserves_unmentioned_fields():
    original = _epoch_ms(dt.datetime(2020, 2, 29, 7, 15, 31, 240_000, tzinfo=dt.timezone.utc))
    translator = Translator([], {}, None)
    updated = invoke_date_calendar(translator, "Date.update", {
        "date": original, "year": 2021,
    })
    assert updated == _epoch_ms(dt.datetime(2021, 2, 28, 7, 15, 31, 240_000, tzinfo=dt.timezone.utc))
    assert any("clamps an inherited day" in warning for warning in translator.warnings)

    updated = _invoke("Date.update", date=original, month=3, day=1, hour=8, minute=9, second=10.125)
    assert updated == _epoch_ms(dt.datetime(2020, 3, 1, 8, 9, 10, 125_000, tzinfo=dt.timezone.utc))
    assert _invoke("Date.update", date=original) == original


def test_update_month_end_clamping_and_explicit_invalid_day_errors():
    january_31 = _epoch_ms(dt.datetime(2021, 1, 31, 12, tzinfo=dt.timezone.utc))
    assert _invoke("Date.update", date=january_31, month=2) == _epoch_ms(
        dt.datetime(2021, 2, 28, 12, tzinfo=dt.timezone.utc)
    )
    with pytest.raises(UnsupportedEEError, match="day is invalid"):
        _invoke("Date.update", date=january_31, month=2, day=31)
    with pytest.raises(UnsupportedEEError, match="day is invalid"):
        _invoke("Date.update", date=january_31, month=2, day=29)


@pytest.mark.parametrize(("field", "value"), [
    ("year", 0), ("year", 10_000), ("month", 0), ("month", 13),
    ("day", 0), ("hour", 24), ("minute", 60), ("second", 60),
    ("second", -0.1), ("second", 1.0001), ("hour", True),
])
def test_update_rejects_out_of_range_or_unrepresentable_fields(field, value):
    base = _epoch_ms(dt.datetime(2020, 1, 31, 12, tzinfo=dt.timezone.utc))
    with pytest.raises(UnsupportedEEError):
        _invoke("Date.update", date=base, **{field: value})


def test_get_range_returns_half_open_calendar_boundaries():
    value = _epoch_ms(dt.datetime(2020, 2, 29, 7, 15, 31, 240_000, tzinfo=dt.timezone.utc))
    expected = {
        "year": (dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc), 366 * 86_400_000),
        "month": (dt.datetime(2020, 2, 1, tzinfo=dt.timezone.utc), 29 * 86_400_000),
        "week": (dt.datetime(2020, 2, 24, tzinfo=dt.timezone.utc), 7 * 86_400_000),
        "day": (dt.datetime(2020, 2, 29, tzinfo=dt.timezone.utc), 86_400_000),
        "hour": (dt.datetime(2020, 2, 29, 7, tzinfo=dt.timezone.utc), 3_600_000),
        "minute": (dt.datetime(2020, 2, 29, 7, 15, tzinfo=dt.timezone.utc), 60_000),
        "second": (dt.datetime(2020, 2, 29, 7, 15, 31, tzinfo=dt.timezone.utc), 1_000),
    }
    for unit, (start, duration) in expected.items():
        start_ms, end_ms = _invoke("Date.getRange", date=value, unit=unit)
        assert start_ms == _epoch_ms(start), unit
        assert end_ms == start_ms + duration, unit
        assert start_ms <= value < end_ms, unit


@pytest.mark.parametrize(("unit", "date", "start", "end"), [
    ("year", "2020-12-31T23:59:59.999Z", "2020-01-01", "2021-01-01"),
    ("year", "2021-01-01T00:00:00Z", "2021-01-01", "2022-01-01"),
    ("month", "2020-02-29T23:59:59.999Z", "2020-02-01", "2020-03-01"),
    ("month", "2020-03-01T00:00:00Z", "2020-03-01", "2020-04-01"),
    ("week", "2020-03-01T23:59:59.999Z", "2020-02-24", "2020-03-02"),
    ("week", "2020-03-02T00:00:00Z", "2020-03-02", "2020-03-09"),
    ("day", "2020-02-29T23:59:59.999Z", "2020-02-29", "2020-03-01"),
    ("day", "2020-03-01T00:00:00Z", "2020-03-01", "2020-03-02"),
])
def test_get_range_edges_are_inclusive_start_exclusive_end(unit, date, start, end):
    actual = _invoke("Date.getRange", date=date, unit=unit)
    expected = (_epoch_ms(dt.datetime.fromisoformat(start + "T00:00:00+00:00")),
                _epoch_ms(dt.datetime.fromisoformat(end + "T00:00:00+00:00")))
    assert actual == expected


def test_get_range_can_represent_the_end_of_year_9999():
    start, end = _invoke("Date.getRange", date="9999-12-31T23:59:59.999Z", unit="year")
    assert start == _epoch_ms(dt.datetime(9999, 1, 1, tzinfo=dt.timezone.utc))
    assert end - start == 365 * 86_400_000
    assert end == _epoch_ms(dt.datetime(9999, 1, 1, tzinfo=dt.timezone.utc)) + 365 * 86_400_000


def test_calendar_operations_preserve_year_one_lower_boundary():
    year_one = _epoch_ms(dt.datetime(1, 1, 1, tzinfo=dt.timezone.utc))
    assert _invoke("Date.parse", format="yyyy-MM-dd", date="0001-01-01") == year_one
    assert _invoke("Date.update", date=year_one, year=1) == year_one
    assert _invoke("Date.getRange", date=year_one, unit="year") == (
        year_one, year_one + 365 * 86_400_000,
    )


@pytest.mark.parametrize("name,arguments", [
    ("Date.update", {"date": 0.5, "hour": 1}),
    ("Date.getRange", {"date": 0.5, "unit": "day"}),
])
def test_calendar_fields_reject_unverified_submillisecond_dates(name, arguments):
    with pytest.raises(UnsupportedEEError, match="sub-millisecond precision"):
        _invoke(name, **arguments)


def test_unit_ratio_exact_units_and_explicit_average_calendar_policy():
    assert _invoke("Date.unitRatio", numerator="day", denominator="minute") == 1440
    assert _invoke("Date.unitRatio", numerator="week", denominator="day") == 7
    assert _invoke("Date.unitRatio", numerator="month", denominator="year") == pytest.approx(1 / 12)
    assert _invoke("Date.unitRatio", numerator="year", denominator="day") == pytest.approx(365.2425)
    translator = Translator([], {}, None)
    invoke_date_calendar(translator, "Date.unitRatio", {"numerator": "year", "denominator": "month"})
    assert any("average-duration constants" in warning for warning in translator.warnings)


@pytest.mark.parametrize(("name", "arguments"), [
    ("Date.parse", {"format": "yyyy", "date": "2020", "locale": "en"}),
    ("Date.parse", {"format": "yyyy"}),
    ("Date.update", {"date": 0, "locale": "en"}),
    ("Date.update", {"year": 2020}),
    ("Date.getRange", {"date": 0, "unit": "fortnight"}),
    ("Date.getRange", {"date": 0, "unit": "day", "timeZone": "UTC+8"}),
    ("Date.unitRatio", {"numerator": "days", "denominator": "hour"}),
    ("Date.unitRatio", {"numerator": "day"}),
])
def test_missing_unknown_and_unsupported_date_arguments_fail(name, arguments):
    with pytest.raises(UnsupportedEEError):
        invoke_date_calendar(Translator([], {}, None), name, arguments)


@pytest.mark.parametrize(("name", "arguments", "work"), [
    ("Date.parse", {"format": "yyyy", "date": "2020"}, 9),
    ("Date.update", {"date": 0}, 2),
    ("Date.getRange", {"date": 0, "unit": "day"}, 2),
    ("Date.unitRatio", {"numerator": "day", "denominator": "second"}, 1),
])
def test_direct_calendar_handlers_precharge_shared_translator_budget(name, arguments, work):
    translator = Translator([], {}, None)
    translator.steps = 50_000 - work
    invoke_date_calendar(translator, name, arguments)
    assert translator.steps == 50_000

    exhausted = Translator([], {}, None)
    exhausted.steps = 50_000 - work + 1
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_date_calendar(exhausted, name, arguments)
    assert exhausted.steps == min(50_000 - work + 2, 50_000)


def test_parse_budget_is_charged_before_pattern_compilation(monkeypatch):
    def parser_must_not_run(*args, **kwargs):
        raise AssertionError("parser was called before work was charged")

    monkeypatch.setattr(date_calendar, "parse_joda_date", parser_must_not_run)
    translator = Translator([], {}, None)
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_date_calendar(translator, "Date.parse", {
            "format": "yyyy", "date": "2020",
        })
    assert translator.steps == 50_000


@pytest.mark.parametrize("name", ["Date.update", "Date.getRange"])
def test_calendar_string_scan_is_precharged_before_datetime_parsing(monkeypatch, name):
    def calendar_must_not_run(*args, **kwargs):
        raise AssertionError("calendar parser was called before work was charged")

    monkeypatch.setattr(date_calendar, "_calendar_date", calendar_must_not_run)
    translator = Translator([], {}, None)
    translator.steps = 49_950
    arguments = {"date": "2020-01-01" * 10}
    if name == "Date.update":
        arguments["year"] = 2021
    else:
        arguments["unit"] = "day"
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_date_calendar(translator, name, arguments)
    assert translator.steps == 49_951


def test_oversized_calendar_strings_and_unit_names_fail_closed():
    with pytest.raises(UnsupportedEEError, match="200 characters"):
        _invoke("Date.parse", format="yyyy", date="2" * 201)
    with pytest.raises(UnsupportedEEError, match="200 characters"):
        _invoke("Date.getRange", date="2020-01-01" * 21, unit="day")
    with pytest.raises(UnsupportedEEError, match="Unsupported Date getRange unit"):
        _invoke("Date.getRange", date=0, unit="d" * 100_000)


def _sdk_date_expressions():
    code = textwrap.dedent(f"""
        import json
        import ee
        from gee.ee_python_client import configure_local_ee
        from scripts.ee_python_api.offline import OfflineGuard

        with OfflineGuard() as guard:
            configure_local_ee(
                'http://127.0.0.1:8787/openeo/1.2', 'a' * 48,
                signatures_path={str(ROOT / 'vendor/earthengine-js/algorithms.json')!r},
            )
            expressions = {{
                'parse': ee.Date.parse('yyyy-MM-dd HH:mm:ss.SSS', '2020-02-29 07:15:31.240'),
                'update': ee.Date('2020-02-29T07:15:31.240Z').update(year=2021),
                'range': ee.Date('2020-02-29T07:15:31.240Z').getRange('month'),
                'ratio': ee.Date.unitRatio('day', 'minute'),
            }}
            encoded = {{name: ee.serializer.encode(value, is_compound=True, for_cloud_api=False)
                       for name, value in expressions.items()}}
        print(json.dumps({{'expressions': encoded, 'network': guard.evidence()}}))
    """)
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, check=True,
        capture_output=True, text=True, timeout=30,
    )
    return json.loads(completed.stdout)


def test_pinned_python_sdk_serialization_and_public_compiler_handler():
    fixture = _sdk_date_expressions()
    assert set(fixture["expressions"]) == {"parse", "update", "range", "ratio"}
    assert fixture["network"]["attempt_count"] == 0
    for name, expression in fixture["expressions"].items():
        result = compile_expression(expression, [], {})
        assert result["kind"] == "value", name

    expected = _epoch_ms(dt.datetime(2020, 2, 29, 7, 15, 31, 240_000, tzinfo=dt.timezone.utc))
    assert compile_expression(fixture["expressions"]["parse"], [], {})["value"] == expected
    updated = compile_expression(fixture["expressions"]["update"], [], {})
    assert updated["value"] == _epoch_ms(
        dt.datetime(2021, 2, 28, 7, 15, 31, 240_000, tzinfo=dt.timezone.utc)
    )
    assert any("clamps an inherited day" in warning for warning in updated["warnings"])
    month_range = compile_expression(fixture["expressions"]["range"], [], {})["value"]
    start = _epoch_ms(dt.datetime(2020, 2, 1, tzinfo=dt.timezone.utc))
    assert month_range == [start, start + 29 * 86_400_000]
    assert compile_expression(fixture["expressions"]["ratio"], [], {})["value"] == 1440
