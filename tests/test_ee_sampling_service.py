"""Sample task protocol with real CSV IO; storage/queue and pixels are fixtures.

This is not a Spark, native process, browser or Google acceptance test.
"""
from __future__ import annotations

import copy
import csv
import json

import pytest

from ee_sampling_workflow_helpers import (
    compile_inputs, load_fixture, reference_sample_rows,
)
from engine.ee_sampling_result import SampledFeatureTable
from gee import graph
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from gee.sampling_values import assemble_sample_features
from gee.services import ee as service
from gee.services.ee_budget import sample_input_budget
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import FinishedTask, USER, install


@pytest.fixture
def integration(tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        data = load_fixture()
        catalog, items, _, _ = compile_inputs(data)
        for item in items[data['collection_id']]:
            item['assets'] = {
                band: {'proj:shape': [3, 4], 'proj:epsg': 4326,
                       'proj:transform': [1, 0, 0, 0, -1, 3]}
                for band in data['catalog_bands']
            }
        monkeypatch.setattr(service, 'catalog_snapshot', lambda: (catalog, items))
        monkeypatch.setattr(service, 'DATA', tmp_path)
        fixture.source = data
        fixture.catalog = catalog
        fixture.items = items
        yield fixture
    assert guard.evidence()['attempt_count'] == 0


def expression(fixture):
    ee, data = fixture.ee, fixture.source
    image = ee.Image(data['items'][0]['id']).select(data['input_properties'])
    samples = image.sampleRegions(
        collection=ee.FeatureCollection(data['training_features']),
        properties=data['sample_properties'], geometries=True,
    )
    return ee.serializer.encode(samples, for_cloud_api=False)


def finish_with_fixture_pixels(fixture, row, *, empty=False):
    """Real SaveResult and worker finish; only sampled pixel production is faked."""
    sampler = next(node for node in row['process']['process_graph'].values()
                   if node['process_id'] == 'local_ee_sample_regions')
    spec = decode_sampling_spec(sampler['arguments']['spec'])
    rows = [] if empty else [
        {key: value[key] for key in ('feature', 'row', 'col', 'x', 'y', 'values')}
        for value in reference_sample_rows(fixture.source)
    ]
    data = assemble_sample_features(spec, rows)
    folder = fixture.root / 'jobs' / row['id'] / 'out'
    folder.mkdir(parents=True)
    SampledFeatureTable(data, sampling_columns(spec)).write_assets(folder / 'out')
    row['status'] = 'running'
    fixture.worker.finish(row, FinishedTask())
    assert row['status'] == 'finished'
    return data


@pytest.mark.parametrize('empty', [False, True])
def test_sample_evaluation_queue_csv_and_owned_result(integration, empty):
    fixture = integration
    response = fixture.dispatch({'action': 'evaluate', 'expression': expression(fixture)})
    assert response['pending'] is True
    row = fixture.store.job(response['job_id'], USER)
    assert row['status'] == 'queued' and row['language'] == 'python'
    assert row['context']['source_job_id'] == fixture.store.parent_id
    assert row['context']['sample_budget']['input_asset_grid_cells'] == 24
    assert fixture.dispatch({'action': 'result', 'job_id': row['id']})['pending'] is True
    graph.validate(row['process']['process_graph'])
    data = finish_with_fixture_pixels(fixture, row, empty=empty)
    result = fixture.dispatch({'action': 'result', 'job_id': row['id']})['value']
    assert result == data
    assert len(result['features']) == (0 if empty else 11)
    if not empty:
        assert result['features'][0]['properties']['red'] == 1
        assert result['features'][0]['id'] == 'f0_r0_c1'
    sibling = {**fixture.account, 'job_id': fixture.store.sibling_id}
    from openeo_driver.errors import JobNotFoundException

    for action in ('result', 'status', 'cancel'):
        with pytest.raises(JobNotFoundException):
            service.dispatch(fixture.backend, sibling, {'action': action, 'job_id': row['id']})
    with pytest.raises(JobNotFoundException):
        service.dispatch(fixture.backend, {'user_id': 'other', 'scope': 'session'},
                         {'action': 'result', 'job_id': row['id']})


def test_sample_export_preserves_selectors_prefix_and_idempotency(integration):
    fixture = integration
    request = {'action': 'export_table', 'expression': expression(fixture),
               'request_id': 'wave24-sampled-export',
               'options': {'fileNamePrefix': '样本', 'fileFormat': 'CSV',
                           'selectors': ['nir', 'system:index', 'plot_id']}}
    response = fixture.dispatch(request)
    assert fixture.dispatch(request)['job_id'] == response['job_id']
    row = fixture.store.job(response['job_id'], USER)
    assert row['status'] == 'created'
    fixture.dispatch({'action': 'start', 'job_id': row['id']})
    finish_with_fixture_pixels(fixture, row)
    assert set(row['assets']) == {'样本.csv'}
    path = fixture.root / 'jobs' / row['id'] / 'out' / '样本.csv'
    with path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        records = list(reader)
    assert reader.fieldnames == request['options']['selectors']
    assert len(records) == 11 and float(records[0]['nir']) == 3
    changed = copy.deepcopy(request)
    changed['options']['selectors'] = ['red']
    from openeo_driver.errors import OpenEOApiException

    with pytest.raises(OpenEOApiException):
        fixture.dispatch(changed)
    assert fixture.backend.batch_jobs.create_calls == 1


def test_invalid_sample_actions_or_metadata_do_not_enqueue(integration):
    fixture = integration
    value = expression(fixture)
    for action, options in [('map', {}), ('export_image', {}),
                            ('export_table', {'fileFormat': 'GeoJSON'}),
                            ('export_table', {'selectors': ['missing']})]:
        with pytest.raises((ValueError, TypeError)):
            fixture.dispatch({'action': action, 'expression': value, 'options': options})
    for item in fixture.items[fixture.source['collection_id']]:
        item['assets']['red'].pop('proj:shape')
    with pytest.raises(ValueError, match='preflight'):
        fixture.dispatch({'action': 'evaluate', 'expression': value})
    assert fixture.backend.batch_jobs.create_calls == 0


def test_sampling_preflight_counts_ancestors_only_and_retains_runtime_guard():
    load = {'process_id': 'load_collection', 'arguments': {
        'id': 'local', '_gee_item_ids': ['a'], 'bands': ['b'],
        'spatial_extent': {'west': 0, 'south': 0, 'east': 1, 'north': 1}}}
    compiled = {'process_graph': {
        'load': load, 'unrelated': copy.deepcopy(load),
        'sample': {'process_id': 'local_ee_sample_regions', 'arguments': {
            'data': {'from_node': 'load'}, 'spec': '{"from_node":"unrelated"}'}}}}
    asset = {'proj:shape': [10, 10], 'proj:transform': [.1, 0, 0, 0, -.1, 1],
             'proj:epsg': 4326}
    items = {'local': [{'id': 'a', 'assets': {'b': asset}}]}
    result = sample_input_budget(compiled, items)
    assert result['input_asset_grid_cells'] == 100
    assert result['runtime_tile_grid_key_work_limits'] == 'separately enforced by native sampler'
    asset['proj:shape'] = [100_000, 100_000]
    asset['proj:transform'] = [.00001, 0, 0, 0, -.00001, 1]
    with pytest.raises(ValueError, match='100000000'):
        sample_input_budget(compiled, items)
    asset['proj:transform'][0] = float('nan')
    with pytest.raises(ValueError, match='metadata'):
        sample_input_budget(compiled, items)
