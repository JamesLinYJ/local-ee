"""Recover an explicit dry-run band selection without guessing raster values."""
from __future__ import annotations


def single_band_metadata(cube, process_id):
    """Validate actual metadata or a bounded, unambiguous pending band filter.

    The pinned DryRunDataCube records filter_bands without updating metadata.
    Follow only known band-preserving trace operations back to the latest
    filter, never through a merge, reducer, or another native operation. Actual
    cubes continue to require one real metadata band and native tile validation.
    """
    from openeo_driver.dry_run import DataTrace, DryRunDataCube

    metadata = cube.metadata
    if not metadata.has_band_dimension():
        raise ValueError(f"{process_id} requires exactly one named source band")
    if isinstance(cube, DryRunDataCube) and len(cube._traces) == 1:
        trace = cube._traces[0]
        preserving = {"spatial_extent", "weak_spatial_extent", "temporal_extent",
                      "resample_spatial", "process_type"}
        seen = set()
        for _ in range(500):
            if not isinstance(trace, DataTrace):
                break
            if id(trace) in seen:
                raise ValueError("Neighborhood dry-run band trace contains a cycle")
            seen.add(id(trace))
            if trace._operation == "bands":
                bands = trace._arguments
                if (type(bands) is not list or len(bands) != 1
                        or type(bands[0]) is not str or not 1 <= len(bands[0]) <= 256):
                    raise ValueError(f"{process_id} requires exactly one explicit source band")
                metadata = metadata.filter_bands(bands)
                break
            if trace._operation not in preserving:
                break
            trace = trace.parent
        else:
            raise ValueError("Neighborhood dry-run band trace exceeds 500 operations")
    if (len(metadata.band_names) != 1 or type(metadata.band_names[0]) is not str
            or not metadata.band_names[0]):
        raise ValueError(f"{process_id} requires exactly one named source band")
    return metadata
