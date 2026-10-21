"""Static Date semantics and serializer contracts for the pinned EE SDK."""
import json
from pathlib import Path

import pytest

from gee.ee_dates import SUPPORTED_DATE_FUNCTIONS, invoke_date
from gee.ee_translate import Translator, UnsupportedEEError, compile_expression, millis


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-date-1.7.49.json"


def invoke(name, **arguments):
    return invoke_date(Translator([], {}, None), name, arguments)


def date_ms(value):
    return millis(value)


def test_difference_uses_average_gregorian_durations_and_direction():
    # 30 calendar days are not one average month (30.436875 days).
    expected_month_fraction = (30 * 86_400_000) / 2_629_746_000
    assert invoke("Date.difference", date=date_ms("2020-01-31"), start=date_ms("2020-01-01"), unit="month") == pytest.approx(expected_month_fraction)
    assert invoke("Date.difference", date=date_ms("2021-01-01"), start=date_ms("2020-01-01"), unit="year") == pytest.approx(366 / 365.2425)
    assert invoke("Date.difference", date=date_ms("2020-01-01"), start=date_ms("2020-01-15"), unit="weeks") == pytest.approx(-2)
    assert invoke("Date.difference", date=1500, start=0, unit="seconds") == pytest.approx(1.5)


def test_difference_fixed_units_preserve_millisecond_precision():
    start = date_ms("2024-03-01T00:00:00.000Z")
    end = date_ms("2024-03-01T00:00:01.250Z")
    assert invoke("Date.difference", date=end, start=start, unit="second") == pytest.approx(1.25)
    assert invoke("Date.difference", date=start, start=start, unit="day") == 0


def test_difference_submillisecond_inputs_are_preserved_with_a_warning():
    translator = Translator([], {}, None)
    result = invoke_date(translator, "Date.difference", {
        "date": 1.75, "start": 0.25, "unit": "second",
    })
    assert result == pytest.approx(0.0015)
    assert any("sub-millisecond rounding behavior has not been verified" in warning
               for warning in translator.warnings)


def test_difference_overflow_and_huge_integer_inputs_fail_stably():
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="result is not finite"):
        invoke_date(translator, "Date.difference", {
            "date": 1e308, "start": -1e308, "unit": "second",
        })
    with pytest.raises(UnsupportedEEError, match="supported numeric range"):
        invoke_date(translator, "Date.difference", {
            "date": 10**1000, "start": 0, "unit": "second",
        })


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -float("inf")])
def test_nonfinite_and_boolean_dates_fail_with_stable_errors(value):
    with pytest.raises(UnsupportedEEError):
        invoke("Date.difference", date=value, start=0, unit="second")
    with pytest.raises(UnsupportedEEError):
        invoke("Date.getFraction", date=value, unit="second")


@pytest.mark.parametrize("name,arguments", [
    ("Date.getFraction", {"date": 0.5, "unit": "second"}),
    ("Date.getFraction", {"date": "1970-01-01T00:00:00.000001Z", "unit": "second"}),
    ("Date.getRelative", {"date": 0.5, "unit": "day", "inUnit": "year"}),
    ("Date.getRelative", {"date": "1970-01-01T00:00:00.000001Z", "unit": "day", "inUnit": "year"}),
])
def test_calendar_fields_reject_unverified_submillisecond_inputs(name, arguments):
    with pytest.raises(UnsupportedEEError, match="sub-millisecond precision"):
        invoke(name, **arguments)


def test_calendar_fields_wrap_large_numeric_overflow_as_unsupported():
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="supported numeric range"):
        invoke_date(translator, "Date.getFraction", {"date": 10**1000, "unit": "day"})
    with pytest.raises(UnsupportedEEError, match="supported calendar range"):
        invoke_date(translator, "Date.getRelative", {
            "date": 1e308, "unit": "day", "inUnit": "year",
        })


def test_calendar_fields_accept_supported_calendar_endpoints():
    first = date_ms("0001-01-01T00:00:00Z")
    last = date_ms("9999-12-31T23:59:59.999Z")
    assert invoke("Date.getFraction", date=first, unit="day") == 0
    assert invoke("Date.getRelative", date=first, unit="day", inUnit="year") == 0
    assert 0 < invoke("Date.getFraction", date=last, unit="year") < 1
    assert invoke("Date.getRelative", date=last, unit="day", inUnit="year") == 364


def test_relative_matches_published_examples_and_zero_based_calendar_fields():
    leap_day = date_ms("2020-02-29T07:15:31.240Z")
    assert invoke("Date.getRelative", date=leap_day, unit="month", inUnit="year") == 1
    assert invoke("Date.getRelative", date=leap_day, unit="day", inUnit="year") == 59
    assert invoke("Date.getRelative", date=leap_day, unit="day", inUnit="month") == 28
    assert invoke("Date.getRelative", date=leap_day, unit="minute", inUnit="day") == 7 * 60 + 15
    assert invoke("Date.getRelative", date=leap_day, unit="second", inUnit="minute") == 31
    assert invoke("Date.getRelative", date=leap_day, unit="year", inUnit="month") == 0


def test_relative_iso_weekyear_boundary_and_week_start():
    # ISO week-year 2020 has week 53 through 2021-01-03; 2021-01-04 is week 1.
    assert invoke("Date.getRelative", date=date_ms("2021-01-01"), unit="week", inUnit="year") == 52
    assert invoke("Date.getRelative", date=date_ms("2021-01-04"), unit="week", inUnit="year") == 0
    assert invoke("Date.getRelative", date=date_ms("2024-01-07T23:00:00Z"), unit="day", inUnit="week") == 6
    assert invoke("Date.getRelative", date=date_ms("2024-01-08T00:00:00Z"), unit="day", inUnit="week") == 0


def test_fraction_uses_actual_calendar_unit_lengths():
    leap_day = date_ms("2020-02-29T07:15:31.240Z")
    millis_of_day = (7 * 3600 + 15 * 60 + 31) * 1000 + 240
    assert invoke("Date.getFraction", date=leap_day, unit="year") == pytest.approx((59 * 86_400_000 + millis_of_day) / (366 * 86_400_000))
    assert invoke("Date.getFraction", date=leap_day, unit="month") == pytest.approx((28 * 86_400_000 + millis_of_day) / (29 * 86_400_000))
    assert invoke("Date.getFraction", date=leap_day, unit="week") == pytest.approx((5 * 86_400_000 + millis_of_day) / (7 * 86_400_000))
    assert invoke("Date.getFraction", date=leap_day, unit="day") == pytest.approx(millis_of_day / 86_400_000)
    assert invoke("Date.getFraction", date=leap_day, unit="hour") == pytest.approx((15 * 60_000 + 31_240) / 3_600_000)
    assert invoke("Date.getFraction", date=leap_day, unit="minute") == pytest.approx(31_240 / 60_000)
    assert invoke("Date.getFraction", date=leap_day, unit="second") == pytest.approx(.24)


def test_fraction_year_and_month_explain_local_calendar_length_policy():
    translator = Translator([], {}, None)
    invoke_date(translator, "Date.getFraction", {
        "date": date_ms("2020-02-29T07:15:31.240Z"), "unit": "year",
    })
    invoke_date(translator, "Date.getFraction", {
        "date": date_ms("2020-02-29T07:15:31.240Z"), "unit": "month",
    })
    warnings = [warning for warning in translator.warnings
                if "actual UTC calendar lengths" in warning]
    assert len(warnings) == 1
    assert "per year" in warnings[0] and "per month" in warnings[0]


def test_relative_rejects_unverified_week_of_month_and_non_utc_zone():
    with pytest.raises(UnsupportedEEError, match="week-of-month"):
        invoke("Date.getRelative", date=date_ms("2024-01-15"), unit="week", inUnit="month")
    with pytest.raises(UnsupportedEEError, match="UTC only"):
        invoke("Date.getRelative", date=date_ms("2024-01-15"), unit="day", inUnit="year", timeZone="Asia/Shanghai")


@pytest.mark.parametrize("name,arguments", [
    ("Date.difference", {"date": 0, "start": 0, "unit": "fortnight"}),
    ("Date.difference", {"date": 0, "start": 0, "unit": "millisecond"}),
    ("Date.getFraction", {"date": 0, "unit": "decade"}),
    ("Date.getRelative", {"date": 0, "unit": "day", "inUnit": "decade"}),
    ("Date.getRelative", {"date": 0, "unit": "day", "inUnit": "second"}),
    ("Date.getRelative", {"date": 0, "unit": "day", "inUnit": "day"}),
])
def test_invalid_units_fail_explicitly(name, arguments):
    with pytest.raises(UnsupportedEEError):
        invoke_date(Translator([], {}, None), name, arguments)


def test_missing_and_unknown_arguments_fail_explicitly():
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="requires date, start, and unit"):
        invoke_date(translator, "Date.difference", {"date": 0, "start": 0})
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_date(translator, "Date.getRelative", {"date": 0, "unit": "day", "inUnit": "year", "locale": "en"})


def _final_invocation(serialized):
    assert serialized["type"] == "CompoundValue"
    reference = serialized["value"]["value"]
    scope = dict(serialized["scope"])
    return scope[reference]


def test_official_sdk_fixture_covers_serialized_date_contracts():
    fixture = json.loads(FIXTURE.read_text())
    assert fixture["sdk"] == "1.7.49"
    assert fixture["source_commit"] == "e189e4b89e785019ea5642ea8e80cb644749cd4a"
    expressions = fixture["expressions"]
    assert set(expressions) == {
        "differenceDaysPlural", "differenceLeapYear", "differenceMonth",
        "relativeMonthYear", "relativeWeekYear", "relativeDayYear",
        "relativeDayMonth", "relativeMinuteDay", "relativeSecondMinute",
        "relativeLargerUnit", "relativeTimezone", "fractionYear", "fractionMonth",
        "fractionWeek", "fractionDay", "fractionHour", "fractionMinute", "fractionSecond",
    }
    difference = _final_invocation(expressions["differenceDaysPlural"])
    assert difference["functionName"] == "Date.difference"
    assert difference["arguments"]["unit"] == "days"
    relative = _final_invocation(expressions["relativeTimezone"])
    assert relative["functionName"] == "Date.getRelative"
    assert relative["arguments"]["timeZone"] == "UTC"
    fraction = _final_invocation(expressions["fractionMonth"])
    assert fraction["functionName"] == "Date.getFraction"
    assert fraction["arguments"]["unit"] == "month"
    assert SUPPORTED_DATE_FUNCTIONS == frozenset({"Date.difference", "Date.getRelative", "Date.getFraction"})


def test_every_official_sdk_date_fixture_compiles_through_public_entrypoint():
    fixture = json.loads(FIXTURE.read_text())
    expected = {
        "differenceDaysPlural": 14,
        "differenceLeapYear": 366 / 365.2425,
        "differenceMonth": 31 * 86_400_000 / 2_629_746_000,
        "relativeMonthYear": 1,
        "relativeWeekYear": 52,
        "relativeDayYear": 59,
        "relativeDayMonth": 28,
        "relativeMinuteDay": 435,
        "relativeSecondMinute": 31,
        "relativeLargerUnit": 0,
        "relativeTimezone": 0,
        "fractionYear": (59 * 86_400_000 + (7 * 3600 + 15 * 60 + 31) * 1000 + 240) / (366 * 86_400_000),
        "fractionMonth": (28 * 86_400_000 + (7 * 3600 + 15 * 60 + 31) * 1000 + 240) / (29 * 86_400_000),
        "fractionWeek": (5 * 86_400_000 + (7 * 3600 + 15 * 60 + 31) * 1000 + 240) / (7 * 86_400_000),
        "fractionDay": ((7 * 3600 + 15 * 60 + 31) * 1000 + 240) / 86_400_000,
        "fractionHour": (15 * 60_000 + 31_240) / 3_600_000,
        "fractionMinute": 31_240 / 60_000,
        "fractionSecond": .24,
    }
    assert set(expected) == set(fixture["expressions"])
    for name, expression in fixture["expressions"].items():
        result = compile_expression(expression, [], {}, options=None)
        assert result["kind"] == "value", name
        assert result["value"] == pytest.approx(expected[name]), name
        if name in {"differenceLeapYear", "differenceMonth"}:
            assert any("direct Google numerical parity has not been verified" in warning
                       for warning in result["warnings"]), name
        if name in {"relativeWeekYear", "fractionWeek"}:
            assert any("direct Google boundary parity has not been verified" in warning
                       for warning in result["warnings"]), name
