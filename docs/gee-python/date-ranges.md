# DateRange

The local compiler evaluates a bounded, static subset of the pinned Earth Engine
`DateRange` API. Finite ranges keep the existing `(start_ms, end_ms)` tuple
representation and use half-open `[start, end)` millisecond boundaries. The
constructor accepts the existing local `Date` inputs, accepts UTC only, and
uses `start + 1` millisecond when `end` is omitted. Numeric endpoints must be
finite and lie within ±2^53 milliseconds; fractional millisecond endpoints are
preserved. The omitted end must be representably later than the start and stay
inside that numeric domain, so an input at the upper bound is rejected rather
than silently producing a zero-width default range.

The supported methods compute local interval algebra for `start`, `end`,
`contains`, `intersection`, `intersects`, `isEmpty`, `isUnbounded`, and `union`.
`contains(Date)` tests the instant against the inclusive start and exclusive
end. The pinned Python SDK promotes Date or numeric operands to a one-millisecond
DateRange before `intersection`, `intersects`, and `union`; the local compiler
evaluates that serialized range through the same constructor rule. A finite
union returns the smallest contiguous interval covering both operands,
including when they are disjoint.

Empty ranges satisfy `start >= end`. The local set policy treats empty ranges
as having no contained dates, as not intersecting any range, and as contained
by every range. Intersection with no common dates returns a zero-width empty
tuple anchored at the later start. Union with an empty range returns the other
operand. The pinned Python wrapper documents an exception for an empty
intersection; the local compiler returns the explicit empty interval so callers
can inspect `isEmpty()`. These boundary choices make the finite evaluator
deterministic; Google empty-range parity remains unverified.

`DateRange.unbounded()` is represented internally by a typed universal-range
marker, not by an infinite JSON number or a guessed endpoint date. Its
`contains`, `intersection`, `intersects`, `isEmpty`, `isUnbounded`, and `union`
operations use universal-set semantics. `start()` and `end()` on this marker
are rejected because no exact finite endpoint is established. A standalone
unbounded range cannot be emitted as public JSON, and date-filter compilation
continues to require a finite interval.

All constructor and method inputs are validated before algebra is evaluated.
Date strings are limited to 200 characters, and each operation charges the
shared 50,000-step compiler budget before producing a result. Unsupported
dynamic endpoints, non-UTC zones, malformed range values, and extra parameters
fail explicitly.

The pinned API signatures and Python wrapper are the compatibility references:
[Earth Engine DateRange](https://developers.google.com/earth-engine/apidocs/ee-daterange),
[DateRange.unbounded](https://developers.google.com/earth-engine/apidocs/ee-daterange-unbounded),
and `vendor/earthengine-python` at the locked `earthengine-api` 1.7.49 revision.
SDK construction and local compilation tests establish syntax and this finite
local behavior. They do not establish Google numerical or empty-range parity,
date-filter support for unbounded ranges, or endpoint behavior for an
unbounded range.

The shared `Date` constructor now validates before conversion too: wrapping an
out-of-range integer in `ee.Date(...)` cannot conceal precision loss before a
DateRange method consumes it. Finite fractional millisecond input is retained.
