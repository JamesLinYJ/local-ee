"""SDK serialization and bounded Image.reduceNeighborhood compiler checks."""
from pathlib import Path
import struct

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.neighborhood_spec import decode_neighborhood_spec
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
EXPORT_REGION = {"type": "Polygon", "coordinates": [[
    [100.3, 30.3], [100.7, 30.3], [100.7, 30.7],
    [100.3, 30.3],
]]}


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


def compile_sdk(ee, value, *, items=None, options=None):
    metadata, default_items, _ = synthetic_inputs()
    return compile_expression(
        ee.serializer.encode(value, for_cloud_api=False), [metadata],
        default_items if items is None else items, options=options,
    )


def neighborhood_nodes(result):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_neighborhood"]


def focal_nodes(result):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_focal"]


def operation_specs(result):
    return {
        decoded["operation"]: decoded
        for decoded in (decode_neighborhood_spec(node["arguments"]["spec"])
                        for node in neighborhood_nodes(result))
    }


def decoded_weights(spec):
    return [
        (dx, dy, struct.unpack(">d", bytes.fromhex(bits))[0])
        for dx, dy, bits in spec["coefficients"]
    ]


def image(ee):
    return ee.ImageCollection("sentinel-2-l2a").first().select("nir")


def fixed_kernel(ee, weights, *, x=0, y=0, normalize=False):
    return ee.Kernel.fixed(
        width=len(weights[0]), height=len(weights), weights=weights,
        x=x, y=y, normalize=normalize,
    )


def test_nonuniform_kernel_sum_and_mean_keep_float64_weights(ee):
    kernel = fixed_kernel(ee, [[0.25, 0.75]])
    image_value = image(ee)
    summed = compile_sdk(ee, image_value.reduceNeighborhood(
        reducer=ee.Reducer.sum(), kernel=kernel,
    ))
    mean = compile_sdk(ee, image_value.reduceNeighborhood(
        reducer=ee.Reducer.mean(), kernel=kernel,
    ))

    assert summed["bands"] == ["nir_sum"]
    assert decoded_weights(operation_specs(summed)["sum"]) == [
        (0, 0, 0.25), (1, 0, 0.75),
    ]
    assert decoded_weights(operation_specs(mean)["mean"]) == [
        (0, 0, 0.25), (1, 0, 0.75),
    ]
    assert len(neighborhood_nodes(summed)) == len(neighborhood_nodes(mean)) == 1


def test_input_weight_kernel_mask_and_min_use_effective_coefficients(ee):
    kernel = fixed_kernel(ee, [[0.25, 2.0]])
    image_value = image(ee)
    kernel_result = compile_sdk(ee, image_value.reduceNeighborhood(
        reducer=ee.Reducer.sum(), kernel=kernel, inputWeight="kernel",
    ))
    mask_result = compile_sdk(ee, image_value.reduceNeighborhood(
        reducer=ee.Reducer.sum(), kernel=kernel, inputWeight="mask",
    ))
    min_result = compile_sdk(ee, image_value.reduceNeighborhood(
        reducer=ee.Reducer.sum(), kernel=kernel, inputWeight="min",
    ))

    assert decoded_weights(operation_specs(kernel_result)["sum"]) == [
        (0, 0, 0.25), (1, 0, 2.0),
    ]
    assert decoded_weights(operation_specs(mask_result)["sum"]) == [
        (0, 0, 1.0), (1, 0, 1.0),
    ]
    assert decoded_weights(operation_specs(min_result)["sum"]) == [
        (0, 0, 0.25), (1, 0, 1.0),
    ]


def test_uniform_legacy_mean_min_max_median_mode_keep_focal_graphs(ee):
    image_value = image(ee)
    kernel = fixed_kernel(ee, [[0.25, 0.25]])
    reducers = [
        ee.Reducer.mean(), ee.Reducer.min(), ee.Reducer.max(),
        ee.Reducer.median(), ee.Reducer.mode(),
    ]
    for reducer in reducers:
        result = compile_sdk(ee, image_value.reduceNeighborhood(
            reducer=reducer, kernel=kernel,
        ))
        assert focal_nodes(result), reducer
        assert not neighborhood_nodes(result), reducer


def test_composed_minmax_and_setoutputs_emit_logical_names(ee):
    reducer = ee.Reducer.minMax().combine(
        ee.Reducer.variance(), outputPrefix="right_", sharedInputs=True,
    ).setOutputs(["low", "high", "spread"])
    result = compile_sdk(ee, image(ee).reduceNeighborhood(
        reducer=reducer, kernel=fixed_kernel(ee, [[1.0, 2.0]]),
    ))

    assert result["bands"] == ["nir_low", "nir_high", "nir_spread"]
    assert set(operation_specs(result)) == {"min", "max", "variance"}
    assert len(neighborhood_nodes(result)) == 3


def test_shared_sum_and_median_normalize_only_the_median_weights(ee):
    reducer = ee.Reducer.sum().combine(
        ee.Reducer.median(), sharedInputs=True,
    ).setOutputs(["weighted", "middle"])
    result = compile_sdk(ee, image(ee).reduceNeighborhood(
        reducer=reducer, kernel=fixed_kernel(ee, [[0.5, 0.5]]),
    ))
    specs = operation_specs(result)

    assert result["bands"] == ["nir_weighted", "nir_middle"]
    assert decoded_weights(specs["sum"]) == [(0, 0, 0.5), (1, 0, 0.5)]
    assert decoded_weights(specs["median"]) == [(0, 0, 1.0), (1, 0, 1.0)]


@pytest.mark.parametrize(
    ("reducer", "operation"),
    [
        ("stdDev", "stdDev"), ("variance", "variance"),
        ("sampleVariance", "sampleVariance"), ("sampleStdDev", "sampleStdDev"),
        ("product", "product"), ("count", "count"),
    ],
)
def test_finite_numeric_reducer_leaves_compile_to_their_actual_operation(
        ee, reducer, operation):
    kernel = fixed_kernel(ee, [[0.2, 0.2]])
    reducer_value = getattr(ee.Reducer, reducer)()
    result = compile_sdk(ee, image(ee).reduceNeighborhood(
        reducer=reducer_value, kernel=kernel,
    ))

    spec = operation_specs(result)[operation]
    weights = decoded_weights(spec)
    expected_output = {
        "sampleVariance": "variance",
        "sampleStdDev": "stdDev",
    }.get(operation, operation)
    assert result["bands"] == [f"nir_{expected_output}"]
    if operation in {"sampleVariance", "sampleStdDev", "product"}:
        assert weights == [(0, 0, 1.0), (1, 0, 1.0)]
    else:
        assert weights == [(0, 0, 0.2), (1, 0, 0.2)]


@pytest.mark.parametrize("reducer_name", [
    "sampleVariance", "sampleStdDev", "product", "median", "mode",
])
def test_nonuniform_unweighted_paths_reject_without_mask_or_unweighted_wrapper(
        ee, reducer_name):
    kernel = fixed_kernel(ee, [[0.25, 0.75]])
    reducer = getattr(ee.Reducer, reducer_name)()
    with pytest.raises(UnsupportedEEError, match="uniform effective weights"):
        compile_sdk(ee, image(ee).reduceNeighborhood(
            reducer=reducer, kernel=kernel, inputWeight="kernel",
        ))


def test_mask_and_unweighted_wrapper_turn_kernel_support_into_unit_weights(ee):
    kernel = fixed_kernel(ee, [[0.25, 0.75]])
    image_value = image(ee)
    masked = compile_sdk(ee, image_value.reduceNeighborhood(
        reducer=ee.Reducer.sampleVariance(), kernel=kernel, inputWeight="mask",
    ))
    unweighted = compile_sdk(ee, image_value.reduceNeighborhood(
        reducer=ee.Reducer.product().unweighted(), kernel=kernel,
    ))

    assert decoded_weights(operation_specs(masked)["sampleVariance"]) == [
        (0, 0, 1.0), (1, 0, 1.0),
    ]
    assert decoded_weights(operation_specs(unweighted)["product"]) == [
        (0, 0, 1.0), (1, 0, 1.0),
    ]


def test_weighted_and_unit_paths_coexist_in_one_composed_plan(ee):
    reducer = ee.Reducer.sum().combine(
        ee.Reducer.sampleVariance(), sharedInputs=True,
    )
    result = compile_sdk(ee, image(ee).reduceNeighborhood(
        reducer=reducer, kernel=fixed_kernel(ee, [[0.25, 0.25]]),
    ))
    specs = operation_specs(result)

    assert decoded_weights(specs["sum"]) == [(0, 0, 0.25), (1, 0, 0.25)]
    assert decoded_weights(specs["sampleVariance"]) == [(0, 0, 1.0), (1, 0, 1.0)]


def test_direct_mode_and_composed_default_mode_are_supported(ee):
    kernel = fixed_kernel(ee, [[0.5, 0.5]])
    direct = compile_sdk(ee, image(ee).reduceNeighborhood(
        reducer=ee.Reducer.mode(), kernel=kernel,
    ))
    composed = compile_sdk(ee, image(ee).reduceNeighborhood(
        reducer=ee.Reducer.mean().combine(
            ee.Reducer.mode(), sharedInputs=True,
        ), kernel=kernel,
    ))

    assert focal_nodes(direct)
    assert set(operation_specs(composed)) == {"mean", "mode"}
    assert decoded_weights(operation_specs(composed)["mean"]) == [
        (0, 0, 0.5), (1, 0, 0.5),
    ]
    assert decoded_weights(operation_specs(composed)["mode"]) == [
        (0, 0, 1.0), (1, 0, 1.0),
    ]


def test_unweighted_reducer_remains_neighborhood_only(ee):
    unweighted = ee.Reducer.mean().unweighted()
    kernel = fixed_kernel(ee, [[0.25, 0.75]])
    result = compile_sdk(ee, image(ee).reduceNeighborhood(
        reducer=unweighted, kernel=kernel,
    ))
    assert focal_nodes(result)

    with pytest.raises(UnsupportedEEError, match="Expected a supported Reducer"):
        compile_sdk(ee, image(ee).reduceRegion(
            reducer=unweighted, geometry=EXPORT_REGION,
        ))
    with pytest.raises(UnsupportedEEError, match="supported scalar or regression Reducer"):
        compile_sdk(ee, ee.List([1, 2]).reduce(unweighted))
    with pytest.raises(UnsupportedEEError, match="legacy Reducer or closed ReducerSpec"):
        compile_sdk(ee, ee.Array([1, 2]).reduce(unweighted, axes=[0]))
    with pytest.raises(UnsupportedEEError, match="supported scalar or regression Reducer"):
        compile_sdk(ee, unweighted.combine(ee.Reducer.sum(), sharedInputs=True))
    with pytest.raises(UnsupportedEEError, match="not a computable output value"):
        compile_sdk(ee, unweighted)
    with pytest.raises(UnsupportedEEError, match="static scalar/list/dictionary condition"):
        compile_sdk(ee, ee.Algorithms.If(unweighted, 1, 0))
    with pytest.raises(UnsupportedEEError, match="cannot be nested"):
        compile_sdk(ee, image(ee).reduceNeighborhood(
            reducer=unweighted.unweighted(), kernel=kernel,
        ))


def test_unsupported_composed_leaves_are_rejected_even_if_dropped(ee):
    reducer = ee.Reducer.mean().combine(
        ee.Reducer.percentile([50]), sharedInputs=True,
    ).setOutputs(["average", None])
    with pytest.raises(UnsupportedEEError, match="default Reducer.mode"):
        compile_sdk(ee, image(ee).reduceNeighborhood(
            reducer=reducer, kernel=fixed_kernel(ee, [[1.0]]),
        ))


@pytest.mark.parametrize(
    ("weights", "input_weight", "pattern"),
    [
        ([[-1.0, 1.0]], "mask", "nonnegative"),
        ([[0.0, 0.0]], "kernel", "positive support"),
        ([[1.0, 2.0]], "unsupported-weight" , "inputWeight"),
    ],
)
def test_kernel_support_and_input_weight_validation(ee, weights, input_weight, pattern):
    reducer = ee.Reducer.mean()
    with pytest.raises(UnsupportedEEError, match=pattern):
        compile_sdk(ee, image(ee).reduceNeighborhood(
            reducer=reducer,
            kernel=fixed_kernel(ee, weights),
            inputWeight=input_weight,
        ))


def test_invalid_parameters_and_unsupported_reducer_shapes_fail_closed(ee):
    image_value = image(ee)
    kernel = fixed_kernel(ee, [[1.0]])
    with pytest.raises(UnsupportedEEError, match="optimization"):
        compile_sdk(ee, image_value.reduceNeighborhood(
            reducer=ee.Reducer.mean(), kernel=kernel, optimization="window",
        ))
    with pytest.raises(UnsupportedEEError, match="sharedInputs=true|exactly one input"):
        compile_sdk(ee, image_value.reduceNeighborhood(
            reducer=ee.Reducer.mean().combine(
                ee.Reducer.sum(), sharedInputs=False,
            ), kernel=kernel,
        ))
    with pytest.raises(UnsupportedEEError, match="default Reducer.mode leaf"):
        compile_sdk(ee, image_value.reduceNeighborhood(
            reducer=ee.Reducer.mode(maxRaw=3), kernel=kernel,
        ))
    with pytest.raises(UnsupportedEEError, match="skipMasked must be boolean"):
        compile_sdk(ee, image_value.reduceNeighborhood(
            reducer=ee.Reducer.mean(), kernel=kernel, skipMasked=1,
        ))


def test_output_name_collisions_and_lengths_reject_before_graph_emission(ee):
    first = ee.Image.constant(1).rename("a_b")
    second = ee.Image.constant(2).rename("a")
    two_bands = first.addBands(second)
    reducer = ee.Reducer.mean().combine(
        ee.Reducer.sum(), sharedInputs=True,
    ).setOutputs(["c", "b_c"])
    with pytest.raises(UnsupportedEEError, match="must be unique"):
        compile_sdk(ee, two_bands.reduceNeighborhood(
            reducer=reducer, kernel=fixed_kernel(ee, [[1.0]]),
        ))

    long_image = ee.Image.constant(1).rename("n" * 9_997)
    with pytest.raises(UnsupportedEEError, match="output band name exceeds"):
        compile_sdk(ee, long_image.reduceNeighborhood(
            reducer=ee.Reducer.mean(), kernel=fixed_kernel(ee, [[1.0]]),
        ))


def test_neighborhood_kernel_work_budget_is_precharged(ee):
    broad_kernel = fixed_kernel(ee, [[1.0] * 33 for _ in range(33)], x=16, y=16)
    with pytest.raises(UnsupportedEEError, match="50000-step work budget"):
        compile_sdk(ee, image(ee).reduceNeighborhood(
            reducer=ee.Reducer.sum(), kernel=broad_kernel,
        ))


def test_extreme_positive_binary64_weights_survive_sdk_compilation(ee):
    kernel = fixed_kernel(ee, [[5e-324, 1e308]])
    result = compile_sdk(ee, image(ee).reduceNeighborhood(
        reducer=ee.Reducer.sum(), kernel=kernel,
    ))
    spec = operation_specs(result)["sum"]
    assert decoded_weights(spec) == [(0, 0, 5e-324), (1, 0, 1e308)]


def test_neighborhood_preserves_full_source_bounds_and_applies_export_grid_afterward(ee):
    result = compile_sdk(
        ee,
        image(ee).reduceNeighborhood(
            reducer=ee.Reducer.sum(), kernel=fixed_kernel(ee, [[1.0]]),
        ),
        options={"region": EXPORT_REGION, "scale": 20, "crs": "EPSG:32610"},
    )
    nodes = list(result["process_graph"].values())
    load = next(node for node in nodes if node["process_id"] == "load_collection")
    neighborhood_index = next(i for i, node in enumerate(nodes)
                              if node["process_id"] == "local_ee_neighborhood")
    resample_index = next(i for i, node in enumerate(nodes)
                          if node["process_id"] == "resample_spatial")

    assert load["arguments"]["spatial_extent"] == {
        "west": 100, "south": 30, "east": 101, "north": 31,
    }
    assert neighborhood_index < resample_index


