"""Portable source and adapter-build contracts for native sampleRegions."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sampler_sources_are_in_the_atomic_adapter_build():
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text()
    for name in ("ee_sample_kernel.scala", "ee_sample_adapter.scala"):
        assert f'ROOT / "engine/{name}"' in builder
    assert "local.ee.sample.LocalEeSampleCubeProcessProvider\\n" in builder
    assert "os.replace(staged_jar, output)" in builder and '"sources"' in builder


def test_sampler_declares_real_bounded_geometry_and_row_contract():
    kernel = (ROOT / "engine/ee_sample_kernel.scala").read_text()
    adapter = (ROOT / "engine/ee_sample_adapter.scala").read_text()
    assert "def sampleTile(" in kernel and "tile: MultibandTile" in kernel
    assert "def parseAndProjectWkts" in kernel and "Transform(LatLng, target)" in kernel
    assert 'Set("Point", "MultiPoint", "Polygon", "MultiPolygon")' in kernel
    assert "geometry.intersection(cellPolygon).getArea > 0.0" in kernel
    assert "pointCells" in kernel and "seen.add(cell)" in kernel
    assert "def tileMayIntersect" in kernel and "intersects(tileBounds)" in kernel
    assert "DoubleConstantNoDataCellType" in kernel and "sampled valid pixels must be finite" in kernel
    assert "MaxResponseBytes = 1000000" in kernel and "MaxRows = 1000" in kernel
    assert 'id = "local_ee_sample_regions"' in adapter
    assert 'arguments.size() == 1 && arguments.containsKey("regions")' in adapter
    assert 'input.kind == "spatial"' in adapter
    assert "LocalEeClassifyReduceBridge.validate" in adapter
    assert "keyInGrid" in adapter and "candidateKeyCount" in adapter and "67108864L" in adapter
    assert "validatedSource = input.source.map" in adapter and "candidates = validatedSource.filter" in adapter
    assert "rowsRdd.take(1001)" in adapter
