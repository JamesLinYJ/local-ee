"""Portable source and builder contracts for the native mask-weight SPI."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mask_weights_sources_are_in_the_atomic_service_adapter():
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text(encoding="utf-8")
    for name in (
        "ee_mask_weights_spec.scala",
        "ee_mask_weights_numeric.scala",
        "ee_mask_weights_adapter.scala",
    ):
        assert f'ROOT / "engine/{name}"' in builder
    assert "LocalEeMaskWeightsCubeProcessProvider\\n" in builder
    assert '"sources": {str(path.relative_to(ROOT)): sha256(path) for path in SOURCES}' in builder
    assert "os.replace(staged_jar, output)" in builder


def test_mask_weights_spec_and_kernel_keep_validity_update_and_apply_closed():
    spec = (ROOT / "engine/ee_mask_weights_spec.scala").read_text(encoding="utf-8")
    numeric = (ROOT / "engine/ee_mask_weights_numeric.scala").read_text(encoding="utf-8")
    adapter = (ROOT / "engine/ee_mask_weights_adapter.scala").read_text(encoding="utf-8")

    assert "STRICT_DUPLICATE_DETECTION" in spec
    assert "MaxSpecBytes = 128" in spec
    assert 'Set("op", "v")' in spec
    assert 'Set("validity", "update", "apply")' in spec
    assert "text == canonicalJson(result)" in spec
    assert "def applyTile(input: MultibandTile, spec: LocalEeMaskWeightsSpec.Value): Tile" in numeric
    assert "validityWeight" in numeric and "value.isNaN" in numeric
    assert "oldWeight == 0d" in numeric and "maskWeight" in numeric
    assert "weight > 0d" in numeric and "rawValue.isNaN || rawValue.isFinite" in numeric
    assert "DoubleConstantNoDataCellType" in numeric
    assert "copyAsDouble" not in numeric and ".convert(" not in numeric
    assert "LocalEeClassifyReduceBridge.validate" in adapter
    assert "LocalEeClassifyReduceBridge.keyInGrid" in adapter
    assert "LocalEeMaskWeightsNumeric.applyTile" in adapter
    assert "67108864L" in adapter and "input.source.keys.take" in adapter
    assert 'id = "local_ee_mask_weights"' in adapter
    assert 'cubeMetadata(input, Seq("v"))' in adapter
    closure = adapter.split("input.source.map {", 1)[1].split("\n    }", 1)[0]
    assert "input.source" not in closure and "input.cube" not in closure


def test_python_bridge_checks_spec_band_count_and_uses_trusted_native_dispatch():
    bridge = (ROOT / "engine/ee_mask_weights.py").read_text(encoding="utf-8")

    assert "decode_mask_weights_spec(text)" in bridge
    assert "MASK_WEIGHT_ARITIES[spec[\"op\"]]" in bridge
    assert "_validate_dry_run_input_bands(cube, expected_count)" in bridge
    assert "_validate_input_bands(cube.metadata, expected_count)" in bridge
    assert 'cube._process(_PROCESS_ID, {"spec": text}, metadata=metadata)' in bridge
    assert 'return _apply_native(cube, _PROCESS_ID, {"spec": text}, metadata)' in bridge


def test_standalone_builder_path_does_not_resolve_native_locks_or_configs():
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text(encoding="utf-8")
    inputs = (ROOT / "scripts/ee_adapter_build_inputs.py").read_text(encoding="utf-8")
    standalone = builder.split("def build_standalone(", 1)[1].split("\ndef build(", 1)[0]

    assert "build_standalone_from_inputs(" in standalone
    assert "engine-lock.json" not in standalone and "_engine_paths(" not in standalone
    assert 'glob("*.jar")' in inputs
    assert "java_sha256" in inputs and "java_version" in inputs
    assert "jar_tool_sha256" in inputs
    assert "scala_tools" in inputs and "runtime_jars" in inputs
    assert '"build_helpers": {str(build_helper.relative_to(root)): sha256(build_helper)}' in inputs
    assert '"format": "local-ee-standalone-audit-v1"' in inputs
    assert '"build_mode": "standalone-explicit-classpath"' in inputs
    assert '"deployment_eligible": False' in inputs
    assert '"provenance_claim_verified": False' in inputs
    assert "runtime_public_attestation" in inputs and "public_runtime_attestation" in inputs
    assert "_PUBLIC_LOCKS" in inputs and ".native" not in inputs
