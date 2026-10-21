import numpy as np
import pytest
from gee.services.raster_preview import rgba


def test_rgb_channels_gamma_and_joint_nodata():
    values=np.ma.array([[[0,100]],[[25,75]],[[100,0]]],mask=False,dtype=float)
    out=rgba(values,{'min':0,'max':100,'gamma':1})
    assert out.tolist()==[[[0,63,255,255],[255,191,0,255]]]
    values.mask[1,0,1]=True
    assert rgba(values,{'min':0,'max':100})[0,1,3]==0
    assert rgba(np.ma.array([[[.25]]]),{'min':0,'max':1,'gamma':2},'gray')[0,0,0]==127


def test_custom_palette_interpolation():
    out=rgba(np.ma.array([[[0,.5,1]]]),{'min':0,'max':1,'palette':['000000','ff0000','ffffff']})
    assert out.tolist()==[[[0,0,0,255],[255,0,0,255],[255,255,255,255]]]


@pytest.mark.parametrize('style',[{'min':2,'max':1},{'gamma':0},{'min':[0,1]},{'palette':['#ffff'] }])
def test_invalid_display_styles_rejected(style):
    with pytest.raises(ValueError):rgba(np.ma.array([[[0.]]]),style)
