import pytest
from gee.graph import validate,materialize
from gee.auth import redact
from gee.sync import checked

def valid_graph():
    return {'load':{'process_id':'load_collection','arguments':{'id':'test'}},
            'out':{'process_id':'save_result','arguments':{'data':{'from_node':'load'},'format':'GTiff'},'result':True}}

@pytest.mark.parametrize('pid',['run_udf','load_stac','load_url','run_cwl'])
def test_unsafe_process_rejected(pid):
    g=valid_graph();g['load']['process_id']=pid
    with pytest.raises(ValueError):validate(g)

def test_cycle_rejected():
    g=valid_graph();g['load']['arguments']['data']={'from_node':'out'}
    with pytest.raises(ValueError,match='循环'):validate(g)

def test_snapshot_uses_only_local_catalog():
    g=valid_graph();m=materialize(g,{'test':{}},'/job')
    assert m['load']['arguments']['url']=='/job/catalog-test.json'
    assert 'url' not in g['load']['arguments']

def test_path_output_option_denied():
    g=valid_graph();g['out']['arguments']['options']={'filename_prefix':'/etc/passwd'}
    with pytest.raises(ValueError):validate(g)

@pytest.mark.parametrize('url',['http://earth-search.aws.element84.com/v1','https://127.0.0.1/x','https://earth-search.aws.element84.com.evil.test/x','https://user:pw@earth-search.aws.element84.com/x'])
def test_provider_allowlist(url):
    with pytest.raises(ValueError):checked(url)

def test_redaction():
    assert 'sensitive' not in redact('Authorization: Bearer sensitive password=sensitive api_key=sensitive')

@pytest.mark.parametrize('value',['https://outside.example/a.geojson','/etc/passwd'])
def test_spatial_stat_requires_inline_geometry(value):
    with pytest.raises(ValueError,match='GeoJSON'):
        validate({'s':{'process_id':'aggregate_spatial','arguments':{'geometries':value},'result':True}})

def test_property_filter_is_not_silently_ignored():
    g=valid_graph();g['load']['arguments']['properties']={'eo:cloud_cover':{'process_graph':{'x':{'process_id':'lt','arguments':{'x':1,'y':2},'result':True}}}}
    with pytest.raises(ValueError,match='属性过滤'):validate(g)

def test_legacy_sentinel_source_rejected_before_io():
    from gee.ingest import optical_item
    with pytest.raises(ValueError,match='Collection 1'):
        optical_item({'collection':'sentinel-2-l2a'},'sentinel-2-l2a',[0,0,1,1])
