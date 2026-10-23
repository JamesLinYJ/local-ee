"""Per-pixel numerical invariants for offline QR/SVD raster compositions."""
import numpy as np

from ee_matrix_orthogonal_workflow_helpers import (
    ITEM_ID, OUTPUT_BANDS, assert_svd, decoded_values, example_module,
    local_fixture, matrix_output, matrices_for_pixel, python_results,
    record_evidence,
)


def test_qr_svd_factors_reconstruct_rectangular_pixels_and_compose_workflows():
    local = local_fixture()
    compiled, _expressions, attempts = python_results(local)
    assert attempts == 0
    values = decoded_values(compiled, local)
    tall_matrices = matrices_for_pixel(local)
    wide_matrices = matrices_for_pixel(local, wide=True)
    rhs = np.stack([local["arrays"][ITEM_ID][f"b{index}"] for index in range(3)], axis=1)
    masked = 5
    qr_errors = []
    svd_errors = []
    for pixel, matrix in enumerate(tall_matrices):
        if pixel == masked:
            for name in OUTPUT_BANDS:
                assert np.isnan(values[name][:, pixel]).all(), name
            continue

        q = matrix_output(values, "qr_tall_q", pixel, (3, 2))
        r = matrix_output(values, "qr_tall_r", pixel, (2, 2))
        assert np.isfinite(q).all() and np.isfinite(r).all()
        np.testing.assert_allclose(q.T @ q, np.eye(2), rtol=0, atol=3e-12)
        np.testing.assert_allclose(np.tril(r, -1), 0, rtol=0, atol=2e-12)
        reconstruction = q @ r
        np.testing.assert_allclose(reconstruction, matrix, rtol=2e-10, atol=2e-10)
        qr_errors.extend(np.abs(reconstruction - matrix).ravel().tolist())
        np.testing.assert_allclose(
            matrix_output(values, "qr_tall_reconstruction", pixel, (3, 2)),
            reconstruction, rtol=2e-10, atol=2e-10,
        )
        projection = q @ q.T @ rhs[pixel]
        np.testing.assert_allclose(
            matrix_output(values, "qr_tall_projection", pixel, (3, 1))[:, 0],
            projection, rtol=2e-10, atol=2e-10,
        )

        coefficients = matrix_output(values, "qr_tall_least_squares", pixel, (2, 1))[:, 0]
        fit = matrix @ coefficients
        np.testing.assert_allclose(
            matrix_output(values, "qr_tall_fit", pixel, (3, 1))[:, 0],
            fit, rtol=2e-9, atol=2e-9,
        )
        if np.linalg.matrix_rank(matrix) == 2:
            reference = np.linalg.lstsq(matrix, rhs[pixel], rcond=None)[0]
            np.testing.assert_allclose(coefficients, reference, rtol=2e-8, atol=2e-8)
            np.testing.assert_allclose(q.T @ (rhs[pixel] - fit), 0, atol=2e-8)

        spectrum = assert_svd(values, "tall", matrix, pixel, (3, 2), (2, 2))
        u = matrix_output(values, "svd_tall_u", pixel, (3, 2))
        singular = matrix_output(values, "svd_tall_s", pixel, (2, 2))
        v = matrix_output(values, "svd_tall_v", pixel, (2, 2))
        reconstructed = u @ singular @ v.T
        np.testing.assert_allclose(reconstructed, matrix, rtol=2e-10, atol=2e-10)
        np.testing.assert_allclose(
            matrix_output(values, "svd_tall_reconstruction", pixel, matrix.shape),
            matrix, rtol=2e-10, atol=2e-10,
        )
        rank2 = u[:, :2] @ singular[:2, :2] @ v[:, :2].T
        np.testing.assert_allclose(rank2, reconstructed, rtol=2e-12, atol=2e-12)
        np.testing.assert_allclose(
            matrix_output(values, "svd_tall_rank2", pixel, matrix.shape),
            rank2, rtol=2e-10, atol=2e-10,
        )
        svd_errors.extend(np.abs(reconstructed - matrix).ravel().tolist())
        if pixel == 3:
            np.testing.assert_allclose(spectrum, [1.0, 1.0], rtol=0, atol=2e-14)
        if pixel == 2:
            np.testing.assert_array_equal(spectrum, [0.0, 0.0])

        augmented = np.column_stack((matrix, rhs[pixel]))
        three_u = matrix_output(values, "svd_truncation_u", pixel, (3, 3))
        three_s = matrix_output(values, "svd_truncation_s", pixel, (3, 3))
        three_v = matrix_output(values, "svd_truncation_v", pixel, (3, 3))
        assert np.isfinite(three_u).all() and np.isfinite(three_s).all()
        assert np.isfinite(three_v).all()
        np.testing.assert_allclose(three_u.T @ three_u, np.eye(3), rtol=0, atol=4e-12)
        np.testing.assert_allclose(three_v.T @ three_v, np.eye(3), rtol=0, atol=4e-12)
        three_spectrum = np.diag(three_s)
        np.testing.assert_allclose(three_s, np.diag(three_spectrum), rtol=0, atol=2e-14)
        assert three_spectrum[0] >= three_spectrum[1] >= three_spectrum[2] >= 0.0
        three_reconstruction = three_u @ three_s @ three_v.T
        np.testing.assert_allclose(
            three_reconstruction, augmented, rtol=2e-10, atol=2e-10,
        )
        svd_errors.extend(np.abs(three_reconstruction - augmented).ravel().tolist())

        square = matrix[:2, :]
        square_u = matrix_output(values, "svd_square_u", pixel, (2, 2))
        square_s = matrix_output(values, "svd_square_s", pixel, (2, 2))
        square_v = matrix_output(values, "svd_square_v", pixel, (2, 2))
        square_spectrum = np.diag(square_s)
        np.testing.assert_allclose(square_u.T @ square_u, np.eye(2), atol=3e-12)
        np.testing.assert_allclose(square_v.T @ square_v, np.eye(2), atol=3e-12)
        np.testing.assert_allclose(square_s, np.diag(square_spectrum), atol=2e-14)
        assert square_spectrum[0] >= square_spectrum[1] >= 0.0
        square_reconstruction = square_u @ square_s @ square_v.T
        np.testing.assert_allclose(square_reconstruction, square, rtol=2e-10, atol=2e-10)
        svd_errors.extend(np.abs(square_reconstruction - square).ravel().tolist())
        np.testing.assert_allclose(
            matrix_output(values, "svd_square_reconstruction", pixel, (2, 2)),
            square_reconstruction, rtol=2e-10, atol=2e-10,
        )
        square_rank1 = square_u[:, :1] @ square_s[:1, :1] @ square_v[:, :1].T
        np.testing.assert_allclose(
            matrix_output(values, "svd_square_rank1", pixel, (2, 2)),
            square_rank1, rtol=2e-10, atol=2e-10,
        )
        np.testing.assert_allclose(
            matrix_output(values, "svd_square_rank2", pixel, (2, 2)),
            square_reconstruction, rtol=2e-10, atol=2e-10,
        )
        if pixel == 3:
            np.testing.assert_allclose(square_spectrum, [1.0, 1.0], atol=2e-14)
        if pixel == 2:
            np.testing.assert_array_equal(square_spectrum, [0.0, 0.0])

    for pixel, matrix in enumerate(wide_matrices):
        if pixel == masked:
            for name in (
                "qr_wide_q", "qr_wide_r", "qr_wide_reconstruction", "svd_wide_u",
                "svd_wide_s", "svd_wide_v", "svd_wide_rank1",
                "svd_wide_reconstruction", "svd_wide_rank2",
            ):
                assert np.isnan(values[name][:, pixel]).all(), name
            continue
        q = matrix_output(values, "qr_wide_q", pixel, (2, 2))
        r = matrix_output(values, "qr_wide_r", pixel, (2, 3))
        np.testing.assert_allclose(q.T @ q, np.eye(2), rtol=0, atol=3e-12)
        np.testing.assert_allclose(np.tril(r[:, :2], -1), 0, rtol=0, atol=2e-12)
        np.testing.assert_allclose(q @ r, matrix, rtol=2e-10, atol=2e-10)
        qr_errors.extend(np.abs(q @ r - matrix).ravel().tolist())
        np.testing.assert_allclose(
            matrix_output(values, "qr_wide_reconstruction", pixel, (2, 3)),
            q @ r, rtol=2e-10, atol=2e-10,
        )
        assert_svd(values, "wide", matrix, pixel, (2, 2), (3, 2))
        wide_u = matrix_output(values, "svd_wide_u", pixel, (2, 2))
        wide_s = matrix_output(values, "svd_wide_s", pixel, (2, 2))
        wide_v = matrix_output(values, "svd_wide_v", pixel, (3, 2))
        wide_reconstruction = wide_u @ wide_s @ wide_v.T
        svd_errors.extend(np.abs(wide_reconstruction - matrix).ravel().tolist())
        np.testing.assert_allclose(
            matrix_output(values, "svd_wide_reconstruction", pixel, matrix.shape),
            matrix, rtol=2e-10, atol=2e-10,
        )
        np.testing.assert_allclose(
            matrix_output(values, "svd_wide_rank2", pixel, matrix.shape),
            matrix, rtol=2e-10, atol=2e-10,
        )

    assert not np.allclose(
        values["svd_tall_rank1"][:, 0], tall_matrices[0].reshape(-1),
    )
    stage = matrices_for_pixel(local, float32_then_double=True)
    np.testing.assert_array_equal(stage[6, 0, 0], np.float64(16_777_216.0))
    assert stage[6, 0, 0] != tall_matrices[6, 0, 0]
    np.testing.assert_allclose(
        values["qr_float32_then_double_reconstruction"][:, 6].reshape(3, 2),
        stage[6], rtol=2e-10, atol=2e-10,
    )
    for pixel, matrix in enumerate(stage):
        actual = values["svd_float32_then_double_reconstruction"][:, pixel]
        if pixel == masked:
            assert np.isnan(actual).all()
        else:
            np.testing.assert_allclose(actual.reshape(3, 2), matrix, rtol=2e-10, atol=2e-10)
            svd_errors.extend(np.abs(actual.reshape(3, 2) - matrix).ravel().tolist())

    record_evidence("numeric-invariants", {
        "fixture": example_module().SYNTHETIC_VERSION,
        "pixels": len(tall_matrices),
        "valid_matrix_pixels": len(tall_matrices) - 1,
        "compiled_outputs": len(OUTPUT_BANDS),
        "masked_matrix_pixels": [masked],
        "rank_deficient_pixels": [1, 2, 4, 10],
        "repeated_singular_value_pixel": 3,
        "zero_matrix_pixel": 2,
        "float32_then_double_rounding": "16777217 becomes 16777216 before factorization",
        "maximum_qr_reconstruction_error": float(max(qr_errors, default=0.0)),
        "maximum_svd_reconstruction_error": float(max(svd_errors, default=0.0)),
        "svd_full_and_rank2_reconstruction_outputs": [
            "svd_tall_reconstruction", "svd_tall_rank2",
            "svd_wide_reconstruction", "svd_wide_rank2",
            "svd_float32_then_double_reconstruction",
        ],
        "rectangular_svd_reconstruction_cells_checked": 5 * 6 * (len(tall_matrices) - 1),
        "three_value_svd_factors": "finite orthogonal U/V and ordered nonnegative S; 3x3 reconstruction checked",
        "three_value_svd_factor_and_reconstruction_cells_checked": 4 * 9 * (len(tall_matrices) - 1),
        "factor_signs_and_repeated_space_bases": "not compared across numerical libraries",
        "scope": "independent synthetic graph evaluator and numerical invariants; no Google/Spark execution",
    })
