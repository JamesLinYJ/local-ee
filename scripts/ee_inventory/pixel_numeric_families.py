"""Explicit finite scope for native pixel math and static numeric helpers."""


PIXEL_NUMERIC_LIMITS = {}
for _operation in (
    "asin", "acos", "atan", "atan2", "sinh", "cosh", "tanh", "cbrt",
    "signum", "gamma", "digamma", "trigamma", "erf", "erfc", "erfInv", "erfcInv",
):
    PIXEL_NUMERIC_LIMITS["Image." + _operation] = [
        "Actual native Float32 tile math through a closed top-level SPI; ordered x[/y] "
        "input, singleton v output, original band pairing/names, grid/time and masks. "
        "Default untyped source/constant operands are visibly converted to Float32; "
        "precision outside Float32 is not preserved. Explicit Double arithmetic rejects "
        "until toFloat. Binary real operands require the same proven source lineage, "
        "not an implicit nearest-neighbor alignment. Constant subtrees need a real "
        "finite grid; no global constant raster. NaN/nonfinite inputs, invalid real domains, "
        "poles and nonfinite/Float32-overflow outputs become NaN. JVM Math/locked Commons "
        "Math3.6.1 with bounded digamma/trigamma reflection for negative nonpoles; atan2 "
        "uses SDK x,y and JVM atan2(y,x), retaining signed zero. Existing compiler50000/"
        "graph500/grid/key/decoded-cell and67108864 pixel-work limits. Trusted standalone "
        "tile proof is separate from unrun full Spark/service/browser/deployment/Google parity."
    ]

for _operation in (
    "bitCount", "bitwiseNot", "bitwise_not", "bitwiseAnd", "bitwise_and",
    "bitwiseOr", "bitwise_or", "bitwiseXor", "bitwise_xor",
    "leftShift", "left_shift", "rightShift", "right_shift",
):
    PIXEL_NUMERIC_LIMITS["Array." + _operation] = [
        "Finite nonempty static integer Arrays, rank8/cells10000/shared50000 work and1MB "
        "output; exact magnitude<=2^53. AND/OR/XOR require identical shapes and nonnegative "
        "operands; left shift nonnegative and nonoverflowing, signed right shift; counts0..63 "
        "are scalar or same shape. bitCount uses signed64 two's-complement; NOT signed "
        "complement. Results remain exact-domain owned readonly Arrays. Negative binary "
        "width policies, PixelTypes/raster implementation and Google dtype parity unverified."
    ]

for _operation in (
    "bitwise_not", "bitwise_and", "bitwise_or", "bitwise_xor", "left_shift", "right_shift",
):
    PIXEL_NUMERIC_LIMITS["Number." + _operation] = [
        "Pinned alias delegates to the existing audited canonical Number integer operation; "
        "signed64 integral domain, constrained nonnegative binary/left shift, signed right "
        "shift0..63, overflow rejects. No Image/raster algorithm or broader coercion implied."
    ]

for _operation in ("identity", "dotProduct", "pad"):
    PIXEL_NUMERIC_LIMITS["Array." + _operation] = [
        "Actual bounded static identity(size>=0, zero yields0x0), equal-length rank1 dot product, or "
        "trailing pad to at least each requested nonnegative axis length (no truncation). "
        "Finite exact-domain input, rank8/cells10000/shared50000 work/1MB output remain; "
        "integer dot products exact, floating products use rational accumulation and one "
        "Float64 conversion. Omitted/null pad=0, unchanged input and owned outputs. "
        "Explicit PixelTypes, general broadcasting and Google dtype/numeric parity unverified."
    ]

PIXEL_NUMERIC_LIMITS["Number.parse"] = [
    "Finite static ASCII string up to256 chars, decimal/fraction/exponent at radix10 "
    "(omitted/null default), complete signed integers at radix2..36; no prefixes or partial "
    "parse. Exact integer magnitude<=2^53 and finite Float64 output. Preserves negative "
    "zero; extreme underflow returns signed zero by local policy. Work is precharged "
    "before lexing/conversion. Shared50000 work/1MB output; Google formatting/parity unverified."
]
