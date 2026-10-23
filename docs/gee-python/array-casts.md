# Static Array dtype casts

Static `ee.Array` values support the pinned element-wise integer and floating
casts below. Camel-case `to...` operations and their SDK aliases are distinct
serialized algorithm names; both spellings are accepted.

| Target type | SDK methods | Local dtype |
| --- | --- | --- |
| unsigned 8-bit | `toByte`, `toUint8`, `byte`, `uint8` | `uint8` |
| signed 8-bit | `toInt8`, `int8` | `int8` |
| signed 16-bit | `toInt16`, `toShort`, `int16`, `short` | `int16` |
| signed 32-bit | `toInt`, `toInt32`, `int`, `int32` | `int32` |
| signed 64-bit | `toInt64`, `toLong`, `int64`, `long` | `int64` |
| unsigned 16-bit | `toUint16`, `uint16` | `uint16` |
| unsigned 32-bit | `toUint32`, `uint32` | `uint32` |
| 32-bit float | `toFloat`, `float` | `float32` |
| 64-bit float | `toDouble`, `double` | `float64` |

The official Array `byte()` reference shows rounding and `[0, 255]` clamping.
The local implementation extends that round-and-clamp policy to the other
integer dtypes, based on their matching element-wise cast descriptions and the
official Number cast references for precision loss and range clamping. The
rounding direction for other dtypes, including negative half ties toward
positive infinity, is an explicit local inference. No live Google numerical
comparison has been run for those cases.
See [Array.byte](https://developers.google.com/earth-engine/apidocs/ee-array-byte),
[Array.toInt8](https://developers.google.com/earth-engine/apidocs/ee-array-toint8),
[Array.toFloat](https://developers.google.com/earth-engine/apidocs/ee-array-tofloat),
and [Number.toInt](https://developers.google.com/earth-engine/apidocs/ee-number-toint).

The implementation accepts finite static numeric arrays only. It rejects
booleans, dynamic values, arrays above rank 8 or 10,000 cells, integer inputs
outside the existing exact Float64 domain, and integer results outside that
same exact domain. Float32 overflow is rejected instead of producing an
infinite value. Rank-0 and already typed empty arrays retain their shapes;
ordinary empty Array construction still requires an explicit PixelType, which
remains unsupported. Every cast precharges the shared 50,000-step Array work
budget and returns an owned, read-only array.
