"""Explicit partial policies for the bounded raster integer implementation."""


INTEGER_IMAGE_LIMITS = {}
for name in (
    "byte", "toByte", "uint8", "toUint8", "int8", "toInt8",
    "short", "toShort", "int16", "toInt16", "uint16", "toUint16",
    "int", "toInt", "int32", "toInt32", "uint32", "toUint32",
    "long", "toLong", "int64", "toInt64",
):
    INTEGER_IMAGE_LIMITS[f"Image.{name}"] = [
        "Finite scalar Image bands only. Local casts clamp and truncate toward zero; "
        "int64 is restricted to +/-2^53, not full signed64 storage. Physical output is "
        "Float64 with NaN NoData to preserve valid dtype minima. Names, masks, metadata "
        "and source grid are retained; generic callback arithmetic requires explicit "
        "toFloat. Finite constant-only results need an existing local destination grid. "
        "Shared compiler/graph/output and native key/cell/work budgets apply. "
        "Google rounding, integer dtype propagation and full Spark/service parity are unverified."
    ]
for name in (
    "bitwiseAnd", "bitwise_and", "bitwiseOr", "bitwise_or", "bitwiseXor", "bitwise_xor",
    "bitwiseNot", "bitwise_not", "leftShift", "left_shift", "rightShift", "right_shift", "bitCount",
):
    INTEGER_IMAGE_LIMITS[f"Image.{name}"] = [
        "Actual finite integral raster values and results within +/-2^53; signed64 "
        "two's complement, bitCount64, signed right shift and exact nonwrapping left "
        "shift with counts0..63. Illegal constants reject even on all-masked images. "
        "One-band broadcast or natural-order equal-band pairing, independent mask "
        "intersection and proven common finite grid precede native execution. Output "
        "is Float64 v, renamed by compiler; use exact predicates or explicit toFloat "
        "before generic callback arithmetic. Shared budgets apply; Google dtype, "
        "overflow and distributed execution parity remain unverified."
    ]
for name in ("eq", "neq", "lt", "lte", "gt", "gte"):
    INTEGER_IMAGE_LIMITS[f"Image.{name}"] = [
        "Existing Float32 path retained. Explicit Float64 operands and local integer "
        "outputs use a native finite binary64 comparison, preserving subnormals/high "
        "bits and -0==+0, with mask intersection and numeric0/1 output. Distinct real "
        "raster operands require common-grid evidence. General Float64 arithmetic "
        "and Google same-data parity remain unverified."
    ]
