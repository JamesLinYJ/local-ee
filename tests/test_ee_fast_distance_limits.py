"""Fast-distance shared compiler work and graph-node boundaries."""
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.image_fast_distance import invoke_image_fast_distance
from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError
from gee.fast_distance_spec import prepare_fast_distance_spec
from scripts.ee_python_api.probe_cases import synthetic_inputs


def test_fast_distance_compilation_respects_shared_work_limit():
    translator = Translator([], {}, None)
    image = Image([("nir", Pixel("constant", (1.0,)))], {})
    translator.steps = 49_900
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_image_fast_distance(translator, {"image": image})

    from gee.compat.earthengine.fast_distance_graph import compile_fast_distance_pixel

    translator = Translator([], {}, None)
    translator.steps = 50_000
    pixel = Pixel(
        "fast_distance",
        (Pixel("band", (Source("sentinel-2-l2a", ("scene-a",), ("nir",)), "nir")),
         prepare_fast_distance_spec()),
    )
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        compile_fast_distance_pixel(Graph(translator), pixel)


def test_cached_double_operand_can_add_fast_transform_at_node_500():
    metadata, items, _ = synthetic_inputs()
    compiler = Graph(Translator([metadata], items, None))
    source_ir = Source("sentinel-2-l2a", ("scene-a",), ("nir",))
    input_pixel = Pixel("to_double", (Pixel("band", (source_ir, "nir")),))
    compiler.expression(input_pixel)
    assert 0 < len(compiler.graph) < 499
    for index in range(499 - len(compiler.graph)):
        compiler.graph[f"budget-{index}"] = {
            "process_id": "noop", "arguments": {},
        }

    result = compiler.expression(Pixel(
        "fast_distance",
        (input_pixel, prepare_fast_distance_spec(neighborhood=1)),
    ))
    assert len(compiler.graph) == 500
    assert result[1] == "v"
