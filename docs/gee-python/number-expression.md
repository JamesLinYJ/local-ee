# `ee.Number.expression`

The compiler supports `ee.Number.expression(expression, vars=None)` for bounded
finite static scalar values. It parses a small numeric language into an internal
tree and evaluates that tree directly; it never calls Python `eval`, executes
user code, or invokes an image callback. The official SDK call is still used to
construct and serialize the request. This is a documented local subset of the
API, not support for every function named by the [official
reference](https://developers.google.com/earth-engine/apidocs/ee-number-expression).

The expression grammar accepts finite decimal/scientific literals, parentheses,
simple variable names, nested dictionary members such as `vals.x`, `Math.PI`,
`Math.E`, calls from the function list below, and these operators:

| Precedence, low to high | Operators | Behavior |
| --- | --- | --- |
| 1 | `?:` | Conditional; right associative |
| 2 | `||` | Numeric truthy OR |
| 3 | `^` | Numeric truthy XOR |
| 4 | `&&` | Numeric truthy AND |
| 5 | `== !=` | Equality |
| 6 | `< <= > >=` | Comparison |
| 7 | `+ -` | Addition and subtraction |
| 8 | `* / %` | Multiplication, division, remainder |
| 9 | `**` | Right-associative power |

Unary `+`, `-`, and `!` are supported. Power binds more tightly than unary
signs, so `-2 ** 2` evaluates as `-(2 ** 2)`. Logical and comparison results
are the Numbers `0` or `1`. `&&`, `||`, and `?:` evaluate only the selected
operand or branch. Before evaluation, the compiler parses and checks the full
tree, resolves every referenced variable in every branch, and validates every
function and arity; unsupported syntax cannot be hidden in a short-circuited
branch. A domain error in an unselected branch is not evaluated.

Supported function calls are:

- Arithmetic and comparison: `add`, `subtract`, `multiply`, `divide`, `mod`,
  `pow`, `eq`, `neq`, `lt`, `lte`, `gt`, and `gte`.
- Unary operations: `abs`, `sqrt`, `round`, `floor`, `ceil`, `sin`, `cos`,
  `tan`, `asin`, `acos`, `atan`, `sinh`, `cosh`, `tanh`, `log`, `log10`,
  `exp`, `cbrt`, `signum`, `erf`, `erfc`, `gamma`, `digamma`, `trigamma`,
  `erfInv`, `erfcInv`, and `not`.
- Binary operations: `hypot`, `atan2`, `min`, `max`, `first`, `firstNonZero`,
  `first_nonzero`, `and`, and `or`.
- Three-argument operations: `clamp` and `unitScale`.

`vars` must be null or a dictionary whose keys are simple identifiers. Values
may be finite `int`/`float` numbers or nested dictionaries of those values.
Every value is checked, including unused entries. Integer inputs and outputs
must lie in the exact Float64 integer domain `[-2^53, 2^53]`; booleans, strings,
arrays, null leaves, non-finite numbers, cyclic dictionaries, and other objects
are rejected. Member lookup traverses dictionaries by key and does not access
Python or EE object attributes.

For integer operands, `/` uses floor division, matching the rule described in
Google's [expression guide](https://developers.google.com/earth-engine/guides/image_math#expressions)
(`10 / 20` is `0`); including a float selects ordinary Float64 division.
Division by zero returns `0`, matching
[`ee.Number.divide`](https://developers.google.com/earth-engine/apidocs/ee-number-divide).
`%` follows the sign behavior in the official
[`ee.Number.mod` examples](https://developers.google.com/earth-engine/apidocs/ee-number-mod);
modulo by zero is rejected because no finite result exists. Numeric overflow,
complex powers, and function-domain errors are rejected instead of producing
NaN or infinity. Local Float64 math results are not a Google numerical parity
claim.

Resource limits are 20,000 expression characters, 4,000 tokens, 64 AST levels,
10,000 variable-tree values, and 32 nested variable dictionaries. The compiler
precharges parser/evaluator work against the existing shared 50,000-step
compilation budget; selected static special functions add their bounded work
cost. The result is one finite scalar Number, not an image, array, string, or
general expression object.

The local language rejects image band access, indexing, assignment, string or
array literals, arbitrary attributes, JavaScript statements, `Math` methods,
unknown functions, and functions outside this list. Unsupported operators and
arguments fail explicitly.
