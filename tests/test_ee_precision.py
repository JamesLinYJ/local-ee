"""A cast must change physical type, and unsupported narrowing must be explicit."""
import pytest

from gee import graph
from gee.backend import Processes
from gee.ee_translate import UnsupportedEEError
from test_ee_translate import local, compile, call


def single():
    return call('Collection.first', collection=call('ImageCollection.load', id='sentinel-2-l2a'))


def test_double_emits_native_process_and_float_is_a_real_narrowing(local):
    double = call('Image.toDouble', value=single())
    for expression, expected in [(double, 'local_ee_to_double'), (call('Image.toFloat', value=double), 'local_ee_to_float')]:
        result = compile(expression, local)
        graph.validate(result['process_graph'])
        assert any(n['process_id'] == expected for n in result['process_graph'].values())


def test_double_math_rejects_implicit_float32_narrowing(local):
    double = call('Image.toDouble', value=single())
    with pytest.raises(UnsupportedEEError, match='Float64 pixel arithmetic'):
        compile(call('Image.add', image1=double, image2=1),local)
    compile(call('Image.add', image1=call('Image.toFloat', value=double), image2=1),local)
    collection = call('Collection.map', collection=call('ImageCollection.load', id='sentinel-2-l2a'), baseAlgorithm={
        'type':'Function','argumentNames':['im'],'body':call('Image.toDouble',value={'type':'ArgumentRef','value':'im'})})
    with pytest.raises(UnsupportedEEError, match='Float64 temporal reductions'):
        compile(call('reduce.mean',collection=collection),local)


def test_local_cast_specs_and_canonical_top_level_boundary():
    registry = Processes().get_process_registry('1.2.0')
    assert registry.get_spec('local_ee_to_double')['parameters'][0]['name'] == 'data'
    for arguments in [{'data':'/untrusted/file'}, {'data':{'from_node':'load'},'dtype':'int32'}]:
        with pytest.raises(ValueError,match='top-level cube reference'):
            graph.validate({'load':{'process_id':'load_collection','arguments':{'id':'test'}},'cast':{
                'process_id':'local_ee_to_double','arguments':arguments,'result':True}})
