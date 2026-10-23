"""Real dry-run constraints and mocked SPI forwarding, without fabricating pixels."""
import pytest
from shapely.geometry import box

from engine import ee_process_adapters as adapters
from engine.ee_focal import register_focal_pushdown_boundary
from gee.focal_spec import prepare_focal_spec
from ee_sampling_bridge_helpers import _dry_cube, _metadata


def apply(cube):
    return adapters.local_ee_focal({"data": cube, "spec": prepare_focal_spec("mean", [(0, 0), (1, 0)], 2)}, None)


def test_downstream_export_and_aggregation_do_not_trim_or_reproject_focal_input():
    from openeo_driver.dry_run import ProcessType

    cube, source, tracer = _dry_cube(bands=("red",), temporal=True)
    full = {"west": 0, "south": 0, "east": 4, "north": 3, "crs": "EPSG:4326"}
    cube = cube.filter_bbox(**full).filter_bands(["red"])
    result = apply(cube)
    assert result.metadata.band_names == ["v"]
    assert result.metadata.has_temporal_dimension()
    assert result._data_tracer is tracer
    assert result._traces[0].get_source() is source
    result = result.resample_spatial(resolution=100, projection=32649, method="near")
    result = result.mask_polygon(box(1, 1, 2, 2))
    result = result.aggregate_spatial(box(1, 1, 2, 2), reducer={})
    result = result.filter_bands(["v"])
    constraints = tracer.get_source_constraints()
    assert len(constraints) == 1
    params = constraints[0][1]
    assert params["spatial_extent"] == full
    assert params["bands"] == ["red"]
    assert ProcessType.FOCAL_SPACE in params["process_type"]
    assert not {"resample", "aggregate_spatial", "filter_spatial", "weak_spatial_extent"} & params.keys()


def test_explicit_operations_before_focal_retain_their_constraints():
    cube, _, tracer = _dry_cube(bands=("red",))
    cube = cube.mask_polygon(box(1, 1, 2, 2))
    cube = cube.resample_spatial(resolution=20, projection=32649, method="near")
    result = apply(apply(cube))
    result.mask_polygon(box(1.2, 1.2, 1.8, 1.8))
    params = tracer.get_source_constraints()[0][1]
    assert params["spatial_extent"]["west"] == 1
    assert params["spatial_extent"]["east"] == 2
    assert params["resample"]["resolution"] == (20, 20)


def test_registration_is_idempotent_and_does_not_change_other_process_blockers():
    from openeo_driver.dry_run import PROPAGATION_RULES

    before = {rule.constraint_key: [x for x in rule.blockers if x != "local_ee_focal"]
              for rule in PROPAGATION_RULES}
    register_focal_pushdown_boundary()
    register_focal_pushdown_boundary()
    after = {rule.constraint_key: [x for x in rule.blockers if x != "local_ee_focal"]
             for rule in PROPAGATION_RULES}
    assert before == after
    assert all(rule.blockers.count("local_ee_focal") <= 1 for rule in PROPAGATION_RULES)


def test_actual_cube_forwards_spec_and_preserved_metadata(monkeypatch):
    from openeo_driver.datacube import DriverDataCube

    cube = DriverDataCube(metadata=_metadata(("red",), temporal=True))
    calls = []
    def native(actual, process_id, args, metadata):
        calls.append((actual, process_id, args, metadata))
        return "actual-spi-return"
    monkeypatch.setattr(adapters, "_apply_native", native)
    assert apply(cube) == "actual-spi-return"
    actual, name, args, metadata = calls[0]
    assert actual is cube
    assert name == "local_ee_focal"
    assert args == {"spec": prepare_focal_spec("mean", [(0, 0), (1, 0)], 2)}
    assert metadata.band_names == ["v"]
    assert metadata.has_temporal_dimension()
    assert metadata.spatial_dimensions == cube.metadata.spatial_dimensions


@pytest.mark.parametrize("bands", [(), ("red", "nir"), ("",)])
def test_focal_rejects_missing_or_multiple_bands(bands):
    cube, _, _ = _dry_cube(bands=bands)
    with pytest.raises(ValueError, match="exactly one"):
        apply(cube)
