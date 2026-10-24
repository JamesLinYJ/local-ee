"""Trusted Python bridge for bounded actual-pixel Image.unmix."""
from __future__ import annotations


def register_unmix_pushdown_boundary():
    """Keep output component selectors from becoming source-band selectors."""
    from openeo_driver.dry_run import PROPAGATION_RULES

    rules = [rule for rule in PROPAGATION_RULES if rule.constraint_key == "bands"]
    if len(rules) != 1:
        raise RuntimeError("Pinned driver lacks the unique band pushdown rule")
    if "local_ee_unmix" not in rules[0].blockers:
        rules[0].blockers.append("local_ee_unmix")


def local_ee_unmix(args, env):
    from openeo_driver.dry_run import DryRunDataCube
    from .ee_cube_admission import validate_cube_trace
    from .ee_process_adapters import _apply_native, _checked_args, _driver_cube
    from gee.spectral_unmix_spec import (
        decode_spectral_unmix_spec, spectral_unmix_component_count,
    )

    process_id = "local_ee_unmix"
    args = _checked_args(args, process_id, {"data", "spec"})
    cube = _driver_cube(args, process_id)
    decoded = decode_spectral_unmix_spec(args["spec"])
    component_count = spectral_unmix_component_count(decoded)
    band_count = len(decoded["endmembers"][0])
    if not cube.metadata.has_band_dimension():
        raise ValueError("local_ee_unmix requires an explicitly named band dimension")
    expected = [f"band{index}" for index in range(band_count)]
    if isinstance(cube, DryRunDataCube):
        # The pinned driver can retain pre-rename labels in a pending trace.
        validate_cube_trace(cube, process_id)
    elif (type(cube.metadata.band_names) not in (list, tuple)
          or tuple(cube.metadata.band_names) != tuple(expected)):
        raise ValueError(f"local_ee_unmix requires ordered input bands: {', '.join(expected)}")

    dimension = cube.metadata.band_dimension.name
    names = [f"unmix{index}" for index in range(component_count)]
    metadata = cube.metadata.reduce_dimension(dimension).add_dimension(
        dimension, names[0], type="bands",
    )
    for name in names[1:]:
        metadata = metadata.append_band(name)
    if isinstance(cube, DryRunDataCube):
        register_unmix_pushdown_boundary()
        return cube._process(process_id, {"spec": args["spec"]}, metadata=metadata)
    return _apply_native(cube, process_id, {"spec": args["spec"]}, metadata)
