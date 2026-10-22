"""Portable source contracts for the native Float64 remap adapter."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_remap_sources_are_in_the_atomic_adapter_and_service_manifest():
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text()
    for name in ("ee_remap_numeric.scala", "ee_remap_adapter.scala"):
        assert f'ROOT / "engine/{name}"' in builder
    assert "local.ee.remap.LocalEeRemapCubeProcessProvider\\n" in builder
    assert '"sources": {str(path.relative_to(ROOT)): sha256(path) for path in SOURCES}' in builder
    assert "os.replace(staged_jar, output)" in builder


def test_remap_parser_kernel_and_cube_adapter_preserve_the_closed_contract():
    numeric = (ROOT / "engine/ee_remap_numeric.scala").read_text()
    adapter = (ROOT / "engine/ee_remap_adapter.scala").read_text()

    assert 'Set("version", "from", "to", "default")' in numeric
    assert "STRICT_DUPLICATE_DETECTION" in numeric
    assert "MaxSpecBytes = 1000000" in numeric and "MaxValues = 256" in numeric
    assert "doubleToRawLongBits" in numeric and "value == 0.0" in numeric
    assert "def parseSpec(text: String): LocalEeRemapSpec" in numeric
    assert "def remapValue(input: Double" in numeric
    assert "def remapTile(tile: MultibandTile" in numeric
    assert "DoubleConstantNoDataCellType" in numeric and "input.isNaN" in numeric
    assert 'id = "local_ee_remap"' in adapter
    assert 'containsKey("spec")' in adapter
    assert "LocalEeClassifyReduceBridge.validate" in adapter
    assert "keyInGrid" in adapter and "67108864L" in adapter
    assert "LocalEeRemapNumeric.remapTile" in adapter
    assert "cubeMetadata(input, Seq(\"v\"))" in adapter
