# Number scalar casts

The pinned `earthengine-api` 1.7.49 signatures expose these scalar methods, each with one required `input` and a `Number` return value:

| Result type | Methods |
| --- | --- |
| unsigned 8-bit integer | `toByte`, `byte`, `toUint8`, `uint8` |
| signed 8-bit integer | `toInt8`, `int8` |
| signed 16-bit integer | `toInt16`, `int16`, `toShort`, `short` |
| unsigned 16-bit integer | `toUint16`, `uint16` |
| signed 32-bit integer | `toInt32`, `int32` |
| unsigned 32-bit integer | `toUint32`, `uint32` |
| signed 64-bit integer | `toInt64`, `int64`, `toLong`, `long` |
| 32-bit float | `toFloat`, `float` |
| 64-bit float | `toDouble`, `double` |

For integer casts, this local evaluator truncates finite static fractions toward zero and clamps out-of-range values to the destination minimum or maximum. Official descriptions confirm loss of fractional precision and their examples document clamping; they do not explicitly state the fractional rounding direction. Relevant references include [toInt8](https://developers.google.com/earth-engine/apidocs/ee-number-toint8), [toInt16](https://developers.google.com/earth-engine/apidocs/ee-number-toint16), [toInt32](https://developers.google.com/earth-engine/apidocs/ee-number-toint32), [toInt64](https://developers.google.com/earth-engine/apidocs/ee-number-toint64), [toUint8](https://developers.google.com/earth-engine/apidocs/ee-number-touint8), [toUint16](https://developers.google.com/earth-engine/apidocs/ee-number-touint16), [toUint32](https://developers.google.com/earth-engine/apidocs/ee-number-touint32), [toByte](https://developers.google.com/earth-engine/apidocs/ee-number-tobyte), [toShort](https://developers.google.com/earth-engine/apidocs/ee-number-toshort), and [toLong](https://developers.google.com/earth-engine/apidocs/ee-number-tolong). The pinned catalogue is `vendor/earthengine-js/algorithms.json`; the Python client lock is `vendor/earthengine-python/upstream-lock.json`.

`toFloat`/`float` perform an IEEE-754 binary32 round-to-nearest conversion and return the rounded value as a Python float. A finite input that overflows binary32 is rejected because the static evaluator only materializes finite Numbers. `toDouble`/`double` retain the finite binary64 value. These width conversions follow the official [toFloat](https://developers.google.com/earth-engine/apidocs/ee-number-tofloat) and [toDouble](https://developers.google.com/earth-engine/apidocs/ee-number-todouble) descriptions; they are not a Google service numerical comparison.

This local static subset accepts only finite Python `int`/`float` inputs and rejects booleans, dynamic EE objects, other types and nonfinite values. Integer inputs and integer cast results are restricted to the repository's exact Float64 integer domain `[-2^53, 2^53]`. Consequently, signed 64-bit cast results outside that local exact domain reject even though the official type range is wider. Narrower integer casts still clamp to their documented bounds. Each call charges one unit against the existing 50,000-step compilation budget before conversion.

The pre-existing `Number.toInt` and `Number.int` paths are unchanged and are not routed through this family; they retain their earlier local `int()` truncation behavior. This intentionally leaves their range handling separate from the newer width-specific methods.

Focused validation uses the actual pinned Python SDK in offline mode to check all 24 emitted method names and input signatures, independent scalar edge expectations, invalid-value rejection, and the shared work limit. It does not establish remote GEE comparison or raster-engine behavior.
