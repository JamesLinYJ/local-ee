"""Pixel quality must select one scene for all bands, including its masks."""
import copy
import numpy as np
import pytest

from test_ee_translate import call, col, compile, evaluate_graph, local, loads
from gee.ee_translate import UnsupportedEEError


def samples():
    quality = [[1,4,np.nan,2,np.nan,7,3,-9],
               [3,4,2,1,np.nan,np.nan,-1,-7],
               [2,1,5,np.nan,np.nan,6,np.nan,-8]]
    payload = [[10,40,90,np.nan,50,70,30,91],
               [30,np.nan,20,10,60,80,11,71],
               [20,10,np.nan,40,70,60,12,81]]
    return {key: {'nir': np.array(q,dtype=float), 'red': np.array(v,dtype=float)}
            for key,q,v in zip('abc',quality,payload)}


def composite(collection):
    selected = call('Image.select', input=collection, bandSelectors=['nir','red'])
    return call('ImageCollection.qualityMosaic', collection=selected, qualityBand='nir')


def independent_reference(arrays, order):
    quality=np.stack([arrays[key]['nir'] for key in order])
    valid=np.isfinite(quality)
    # Reverse argmax selects the last equal-quality scene without a shared
    # conditional implementation with the compiler.
    index=len(order)-1-np.argmax(np.where(valid,quality,-np.inf)[::-1],axis=0)
    values=[]
    for name in ['nir','red']:
        data=np.stack([arrays[key][name] for key in order])
        chosen=np.take_along_axis(data,index[None,:],axis=0)[0]
        values.append(np.where(valid.any(axis=0),chosen,np.nan))
    return np.stack(values)


@pytest.mark.parametrize('explicit', [False,True])
@pytest.mark.parametrize('reverse', [False,True])
def test_quality_keeps_scene_coherence_and_mask(local,explicit,reverse):
    collection=col()
    if explicit:
        collection=call('ImageCollection.fromImages',images=call('Collection.toList',collection=collection,count=3))
    if reverse:
        collection=call('Collection.limit',collection=collection,key='system:time_start',ascending=False)
    result=compile(composite(collection),local)
    actual=evaluate_graph(result,samples())[0]
    np.testing.assert_allclose(actual,independent_reference(samples(),'cba' if reverse else 'abc'),equal_nan=True)
    assert result['bands']==['nir','red']
    assert result['properties']=={} and not result['has_time_dimension']
    assert 'tie policy' in ' '.join(result['warnings'])


def test_quality_same_day_frames_are_not_collapsed(local):
    metadata=copy.deepcopy(local)
    for item in metadata[1]['sentinel-2-l2a']:
        item['properties']['system:time_start']=1000
    result=compile(composite(col()),metadata)
    assert len(loads(result))==3
    np.testing.assert_allclose(evaluate_graph(result,samples())[0],independent_reference(samples(),'abc'),equal_nan=True)


def test_quality_rejects_missing_band_empty_collection_and_extra_options(local):
    with pytest.raises(UnsupportedEEError,match='quality band'):
        compile(call('ImageCollection.qualityMosaic',collection=col(),qualityBand='QA60'),local)
    with pytest.raises(UnsupportedEEError,match='empty'):
        compile(call('ImageCollection.qualityMosaic',collection=call('ImageCollection.fromImages',images=[]),qualityBand='nir'),local)
    with pytest.raises(UnsupportedEEError,match='arguments'):
        compile(call('ImageCollection.qualityMosaic',collection=col(),qualityBand='nir',ignored=True),local)


def test_quality_preserves_distinct_scene_payloads_under_same_quality(local):
    arrays=samples()
    for key in arrays:arrays[key]['nir']=np.ones(8)
    result=compile(composite(col()),local)
    actual=evaluate_graph(result,arrays)[0]
    np.testing.assert_allclose(actual[1],arrays['c']['red'],equal_nan=True)
