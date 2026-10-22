"""Portable source and builder contracts for the native exact classifier."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_classifier_sources_are_in_the_atomic_adapter_build():
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text()
    for name in (
        "ee_classify_numeric.scala",
        "ee_classify_model.scala",
        "ee_classify_adapter.scala",
    ):
        assert f'ROOT / "engine/{name}"' in builder
    assert "local.ee.classify.LocalEeClassifyCubeProcessProvider\\n" in builder
    assert "os.replace(staged_jar, output)" in builder and '"sources"' in builder


def test_classifier_source_declares_exact_bounded_contract_and_output_type():
    model = (ROOT / "engine/ee_classify_model.scala").read_text()
    numeric = (ROOT / "engine/ee_classify_numeric.scala").read_text()
    adapter = (ROOT / "engine/ee_classify_adapter.scala").read_text()

    assert 'Set("version", "metric", "schema", "labels", "centers")' in model
    assert "def fromJavaMap(value: java.util.Map[_, _])" in model
    assert "MaxStringChars = 700" in model and "fractionString" in model
    assert "MaxRationalBits = 2200" in model
    assert 'Set("euclidean", "manhattan", "cosine")' in model
    assert "doubleToRawLongBits(value)" in numeric
    assert "compareCosine" in numeric and "equal-distance class centers" in numeric
    assert "hasNoData" in numeric and "input pixels must be finite or NoData" in numeric
    assert 'id = "local_ee_minimum_distance"' in adapter
    assert "input.names == model.schema" in adapter
    assert "keyInGrid" in adapter and "67108864L" in adapter
    assert "IntConstantNoDataCellType" in adapter
