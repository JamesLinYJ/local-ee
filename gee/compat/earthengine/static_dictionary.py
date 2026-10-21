"""Static Dictionary operations with explicit absent-key and null semantics."""
from __future__ import annotations

from .ir import fail


def dictionary_value(operation, arguments):
    value = arguments.get("dictionary")
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        fail("Dictionary operations require a dictionary with string keys")
    if operation in {"get", "contains", "set"}:
        key = arguments.get("key")
        if not isinstance(key, str):
            fail(f"Dictionary.{operation} key must be a string")
        if operation == "get":
            if key in value:
                return value[key]
            default = arguments.get("defaultValue")
            if default is None:
                fail(f"Dictionary.get: dictionary does not contain key: {key!r}")
            return default
        if operation == "contains":
            return key in value
        if "value" not in arguments:
            fail("Dictionary.set requires value")
        return {**value, key: arguments["value"]}
    if operation in {"keys", "values"}:
        keys = arguments.get("keys") if operation == "values" else None
        if keys is None:
            if len(value) > 10000:
                fail("Dictionary key/value list exceeds 10000 values")
            keys = sorted(value)
        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
            fail("Dictionary.values keys must be a list of strings")
        if len(keys) > 10000:
            fail("Dictionary key/value list exceeds 10000 values")
        if operation == "keys":
            return keys
        missing = next((key for key in keys if key not in value), None)
        if missing is not None:
            fail(f"Dictionary.values: dictionary does not contain key: {missing!r}")
        return [value[key] for key in keys]
    fail(f"Unsupported static operation: Dictionary.{operation}")
