"""Shared fixtures for focused Smile RF bridge tests."""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from openeo.metadata import Band, BandDimension, CollectionMetadata, SpatialDimension, TemporalDimension
from openeo_driver.dry_run import DataSource, DryRunDataCube, DryRunDataTracer
from engine.ee_sampling_result import SampledFeatureTable
from gee.smile_rf_spec import (
    decode_rf_spec,
    prepare_rf_parameters,
    prepare_rf_rows,
    prepare_rf_spec,
)


class JavaObjectStub:
    """Test-only shape used as the Py4J JavaObject boundary marker."""

    pass


def metadata(names=("red", "nir"), timed=True):
    dimensions = [
        SpatialDimension("x", (0, 2), crs=32610),
        SpatialDimension("y", (0, 2), crs=32610),
    ]
    if timed:
        dimensions.append(TemporalDimension("t", ("2025-01-01", "2025-01-02")))
    dimensions.append(BandDimension("bands", [Band(name) for name in names]))
    return CollectionMetadata({}, dimensions=dimensions)


def dry_cube(tracer=None, source=None, names=("red", "nir"), timed=True):
    tracer = DryRunDataTracer() if tracer is None else tracer
    source = tracer.add_trace(DataSource("load_collection", {"id": "predict"})) if source is None else source
    return DryRunDataCube([source], tracer, metadata=metadata(names, timed))


def _parameters(**changes):
    values = {
        "number_of_trees": 1,
        "variables_per_split": None,
        "min_leaf_population": 1,
        "bag_fraction": 0.5,
        "max_nodes": None,
        "seed": 0,
    }
    values.update(changes)
    return values


def spec(schema=("red", "nir"), class_property="landcover", **parameters):
    normalized = prepare_rf_parameters(**_parameters(**parameters))
    return prepare_rf_spec(normalized, list(schema), class_property)


def rows_text(spec_text=None):
    spec_value = decode_rf_spec(spec() if spec_text is None else spec_text)
    return prepare_rf_rows([[0, [1.25, 2]], [1, [8, 9.5]]], spec_value)


def sample_table(labels=(0.0, 1.0), *, rows=None, columns=None):
    rows = list(rows) if rows is not None else [
        {"type": "Feature", "id": f"f0_r0_c{index}", "geometry": None,
         "properties": {"landcover": label, "red": index + 0.25, "nir": index + 2}}
        for index, label in enumerate(labels)
    ]
    columns = list(columns) if columns is not None else [
        "system:index", "landcover", "red", "nir", ".geo",
    ]
    return SampledFeatureTable({"type": "FeatureCollection", "features": rows}, columns)


def large_rf_sample_case(*, prior_work=0):
    """1000x8 bounded reflectance fixture for Python bridge capacity tests."""
    schema = tuple(f"B{index}" for index in range(8))
    spec_text = spec(
        schema=schema, class_property="class", number_of_trees=100,
        variables_per_split=8,
    )
    decoded = decode_rf_spec(spec_text)
    rows = []
    features = []
    for index in range(1000):
        label = index % 2
        values = [round(0.04 + ((index * 37 + band * 19) % 700000) / 1_000_000, 6)
                  for band in range(8)]
        rows.append([label, values])
        features.append({
            "type": "Feature", "id": f"f0_r0_c{index}", "geometry": None,
            "properties": {"class": label, **dict(zip(schema, values))},
        })
    rows_text = prepare_rf_rows(rows, decoded)
    columns = ["system:index", "class", *schema, ".geo"]
    table = sample_table(rows=features, columns=columns)
    table.sample_operation_work = prior_work
    return spec_text, table, rows_text


def jvm_model():
    # A Py4J proxy proves only Python boundary dispatch, not that a JVM is running.
    proxy = JavaObjectStub()
    proxy._target_id = "o1"
    proxy._gateway_client = object()
    return proxy


def install_factory(monkeypatch, *, result=None, error=None):
    calls = []

    def train(spec_text, rows_text):
        calls.append((spec_text, rows_text))
        if error is not None:
            raise error
        return jvm_model() if result is None else result

    factory = SimpleNamespace(train=train)
    jvm = SimpleNamespace(local=SimpleNamespace(ee=SimpleNamespace(smile=SimpleNamespace(
        LocalEeSmileRfFactory=factory,
    ))))
    package = types.ModuleType("openeogeotrellis")
    package.__path__ = []
    utils = types.ModuleType("openeogeotrellis.utils")
    utils.get_jvm = lambda: jvm
    package.utils = utils
    monkeypatch.setitem(sys.modules, "openeogeotrellis", package)
    monkeypatch.setitem(sys.modules, "openeogeotrellis.utils", utils)
    py4j = types.ModuleType("py4j")
    py4j.__path__ = []
    gateway = types.ModuleType("py4j.java_gateway")
    gateway.JavaObject = JavaObjectStub
    py4j.java_gateway = gateway
    monkeypatch.setitem(sys.modules, "py4j", py4j)
    monkeypatch.setitem(sys.modules, "py4j.java_gateway", gateway)
    return calls
