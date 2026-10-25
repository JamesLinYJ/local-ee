"""Explicit model and numerical limits of the bounded geometry measures."""


GEOMETRY_MEASURE_LIMITS = {}

for _family in ("Geometry", "Feature"):
    for _method in ("area", "length", "perimeter", "centroid"):
        GEOMETRY_MEASURE_LIMITS[_family + "." + _method] = [
            "Finite inline EPSG:4326 geometries only. Omitted/null proj uses "
            "declared great-circle edges: WGS84 surface/line integration for "
            "scalar metrics and the highest-dimensional S2 vector centroid. "
            "Explicit EPSG:4326 accepts actual planar edges and returns degree "
            "or square-degree metrics. No implicit edge-model conversion or "
            "other CRS transformation. Valid maxError is accepted on these "
            "no-reprojection paths, not used as a numerical accuracy promise. "
            "Area and perimeter consume polygon components; length consumes "
            "linear components only. Original duplicate/overlapping components "
            "are summed independently. Explicit planar overlapping/duplicate "
            "MultiPolygon inputs preserve individually valid polygon components "
            "through official decoding, metadata and closed literal CSV export. "
            "Set/raster/sampling and table-backed classifier consumers retain strict aggregate "
            "topology validation; invalid shells or holes are never repaired. "
            "Empty scalar measures are zero; empty, "
            "cancelled or numerically indeterminate centroid projections reject. "
            "Point identity returns freshly owned original coordinates. WGS84 "
            "integration has a bounded local convergence policy, not a formal "
            "error certificate or Google numerical-equivalence result. Native "
            "work/output/scan costs share50000 steps and existing geometry "
            "limits. Request-local exact-content reuse lets the preserved full "
            "four-row WGS84 and six-row planar paired Geometry/Feature formulas "
            "fit that unchanged budget; larger compositions remain bounded. "
            "64MiB is tracked S2 memory, not total RSS. Full-sphere public "
            "encoding, distance/buffer and general reprojection remain gaps. "
            "Offline official-client wires, independent references and physical "
            "synthetic CSV do not establish full service/deployment acceptance."
        ]
        if _family == "Feature":
            GEOMETRY_MEASURE_LIMITS[_family + "." + _method].append(
                "Only actual finite inline Features. Centroid retains freshly "
                "owned properties and source identity under the existing local "
                "ID policy; scalar methods return numbers. Null geometry has "
                "zero scalar measures and no centroid. No dynamic raster or "
                "runtime-table geometry overload is implied."
            )
