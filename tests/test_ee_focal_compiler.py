"""SDK serialization and bounded compiler checks for focal image filters."""
from copy import deepcopy
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.focal_spec import decode_focal_spec
from gee.local_processes import process_spec
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield guard
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def compile_sdk(ee, value, *, items=None):
    metadata, default_items, _ = synthetic_inputs()
    return compile_expression(
        ee.serializer.encode(value, for_cloud_api=False), [metadata],
        default_items if items is None else items,
    )


def focal_nodes(result):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_focal"]


def only_focal_spec(result):
    nodes = focal_nodes(result)
    assert len(nodes) == 1
    return decode_focal_spec(nodes[0]["arguments"]["spec"])


@pytest.mark.parametrize(
    ("camel", "snake", "operation"),
    [
        ("focalMin", "focal_min", "min"),
        ("focalMax", "focal_max", "max"),
        ("focalMean", "focal_mean", "mean"),
        ("focalMedian", "focal_median", "median"),
        ("focalMode", "focal_mode", "mode"),
    ],
)
def test_camel_and_deprecated_snake_case_aliases_compile(ee, camel, snake, operation):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    camel_result = compile_sdk(ee, getattr(image, camel)())
    snake_result = compile_sdk(ee, getattr(image, snake)())

    assert camel_result["kind"] == snake_result["kind"] == "image"
    assert camel_result["bands"] == snake_result["bands"] == ["nir"]
    assert only_focal_spec(camel_result)["operation"] == operation
    assert only_focal_spec(snake_result)["operation"] == operation
    assert only_focal_spec(camel_result)["offsets"] == only_focal_spec(snake_result)["offsets"]
    process_ids = [node["process_id"] for node in camel_result["process_graph"].values()]
    assert (
        process_ids.index("local_ee_to_double")
        < process_ids.index("local_ee_drop_single_time")
        < process_ids.index("local_ee_focal")
    )


def test_focal_defaults_custom_kernel_and_image_metadata_are_preserved(ee):
    kernel = ee.Kernel.fixed(
        width=3, height=3,
        weights=[[1, 1, 1], [1, 1, 1], [1, 1, 1]], x=1, y=1,
    )
    image = (ee.ImageCollection("sentinel-2-l2a").first().select("nir")
             .set("local-tag", "kept"))
    result = compile_sdk(ee, image.focalMax(
        radius=-9, kernelType="ignored-with-custom-kernel", kernel=kernel,
    ))

    spec = only_focal_spec(result)
    assert spec["operation"] == "max"
    assert spec["iterations"] == 1
    assert spec["skip_masked"] is True
    assert spec["v"] == 1
    assert spec["offsets"] == [
        [dx, dy] for dy in (-1, 0, 1) for dx in (-1, 0, 1)
    ]
    assert result["properties"]["local-tag"] == "kept"
    assert result["bands"] == ["nir"]


@pytest.mark.parametrize(
    "shape", ["circle", "square", "cross", "plus", "octagon", "diamond"],
)
def test_named_focal_masks_match_kernel_constructor_masks(ee, shape):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    named = compile_sdk(ee, image.focalMean(radius=3, kernelType=shape))
    kernel = getattr(ee.Kernel, shape)(radius=3, normalize=False)
    custom = compile_sdk(ee, image.focalMean(kernel=kernel))
    assert only_focal_spec(named)["offsets"] == only_focal_spec(custom)["offsets"]


def test_focal_cross_and_plus_have_distinct_masks_and_named_radius_is_bounded(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    cross = only_focal_spec(compile_sdk(
        ee, image.focalMean(radius=2, kernelType="cross"),
    ))["offsets"]
    plus = only_focal_spec(compile_sdk(
        ee, image.focalMean(radius=2, kernelType="plus"),
    ))["offsets"]
    assert cross != plus
    with pytest.raises(UnsupportedEEError, match="at most 16"):
        compile_sdk(ee, image.focalMean(radius=17, kernelType="square"))


def test_focal_uses_custom_kernel_positive_support_and_bounds_iterations(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    kernel = ee.Kernel.fixed(
        width=2, height=2, weights=[[0, 2], [4, 0]], x=0, y=0,
    )
    result = compile_sdk(ee, image.focalMean(kernel=kernel, iterations=8))
    assert only_focal_spec(result)["offsets"] == [[1, 0], [0, 1]]
    assert only_focal_spec(result)["iterations"] == 8
    with pytest.raises(UnsupportedEEError, match="1 to 8"):
        compile_sdk(ee, image.focalMean(iterations=9))


def test_focal_process_contract_declares_float64_output():
    spec = process_spec("local_ee_focal")
    assert spec["returns"]["description"] == "Float64 raster cube"


def test_focal_output_reuses_native_v_band_without_adding_a_second_dimension(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    result = compile_sdk(ee, image.focalMean())
    process_ids = [node["process_id"] for node in result["process_graph"].values()]
    assert "add_dimension" not in process_ids
    assert process_ids.count("local_ee_focal") == 1
    assert process_ids[-1] == "rename_labels"


def test_nested_focal_filters_chain_native_single_band_results(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    result = compile_sdk(ee, image.focalMean().focalMax())
    nodes = focal_nodes(result)
    assert len(nodes) == 2
    assert nodes[1]["arguments"]["data"] == {
        "from_node": next(
            key for key, node in result["process_graph"].items()
            if node is nodes[0]
        ),
    }
    assert "add_dimension" not in [
        node["process_id"] for node in result["process_graph"].values()
    ]


def test_focal_preserves_time_dimension_through_collection_map(ee):
    _, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32610"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3500000]
    collection = ee.ImageCollection("sentinel-2-l2a").map(
        lambda image: image.select("nir").focalMean(iterations=2),
    )
    result = compile_sdk(ee, collection, items=items)

    assert result["kind"] == "collection"
    assert result["has_time_dimension"] is True
    assert result["bands"] == ["nir"]
    spec = only_focal_spec(result)
    assert spec["operation"] == "mean" and spec["iterations"] == 2


@pytest.mark.parametrize(
    ("reducer", "operation"),
    [
        ("mean", "mean"), ("min", "min"), ("max", "max"),
        ("median", "median"), ("mode", "mode"),
    ],
)
def test_reduce_neighborhood_single_output_reducers(ee, reducer, operation):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    kernel = ee.Kernel.square(radius=1, normalize=False)
    reducer_value = getattr(ee.Reducer, reducer)()
    result = compile_sdk(ee, image.reduceNeighborhood(
        reducer=reducer_value, kernel=kernel, skipMasked=False,
    ))

    assert result["bands"] == [f"nir_{operation}"]
    spec = only_focal_spec(result)
    assert spec["operation"] == operation
    assert spec["skip_masked"] is False
    assert spec["iterations"] == 1


def test_reduce_neighborhood_mask_weights_allow_nonuniform_positive_kernel(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    kernel = ee.Kernel.fixed(
        width=2, height=2, weights=[[1, 2], [3, 4]], x=0, y=0,
    )
    result = compile_sdk(ee, image.reduceNeighborhood(
        reducer=ee.Reducer.mean(), kernel=kernel, inputWeight="mask",
    ))

    spec = only_focal_spec(result)
    assert spec["offsets"] == [[0, 0], [1, 0], [0, 1], [1, 1]]
    assert spec["operation"] == "mean"


@pytest.mark.parametrize(
    ("kernel_weights", "input_weight", "pattern"),
    [
        ([[1, 2], [1, 1]], "kernel", "Nonuniform kernel weights"),
        ([[1, 2], [1, 1]], "min", "Nonuniform kernel weights"),
        ([[-1, 1], [1, 1]], "mask", "nonnegative"),
        ([[0, 0], [0, 0]], "mask", "nonnegative|support|weight"),
    ],
)
def test_reduce_neighborhood_rejects_unsupported_kernel_weights(
        ee, kernel_weights, input_weight, pattern):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    kernel = ee.Kernel.fixed(
        width=2, height=2, weights=kernel_weights, x=0, y=0,
    )
    with pytest.raises(UnsupportedEEError, match=pattern):
        compile_sdk(ee, image.reduceNeighborhood(
            reducer=ee.Reducer.mean(), kernel=kernel, inputWeight=input_weight,
        ))


def test_reduce_neighborhood_rejects_optimization_composition_and_mode_maxraw(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    kernel = ee.Kernel.square(radius=1)
    with pytest.raises(UnsupportedEEError, match="optimization"):
        compile_sdk(ee, image.reduceNeighborhood(
            reducer=ee.Reducer.mean(), kernel=kernel, optimization="window",
        ))
    with pytest.raises(UnsupportedEEError, match="single-input, single-output"):
        compile_sdk(ee, image.reduceNeighborhood(
            reducer=ee.Reducer.mean().combine(
                reducer2=ee.Reducer.max(), sharedInputs=True,
            ),
            kernel=kernel,
        ))
    with pytest.raises(UnsupportedEEError, match="maxRaw"):
        compile_sdk(ee, image.reduceNeighborhood(
            reducer=ee.Reducer.mode(maxRaw=64), kernel=kernel,
        ))


def test_focal_rejects_meter_units_invalid_kernel_shapes_and_unbound_constants(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    with pytest.raises(UnsupportedEEError, match="pixel units"):
        compile_sdk(ee, image.focalMean(units="meters"))
    with pytest.raises(UnsupportedEEError, match="kernelType"):
        compile_sdk(ee, image.focalMean(kernelType="triangle"))
    with pytest.raises(UnsupportedEEError, match="bound raster source"):
        compile_sdk(ee, ee.Image.constant(5).focalMin())


def test_focal_proves_a_common_grid_before_merging_source_observations(ee):
    from scripts.ee_python_api.probe_cases import synthetic_inputs

    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32610"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3500000]
    second = deepcopy(items["sentinel-2-l2a"][1])
    second["properties"]["system:index"] = "scene-b"
    second["properties"]["proj:transform"][2] += 5
    left = ee.ImageCollection("sentinel-2-l2a").filter(
        ee.Filter.eq(name="system:index", value="scene-a"),
    ).first().select("nir")
    right = ee.ImageCollection("sentinel-2-l2a").filter(
        ee.Filter.eq(name="system:index", value="scene-b"),
    ).first().select("nir")

    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        expression = left.add(image2=right).focalMean()
        compile_expression(
            ee.serializer.encode(expression, for_cloud_api=False),
            [metadata], {"sentinel-2-l2a": [items["sentinel-2-l2a"][0], second]},
        )
