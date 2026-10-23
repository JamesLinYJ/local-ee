# Date calendar algorithms

This note covers the finite local implementation of `Date.parse`, `Date.update`,
`Date.getRange`, and `Date.unitRatio` for the pinned `earthengine-api` 1.7.49.
Official signatures are retained from the pinned algorithm inventory. These
static handlers do not add support for computed/dynamic dates or external time
zone databases.

The public signatures describe `Date.parse(format, date, timeZone)`,
`Date.update(date, year, month, day, hour, minute, second, timeZone)`,
`Date.getRange(date, unit, timeZone)`, and
`Date.unitRatio(numerator, denominator)`. The returned Date value is epoch
milliseconds; a DateRange is the existing half-open `(start_ms, end_ms)` value.
Google's docs describe the DateRange start as inclusive and end as exclusive.
See the [Earth Engine Date API](https://developers.google.com/earth-engine/apidocs/ee-date-parse),
[Date.update](https://developers.google.com/earth-engine/apidocs/ee-date-update),
[Date.getRange](https://developers.google.com/earth-engine/apidocs/ee-date-getrange),
and [Date.unitRatio](https://developers.google.com/earth-engine/apidocs/ee-date-unitratio).

All four handlers accept only UTC. A non-UTC `timeZone` argument, a non-zero
offset token, or a non-UTC zone ID is rejected explicitly. Dates must fit the
Python proleptic Gregorian range, years 1 through 9999; getRange can still
return the exclusive start of year 10000 as milliseconds for a range ending at
the supported upper endpoint. Date.update and Date.getRange reject
fractional-millisecond inputs because the existing calendar handlers do not
claim sub-millisecond parity.

`Date.getRange` uses calendar boundaries for year, month, day, hour, minute,
and second. A week starts Monday and ends the following Monday (ISO week
boundaries). The Google API lists week as a valid unit but does not state its
boundary convention, so the local week rule emits a warning and has no direct
Google boundary comparison. Month and year lengths are actual Gregorian
calendar lengths; range ends are computed as milliseconds so the end of year
9999 remains representable.

`Date.update` checks calendar fields instead of normalizing out-of-range
values. Year is 1..9999, month 1..12, day must exist in the selected month,
hour is 0..23, minute is 0..59, and second is in [0, 60). Fractional seconds
must resolve exactly to milliseconds. If changing only year or month makes the
inherited day invalid, the local rule clamps to the last day of the new month
and emits a warning; an explicitly supplied invalid day fails. A supplied
second sets both the integer second and millisecond part; when it is omitted,
the original second and subsecond fields are preserved. The public docs say
that components are set but do not specify invalid-day resolution, so the
clamping policy is local and has not been compared against Google.

`Date.parse` supports the numeric and zone tokens currently present in the
local `Date.format` implementation: `yyyy`, `YYYY`, `yy`, `M`/`MM`, `d`/`dd`,
`D`/`DDD`, `H`/`HH`, `m`/`mm`, `s`/`ss`, `SSS`, and UTC-only `Z`, `ZZ`, `ZZZ`.
Quoted literals and doubled apostrophes follow the same finite quote grammar
as Date.format. Parsing is limited to 200 characters for both pattern and
input. Variable numeric fields are bounded to four year digits, two month/day/
time digits, and three ordinal-day digits; `yy` is exactly two digits and
`SSS` exactly three. Adjacent numeric fields require tokens with a fixed width
(`yyyyMMdd` is supported; ambiguous adjacency such as `yyyyMdd` is rejected).
These caps bound regex work even when patterns and inputs contain long runs of
digit literals.
Text month names and unsupported letters fail instead of being treated as
literals. Calendar-invalid dates (including non-leap February 29), invalid
ordinal days, seconds above 59, and years outside 1..9999 fail explicitly.

The parser fills an omitted month/day with January 1; a month/day without a
year uses 2000, while a time-only pattern uses 1970-01-01. Joda's parser bucket
uses the default year for month/day-only input, while time-only parsing retains
its initial epoch date. The `yy` token uses a fixed 1950..2049
window to keep local results reproducible; it emits a warning because Joda's
default two-digit pivot is date-dependent. `YYYY` is interpreted as a
calendar-year alias to match this repository's existing Date.format token
table; this does not implement Joda week-year/year-of-era edge cases. The
[Joda pattern reference](https://www.joda.org/joda-time/apidocs/org/joda/time/format/DateTimeFormat.html)
and [Joda DateTimeParserBucket source](https://raw.githubusercontent.com/JodaOrg/joda-time/main/src/main/java/org/joda/time/format/DateTimeParserBucket.java)
document the wider parser behavior; locale text, week-year, and other tokens
are outside this handler's supported subset.

`Date.unitRatio` returns the numerator unit length divided by the denominator
unit length. Week through second use exact UTC durations. Year and month use
the ISO chronology average-duration constants, 365.2425 and 30.436875 days,
respectively, and emit a warning when the ratio depends on those units. Joda
defines `getUnitMillis()` for imprecise fields as a suitable average, but the
Earth Engine method docs say only that the function returns a ratio of unit
lengths; they do not spell out a year/month convention. The values match the
constants in Joda's Gregorian chronology implementation, but this does not
establish that Earth Engine uses that implementation. Therefore these ratios
are a documented local policy, not a Google parity claim. See the
[Earth Engine unitRatio reference](https://developers.google.com/earth-engine/apidocs/ee-date-unitratio),
[Joda DurationField](https://www.joda.org/joda-time/apidocs/org/joda/time/DurationField.html),
and [Joda GregorianChronology source](https://raw.githubusercontent.com/JodaOrg/joda-time/main/src/main/java/org/joda/time/chrono/GregorianChronology.java).

The focused tests use independent `datetime` expectations, invalid and limit
cases, direct handler calls, and expressions serialized by the pinned Python
SDK before compiling through the public expression entry point. They do not
establish Google numerical or time-zone parity.
