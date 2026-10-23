"""Explicit contracts for finite nested, aggregate and grouped table families."""

TABLE_FAMILY_LIMITS = {}

for _suffix in (
    'pearsonsCorrelation', 'spearmansCorrelation', 'kendallsCorrelation', 'sensSlope',
    'covariance', 'centeredCovariance', 'fixedHistogram', 'fixed2DHistogram',
    'toList', 'toCollection',
):
    TABLE_FAMILY_LIMITS['Reducer.' + _suffix] = [
        'Actual finite List/inline table kernels within closed composed reducer trees. '
        'Complete-case correlations and Sen median pair slopes; typed rank1 vectors '
        'for covariance with explicit n-1 denominator; fixed exact binary64 histogram '
        'bins; owned collected tuples/features with optional trailing null inputs. '
        'Original shared50000 work/1000rows/32inputs/10000arraycells/1MB output; '
        'quadratic pairwise algorithms can reject substantially below1000rows. '
        'No raster/Array.reduce/dynamic-table/weighted contexts. Some default output '
        'keys, Sen intercept and null/empty policies are local interpretations without '
        'Google oracle evidence; no complete parameter or numerical parity claim.'
    ]

for _name in (
    'DateRange.contains', 'DateRange.end', 'DateRange.intersection',
    'DateRange.intersects', 'DateRange.isEmpty', 'DateRange.isUnbounded',
    'DateRange.start', 'DateRange.union', 'DateRange.unbounded',
):
    TABLE_FAMILY_LIMITS[_name] = [
        'Finite half-open UTC millisecond intervals within ±2^53; actual interval algebra. '
        'Only contains accepts a Date point directly; pinned SDK promotes other scalar '
        'range operands through the one-millisecond constructor. Unbounded is typed IR, '
        'not an invented timestamp; direct endpoints/JSON/date-filter contexts reject. '
        'Empty intersections and bounding interval unions use documented local policies; '
        'shared50000 work and1MB output, no Google interval-edge parity.'
    ]

TABLE_FAMILY_LIMITS['Collection.flatten'] = [
    'Finite nested FeatureCollections from constructor or homogeneous map results; '
    'typed nested IR, depth96/nodes10000/immediate children1000/flattened rows1000. '
    'Depth-first source order, actual feature IDs/geometry/properties preserved; '
    'outer metadata retained, child collection metadata discarded by explicit local policy. '
    'Full validation and owned copies precharged within shared50000 work/1MB output. '
    'Empty flatten supported; mixed/dynamic/Image children and unflattened public IR reject. '
    'No remote vector engine or Google identity/metadata parity.'
]

for _suffix in (
    'first', 'count', 'count_distinct', 'min', 'max', 'mean', 'product',
    'sum', 'sample_sd', 'sample_var', 'total_sd', 'total_var', 'stats', 'histogram',
):
    TABLE_FAMILY_LIMITS['AggregateFeatureCollection.' + _suffix] = [
        'Actual bounded inline feature or declared finite image metadata, <=1000 rows; '
        'not sampled/RF table or pixel evaluation. Numeric statistics require finite '
        'numbers/exact integers<=2^53; min/max also support homogeneous strings. '
        'Missing/null/empty/singleton, Unicode ordering and histogram string-key collision '
        'policies documented locally. Bounded JSON, stable numerical kernels, precharged '
        'scans/copies/hash/output under shared50000 work/1MB; no Google numerical parity.'
    ]

for _name in ('Reducer.combine', 'Reducer.group', 'Reducer.setOutputs', 'Reducer.getOutputs',
              'Reducer.repeat', 'Reducer.forEach',
              'List.reduce', 'Collection.reduceColumns'):
    TABLE_FAMILY_LIMITS[_name] = [
        'Actual closed immutable reducer trees consumed by static List.reduce and inline '
        'FeatureCollection.reduceColumns. Scalar, regression and finite statistical leaves; '
        'shared/concatenated inputs, grouping, repetition, named copies and output renaming/removal. '
        'No raster/Array/runtime table consumer, nonempty weights or arbitrary reducer leaves. '
        'Depth16/nodes64/inputs32/outputs256/rows1000 plus shared50000 work/1MB output; '
        'owned JSON and typed arrays, explicit collision/null/group-order policies. '
        'No Google grouping/statistical parity.'
    ]

for _suffix in (
    'minMax', 'product', 'stdDev', 'variance', 'sampleVariance', 'countEvery',
    'countDistinct', 'countDistinctNonNull', 'firstNonNull', 'lastNonNull',
    'countRuns', 'frequencyHistogram', 'allNonZero', 'anyNonZero', 'and', 'or',
    'bitwiseAnd', 'bitwiseOr',
):
    TABLE_FAMILY_LIMITS['Reducer.' + _suffix] = [
        'Actual finite static List.reduce or inline FeatureCollection.reduceColumns only; '
        'closed immutable leaf, also usable inside combine/group/repeat/forEach/setOutputs. '
        'At most1000rows; shared50000 work and1MB output. Numeric finite exact inputs, '
        'population/sample dispersion distinguished, bounded discrete identities and owned '
        'first/last values. Documented empty/null/bitwise/frequency-key policies; no raster, '
        'Array, sampled/classified runtime table, fractional weights or Google parity claim.'
    ]
