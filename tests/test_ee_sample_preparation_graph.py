"""Strict raster/table producer types and immutable operation specifications."""
import copy

import pytest

from ee_sampling_contract_helpers import _valid_sampling_graph
from gee.graph import validate
from gee.local_processes import process_spec, validate_local_process
from gee.remap_spec import prepare_remap_spec
from gee.sample_table_spec import prepare_sample_limit


def prepared_graph(count=1):
    graph = _valid_sampling_graph()
    previous = 'samples'
    for i in range(count):
        key = f'operation{i}'
        graph[key] = {'process_id': 'local_ee_sample_table_op', 'arguments': {
            'data': {'from_node': previous}, 'spec': prepare_sample_limit(None)}}
        previous = key
    graph['model']['arguments']['data'] = {'from_node': previous}
    return graph


def test_sixteen_audited_operations_can_feed_training_with_original_columns():
    graph = prepared_graph(16)
    before = copy.deepcopy(graph)
    validate(graph)
    assert graph == before
    with pytest.raises(ValueError, match='16 operations'):
        validate(prepared_graph(17))


@pytest.mark.parametrize('source', ['source', 'model', 'classify'])
def test_sample_operation_cannot_use_other_types_as_its_producer(source):
    graph = prepared_graph()
    graph['operation0']['arguments']['data'] = {'from_node': source}
    with pytest.raises(ValueError, match='sample_regions|cycle'):
        validate(graph)


def test_operation_cycle_is_rejected_before_model_schema_traversal():
    graph = prepared_graph(2)
    graph['operation0']['arguments']['data'] = {'from_node': 'operation1'}
    with pytest.raises(ValueError, match='cycle'):
        validate(graph)


@pytest.mark.parametrize('process', ['local_ee_remap', 'local_ee_sample_regions'])
def test_prepared_feature_table_cannot_be_used_as_raster(process):
    graph = prepared_graph()
    if process == 'local_ee_remap':
        graph['bad'] = {'process_id': process, 'arguments': {
            'data': {'from_node': 'operation0'}, 'spec': prepare_remap_spec([1], [2])}}
    else:
        graph['samples']['arguments']['data'] = {'from_node': 'operation0'}
    with pytest.raises(ValueError, match='raster cube|cycle'):
        validate(graph)


@pytest.mark.parametrize('process,spec', [
    ('local_ee_remap', prepare_remap_spec([1], [2])),
    ('local_ee_sample_table_op', prepare_sample_limit(1)),
])
def test_new_processes_require_exact_arguments_and_top_level_string_refs(process, spec):
    arguments = {'data': {'from_node': 'input'}, 'spec': spec}
    validate_local_process(process, arguments, 0)
    assert process_spec(process)['experimental'] is True
    for malformed in [
        {**arguments, 'extra': True},
        {**arguments, 'spec': {'process_id': 'add'}},
        {**arguments, 'data': {'from_node': 1}},
        {**arguments, 'data': {'from_parameter': 'data'}},
    ]:
        with pytest.raises(ValueError):
            validate_local_process(process, malformed, 0)
    with pytest.raises(ValueError):
        validate_local_process(process, arguments, 1)
