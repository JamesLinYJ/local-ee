"""Compare static QR, LU and SVD solutions on a synthetic spectral mixture."""

SYNTHETIC_VERSION = "local-ee-synthetic-matrix-unmixing/v1"


def build_unmixing(ee, mixing_values, observation_values):
    """Return abundance estimates, reconstructions and factorization checks."""
    mixing = ee.Array(mixing_values)
    observations = ee.Array(observation_values)

    qr_parts = ee.Dictionary(mixing.matrixQRDecomposition())
    q = ee.Array(qr_parts.get("Q"))
    r = ee.Array(qr_parts.get("R"))
    qr_abundances = r.matrixSolve(q.matrixTranspose().matrixMultiply(observations))

    lu_parts = ee.Dictionary(mixing.matrixLUDecomposition())
    p = ee.Array(lu_parts.get("P"))
    lower = ee.Array(lu_parts.get("L"))
    upper = ee.Array(lu_parts.get("U"))
    permuted_observations = p.matrixMultiply(observations)
    intermediate = lower.matrixSolve(permuted_observations)
    lu_abundances = upper.matrixSolve(intermediate)

    svd_parts = ee.Dictionary(mixing.matrixSingularValueDecomposition())
    left_vectors = ee.Array(svd_parts.get("U"))
    singular_matrix = ee.Array(svd_parts.get("S"))
    right_vectors = ee.Array(svd_parts.get("V"))
    svd_inverse = right_vectors.matrixMultiply(
        singular_matrix.matrixInverse()
    ).matrixMultiply(left_vectors.matrixTranspose())
    svd_abundances = svd_inverse.matrixMultiply(observations)

    return ee.Dictionary({
        "observations": observations,
        "qr": ee.Dictionary({
            "Q": q,
            "R": r,
            "factorization_residual": mixing.subtract(q.matrixMultiply(r)),
            "abundances": qr_abundances,
            "reconstruction": mixing.matrixMultiply(qr_abundances),
            "noisy_sample_component_0": qr_abundances.get([0, 3]),
        }),
        "lu": ee.Dictionary({
            "P": p,
            "L": lower,
            "U": upper,
            "factorization_residual": p.matrixMultiply(mixing).subtract(
                lower.matrixMultiply(upper)
            ),
            "abundances": lu_abundances,
            "reconstruction": mixing.matrixMultiply(lu_abundances),
        }),
        "svd": ee.Dictionary({
            "U": left_vectors,
            "S": singular_matrix,
            "V": right_vectors,
            "factorization_residual": mixing.subtract(
                left_vectors.matrixMultiply(singular_matrix).matrixMultiply(
                    right_vectors.matrixTranspose()
                )
            ),
            "abundances": svd_abundances,
            "reconstruction": mixing.matrixMultiply(svd_abundances),
        }),
    })


def main():
    import json
    from pathlib import Path
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression

    data = json.loads((root / "tests/fixtures/ee-matrix-unmixing-v1.json").read_text())
    if data["schema"] != SYNTHETIC_VERSION:
        raise ValueError("Unexpected synthetic matrix fixture version")
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    expression = build_unmixing(ee, data["mixing_matrix"], data["observations"])
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    result = compile_expression(encoded, [], {})["value"]
    print(json.dumps({"fixture": SYNTHETIC_VERSION, "result": result}, indent=2))


if __name__ == "__main__":
    main()
