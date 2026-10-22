"""Shared fixtures for the bounded EE sampling bridge tests."""
from __future__ import annotations

import json
import sys
import types

from openeo.metadata import Band, BandDimension, CollectionMetadata, SpatialDimension, TemporalDimension
from openeo_driver.datacube import DriverDataCube
from openeo_driver.dry_run import DataSource, DryRunDataCube, DryRunDataTracer
from gee.sampling_spec import encode_spec, prepare_sampling_spec


def _fixture():
    from pathlib import Path

    path = Path(__file__).parent / "fixtures/ee-sampling-training-v1.json"
    return json.loads(path.read_text())


def _spec(*, geometries=True, properties=None, grid=None, features=None):
    source = _fixture()
    collection = {
        "type": "FeatureCollection",
        "features": source["training_features"] if features is None else features,
    }
    return prepare_sampling_spec(
        collection,
        source["input_properties"],
        properties=["plot_id", "landcover"] if properties is None else properties,
        geometries=geometries,
        grid=grid,
    )


def _training_spec(*, schema=None, class_property="landcover", metric="euclidean"):
    return encode_spec({
        "version": 1,
        "metric": metric,
        "class_property": class_property,
        "schema": ["red", "nir"] if schema is None else schema,
    })


def _metadata(bands=("red", "nir"), *, temporal=False):
    dimensions = [SpatialDimension("x", (0, 4)), SpatialDimension("y", (0, 3))]
    if temporal:
        dimensions.append(TemporalDimension("t", ("2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z")))
    dimensions.append(BandDimension("bands", [Band(name) for name in bands]))
    return CollectionMetadata(metadata={}, dimensions=dimensions)


def _dry_cube(tracer=None, bands=("red", "nir"), *, temporal=False, source_id="training"):
    tracer = tracer or DryRunDataTracer()
    source = tracer.add_trace(DataSource("load_collection", {"id": source_id}))
    return DryRunDataCube(
        traces=[source], data_tracer=tracer, metadata=_metadata(bands, temporal=temporal)
    ), source, tracer


def _native_row(feature, row, col, values, x=0.5, y=2.5):
    return {"feature": feature, "row": row, "col": col, "x": x, "y": y, "values": values}


def _actual_cube(
    monkeypatch, *, bands=("red", "nir"), crs="EPSG:3857", layer_type="spatial",
    cell_size=10, layout=True,
):
    class Level:
        def __init__(self):
            self.layer_type = layer_type
            metadata = {"crs": crs}
            if layout:
                metadata["layout_definition"] = types.SimpleNamespace(
                    extent=types.SimpleNamespace(
                        xmin=0, ymin=0, xmax=cell_size * 4, ymax=cell_size * 3,
                    ),
                    tileLayout=types.SimpleNamespace(
                        layoutCols=1, layoutRows=1, tileCols=4, tileRows=3,
                    ),
                )
            self.layer_metadata = types.SimpleNamespace(**metadata)

    class Cube(DriverDataCube):
        def __init__(self):
            super().__init__(metadata=_metadata(bands))
            self.level_calls = 0
            self.level = Level()

        def get_max_level(self):
            self.level_calls += 1
            return self.level

    monkeypatch.setitem(
        sys.modules,
        "geopyspark",
        types.SimpleNamespace(LayerType=types.SimpleNamespace(SPATIAL="spatial")),
    )
    return Cube()
