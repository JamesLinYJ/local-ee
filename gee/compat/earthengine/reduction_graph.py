"""Float64 band-axis reductions that bypass narrowing upstream callbacks."""
from .ir import fail


def reduce_bands_double(graph, pixel):
    data = None
    time_state = None
    for index, operand in enumerate(pixel.args[0]):
        ref, label, timed = graph.expression(operand)
        if label is None:
            fail("Float64 band reduction requires each operand on a finite raster grid")
        if time_state is not None and timed != time_state:
            fail("Float64 band reduction requires matching spatial/temporal dimensions")
        time_state = timed
        ref = graph.node("rename_labels", data=ref, dimension="bands", target=[f"a{index}"])
        data = ref if data is None else graph.node("merge_cubes", cube1=data, cube2=ref)
    if data is None:
        fail("Cannot reduce an empty Float64 band axis")
    return graph.node("local_ee_reduce_bands", data=data, reducer=pixel.args[1]), "v", time_state
