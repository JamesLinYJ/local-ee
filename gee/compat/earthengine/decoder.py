"""Bounded decoder for the official client's serialized Earth Engine DAG."""
from __future__ import annotations

import copy

from .catalog import CatalogOperations
from .filtering import FilteringOperations
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

    def warn(self, value):
        if value not in self.warnings:
            self.warnings.append(value)

    def evaluate(self, value, env=None, depth=0):
        self.steps += 1
        if depth > 96 or self.steps > 50000:
            fail("Earth Engine graph exceeds compilation limits")
        env = {} if env is None else env
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
            return self.evaluate(self.scope[key], env, depth + 1)
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
                selected = "trueCase" if static_truth(condition) else "falseCase"
                return self.evaluate(raw.get(selected), env, depth + 1)
            arguments = {
                key: self.evaluate(argument, env, depth + 1)
                for key, argument in value.get("arguments", {}).items()
            }
            if "functionName" in value:
                return self.invoke(value["functionName"], arguments)
            function = self.evaluate(value.get("function"), env, depth + 1)
            if isinstance(function, ParsedExpression):
                from ...ee_expression import parse_expression

                return parse_expression(function.text, arguments, function.default, self)
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
        geometry_types = {
            "Point", "MultiPoint", "LineString", "MultiLineString",
            "Polygon", "MultiPolygon", "GeometryCollection",
        }
        if value_type in geometry_types:
            if value.get("geodesic") is True:
                fail("Geodesic geometries require spherical geometry support")
            crs = value.get("crs")
            if crs and crs not in {"EPSG:4326"}:
                fail("Only EPSG:4326 input GeoJSON geometries are supported")
            output = {
                key: copy.deepcopy(item)
                for key, item in value.items()
                if key in {"type", "coordinates", "geometries"}
            }
            if value_type == "Polygon":
                for ring in output["coordinates"]:
                    if ring and ring[0] != ring[-1]:
                        ring.append(ring[0])
            return output
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
