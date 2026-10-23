"""Shared bounded admission for trusted raster extension bridges."""
from __future__ import annotations


def validate_cube_trace(cube, process_id, *, max_nodes=500, max_roots=500):
    """Bound and cycle-check traces without inferring dry-run input bands.

    The pinned driver leaves selected and renamed band metadata stale and
    represents merged cubes with separate traces. Dry-run therefore proves
    only the output schema and retains the dependency graph; ordered input
    labels are checked when an actual cube reaches this bridge. Each invocation
    is limited to 500 roots and 500 distinct trace nodes, including sources.
    """
    if (type(max_nodes) is not int or not 1 <= max_nodes <= 500
            or type(max_roots) is not int or not 1 <= max_roots <= 500):
        raise ValueError("Cube trace bounds must remain within1..500")
    from openeo_driver.dry_run import DataSource, DataTrace

    traces = cube._traces
    if type(traces) not in (list, tuple):
        raise ValueError(f"{process_id} requires a valid dry-run trace list")
    if len(traces) > max_roots:
        raise ValueError(
            f"{process_id} dry-run trace exceeds {max_roots} source branches"
        )

    counted = set()
    completed = set()
    for root in traces:
        if root is None:
            raise ValueError(f"{process_id} dry-run trace does not reach a data source")
        trace = root
        path = set()
        while True:
            if isinstance(trace, DataSource):
                identity = id(trace)
                if identity not in counted:
                    counted.add(identity)
                    if len(counted) > max_nodes:
                        raise ValueError(
                            f"{process_id} dry-run trace exceeds {max_nodes} nodes"
                        )
                completed.add(identity)
                completed.update(path)
                break
            if not isinstance(trace, DataTrace):
                if trace is None:
                    raise ValueError(
                        f"{process_id} dry-run trace does not reach a data source"
                    )
                raise ValueError(f"{process_id} dry-run trace contains an unknown node")
            identity = id(trace)
            if identity in path:
                raise ValueError(f"{process_id} dry-run trace contains a cycle")
            if identity in completed:
                completed.update(path)
                break
            path.add(identity)
            if identity not in counted:
                counted.add(identity)
                if len(counted) > max_nodes:
                    raise ValueError(
                        f"{process_id} dry-run trace exceeds {max_nodes} nodes"
                    )
            trace = trace.parent
