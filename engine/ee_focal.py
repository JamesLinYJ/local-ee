"""Trusted focal bridge with explicit upstream optimizer boundaries."""
from __future__ import annotations


def register_focal_pushdown_boundary():
    """Teach the pinned optimizer which downstream constraints cannot commute.

    Changing only the blocker for this local process leaves upstream processes
    intact. A later export/aggregate must not trim the pixels needed by a halo,
    and output reprojection must not redefine this pixel-unit input kernel.
    """
    from openeo_driver.dry_run import PROPAGATION_RULES

    expected = {"spatial_extent", "weak_spatial_extent", "aggregate_spatial",
                "filter_spatial", "bands", "resample"}
    rules = [rule for rule in PROPAGATION_RULES if rule.constraint_key in expected]
    if {rule.constraint_key for rule in rules} != expected:
        raise RuntimeError("Pinned driver lacks required focal pushdown boundaries")
    for rule in rules:
        if "local_ee_focal" not in rule.blockers:
            rule.blockers.append("local_ee_focal")


def local_ee_focal(args, env):
    from openeo_driver.dry_run import DryRunDataCube, ProcessType
    from .ee_process_adapters import _apply_native, _checked_args, _driver_cube
    from gee.focal_spec import decode_focal_spec
    from .ee_neighborhood_metadata import single_band_metadata

    args = _checked_args(args, "local_ee_focal", {"data", "spec"})
    cube = _driver_cube(args, "local_ee_focal")
    decode_focal_spec(args["spec"])
    source_metadata = single_band_metadata(cube, "local_ee_focal")
    dimension = source_metadata.band_dimension.name
    metadata = source_metadata.reduce_dimension(dimension).add_dimension(dimension, "v", type="bands")
    if isinstance(cube, DryRunDataCube):
        register_focal_pushdown_boundary()
        # Record the operation, not merely its metadata; downstream constraints
        # otherwise propagate through it and silently change the calculation.
        return cube._process("process_type", [ProcessType.FOCAL_SPACE])._process(
            "local_ee_focal", {"spec": args["spec"]}, metadata=metadata,
        )
    return _apply_native(cube, "local_ee_focal", {"spec": args["spec"]}, metadata)
