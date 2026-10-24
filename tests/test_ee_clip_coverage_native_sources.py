"""Portable source contracts for the native geodesic clip-coverage producer."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_sources_and_provider_are_registered_in_the_atomic_adapter_build():
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text(encoding="utf-8")
    for name in (
        "ee_clip_coverage_spec.scala",
        "ee_clip_coverage_geometry.scala",
        "ee_clip_coverage_numeric.scala",
        "ee_clip_coverage_budget.scala",
        "ee_clip_coverage_adapter.scala",
    ):
        assert f'ROOT / "engine/{name}"' in builder
    assert "LocalEeClipCoverageCubeProcessProvider\\n" in builder


def test_wire_and_geometry_keep_float64_geodesic_inputs_and_actual_source_grid():
    spec = (ROOT / "engine/ee_clip_coverage_spec.scala").read_text(encoding="utf-8")
    geometry = (ROOT / "engine/ee_clip_coverage_geometry.scala").read_text(encoding="utf-8")
    assert 'JsonToken.VALUE_NUMBER_FLOAT' in spec
    assert '"great-circle"' in spec and 'maximumLongitude - minimumLongitude < 180.0' in spec
    assert "MaxPositions = 10000" in spec and "MaxPolygons = 1000" in spec
    assert "text.startsWith" in spec and "text.endsWith" in spec
    assert "projectPosition(ring(index), context)" in geometry
    assert "MaxAngularStep = math.toRadians(0.25)" in geometry
    assert "t0 + span * 0.25" in geometry and "t0 + span * 0.5" in geometry
    assert "t0 + span * 0.75" in geometry and "MaxChordDeviationPixels = 1e-6" in geometry
    assert "exact binary64 source-pixel coordinates" in geometry
    assert "lat > -90.0 && lat < 90.0" in geometry
    assert geometry.index("require(lon.isFinite") < geometry.index("epsg match")
    assert "not Norway/Svalbard exceptions" in geometry
    assert "pixel chord tolerance" in geometry
    assert "positiveAreaOrEmpty" in geometry and "Location.INTERIOR" in geometry
    assert "does not define a mathematical degeneracy threshold" in geometry
    assert "meridianLongitude: Option[Double]" in geometry and "arc.equator" in geometry
    assert "if (start.lon == end.lon) Some(start.lon) else None" in geometry


def test_actual_tile_kernel_keeps_independent_weights_and_charges_adapter_before_spark_map():
    numeric = (ROOT / "engine/ee_clip_coverage_numeric.scala").read_text(encoding="utf-8")
    adapter = (ROOT / "engine/ee_clip_coverage_adapter.scala").read_text(encoding="utf-8")
    assert numeric.index("source.getDouble(col, row)") < numeric.index("val tileGeometry =")
    assert "value.isNaN || value.isFinite" in numeric
    assert "PreparedGeometryFactory" in numeric and "prepared.covers(cell)" in numeric
    assert "prepared.intersects(cell)" in numeric and "overlap.getArea" in numeric
    assert "cols == grid.tileCols && rows == grid.tileRows" in numeric
    assert "LocalEeClipCoverageGeometry.positiveAreaOrEmpty" in numeric
    assert "input.source.keys.take(MaxTileKeys + 1).length" in adapter
    assert "MaxDecodedCells = 100000000L" in adapter
    assert "MaxTileCells = 10000000L" in adapter
    assert "local_ee_clip_coverage" in adapter and 'Seq("v")' in adapter
    assert "LocalEeClipCoverageBudget.admit" in adapter
    assert adapter.index("LocalEeClipCoverageBudget.admit") < adapter.index("val output: RDD")
    assert "val geometry = admission.geometry" in adapter
    closure = adapter.split("val output: RDD[(Any, MultibandTile)] = source.map", 1)[1]
    assert "input." not in closure


def test_budget_precharges_projection_then_deduplicates_bounded_closed_cell_boxes():
    budget = (ROOT / "engine/ee_clip_coverage_budget.scala").read_text(encoding="utf-8")
    adapter = (ROOT / "engine/ee_clip_coverage_adapter.scala").read_text(encoding="utf-8")
    assert "MaxCoverageWork = 67108864L" in budget
    assert "MaxBoundaryVisits = 1000000L" in budget
    assert "MaxBoundaryCells = 1000000L" in budget
    assert budget.index("preGeometryWork <= BigInt(MaxCoverageWork)") < budget.index("val geometry = buildGeometry()")
    assert "observedTimeCount >= 1L && observedTimeCount <= keyCount" in budget
    assert "BigInt(tileCells) == BigInt(grid.tileCols) * BigInt(grid.tileRows)" in budget
    assert "BigInt(decodedCells) == BigInt(tileCells) * BigInt(keyCount)" in budget
    assert "MaxGeometryDepth = 64" in budget
    assert budget.index("val nextVisits = BigInt(visits) + bboxVisits") < budget.index("while (row <= rowRange.last)")
    assert "reserveTraceWork(bboxVisits)" in budget
    assert "math.ceil(clippedMinimum) - 1.0" in budget
    assert "math.floor(clippedMaximum)" in budget
    assert "cells.contains(cell)" in budget and "cells.add(cell)" in budget
    assert "polygon.getExteriorRing" in budget and "polygon.getInteriorRingN(hole)" in budget
    assert "case multi: MultiPolygon" in budget and "case collection: GeometryCollection" in budget
    assert "conservativeCandidates = BigInt(traced.uniqueCells)" in budget
    assert ".min(plan.boundaryCellUpperBoundPerTile)" in budget
    assert "input.times.size.toLong.max(1L)" in adapter
    assert "Math.multiplyExact(tileCells, keyCount)" in adapter
    assert "(conservativeCandidates * observations).min(BigInt(decodedCells))" in budget


def test_kernel_probe_uses_real_synthetic_tiles_and_actual_sample_rows_not_expected_row_injection():
    probe = (ROOT / "tests/fixtures/ee-clip-coverage-kernel-probe.scala").read_text(encoding="utf-8")
    assert "local.ee.reduce.EeClipCoverageKernelProbe" in probe
    assert "LocalEeClipCoverageNumeric.applyTile" in probe
    assert "LocalEeMaskWeightsNumeric.applyTile" in probe
    assert "LocalEeImageSampleKernel.sampleTileIterator" in probe
    assert "source_footprint_default_sample_drop_nulls_true" in probe
    assert "source_footprint_unary_absolute_sample_drop_nulls_true" in probe
    assert "source_footprint_scalar_multiply_2_sample_drop_nulls_true" in probe
    assert "explicitFalse.isArray" in probe and "explicitFalse.get(\"rows\")" not in probe
    assert "explicit_roi_clip_sample_drop_nulls_false" in probe
    assert "independent_numeric_reference_controls" in probe
    assert "EPSG:32647" in probe and "synthetic-kernel-grid" in probe
    assert "LocalEeClipCoverageCubeProcessProvider" in probe
    assert "positive_coverage_cells" in probe and "partial_coverage_cells" in probe
    assert "actual_native_fraction" in probe and "separate_reference_fraction" in probe
    assert "checkPoleRoundingRejected" in probe
    assert 'coverageCase("meridian_touch_zero"' in probe
    assert 'coverageCase("meridian_near_touch_positive_2^-52"' in probe
    assert "LocalEeClipCoverageBudget.admit" in probe
    assert "default_256_admission_probe" in probe and "256L, 256L, 256, 256" in probe


def test_native_probe_receipt_validates_each_sample_against_its_actual_tile_cell():
    runner = (ROOT / "scripts/probe_clip_coverage_native.py").read_text(encoding="utf-8")
    for route in (
        "explicit_roi_clip_sample_drop_nulls_false",
        "explicit_roi_clip_sample_drop_nulls_true",
        "explicit_roi_mask_getter_sample_drop_nulls_false",
        "source_footprint_default_sample_drop_nulls_true",
        "source_footprint_unary_absolute_sample_drop_nulls_true",
        "source_footprint_scalar_multiply_2_sample_drop_nulls_true",
    ):
        assert f'"{route}"' in runner
    assert "nonpolar_intermediate_rejected" in runner
    assert "route_tiles[route][row[\"row\"] * 8 + row[\"col\"]]" in runner
    assert "expected_explicit_true" in runner and "expected_cells" in runner
    assert '"meridian_touch_zero"' in runner
    assert '"meridian_near_touch_positive_2^-52"' in runner
    assert 'DEFAULT_OUTPUT = ROOT / "audit/gee-python-wave70/native/tile-receipt-v4.json"' in runner
    assert '"default_256_admission_probe"' in runner
    assert "1_000_000" in runner and 'admission.get("max_work") != 67108864' in runner
