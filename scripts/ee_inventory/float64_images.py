"""Partial limits for the closed Double scalar raster operation family."""


FLOAT64_IMAGE_LIMITS = {}
for method in (
    "add", "subtract", "multiply", "divide", "pow", "mod", "min", "max", "and", "or",
    "abs", "sqrt", "log", "log10", "exp", "round", "floor", "ceil", "sin", "cos", "tan", "not",
):
    FLOAT64_IMAGE_LIMITS[f"Image.{method}"] = [
        "Existing Float32 path is retained unless a typed Float64 operand requires the "
        "closed native binary64 path. One/two ordered finite source operands, explicit "
        "grid proof before merging, per-used-band mask intersection and metadata/time "
        "preservation. NoData remains NaN; domain or nonfinite arithmetic results mask, "
        "division by zero yields0, mod uses signed remainder and a zero divisor masks. "
        "Round uses local ties toward positive infinity without perturbing large "
        "integral values. Native StrictMath and staged binary64, not Google ULP/dtype "
        "parity. Source-free constants require existing finite grid binding and keep "
        "its +/-2^53 exact-domain limit; nested explicit toFloat boundaries round. "
        "Shared compiler50000/graph500/public1MB and native key/cell/work caps apply. "
        "Fixed-shape array add/subtract/multiply/divide can reuse this scalar path "
        "with whole-array masks; this does not enable arbitrary callbacks, general "
        "Double array/matrix algorithms, trinary "
        "where or other Float32-only scientific operators, or prove full Spark/service acceptance."
    ]

for method in ("clamp", "unitScale", "normalizedDifference", "parseExpression"):
    FLOAT64_IMAGE_LIMITS[f"Image.{method}"] = [
        "Existing scalar lowering can use the closed native Double core when its "
        "operands carry Float64. normalizedDifference keeps negative-input and "
        "zero-denominator masks; an explicit arithmetic expression has its distinct "
        "signed/zero-divisor policy. Existing band naming/property behavior, finite "
        "grid/source proof and all resource limits remain. Arbitrary execution text, "
        "dynamic arrays and full Google same-data/production parity are not established."
    ]
