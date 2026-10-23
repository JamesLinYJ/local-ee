"""A cast must change physical type, and unsupported narrowing must be explicit."""
import json
import pytest
import numpy as np

from gee import graph
from gee.backend import Processes
from gee.integer_values_spec import constant_operand
from test_ee_translate import local, compile, call, evaluate_graph


def single():
    return call('Collection.first', collection=call('ImageCollection.load', id='sentinel-2-l2a'))


def test_double_emits_native_process_and_float_is_a_real_narrowing(local):
    double = call('Image.toDouble', value=single())
    for expression, expected in [(double, 'local_ee_to_double'), (call('Image.toFloat', value=double), 'local_ee_to_float')]:
        result = compile(expression, local)
        graph.validate(result['process_graph'])
        assert any(n['process_id'] == expected for n in result['process_graph'].values())


def test_double_math_uses_native_float64_and_float32_remains_explicit(local):
    double = call('Image.toDouble', value=single())
    native = compile(call('Image.add', image1=double, image2=1), local)
    graph.validate(native['process_graph'])
    integer = [node for node in native['process_graph'].values()
               if node['process_id'] == 'local_ee_integer_values']
    assert len(integer) == 5  # Image.first() retains the five source bands.
    assert [json.loads(node['arguments']['spec']) for node in integer] == [{
        'dtype': None, 'op': 'add',
        'operands': [{'band': 0}, constant_operand(1)], 'v': 1,
    }] * 5
    assert not any(node['process_id'] == 'reduce_dimension'
                   and node['arguments'].get('dimension') == 'bands'
                   for node in native['process_graph'].values())

    explicit_float = compile(
        call('Image.add', image1=call('Image.toFloat', value=double), image2=1), local,
    )
    graph.validate(explicit_float['process_graph'])
    assert not any(node['process_id'] == 'local_ee_integer_values'
                   for node in explicit_float['process_graph'].values())
    assert any(node['process_id'] == 'reduce_dimension'
               and node['arguments'].get('dimension') == 'bands'
               for node in explicit_float['process_graph'].values())
    collection = call('Collection.map', collection=call('ImageCollection.load', id='sentinel-2-l2a'), baseAlgorithm={
        'type':'Function','argumentNames':['im'],'body':call('Image.toDouble',value={'type':'ArgumentRef','value':'im'})})
    result = compile(call('reduce.mean',collection=collection),local)
    graph.validate(result['process_graph'])
    processes = {node['process_id'] for node in result['process_graph'].values()}
    assert {'local_ee_drop_single_time', 'local_ee_reduce_bands'} <= processes
    assert result['has_time_dimension'] is False


def test_local_cast_specs_and_canonical_top_level_boundary():
    registry = Processes().get_process_registry('1.2.0')
    assert registry.get_spec('local_ee_to_double')['parameters'][0]['name'] == 'data'
    for arguments in [{'data':'/untrusted/file'}, {'data':{'from_node':'load'},'dtype':'int32'}]:
        with pytest.raises(ValueError,match='top-level cube reference'):
            graph.validate({'load':{'process_id':'load_collection','arguments':{'id':'test'}},'cast':{
                'process_id':'local_ee_to_double','arguments':arguments,'result':True}})


@pytest.mark.parametrize("valid", [0, 1])
def test_constant_mask_preserves_double_values_and_missing_cells(local, valid):
    selected = call("Image.select", input=single(), bandSelectors=["red"])
    masked = call("Image.updateMask", image=call("Image.toDouble", value=selected),
                  mask=call("Image.constant", value=valid))
    result = compile(masked, local)
    graph.validate(result["process_graph"])
    data, names, timed = evaluate_graph(result, {"a": {"red": np.array([2**24 + 1., np.nan])}})
    np.testing.assert_array_equal(data, [[2**24 + 1. if valid else np.nan, np.nan]])
    assert names == ["red"] and not timed
    processes = [node["process_id"] for node in result["process_graph"].values()]
    assert "local_ee_drop_single_time" in processes
    assert "mask" in processes


def test_missing_boolean_mask_never_restores_float64_values(local):
    from gee.compat.earthengine.decoder import Translator
    from gee.compat.earthengine.graph import Graph
    from gee.compat.earthengine.ir import Image, Pixel, Source, const

    translator = Translator(*local, {})
    source = Source("sentinel-2-l2a", ("a",), ("red",))
    data = Pixel("reduce_t", (Pixel("to_double", (Pixel("band", (source, "red")),)), "first"))
    value = Pixel("if", (const(None), data, const(None)))
    compiler = Graph(translator)
    ref, _ = compiler.image(Image([("red", value)], {}, source))
    result = {"process_graph": compiler.finish(ref)}
    output, _, _ = evaluate_graph(result, {"a": {"red": np.array([2**24 + 1., np.nan])}})
    assert np.isnan(output).all()
