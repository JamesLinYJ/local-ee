"""Lazy projections of actual trained Smile RandomForest explanations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...rf_explanation_spec import (
    decode_explanation_spec,
    prepare_explanation_spec,
)
from .array_core import charge_array
from .ir import TrainedSmileRandomForest, fail
from .rf_explanation_wire import ROOT_KEY_WORK, precharge_explanation_spec
from .smile_rf_training import validate_trained_classifier


ROOT_KEYS = ("importance", "numberOfTrees", "outOfBagErrorEstimate")
MAX_PROJECTION_KEYS = 64
UNHANDLED = object()


@dataclass(frozen=True)
class RuntimeRFExplanation:
    """A typed runtime value backed by one validated RF training lineage."""

    classifier: TrainedSmileRandomForest
    spec: str


def _prepare(translator, classifier, view="explanation", keys=None):
    schema = classifier.schema
    if keys is not None and (type(keys) is not list
                             or len(keys) > MAX_PROJECTION_KEYS):
        fail("RF explanation projections accept at most 64 string keys")
    if (type(schema) not in (list, tuple) or not 1 <= len(schema) <= 8
            or any(type(name) is not str or not name or len(name) > 256
                   or "." in name for name in schema)):
        fail("RF explanation schema must contain 1..8 bounded flat names")
    if (type(view) is not str or len(view) > 32
            or (keys is not None and any(
                type(key) is not str or len(key) > 256 for key in keys
            ))):
        fail("RF explanation projection keys must be bounded strings")
    trees = classifier.classifier.number_of_trees
    if type(trees) is not int or not 1 <= trees <= 256:
        fail("RF explanation trees must be an integer from 1 through 256")
    precharge_explanation_spec(translator, schema, trees, view, keys)
    copied_schema = list(schema)
    copied_keys = list(keys) if keys is not None else None
    try:
        return prepare_explanation_spec(
            copied_schema, trees,
            view=view, keys=copied_keys,
        )
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Invalid Smile RandomForest explanation projection: {exc}")


def _decoded(translator, value):
    if (not isinstance(value, RuntimeRFExplanation)
            or not isinstance(value.classifier, TrainedSmileRandomForest)
            or type(value.spec) is not str):
        fail("Runtime Smile RandomForest explanation is malformed")
    classifier = validate_trained_classifier(translator, value.classifier)
    # Charge the bounded wire scan and the schema snapshot before parsing or
    # making another copy. The shared decoder independently checks 16 KiB.
    if len(value.spec) > 16_384:
        fail("RF explanation specification exceeds16384 UTF-8 bytes")
    # Charge the wire-length scan, then the parser and copied schema before
    # asking the shared helper to allocate decoded JSON objects.
    charge_array(translator, len(value.spec) + 1)
    wire_bytes = 0
    for character in value.spec:
        code = ord(character)
        wire_bytes += 1 if code <= 0x7f else 2 if code <= 0x7ff else 3 if code <= 0xffff else 4
    if wire_bytes > 16_384:
        fail("RF explanation specification exceeds16384 UTF-8 bytes")
    # decode_explanation_spec validates UTF-8, parses, and re-encodes the wire;
    # expected prepare_explanation_spec repeats bounded serialization and
    # canonical checks. Reserve those whole-wire passes before either helper.
    charge_array(
        translator,
        16 * wire_bytes + 257 * len(classifier.schema)
        + ROOT_KEY_WORK + 64,
    )
    try:
        spec = decode_explanation_spec(value.spec)
        expected = prepare_explanation_spec(
            list(classifier.schema), classifier.classifier.number_of_trees,
            view=spec["view"], keys=spec.get("keys"),
        )
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Runtime Smile RandomForest explanation has an invalid specification: {exc}")
    if (expected != value.spec or spec.get("schema") != list(classifier.schema)
            or spec.get("trees") != classifier.classifier.number_of_trees):
        fail("Runtime Smile RandomForest explanation does not match its trained model")
    return classifier, spec


def _new(translator, classifier, view, keys=None):
    return RuntimeRFExplanation(classifier, _prepare(translator, classifier, view, keys))


def _known_keys(spec):
    view = spec["view"]
    if view == "explanation":
        return tuple(sorted(ROOT_KEYS))
    if view == "importance":
        return tuple(sorted(spec["schema"]))
    return None


def _copy_keys(translator, keys, allowed):
    if type(keys) is not list or len(keys) > MAX_PROJECTION_KEYS:
        fail("RF explanation projections accept at most 64 string keys")
    charge_array(translator, 257 * len(keys) + 1)
    if any(type(key) is not str or len(key) > 256 for key in keys):
        fail("RF explanation projection keys must be bounded strings")
    missing = next((key for key in keys if key not in allowed), None)
    if missing is not None:
        fail(f"Dictionary.values: explanation does not contain key: {missing!r}")
    return list(keys)


def _get(translator, value, arguments):
    translator.allowed(arguments, {"dictionary", "key", "defaultValue"})
    key = arguments.get("key")
    if type(key) is not str:
        fail("Dictionary.get key must be a string")
    charge_array(translator, len(key) + 1)
    classifier, spec = _decoded(translator, value)
    allowed = _known_keys(spec)
    if allowed is None:
        fail("Dictionary.get requires an RF explanation dictionary projection")
    if key not in allowed:
        default = arguments.get("defaultValue")
        if default is None:
            fail(f"Dictionary.get: dictionary does not contain key: {key!r}")
        if _contains(default, translator):
            fail("RF explanation values cannot be nested in Dictionary defaults")
        return default
    if spec["view"] == "explanation":
        views = {
            "importance": "importance",
            "numberOfTrees": "numberOfTrees",
            "outOfBagErrorEstimate": "outOfBagErrorEstimate",
        }
        return _new(translator, classifier, views[key])
    return _new(translator, classifier, "importance_value", [key])


def _keys(translator, value, operation, arguments):
    translator.allowed(arguments, {"dictionary"})
    _, spec = _decoded(translator, value)
    known = _known_keys(spec)
    if known is None:
        fail(f"Dictionary.{operation} requires an RF explanation dictionary projection")
    charge_array(translator, len(known) + sum(map(len, known)) + 1)
    return list(known)


def _contains_key(translator, value, arguments):
    translator.allowed(arguments, {"dictionary", "key"})
    key = arguments.get("key")
    if type(key) is not str:
        fail("Dictionary.contains key must be a string")
    charge_array(translator, len(key) + 1)
    _, spec = _decoded(translator, value)
    known = _known_keys(spec)
    if known is None:
        fail("Dictionary.contains requires an RF explanation dictionary projection")
    charge_array(translator, len(known) + sum(map(len, known)) + 1)
    return key in known


def _values(translator, value, arguments):
    translator.allowed(arguments, {"dictionary", "keys"})
    classifier, spec = _decoded(translator, value)
    known = _known_keys(spec)
    if known is None:
        fail("Dictionary.values requires an RF explanation dictionary projection")
    raw_keys = arguments.get("keys")
    if raw_keys is None:
        charge_array(translator, len(known) + sum(map(len, known)) + 1)
        requested = list(known)
    else:
        requested = _copy_keys(translator, raw_keys, known)
    view = "values" if spec["view"] == "explanation" else "importance_values"
    return _new(translator, classifier, view, requested)


def _cast(translator, name, arguments):
    translator.allowed(arguments, {"input", "value", "values", "dictionary"})
    if len(arguments) != 1:
        fail(f"{name} requires exactly one RF explanation projection")
    value = next(iter(arguments.values()))
    classifier, spec = _decoded(translator, value)
    view = spec["view"]
    if name == "Dictionary" and view in {"explanation", "importance"}:
        return value
    if name == "Number" and view in {
        "numberOfTrees", "outOfBagErrorEstimate", "importance_value",
    }:
        return value
    if name == "List" and view in {"values", "importance_values"}:
        return value
    fail(f"{name} cast does not match RF explanation projection {view!r}")


def _contains(value: Any, translator=None) -> bool:
    pending = [value]
    visited = set()
    while pending:
        current = pending.pop()
        if isinstance(current, RuntimeRFExplanation):
            return True
        if type(current) not in (dict, list, tuple):
            continue
        identity = id(current)
        if identity in visited:
            continue
        if translator is not None:
            charge_array(
                translator,
                (2 * len(current) if type(current) is dict else len(current)) + 1,
            )
        visited.add(identity)
        if type(current) is dict:
            for key, child in current.items():
                pending.append(key)
                pending.append(child)
        else:
            pending.extend(current)
    return False


def contains_runtime_explanation(value, translator=None):
    return _contains(value, translator)


def has_runtime_explanation_argument(arguments):
    return any(isinstance(value, RuntimeRFExplanation)
               for value in arguments.values())


def runtime_explanation_seen(translator):
    return bool(getattr(translator, "_runtime_rf_explanation_seen", False))


def mark_runtime_explanation_seen(translator):
    translator._runtime_rf_explanation_seen = True


def invoke_runtime_explanation(translator, name, arguments, *, known_present=False):
    """Handle explain construction and typed reads; reject every other sink."""
    if name == "Classifier.explain":
        translator.allowed(arguments, {"classifier"})
        classifier = arguments.get("classifier")
        if not isinstance(classifier, TrainedSmileRandomForest):
            fail("Classifier.explain requires a trained Smile RandomForest classifier")
        classifier = validate_trained_classifier(translator, classifier)
        result = _new(translator, classifier, "explanation")
        mark_runtime_explanation_seen(translator)
        return result

    if not known_present and not _contains(arguments, translator):
        return UNHANDLED
    if name in {"Dictionary", "Number", "List"}:
        value = next((item for item in arguments.values()
                      if isinstance(item, RuntimeRFExplanation)), None)
        # A single typed cast accepts exactly one direct argument. Nested
        # containers therefore have no valid route through _cast; checking
        # that arity and the direct value avoids an unneeded recursive rescan.
        if value is None:
            fail("RF explanation values cannot be nested in generic containers")
        return _cast(translator, name, arguments)

    value = arguments.get("dictionary")
    if isinstance(value, RuntimeRFExplanation):
        operation = name.removeprefix("Dictionary.") if name.startswith("Dictionary.") else None
        if operation == "get":
            return _get(translator, value, arguments)
        if operation == "keys":
            return _keys(translator, value, operation, arguments)
        if operation == "contains":
            return _contains_key(translator, value, arguments)
        if operation == "values":
            return _values(translator, value, arguments)
        if operation == "set":
            fail("Dictionary.set is unsupported for runtime RF explanations")

    fail("Runtime RF explanations support only typed dictionary reads and direct JSON output")


def compile_runtime_explanation(value, translator):
    """Lower the fixed training lineage to one owned runtime JSON sink."""
    if not isinstance(value, RuntimeRFExplanation):
        fail("Internal runtime RF explanation value is malformed")
    classifier, spec = _decoded(translator, value)
    charge_array(translator, len(value.spec) + 1)
    escaped_size = 2
    for character in value.spec:
        code = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            escaped_size += 2
        elif code < 0x20:
            escaped_size += 6
        elif code >= 0x10000:
            escaped_size += 12
        elif code >= 0x80:
            escaped_size += 6
        else:
            escaped_size += 1
    # Graph.node canonicalizes its arguments and the final result is copied
    # through public JSON; charge those bounded wire copies before mutation.
    charge_array(
        translator,
        2 * escaped_size + 257 * len(spec["schema"]) + 32,
    )
    from .graph import Graph
    from .smile_rf_graph import compile_smile_rf_model

    graph = Graph(translator)
    model = compile_smile_rf_model(graph, classifier)
    reference = graph.node("local_ee_smile_rf_explain", model=model, spec=value.spec)
    source_ids = list(dict.fromkeys(
        [item_id for source in graph.sources for item_id in source.ids]
        + graph.auxiliary_source_item_ids
    ))
    return {
        "kind": "runtime_explanation",
        "explanation_spec": value.spec,
        "process_graph": graph.finish(reference),
        "bands": [],
        "warnings": list(translator.warnings),
        "source_item_ids": source_ids,
    }
