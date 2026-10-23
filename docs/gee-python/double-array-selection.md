# Double raster-array sorting and selection

This finite workflow uses the pinned Python and JavaScript Earth Engine clients
with the same local `reshape-scene` fixture. It exercises a Double keyed sort
that reorders full slices of a 2×2 payload, first-maximum coordinates, and a
trimmed mean. The fixture includes adjacent binary64 values from
`nextafter(1, +∞)`, a tied maximum, a missing key, and a missing payload.

The backend compares actual declared Double values and copies selected payloads
through a closed native ternary operation. This avoids Float32 callback
quantization and ordinary-mask behavior that leaves payload tiles unchanged
when the condition key is absent. The existing bounded cube merge unions
observed keys and fills absent input bands with NoData; all-empty inputs still
fail closed. Mixed spatial/temporal dimensions are explicitly rejected.

```python
payload = image.select(["blue", "green", "red", "nir"]).toArray()
payload = payload.arrayReshape(ee.Image.constant(ee.Array([2, 2])), 2).toDouble()
keys = image.select(["b5", "b4"]).toArray()
keys = keys.arrayReshape(ee.Image.constant(ee.Array([1, 2])), 2).toDouble()
ordered = payload.arraySort(keys)
maximum_coordinates = score_grid.toDouble().arrayArgmax()
```

The local sort is stable for equal keys and moves each complete array slice with
its key through exact conditional selection; it does not calculate new payload
values. Each fixed array must have one uniform explicit top-level `toFloat()` or
`toDouble()` cast. The value and key arrays can use different casts, while
`Image.arrayArgmax` also requires one uniform cast on its input. Casting the
adjacent keys through Float32 makes them equal and can therefore change the
permutation; converting them back to Double does not restore the lost bit.
`Image.arrayArgmax` returns row-major coordinates as local Float32 integer
values. The companion `arraySlice` / `arrayReduce` example selects the two
middle sorted values before taking their mean.

Official references: [Image.arraySort](https://developers.google.com/earth-engine/apidocs/ee-image-arraysort)
and [Image.arrayArgmax](https://developers.google.com/earth-engine/apidocs/ee-image-arrayargmax).

The workflow test evaluates the compiled sample graph and compares it with an
independent NumPy stable-index reference. That evaluator is test evidence only;
it does not establish native or Spark execution or Google numerical parity.
The workflow also does not establish support for arbitrary dynamic array shapes
or guaranteed compilation at the 64-cell maximum. Existing 64-cell,
50,000-work, and 500-graph-node limits remain in force.

## Double conditional replacement

```python
input_value = image.select("nir").toDouble()
replacement = image.select("red").toDouble()
result = input_value.where(image.select("blue").gt(0), replacement)
```

For Double payloads, `where` uses a separate native ternary policy: missing test
or replacement keeps the original, while missing original remains NoData.
Generic internal selection instead masks a missing condition or selected
payload and ignores an unselected missing payload. Signed zeros are copied
without arithmetic. Both operations reject valid source Infinity, including
unselected input bands, through the existing finite native admission gate.
Literal wire constants can be any finite binary64 value; raw integers remain
within ±2^53. Existing standalone grid-constant materialization limits are
unchanged. Float32 payloads retain their established callback path.

Distinct observations require fresh explicit common-grid evidence. For one
item, absent optional projection fields retain the existing source contract;
explicit conflicting asset CRS, affine basis or fractional-pixel origins reject.
Native tile controls and source review of the pinned upstream key join are
reported separately from full Spark tasks, physical exports or Google tests.
See the [official where semantics](https://developers.google.com/earth-engine/apidocs/ee-image-where).
