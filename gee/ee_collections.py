"""Finite EE image-axis operations; no code execution or invented timestamps."""
from dataclasses import replace

from .compat.earthengine.ir import Collection, Image, ImageSequence, Function, Filter, Pixel, Reducer, as_image, fail, integer, rebind


def frames(t, value):
    if isinstance(value, ImageSequence):return value.images
    if isinstance(value, Collection):
        if len(value.source.ids)>1000:fail('Explicit image collections are limited to 1000 frames')
        return [t.first(rebind(value,[iid])) for iid in value.source.ids]
    fail('Expected an ImageCollection')


def reduce_sequence(t, sequence, reducer, suffix=False):
    images=sequence.images
    if not images:fail('Cannot reduce an empty local ImageCollection')
    names=[n for n,_ in images[0].bands if all(n in dict(im.bands) for im in images)]
    if not names:fail('ImageCollection has no common band names to reduce')
    label='stdDev' if reducer=='sd' else reducer
    bands=[(name+('_'+label if suffix else ''),Pixel('reduce_bands',(tuple(dict(im.bands)[name] for im in images),reducer))) for name in names]
    # Footprints can differ by period. Keep their union, rather than inheriting
    # the first frame's clip geometry or a fabricated observation date.
    footprint=t.footprint(sequence)
    return Image(bands,{},images[0].source,inherit_props=False,footprint=footprint,footprint_is_absolute=True)


def invoke_sequence(t, name, a):
    if name=='ImageCollection.fromImages':
        t.allowed(a,{'images'}); images=a['images']
        if not isinstance(images,list) or len(images)>1000:fail('fromImages requires at most 1000 explicit Images')
        result=[]
        for index,image in enumerate(images):
            image=as_image(image)
            result.append(replace(image,props={'system:index':str(index),**image.props}))
        return ImageSequence(result)
    if name=='ImageCollection.merge':
        t.allowed(a,{'collection1','collection2'})
        images=frames(t,a['collection1'])+frames(t,a['collection2'])
        if len(images)>1000:fail('Merged ImageCollection exceeds 1000 frames')
        return ImageSequence(images)
    sequence=a['collection']; images=sequence.images
    if name=='Collection.size':
        t.allowed(a,{'collection'});return len(images)
    if name=='Collection.first':
        t.allowed(a,{'collection'})
        if not images:fail('Cannot take first image of an empty collection')
        return images[0]
    if name=='Collection.toList':
        t.allowed(a,{'collection','count','offset'})
        count=integer(a['count'],'Collection count',0); offset=integer(a.get('offset',0),'Collection offset',0)
        if count>1000:fail('Collection.toList supports at most 1000 images')
        return images[offset:offset+count]
    if name=='Collection.map':
        t.allowed(a,{'collection','baseAlgorithm','dropNulls'});fun=a['baseAlgorithm']
        if not isinstance(fun,Function) or len(fun.names)!=1:fail('map requires a one-argument serialized callback')
        result=[]
        for image in images:
            value=t.evaluate(fun.body,{**fun.env,fun.names[0]:image})
            if value is None and a.get('dropNulls'):continue
            if not isinstance(value,Image):fail('ImageCollection.map must return an Image')
            result.append(value)
        return ImageSequence(result)
    if name=='Collection.filter':
        t.allowed(a,{'collection','filter'});f=a['filter']
        if not isinstance(f,Filter):fail('Expected an ee.Filter')
        def spatial(f):
            if f.name=='intersects':return True
            if f.name in {'and','or'}:return any(spatial(child) for child in f.args['filters'])
            return f.name=='not' and spatial(f.args['filter'])
        return ImageSequence([im for im in images if t.matches(f,{'geometry':t.footprint(im) if spatial(f) else None,'properties':im.props})])
    if name in {'Collection.limit','Collection.sort'}:
        t.allowed(a,{'collection','key','ascending','limit'});images=list(images)
        if a.get('key') is not None:
            key=a['key']
            if any(key not in im.props for im in images):fail('Sort property is unavailable: '+str(key))
            images.sort(key=lambda im:im.props[key],reverse=not a.get('ascending',True))
        if a.get('limit') is not None:images=images[:integer(a['limit'],'Collection limit',0)]
        return ImageSequence(images)
    if name=='AggregateFeatureCollection.array':
        t.allowed(a,{'collection','property'});key=a['property']
        if any(key not in im.props for im in images):fail('Item metadata property is unavailable: '+str(key))
        return [im.props[key] for im in images]
    if name=='Collection.geometry':
        t.allowed(a,{'collection','maxError'});return t.footprint(sequence)
    if name=='ImageCollection.toBands':
        t.allowed(a,{'collection'});bands=[]
        for image in images:
            index=image.props.get('system:index')
            if not isinstance(index,str):fail('toBands requires system:index on each image')
            bands.extend((index+'_'+n,p) for n,p in image.bands)
        if len(bands)>100:fail('Local toBands is limited to 100 output bands')
        if not images or len({n for n,_ in bands})!=len(bands):fail('toBands needs nonempty images with distinct output band names')
        return Image(bands,{},images[0].source,inherit_props=False,footprint=t.footprint(sequence),footprint_is_absolute=True)
    if name=='ImageCollection.mosaic':
        t.allowed(a,{'collection'});return reduce_sequence(t,sequence,'last')
    if name.startswith('reduce.'):
        t.allowed(a,{'collection'});reducer=name.split('.',1)[1]
        if reducer not in {'median','mean','min','max','sum','count'}:fail('Unsupported collection reducer: '+reducer)
        return reduce_sequence(t,sequence,reducer)
    if name=='ImageCollection.reduce':
        t.allowed(a,{'collection','reducer','parallelScale'})
        parallel=a.get('parallelScale',1)
        if isinstance(parallel,bool) or not isinstance(parallel,(int,float)) or not 1<=parallel<1e6:fail('parallelScale must be finite and >= 1')
        if not isinstance(a['reducer'],Reducer):fail('Expected a supported single-output reducer')
        return reduce_sequence(t,sequence,a['reducer'].name,suffix=True)
    fail('Unsupported operation on an explicitly constructed ImageCollection: '+name)
