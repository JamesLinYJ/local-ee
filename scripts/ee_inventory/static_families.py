"""Explicit local limits for batch static EE operator families."""

STATIC_FAMILY_LIMITS = {}

NUMBER_FUNCTIONS = (
    'Number.acos', 'Number.and', 'Number.asin',
    'Number.atan', 'Number.cbrt', 'Number.clamp',
    'Number.cosh', 'Number.erf', 'Number.erfc',
    'Number.exp', 'Number.first', 'Number.firstNonZero',
    'Number.first_nonzero', 'Number.gamma', 'Number.log',
    'Number.log10', 'Number.max', 'Number.min',
    'Number.not', 'Number.or', 'Number.signum',
    'Number.sinh', 'Number.tan', 'Number.tanh',
    'Number.unitScale',
)
for _name in NUMBER_FUNCTIONS:
    STATIC_FAMILY_LIMITS[_name] = ['Finite static numeric operands, exact integer magnitude<=2^53, true finite libm/Fraction computation; domain/nonfinite/overflow reject. All operands checked including first/firstNonZero. Clamp reversed bounds reject; unitScale equal bounds returns0 and does not clamp outside values. Float64/libm/zero-bound policies are local without Google parity. Shared50000 compiler work/output1MB.']

ARRAY_FUNCTIONS = (
    'Array.acos', 'Array.and', 'Array.asin',
    'Array.atan', 'Array.cbrt', 'Array.ceil',
    'Array.cos', 'Array.cosh', 'Array.eq',
    'Array.erf', 'Array.erfc', 'Array.exp',
    'Array.first', 'Array.firstNonZero', 'Array.first_nonzero',
    'Array.floor', 'Array.gamma', 'Array.gt',
    'Array.gte', 'Array.log', 'Array.log10',
    'Array.lt', 'Array.lte', 'Array.max',
    'Array.min', 'Array.mod', 'Array.neq',
    'Array.not', 'Array.or', 'Array.pow',
    'Array.round', 'Array.signum', 'Array.sin',
    'Array.sinh', 'Array.tan', 'Array.tanh',
)
for _name in ARRAY_FUNCTIONS:
    STATIC_FAMILY_LIMITS[_name] = ['Actual elementwise finite numeric math; exact same shape, no broadcast; rank8/cells10000/shared50000 work, precharged kernels, owned readonly outputs. Exact integer powers reject before huge allocations; mod retains dividend sign; round uses existing tie-toward-positive-infinity policy. Non-real/nonfinite/overflow and typed dynamic operands reject. No Google dtype/numerical equivalence or raster-array implementation implied.']

LIST_FUNCTIONS = (
    'List.containsAll', 'List.equals', 'List.frequency',
    'List.getArray', 'List.getGeometry', 'List.getNumber',
    'List.getString', 'List.indexOf', 'List.indexOfSublist',
    'List.insert', 'List.join', 'List.lastIndexOfSubList',
    'List.remove', 'List.removeAll', 'List.replace',
    'List.replaceAll', 'List.rotate', 'List.splice',
)
for _name in LIST_FUNCTIONS:
    STATIC_FAMILY_LIMITS[_name] = ['Bounded static lists up to10000values subject to shared50000 work/output1MB; structural comparisons retain existing typed-array/bool rules. Input ownership preserved; negative index/empty/null/duplicate policies tested. Positive rotate uses local rightward convention; join formatting and typed getters have documented finite scope. No Google runtime/value formatting or arbitrary dynamic-list parity.']

DICTIONARY_FUNCTIONS = (
    'Dictionary.combine', 'Dictionary.fromLists', 'Dictionary.getArray',
    'Dictionary.getGeometry', 'Dictionary.getNumber', 'Dictionary.getString',
    'Dictionary.map', 'Dictionary.rename', 'Dictionary.size',
    'Dictionary.toArray',
)
for _name in DICTIONARY_FUNCTIONS:
    STATIC_FAMILY_LIMITS[_name] = ['Finite static combine/fromLists/rename/size/map/toArray/typed getters with owned deep values and existing50000 work/1MB/depth caps. Map expects two-argument serialized pure Function and drops null results. Local duplicate fromLists last-value-wins; rename rejects missing/duplicate sources or destinations, overwrites only when requested. Array values require coherent shape/axis. No arbitrary dynamic objects or Google collision/dtype parity; regex selection is separately documented.']

STRING_FUNCTIONS = (
    'String.decodeJSON', 'String.encodeJSON', 'String.equals',
    'String.index', 'String.rindex', 'String.slice',
    'String.toLowerCase', 'String.toUpperCase', 'String.trim',
)
for _name in STRING_FUNCTIONS:
    STATIC_FAMILY_LIMITS[_name] = ['Finite static equals/search/slice/case/trim and bounded JSON primitives/list/dictionary. Existing Python Unicode codepoint/case/whitespace policy; compact sorted-key local JSON formatting, exact integers<=2^53 and finite numbers. Reject duplicates/nonfinite/cycles/opaque/deep/oversized values before unsafe allocation. No Google Unicode/JSON formatting parity; regex methods have a separate bounded contract; existing50000work/1MB output remain.']

for _name in ('Date.parse', 'Date.update', 'Date.getRange', 'Date.unitRatio'):
    STATIC_FAMILY_LIMITS[_name] = [
        'Finite UTC-only calendar values, years1..9999, bounded numeric Joda-pattern subset; '
        'half-open ranges retain millisecond endpoints. Shared50000 work precharged. '
        'ISO Monday weeks, inherited-day clamping, fixed1950..2049 yy pivot and '
        '365.2425-day average year / one-twelfth month are explicit local policies. '
        'No timezone/DST/locale-text or Google calendar parity.'
    ]

for _name in ('Array.bitsToArray', 'Array.cut', 'Array.mask'):
    STATIC_FAMILY_LIMITS[_name] = [
        'Finite static owned readonly Arrays, rank8/cells10000/shared50000 work. '
        'bitsToArray is most-significant-first with zero=[0], exact integers<=2^53; '
        'negative64-bit twos-complement is a local inference beyond the documented -1 example. '
        'cut preserves axis rank and accepts -1 for a complete axis. mask requires equal shape '
        'and rank1 or one varying axis; no general multidimensional mask or broadcast. '
        'No Image array implementation or Google dtype parity.'
    ]

STATIC_FAMILY_LIMITS['Number.expression'] = [
    'Finite scalar parser, never eval; arithmetic/comparison/logical/ternary, Math.PI/E, '
    'nested identifier dictionaries and an explicit Number function allowlist. '
    '20kchars/4ktokens/depth64/10kvars/depth32/64-char keys and shared50000 work; '
    'all branches validated before short-circuit evaluation. Exact integers<=2^53. '
    'Integer division floors, zero division returns0, remainder follows dividend. '
    'No array/image/string/assignment/object access or general Google expression parity.'
]

for _name in ('String.match', 'String.replace', 'String.split',
              'Dictionary.select', 'Dictionary.remove'):
    STATIC_FAMILY_LIMITS[_name] = [
        'Actual pinned RE2, 4096-byte pattern/1MiB program cap and shared50000 work; '
        'program-size times UTF8 bytes/codepoints/subject count reserved before matching. '
        'Finite valid Unicode only, no lookaround/backreferences/byte escape. '
        'String flags g/i (split i only), literal replacements without dollar/backslash, '
        'full matches/split pieces omit captures; empty split uses codepoints. '
        'Dictionary regexes fullmatch keys including literal-looking ones; owned values, '
        'source order, nulls and ignoreMissing retained. No Google regex/Unicode parity.'
    ]

for _name in ('Collection.distinct', 'Collection.remap', 'Collection.fromColumns'):
    STATIC_FAMILY_LIMITS[_name] = [
        'Finite inline FeatureCollections only,1000rows/shared50000 work/1MB output. '
        'distinct uses canonical local JSON/SHA256 and collision byte comparison, first row; '
        'missing/null/dynamic selected values reject, .geo is exact decoded geometry. '
        'remap accepts unique string/integer keys and exact integer outputs; unmatched rows drop. '
        'fromColumns uses equal-length literal columns, unique names, null geometry, no invented IDs; '
        'non-null propertyTypes unsupported. Actual IDs/metadata/order retained by selection. '
        'Pinned JS uses ee.call for hidden fromColumns. No sampled/RF/image collections, '
        'nested flatten or Google hash/type/collision parity.'
    ]
