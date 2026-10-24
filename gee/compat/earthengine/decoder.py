"""Bounded decoder for the official client's serialized Earth Engine DAG."""
from __future__ import annotations

from .catalog import CatalogOperations
from .filtering import FilteringOperations
from .geometry_values import GEOMETRY_TYPES, decode_geometry_bounded
from .ir import Function, ParsedExpression, fail, static_truth


class Translator(CatalogOperations, FilteringOperations):
    """Compatibility facade that evaluates descriptions, never user source."""

    def __init__(self, catalog, items, options):
        self.catalog = {item["id"]: item for item in catalog}
        self.items = items
        self.options = dict(options or {})
        unknown = set(self.options) - {"region", "scale", "crs"}
        if unknown:
            fail(f"Unsupported compilation options: {sorted(unknown)}")
        self.scope = {}
        self.warnings = []
        self.steps = 0
        self._root_env = None
        self._root_value_cache = {}
        self._root_scalar_image_snapshots = 0
        self._runtime_rf_explanation_seen = False
        self._pixel_math_seen = False
        # Reused only inside this compilation. Sample-table schema facts may
        # be checked at several consumers of the same immutable IR node.
        self._sampled_schema_cache = {}

    def warn(self, value):
        if value not in self.warnings:
            self.warnings.append(value)

    def evaluate(self, value, env=None, depth=0):
        self.steps += 1
        if depth > 96 or self.steps > 50000:
            fail("Earth Engine graph exceeds compilation limits")
        if env is None:
            env = {}
        if depth == 0:
            self._root_env = env
            self._root_value_cache.clear()
            self._root_scalar_image_snapshots = 0
        if isinstance(value, list):
            if len(value) > 10000:
                fail("Inline list exceeds 10000 values")
            return [self.evaluate(item, env, depth + 1) for item in value]
        if not isinstance(value, dict):
            return value
        value_type = value.get("type")
        if value_type == "CompoundValue":
            for key, scoped_value in value.get("scope", []):
                if key in self.scope:
                    fail("Duplicate serialized scope reference")
                self.scope[key] = scoped_value
            return self.evaluate(value["value"], env, depth + 1)
        if value_type == "ValueRef":
            key = value.get("value")
            if key not in self.scope:
                fail("Unknown serialized value reference")
            if env is self._root_env and key in self._root_value_cache:
                from .raster_factor_snapshot import restore_factor
                from .scalar_image_snapshot import restore_scalar_image

                return restore_scalar_image(
                    self, restore_factor(self, self._root_value_cache[key]),
                )
            result = self.evaluate(self.scope[key], env, depth + 1)
            # The official serializer uses ValueRef for a shared, immutable
            # server-side object. Reuse the audited RF table/model IR and
            # whitelisted factor or RGB/HSV results only in the root scope.
            # Image snapshots share proven frozen scalar IR, with detached
            # owned metadata on storage and every cache hit.
            from .ir import SampledFeatures, TrainedSmileRandomForest

            if (env is self._root_env
                    and isinstance(result, (SampledFeatures, TrainedSmileRandomForest))):
                self._root_value_cache[key] = result
            elif env is self._root_env and len(self._root_value_cache) < 500:
                from .raster_factor_snapshot import FACTOR_METHODS, snapshot_factor
                from .scalar_image_snapshot import (
                    MAX_SCALAR_IMAGE_SNAPSHOTS,
                    SCALAR_IMAGE_SNAPSHOT_METHODS,
                    snapshot_scalar_image,
                )

                scoped = self.scope[key]
                if (type(scoped) is dict and type(scoped.get("functionName")) is str
                        and scoped["functionName"] in FACTOR_METHODS):
                    snapshot = snapshot_factor(self, result)
                    if snapshot is not None:
                        from .array_core import charge_array

                        charge_array(self, 2)
                        self._root_value_cache[key] = snapshot
                elif (type(scoped) is dict
                      and type(scoped.get("functionName")) is str
                      and scoped.get("functionName") in SCALAR_IMAGE_SNAPSHOT_METHODS
                      and self._root_scalar_image_snapshots < MAX_SCALAR_IMAGE_SNAPSHOTS):
                    snapshot = snapshot_scalar_image(self, result)
                    if snapshot is not None:
                        from .array_core import charge_array

                        charge_array(self, 2)
                        self._root_value_cache[key] = snapshot
                        self._root_scalar_image_snapshots += 1
            return result
        if value_type == "ArgumentRef":
            if value["value"] not in env:
                fail("Unbound mapped-function argument")
            return env[value["value"]]
        if value_type == "Function":
            return Function(value["argumentNames"], value["body"], dict(env))
        if value_type == "Invocation":
            if value.get("functionName") == "If":
                raw = value.get("arguments", {})
                self.allowed(raw, {"condition", "trueCase", "falseCase"})
                condition = self.evaluate(raw.get("condition"), env, depth + 1)
                selected = "trueCase" if static_truth(condition, self) else "falseCase"
                return self.evaluate(raw.get(selected), env, depth + 1)
            arguments = {
                key: self.evaluate(argument, env, depth + 1)
                for key, argument in value.get("arguments", {}).items()
            }
            if "functionName" in value:
                return self.invoke(value["functionName"], arguments)
            function = self.evaluate(value.get("function"), env, depth + 1)
            if isinstance(function, ParsedExpression):
                from .image_expression import invoke

                return invoke(self, function, arguments)
            if isinstance(function, Function):
                if set(arguments) != set(function.names):
                    fail("Function argument names do not match")
                return self.evaluate(function.body, {**function.env, **arguments}, depth + 1)
            fail("Unsupported computed function invocation")
        if value_type == "Dictionary":
            return {
                key: self.evaluate(item, env, depth + 1)
                for key, item in value.get("value", {}).items()
            }
        if value_type in GEOMETRY_TYPES:
            return decode_geometry_bounded(self, value)
        if value_type:
            fail(f"Unsupported serialized value type: {value_type}")
        return {
            key: self.evaluate(item, env, depth + 1)
            for key, item in value.items()
        }

    @staticmethod
    def allowed(args, names):
        unknown = set(args) - names
        if unknown:
            fail(f"Unsupported algorithm arguments: {sorted(unknown)}")

    def invoke(self, name, arguments):
        from .dispatch import invoke

        return invoke(self, name, arguments)

    def static(self, name, arguments):
        from .static_values import invoke_static

        return invoke_static(self, name, arguments)
