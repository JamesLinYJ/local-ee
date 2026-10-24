"""Local compile/graph checks for default-geodesic clip and sampling workflows.

These tests stop at the real process-graph boundary. They never create sample
rows; an actual tile and CSV readback belongs to the separately source-attested
native probe.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import uuid

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.image_sampling_spec import decode_image_sample_spec, prepare_image_sample_spec
from gee.sampling_spec import sampling_columns
from gee.sampling_values import assemble_sample_features
from gee.services.ee_sample_results import read_result
from engine.ee_sampling_result import SampledFeatureTable
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-geodesic-clip-wave70-v1.json"
CATALOG = ROOT / "vendor/earthengine-js/algorithms.json"
NATIVE_RECEIPT = ROOT / "audit/gee-python-wave70/native/tile-receipt-v4.json"


@pytest.fixture(scope="module")
def fixture_data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48, signatures_path=CATALOG,
    )
    assert client.__version__ == "1.7.49"
    return client


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


def _local_inputs(fixture):
    synthetic = fixture["synthetic_local_input"]
    return [copy.deepcopy(synthetic["catalog"])], copy.deepcopy(synthetic["items"])


def _workflow(ee, fixture):
    coordinates = fixture["workflow"]["roi"]["coordinates"]
    roi = ee.Geometry.Polygon(coordinates)
    source = ee.ImageCollection(fixture["workflow"]["collection_alias"]).first()
    image = source.select(fixture["workflow"]["real_band"])
    clipped = image.clip(roi)
    return roi, image, clipped


def _encode(ee, value):
    return ee.serializer.encode(value, is_compound=True, for_cloud_api=False)


def _compile(ee, fixture, expression):
    catalog, items = _local_inputs(fixture)
    return compile_expression(_encode(ee, expression), catalog, items)


def _nodes(result, process_id):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == process_id]


def _clip_coverage_pixels(pixel):
    found = []
    if not isinstance(pixel, Pixel):
        return found
    if pixel.op == "clip_coverage":
        found.append(pixel)
    for child in pixel.args:
        if isinstance(child, Pixel):
            found.extend(_clip_coverage_pixels(child))
        elif isinstance(child, (tuple, list)):
            for nested in child:
                found.extend(_clip_coverage_pixels(nested))
    return found


def _has_pixel(pixel, op):
    if not isinstance(pixel, Pixel):
        return False
    if pixel.op == op:
        return True
    for child in pixel.args:
        if isinstance(child, Pixel) and _has_pixel(child, op):
            return True
        if isinstance(child, (tuple, list)) and any(
                _has_pixel(nested, op) for nested in child):
            return True
    return False


def _assert_sample_has_no_rows(result):
    assert result["kind"] == "sample_table"
    assert "process_graph" in result
    assert "sample_spec" in result
    assert "features" not in result
    assert "rows" not in result
    assert "values" not in result
    assert _nodes(result, "local_ee_sample_regions")


@pytest.mark.parametrize("sample_kind", [
    "default_science", "default_scalar_math", "default_unary_math",
    "science_explicit_roi_keep_nulls", "mask_view_explicit_roi",
    "scalar_math_explicit_roi", "unary_math_explicit_roi",
])
def test_default_and_explicit_roi_sample_workflows_compile_to_opaque_tables(
        ee, fixture_data, sample_kind):
    roi, _image, clipped = _workflow(ee, fixture_data)
    if sample_kind == "default_science":
        # GEE's default dropNulls=true lets zero-coverage cells stay out when
        # Image.sample defaults to the source footprint. This is a local
        # compiler path assertion, not a Google same-data comparison.
        expression = clipped.sample()
        expected_drop_nulls = True
    elif sample_kind == "default_scalar_math":
        expression = clipped.multiply(2).sample()
        expected_drop_nulls = True
    elif sample_kind == "default_unary_math":
        expression = clipped.sqrt().sample()
        expected_drop_nulls = True
    elif sample_kind == "science_explicit_roi_keep_nulls":
        expression = clipped.sample(region=roi, dropNulls=False)
        expected_drop_nulls = False
    elif sample_kind == "mask_view_explicit_roi":
        # Numeric mask views contain meaningful zeros. Bound their sample area
        # explicitly so valid zeros outside the clipping ROI are not admitted.
        expression = clipped.mask().sample(region=roi, dropNulls=False)
        expected_drop_nulls = False
    elif sample_kind == "scalar_math_explicit_roi":
        expression = clipped.multiply(2).sample(region=roi, dropNulls=False)
        expected_drop_nulls = False
    else:
        expression = clipped.sqrt().sample(region=roi, dropNulls=False)
        expected_drop_nulls = False

    result = _compile(ee, fixture_data, expression)
    _assert_sample_has_no_rows(result)
    spec = decode_image_sample_spec(result["sample_spec"])
    assert spec["image_sample"]["drop_nulls"] is expected_drop_nulls
    assert spec["bands"] == [fixture_data["workflow"]["real_band"]]
    assert _nodes(result, "local_ee_clip_coverage")
    if sample_kind != "mask_view_explicit_roi":
        # The scientific sample retains its raw source-backed band. Coverage is
        # a separate mask carrier compiled by the audited mask consumer.
        assert _nodes(result, "local_ee_mask_weights")


def test_clip_ir_keeps_raw_science_and_canonical_coverage_separate(ee, fixture_data):
    _roi, _source, clipped = _workflow(ee, fixture_data)
    catalog, items = _local_inputs(fixture_data)
    translator = Translator(catalog, items, {})
    image = translator.evaluate(_encode(ee, clipped))

    assert isinstance(image, Image)
    assert [name for name, _pixel in image.bands] == ["nir"]
    carrier = image.bands[0][1]
    assert carrier.op == "with_mask"
    raw_science, _weight = carrier.args
    assert _has_pixel(raw_science, "band")
    coverages = _clip_coverage_pixels(carrier)
    assert len(coverages) == 1
    assert coverages[0].args[0] is raw_science
    actual_spec = json.loads(coverages[0].args[1])
    assert actual_spec == fixture_data["expected_clip_coverage_contract"]


def test_mask_getter_remains_a_raster_without_invented_sample_rows(ee, fixture_data):
    _roi, _image, clipped = _workflow(ee, fixture_data)
    result = _compile(ee, fixture_data, clipped.mask())

    assert result["kind"] == "image"
    assert result["bands"] == [fixture_data["workflow"]["real_band"]]
    assert _nodes(result, "local_ee_clip_coverage")
    assert "features" not in result
    assert "rows" not in result


def test_default_sample_and_geometry_access_respect_the_pending_clip_footprint(
        ee, fixture_data):
    roi, image, clipped = _workflow(ee, fixture_data)
    catalog, items = _local_inputs(fixture_data)

    # Without null dropping, the default sample footprint reaches beyond the
    # clipping ROI. A numeric mask view has valid zeros there, so it needs an
    # explicit region. Math outputs also need an explicit region unless they
    # remain the direct clip carrier accepted by the narrow default route.
    rejected = [
        clipped.sample(dropNulls=False),
        clipped.mask().sample(),
        clipped.mask().sample(dropNulls=False),
        clipped.multiply(2).sample(dropNulls=False),
        clipped.sqrt().sample(dropNulls=False),
        clipped.geometry(),
        clipped.select("nir").geometry(),
        clipped.select([]).geometry(),
        clipped.mask().geometry(),
        clipped.updateMask(0.5).geometry(),
        clipped.mask(ee.Image.constant(0.5)).geometry(),
    ]
    for expression in rejected:
        with pytest.raises(UnsupportedEEError):
            compile_expression(_encode(ee, expression), catalog, items)

    # An explicit region is the supported escape for science or numeric-weight
    # sampling; it does not change the canonical edge model.
    result = _compile(ee, fixture_data,
                      clipped.mask().sample(region=roi, dropNulls=False))
    _assert_sample_has_no_rows(result)

    mapped = ee.ImageCollection(
        fixture_data["workflow"]["collection_alias"]
    ).map(lambda item: item.clip(roi))
    with pytest.raises(UnsupportedEEError):
        compile_expression(_encode(ee, mapped.geometry()), catalog, items)


def test_fixture_preserves_the_original_preimplementation_verification_state(fixture_data):
    # The fixture is byte-bound to the source-attested native receipt. Its
    # initial `not_run` values remain historical facts and are not rewritten
    # after current kernel/readback evidence is produced.
    state = fixture_data["verification_state"]
    assert state["actual_local_kernel_readback"] == "not_run"
    assert state["independent_numeric_raster_reference"] == (
        "not_available_without_a_real_local_raster"
    )
    assert state["sample_rows"] == "not_generated"
    assert state["physical_csv"] is None


@pytest.mark.parametrize(("route", "drop_nulls"), [
    ("explicit_roi_clip_sample_drop_nulls_false", False),
    ("explicit_roi_clip_sample_drop_nulls_true", True),
])
def test_attested_native_sample_rows_round_trip_through_physical_csv(
        fixture_data, tmp_path, route, drop_nulls):
    """Consume only a separately produced actual-kernel receipt, when available."""
    if not NATIVE_RECEIPT.is_file():
        pytest.skip("source-attested native clip-coverage tile receipt is not available")

    from scripts.probe_clip_coverage_native import validate_tile_result

    receipt = json.loads(NATIVE_RECEIPT.read_text(encoding="utf-8"))
    fixture_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert receipt["schema"] == "local-ee-clip-coverage-native-probe-receipt/v1"
    assert hashlib.sha256(NATIVE_RECEIPT.read_bytes()).hexdigest() == (
        "301d58291da9e9d9764d0e2d03a72551136edb288f9b037caa426f36158286e1"
    )
    assert receipt["fixture_path"] == "tests/fixtures/ee-geodesic-clip-wave70-v1.json"
    assert fixture_hash == (
        "eb494b45b97cf293d49fed21b6782bf9de7504dfc770724dc0821e80a5881c2b"
    )
    assert receipt["fixture_sha256"] == fixture_hash
    assert receipt["manifest_format"] == "local-ee-standalone-audit-v1"
    assert receipt["manifest_adapter_label"] == "local-ee-mask-weights-audit-adapter"
    assert receipt["deployment_eligible"] is False
    assert receipt["manifest_jar"].endswith(
        "/audit/gee-python-wave70/native/final-4/local-ee-clip-coverage-adapter.jar"
    )
    assert receipt["manifest_jar_sha256"] == (
        "a46778297d684128d9f46389bc8f61bf13a0f2b94412fb369333550448b03b55"
    )
    assert receipt["probe_source"] == "tests/fixtures/ee-clip-coverage-kernel-probe.scala"
    assert receipt["probe_source_sha256"] == (
        "2aad18723f6b8a95621aec4391df86b5dbc687df2d259bc7c68393f13ccd71bc"
    )
    assert hashlib.sha256((ROOT / receipt["probe_source"]).read_bytes()).hexdigest() == (
        receipt["probe_source_sha256"]
    )
    tile = validate_tile_result(receipt["native_tile_result"], fixture_hash)
    assert tile["producer"] == "local.ee.reduce.EeClipCoverageKernelProbe"
    admission = tile["default_256_admission_probe"]
    assert admission["label"] == "synthetic-256x256-one-degree-EPSG4326-grid"
    assert admission["admitted"] is True
    assert (admission["tile_cols"], admission["tile_rows"]) == (256, 256)
    assert admission["actual_positive_coverage_cells"] == 24793
    assert admission["actual_partial_coverage_cells"] == 656
    assert int(admission["total_work"]) == 30781465 <= admission["max_work"]

    rows = tile["sample_rows"][route]
    assert rows
    coverage = tile["coverage_values_row_major"]
    clipped_science = tile["clipped_science_values_row_major"]
    for sample_row in rows:
        assert sample_row["feature"] == 0
        assert 0 <= sample_row["row"] < 8 and 0 <= sample_row["col"] < 8
        cell = sample_row["row"] * 8 + sample_row["col"]
        actual_value = sample_row["values"][0]
        assert actual_value == clipped_science[cell]
        if drop_nulls:
            assert actual_value is not None and coverage[cell] > 0.0

    region = {
        "type": "Polygon",
        "coordinates": fixture_data["expected_clip_coverage_contract"]["polygons"][0],
    }
    sample_text = prepare_image_sample_spec(
        region, [fixture_data["workflow"]["real_band"]], grid=None,
        drop_nulls=drop_nulls, geometries=False,
    )
    sample_spec = decode_image_sample_spec(sample_text)
    data = assemble_sample_features(sample_spec, rows)
    table = SampledFeatureTable(data, sampling_columns(sample_spec))
    table.sample_spec = sample_text
    table.sample_spec_verified = True
    table.sample_operations = ()
    table.sample_operation_work = 0

    job_id = str(uuid.uuid4())
    output = tmp_path / "jobs" / job_id / "out"
    output.mkdir(parents=True)
    assets = table.write_assets(output / "out")
    csv_names = [name for name in assets if name.endswith(".csv")]
    assert csv_names == ["openEO.csv"]
    assert (output / csv_names[0]).is_file()

    row = {
        "id": job_id,
        "assets": assets,
        "context": {
            "protocol": "earthengine",
            "result_kind": "samples",
            "sample_spec": sample_text,
        },
    }
    actual = read_result(tmp_path, row)
    assert actual == data
    assert actual["properties"] == {"band_order": [fixture_data["workflow"]["real_band"]]}
    assert len(actual["features"]) == len(rows)
