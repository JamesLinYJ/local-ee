"""Trusted terrain bridge retaining the actual source grid and constraints."""
from __future__ import annotations


def register_terrain_pushdown_boundary():
    from openeo_driver.dry_run import PROPAGATION_RULES

    expected = {"spatial_extent", "weak_spatial_extent", "aggregate_spatial",
                "filter_spatial", "bands", "resample"}
    rules = [rule for rule in PROPAGATION_RULES if rule.constraint_key in expected]
    if {rule.constraint_key for rule in rules} != expected:
        raise RuntimeError("Pinned driver lacks required terrain pushdown boundaries")
    for rule in rules:
        if "local_ee_terrain" not in rule.blockers:
            rule.blockers.append("local_ee_terrain")


def local_ee_terrain(args, env):
    from openeo_driver.dry_run import DryRunDataCube, ProcessType
    from .ee_process_adapters import _apply_native, _checked_args, _driver_cube
    from .ee_neighborhood_metadata import single_band_metadata
    from gee.terrain_spec import decode_terrain_spec

    args = _checked_args(args, "local_ee_terrain", {"data", "spec"})
    cube = _driver_cube(args, "local_ee_terrain")
    decode_terrain_spec(args["spec"])
    source_metadata = single_band_metadata(cube, "local_ee_terrain")
    dimension = source_metadata.band_dimension.name
    metadata = source_metadata.reduce_dimension(dimension).add_dimension(dimension, "v", type="bands")
    if isinstance(cube, DryRunDataCube):
        register_terrain_pushdown_boundary()
        return cube._process("process_type", [ProcessType.FOCAL_SPACE])._process(
            "local_ee_terrain", {"spec": args["spec"]}, metadata=metadata)
    return _apply_native(cube, "local_ee_terrain", {"spec": args["spec"]}, metadata)
