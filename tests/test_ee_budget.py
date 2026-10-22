import pytest

from gee.services.ee_budget import pixel_budget


def fixture():
    bbox={'west':113.55,'south':22.3,'east':113.57,'north':22.32}
    compiled={'process_graph':{'load':{'process_id':'load_collection','arguments':{'id':'s','_gee_item_ids':['a'],'bands':['red'],'spatial_extent':bbox},'result':True}}}
    items={'s':[{'id':'a','assets':{'red':{'proj:epsg':32649,'proj:transform':[10,0,762680,0,-10,2470510]}}}]}
    return compiled,items


def test_high_maxpixels_still_has_a_local_limit():
    c,i=fixture()
    result=pixel_budget(c,i,{'scale':10,'crs':'EPSG:32649'},1e13)
    assert 45000 < result['conservative_pixels_per_band'] < 60000
    assert result['local_limit']==100_000_000
    with pytest.raises(ValueError,match='exceeds'):
        pixel_budget(c,i,{'scale':.01,'crs':'EPSG:32649'},1e13)


def test_small_requested_limit_is_enforced():
    c,i=fixture()
    with pytest.raises(ValueError,match='exceeds'):pixel_budget(c,i,{},100)


@pytest.mark.parametrize('value',[False,0,-1,float('inf'),1.5])
def test_invalid_maxpixels(value):
    c,i=fixture()
    with pytest.raises(ValueError):pixel_budget(c,i,{},value)
