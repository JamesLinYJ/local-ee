# Bounded Earth Engine String regular expressions

This local finite subset adds `String.match`, `String.replace`, and
`String.split` for literal inputs. The signatures and documented flags follow
the pinned Earth Engine API metadata and its method pages:
[match](https://developers.google.com/earth-engine/apidocs/ee-string-match),
[replace](https://developers.google.com/earth-engine/apidocs/ee-string-replace),
and [split](https://developers.google.com/earth-engine/apidocs/ee-string-split).

| Method | Local behavior |
| --- | --- |
| `String.match(regex, flags)` | Returns a list of full matched strings. Without `g`, it returns the first match; `g` returns non-overlapping matches. Capturing groups do not change the result shape. `i` enables RE2 case-insensitive matching. No match returns `[]`. |
| `String.replace(regex, replacement, flags)` | Replaces the first match unless `g` is present. `i` enables case-insensitive matching. Replacement text is literal. Replacements containing `$` or `\` are rejected because the pinned method documentation does not specify capture expansion or escape rules. |
| `String.split(regex, flags)` | Splits on non-overlapping matches and omits both separators and capture groups. `i` is supported. An empty regex splits into Unicode code points; regex separators can produce empty leading or trailing elements. |

`match` and `replace` accept only unique `g` and/or `i` flags. `split` accepts
only `i`; unknown or duplicate flags fail. Regex syntax is compiled by the
pinned `google-re2` binding with UTF-8 encoding, Perl character classes and
word boundaries enabled. Unsupported RE2 syntax, including look-around and
backreferences, fails as `UnsupportedEEError`; the byte-oriented `\\C` escape
is also rejected because it can bisect a UTF-8 scalar. The implementation
never falls back to Python's backtracking regex engine.

The local resource policy uses a 1 MiB RE2 program-memory limit, a 4096-byte
pattern limit, at most 10000 subject strings, a 1 MB aggregate UTF-8 input
limit, a 1 MB UTF-8 output limit, and at most 10000 output items. All Unicode
scalar validation, pattern compilation, and matching work is charged to the
existing 50000-step static String budget. Matching work reserves
`(programsize + reverseprogramsize) * (UTF-8 input bytes + Unicode code
points + subject count)` before scanning, including empty subjects.
Replacement expansion reserves a conservative
worst-case output bound before scanning and building the result. The RE2
wrapper's bounded pattern LRU is cleared after compilation; compiled matchers
do not retain subject strings.

Offsets and empty-string splitting use Unicode code points in this local
subset. Unicode case folding, zero-width boundary details, replacement escape
semantics, and outputs beyond the examples in the API documentation have not
been compared with Google's evaluator. This is local bounded compatibility
behavior, not a Google same-data parity claim.
