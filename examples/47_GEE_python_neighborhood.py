"""Pixel-unit neighborhood workflows on an existing local collection.

Run build_workflow(ee, collection) with the workbench-provided official ee
client. Results are lazy Images/collections; export with the normal local task
API. Meter kernels, weighted kernels and Google parity are not yet supported.
"""


def build_workflow(ee, collection):
    image = collection.first().select("nir")
    square = ee.Kernel.square(1, "pixels", False)
    directional = ee.Kernel.fixed(3, 1, [[0, 1, 1]], 1, 0)
    outputs = {
        operation: getattr(image, "focal" + operation.title())(radius=1, kernelType="square")
        for operation in ("mean", "min", "max", "median", "mode")
    }
    outputs.update({
        "opening": image.focalMin(kernel=square, iterations=2).focalMax(kernel=square, iterations=2),
        "closing": image.focalMax(kernel=square).focalMin(kernel=square),
        "directional": image.reduceNeighborhood(ee.Reducer.mean(), directional),
        "fill": image.reduceNeighborhood(ee.Reducer.median(), square, skipMasked=False),
        "majority": image.reduceNeighborhood(ee.Reducer.mode(), square),
        "normalized": image.reduceNeighborhood(ee.Reducer.mean(), ee.Kernel.circle(1)),
        "observations": collection.map(lambda item: item.select("nir").focalMean(radius=1)),
    })
    return outputs
