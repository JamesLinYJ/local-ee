"""Bounded local raster rendering; display styles never modify scientific results."""
import re
import numpy as np
from PIL import ImageColor


def color(text):
    if re.fullmatch(r'[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8}',text):text='#'+text
    values=ImageColor.getrgb(text)
    if len(values)!=3:raise ValueError('Palette alpha is not supported; use layer opacity')
    return values


def rgba(array,style=None,palette='vegetation'):
    style=style or {}
    if array.ndim!=3 or array.shape[0] not in {1,3}:raise ValueError('Preview requires one or three bands')
    valid=(~np.ma.getmaskarray(array)&np.isfinite(array.data)).all(axis=0)
    def channel_values(key,default):
        values=style.get(key,default)
        values=values if isinstance(values,list) else [values]*len(array)
        if len(values)!=len(array):raise ValueError(key+' must have one value per display band')
        if not np.isfinite(values).all():raise ValueError('Nonfinite preview style')
        return values
    defaults_low=[float(np.percentile(b.data[valid],2)) if valid.any() else 0 for b in array]
    defaults_high=[float(np.percentile(b.data[valid],98)) if valid.any() else 1 for b in array]
    lows=channel_values('min',defaults_low);highs=channel_values('max',defaults_high);gammas=channel_values('gamma',1)
    bands=[]
    for b,low,high,gamma in zip(array,lows,highs,gammas):
        if high<low or gamma<=0:raise ValueError('Invalid min/max/gamma')
        v=np.clip((b.filled(low)-low)/(high-low or 1),0,1)
        bands.append(v**(1/gamma))
    if len(array)==3:
        if 'palette' in style:raise ValueError('Palette requires one display band')
        rgb=np.stack(bands,axis=-1)*255
    else:
        v=bands[0]
        if 'palette' in style:
            colors=np.asarray([color(x) for x in style['palette']],dtype=float)
            positions=np.linspace(0,1,len(colors))
            rgb=np.stack([np.interp(v,positions,colors[:,i]) for i in range(3)],axis=-1)
        elif palette=='water':rgb=np.stack([30+v*20,50+v*140,100+v*150],axis=-1)
        elif palette=='gray':rgb=np.stack([v*255]*3,axis=-1)
        else:rgb=np.stack([210-v*180,190-v*55,125-v*70],axis=-1)
    return np.concatenate([rgb,valid[:,:,None]*255],axis=-1).astype('uint8')
