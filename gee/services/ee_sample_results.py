"""Owned, bounded sampled-feature results for the existing EE task protocol."""
from __future__ import annotations

from ..artifacts import artifact_path
from ..sampling_spec import decode_sampling_spec
from ..sampling_values import read_sample_csv


def result_context(compiled):
    text = compiled['sample_spec']
    decode_sampling_spec(text)
    return {'result_kind': 'samples', 'sample_spec': text}


def read_result(root, row):
    """The dispatcher checks identity/parent scope and finished state first."""
    context = row.get('context', {})
    if context.get('protocol') != 'earthengine' or context.get('result_kind') != 'samples':
        raise ValueError('Task is not a sampled-feature value result')
    spec = decode_sampling_spec(context.get('sample_spec'))
    names = [name for name in row['assets'] if name.endswith('.csv')]
    if len(names) != 1:
        raise ValueError('Expected one sampled-feature CSV result')
    path = artifact_path(root, row['id'], names[0])
    return read_sample_csv(path, spec)
