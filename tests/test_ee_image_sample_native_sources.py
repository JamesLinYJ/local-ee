"""Source contracts for the bounded native Image.sample adapter."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_image_sample_sources_and_provider_are_in_the_atomic_adapter_build():
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text()
    for name in (
        "ee_image_sample_options.scala",
        "ee_image_sample_kernel.scala",
        "ee_image_sample_adapter.scala",
    ):
        assert f'ROOT / "engine/{name}"' in builder
    assert "local.ee.image.sample.LocalEeImageSampleCubeProcessProvider\\n" in builder
    assert 'os.replace(staged_jar, output)' in builder and '"sources"' in builder


def test_image_sampler_uses_finite_metadata_keys_and_nullable_real_tiles():
    adapter = (ROOT / "engine/ee_image_sample_adapter.scala").read_text()
    kernel = (ROOT / "engine/ee_image_sample_kernel.scala").read_text()
    assert 'id = "local_ee_image_sample"' in adapter
    assert 'arguments.size() == 2' in adapter and 'containsKey("regions")' in adapter
    assert 'containsKey("options")' in adapter
    assert "metadata.bounds.getOrElse" in adapter
    assert "metadata.tileBounds" in adapter
    assert "sourceMinKey: SpatialKey, sourceMaxKey: SpatialKey" in adapter
    assert "finiteMinKey: SpatialKey, finiteMaxKey: SpatialKey" in adapter
    assert "feature, grid, input.finiteMinKey, input.finiteMaxKey" in adapter
    assert "MaxDecodedCells = 100000000L" in adapter
    assert "MaxTileDecodedCells = 10000000L" in adapter
    assert "tileCells <= MaxTileDecodedCells" in adapter
    assert "MaxDecodedCells / tileCells" in adapter
    assert "maximum.col <= finiteMaxCol" in adapter and "maximum.row <= finiteMaxRow" in adapter
    assert "validateInput(data)" in adapter and "validateSource(input)" in adapter
    assert "val sourceMinKey = input.sourceMinKey" in adapter
    assert "val sourceMaxKey = input.sourceMaxKey" in adapter
    assert "sourceMinKey.col" in adapter and "sourceMaxKey.col" in adapter
    assert "checked.keys.take(maxSourceKeys + 1)" in adapter
    assert "reduceByKey(_ + _)" in adapter and "duplicate source tile keys" in adapter
    assert "tile.bandCount == bandCount" in adapter
    assert "parallelize(candidateKeys, partitions)" in adapter
    assert "keys.leftOuterJoin(source)" in adapter
    assert "input.source.take" not in adapter and ".collect()" not in adapter
    assert "geometry.covers(GeometryFactory.createPoint" in kernel
    assert 'case None => Vector.fill(bandCount)(None)' in kernel
    assert 'options.dropNulls && values.exists(_.isEmpty)' in kernel
    assert "gridRandom(options.seed, cell.col, cell.row)" in kernel
    assert "count.toDouble / population.toDouble" in kernel
    assert "MaxGridKeys = 100000L" in kernel
    assert "keys.size.toLong <= MaxGridKeys" in kernel
    assert "output.take(1001)" in adapter and "rows.sortBy(row => (row.feature, row.row, row.col))" in adapter


def test_missing_edge_tile_probe_separates_finite_extent_from_observed_source_bounds():
    probe = (ROOT / "tests/fixtures/ee-image-sample-kernel-probe.scala").read_text()
    assert "actual RDD has only key (0, 0)" in probe
    assert "finiteMax = SpatialKey(2, 0)" in probe
    assert "candidateKeys(feature, grid, finiteMin, finiteMax)" in probe
    assert "candidateKeys(feature, grid, sourceMin, sourceMax)" in probe
    assert "sampleTileIterator(None, key, grid, feature, options, 2, population" in probe
    assert "rows.length == 4 && rows.forall(_.values == Vector(None, None))" in probe


def test_spark_transform_closures_capture_only_serializable_locals():
    adapter = (ROOT / "engine/ee_image_sample_adapter.scala").read_text()
    source_map = adapter.split("val checked = input.source.map", 1)[1].split("val keyCount", 1)[0]
    output_map = adapter.split("val output = keys.leftOuterJoin(source).flatMap", 1)[1].split("val rows = output.take", 1)[0]
    assert "input." not in source_map
    assert "input." not in output_map


def test_native_options_independently_reject_unknown_duplicate_trailing_and_bad_values():
    parser = (ROOT / "engine/ee_image_sample_options.scala").read_text()
    assert "STRICT_DUPLICATE_DETECTION" in parser
    assert "parser.nextToken() == null" in parser
    assert "Fields(name)" in parser and "fields == Fields" in parser
    assert "value.isFinite && value > 0.0 && value <= 1.0" in parser
    assert "getBigIntegerValue" in parser
    assert "Int.MinValue" in parser and "Int.MaxValue" in parser
