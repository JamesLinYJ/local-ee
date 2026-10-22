"""Canonical, bounded feature predicates and order-preserving sample operations."""
from __future__ import annotations

import math

from .sampling_spec import _parse, encode_spec


MAX_OPERATION_BYTES = 16_384
MAX_OPERATIONS = 16
MAX_PREDICATES = 64
MAX_DEPTH = 16
_BINARY = {'equals', 'lessThan', 'greaterThan', 'stringContains', 'inList', 'listContains', 'maxDifference'}
_OPERANDS = {'leftField', 'leftValue', 'rightField', 'rightValue'}


def _field(value):
    if type(value) is not str or not value or len(value) > 256 or '.' in value:
        raise ValueError('Sample filters require nonempty flat field names <=256 characters')


def _scalar(value):
    if type(value) is bool:
        return
    if type(value) is str and len(value) <= 4096:
        return
    try:
        if (type(value) in (int, float) and math.isfinite(value)
                and (type(value) is not int or abs(value) <= 2**53)):
            return
    except OverflowError:
        pass
    raise ValueError('Sample filter literals must be bounded finite scalar values, without null')


def _literal(value):
    if type(value) is list:
        if len(value) > 64:
            raise ValueError('Sample filter literal lists support at most64 scalar values')
        for child in value:
            _scalar(child)
    else:
        _scalar(value)


def _predicate(value, *, from_ir=False):
    from .compat.earthengine.ir import Filter

    budget = [0]

    def visit(node, depth):
        budget[0] += 1
        if budget[0] > MAX_PREDICATES or depth > MAX_DEPTH:
            raise ValueError('Sample predicates exceed64 nodes or depth16')
        if from_ir:
            if not isinstance(node, Filter):
                raise ValueError('Sample filter requires a serialized ee.Filter')
            name, arguments = node.name, node.args
        else:
            if type(node) is not dict or set(node) != {'name', 'arguments'}:
                raise ValueError('Sample predicate requires exactly name/arguments')
            name, arguments = node['name'], node['arguments']
        if type(name) is not str or type(arguments) is not dict:
            raise ValueError('Invalid sample predicate name/arguments')
        if name in {'and', 'or'}:
            children = arguments.get('filters')
            if (set(arguments) != {'filters'} or type(children) is not list
                    or len(children) > 64):
                raise ValueError('Sample boolean filters require0..64 child filters')
            normalized = {'filters': [visit(child, depth + 1) for child in children]}
        elif name == 'not':
            if set(arguments) != {'filter'}:
                raise ValueError('Sample Filter.not requires exactly one filter')
            normalized = {'filter': visit(arguments['filter'], depth + 1)}
        elif name == 'notNull':
            fields = arguments.get('properties')
            if (set(arguments) != {'properties'} or type(fields) is not list
                    or len(fields) > 64):
                raise ValueError('Sample Filter.notNull requires0..64 flat fields')
            for field in fields:
                _field(field)
            normalized = {'properties': fields.copy()}
        elif name in _BINARY:
            allowed = _OPERANDS | ({'difference'} if name == 'maxDifference' else set())
            if set(arguments) - allowed:
                raise ValueError('Unsupported sample filter operands')
            normalized = dict(arguments)
            for side in ('left', 'right'):
                field, literal = side + 'Field', side + 'Value'
                if (field in arguments) == (literal in arguments):
                    raise ValueError('Sample filters require exactly one field/value per side')
                if field in arguments:
                    _field(arguments[field])
                elif name in {'inList', 'listContains'}:
                    _literal(arguments[literal])
                else:
                    _scalar(arguments[literal])
            if name == 'maxDifference':
                difference = arguments.get('difference')
                _scalar(difference)
                if type(difference) not in (int, float) or difference < 0:
                    raise ValueError('Sample maxDifference must be a finite nonnegative number')
        else:
            raise ValueError('Unsupported sampled feature filter: ' + name)
        return {'name': name, 'arguments': normalized}

    return visit(value, 0)


def decode_sample_predicate(value):
    """Construct only the already implemented predicate IR, never executable code."""
    from .compat.earthengine.ir import Filter

    checked = _predicate(value)

    def build(node):
        name, args = node['name'], dict(node['arguments'])
        if name in {'and', 'or'}:
            args['filters'] = [build(child) for child in args['filters']]
        elif name == 'not':
            args['filter'] = build(args['filter'])
        return Filter(name, args)

    return build(checked)


def decode_sample_operation(text):
    if type(text) is not str or len(text.encode('utf-8')) > MAX_OPERATION_BYTES:
        raise ValueError('Sample operation must be bounded canonical JSON <=16384 bytes')
    spec = _parse(text)
    if (type(spec) is not dict or type(spec.get('version')) is not int
            or spec['version'] != 1):
        raise ValueError('Unsupported sample operation version')
    operation = spec.get('operation')
    if operation == 'filter' and set(spec) == {'version', 'operation', 'predicate'}:
        _predicate(spec['predicate'])
    elif operation == 'limit' and set(spec) == {'version', 'operation', 'count'}:
        count = spec['count']
        if count is not None and (type(count) is not int or not 0 <= count <= 1000):
            raise ValueError('Sample limit must be null or integer0..1000')
    elif operation == 'random_column':
        from .random_column_spec import validate_random_column_spec

        validate_random_column_spec(spec)
    else:
        raise ValueError('Unsupported sample operation or fields')
    return spec


def prepare_sample_filter(filt):
    text = encode_spec({'version': 1, 'operation': 'filter', 'predicate': _predicate(filt, from_ir=True)})
    decode_sample_operation(text)
    return text


def prepare_sample_limit(count):
    text = encode_spec({'version': 1, 'operation': 'limit', 'count': count})
    decode_sample_operation(text)
    return text
