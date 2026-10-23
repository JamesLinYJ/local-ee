"""Trusted convolution bridge; preserve native grid before output constraints."""
from __future__ import annotations


def register_convolve_pushdown_boundary():
    from openeo_driver.dry_run import PROPAGATION_RULES

    expected = {"spatial_extent", "weak_spatial_extent", "aggregate_spatial",
                "filter_spatial", "bands", "resample"}
    rules = [rule for rule in PROPAGATION_RULES if rule.constraint_key in expected]
    if {rule.constraint_key for rule in rules} != expected:
        raise RuntimeError("Pinned driver lacks required convolution pushdown boundaries")
    for rule in rules:
        if "local_ee_convolve" not in rule.blockers:
            rule.blockers.append("local_ee_convolve")


def local_ee_convolve(args, env):
    from openeo_driver.dry_run import DryRunDataCube, ProcessType
    from .ee_process_adapters import _apply_native, _checked_args, _driver_cube
    from gee.convolve_spec import decode_convolve_spec
    from .ee_neighborhood_metadata import single_band_metadata

    args = _checked_args(args, "local_ee_convolve", {"data", "spec"})
    cube = _driver_cube(args, "local_ee_convolve")
    decode_convolve_spec(args["spec"])
    source_metadata = single_band_metadata(cube, "local_ee_convolve")
    dimension = source_metadata.band_dimension.name
    metadata = source_metadata.reduce_dimension(dimension).add_dimension(dimension, "v", type="bands")
    if isinstance(cube, DryRunDataCube):
        register_convolve_pushdown_boundary()
        return cube._process("process_type", [ProcessType.FOCAL_SPACE])._process(
            "local_ee_convolve", {"spec": args["spec"]}, metadata=metadata,
        )
    return _apply_native(cube, "local_ee_convolve", {"spec": args["spec"]}, metadata)
