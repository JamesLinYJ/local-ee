"""Dry-run and actual-cube bridge checks, with no invented raster values."""
import pytest
from shapely.geometry import box

from ee_sampling_bridge_helpers import _dry_cube, _metadata
from engine import ee_process_adapters as adapters
from engine.ee_neighborhood import register_neighborhood_pushdown_boundary
from gee.neighborhood_spec import prepare_neighborhood_spec
from gee.terrain_spec import prepare_terrain_spec
from engine.ee_terrain import register_terrain_pushdown_boundary

SPEC = prepare_neighborhood_spec("stdDev", [(0, 0, 0.5), (1, 0, 1.0)])


@pytest.mark.parametrize("process,spec", [("local_ee_neighborhood", SPEC),
                                         ("local_ee_terrain", prepare_terrain_spec("hillshade"))])
def test_spatial_statistics_block_output_constraints_and_preserve_source_band(process, spec):
    from openeo_driver.dry_run import ProcessType

    cube, source, tracer = _dry_cube(bands=("red", "nir"), temporal=True)
    full = {"west": 0, "south": 0, "east": 4, "north": 3, "crs": "EPSG:4326"}
    cube = cube.filter_bbox(**full).filter_bands(["nir"])
    result = getattr(adapters, process)({"data": cube, "spec": spec}, None)
    assert result.metadata.band_names == ["v"] and result.metadata.has_temporal_dimension()
    assert result._data_tracer is tracer and result._traces[0].get_source() is source
    result.resample_spatial(resolution=20, projection=32649).mask_polygon(box(1, 1, 2, 2))
    params = tracer.get_source_constraints()[0][1]
    assert params["spatial_extent"] == full and params["bands"] == ["nir"]
    assert ProcessType.FOCAL_SPACE in params["process_type"]
    assert "resample" not in params and "weak_spatial_extent" not in params


@pytest.mark.parametrize("process,spec", [("local_ee_neighborhood", SPEC),
                                         ("local_ee_terrain", prepare_terrain_spec("hillshade"))])
def test_actual_cube_forwards_spec_without_pixel_or_metadata_substitution(monkeypatch, process, spec):
    from openeo_driver.datacube import DriverDataCube

    cube = DriverDataCube(metadata=_metadata(("red",), temporal=True))
    calls = []
    def native(actual, process_id, arguments, metadata):
        calls.append((actual, process_id, arguments, metadata))
        return "native-result"
    monkeypatch.setattr(adapters, "_apply_native", native)
    assert getattr(adapters, process)({"data": cube, "spec": spec}, None) == "native-result"
    actual, process_id, arguments, metadata = calls[0]
    assert actual is cube and process_id == process and arguments == {"spec": spec}
    assert metadata.band_names == ["v"] and metadata.has_temporal_dimension()
    assert cube.metadata.band_names == ["red"]
    assert metadata.spatial_dimensions == cube.metadata.spatial_dimensions
    with pytest.raises(ValueError, match="exactly one"):
        getattr(adapters, process)({"data": DriverDataCube(metadata=_metadata()), "spec": spec}, None)


@pytest.mark.parametrize("process,register", [
    ("local_ee_neighborhood", register_neighborhood_pushdown_boundary),
    ("local_ee_terrain", register_terrain_pushdown_boundary),
])
def test_registration_does_not_change_other_process_blockers(process, register):
    from openeo_driver.dry_run import PROPAGATION_RULES

    before = {r.constraint_key: [x for x in r.blockers if x != process]
              for r in PROPAGATION_RULES}
    register()
    register()
    assert before == {r.constraint_key: [x for x in r.blockers if x != process]
                      for r in PROPAGATION_RULES}
    assert all(r.blockers.count(process) <= 1 for r in PROPAGATION_RULES)
