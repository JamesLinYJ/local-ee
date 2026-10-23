"""Local pixel-kernel smoothing and edge workflows using the official EE client.

Input must refer to locally catalogued images. This bounded implementation uses
complete nonzero-weight support: a masked neighbor masks the output. Kernel
footprints and mask behavior have not been compared against Google's service.
"""


def build_workflow(ee, collection):
    image = collection.first().select("nir")
    gaussian = ee.Kernel.gaussian(radius=1, sigma=1)
    sobel = ee.Kernel.sobel()
    smooth = image.convolve(gaussian)
    return {
        "boxcar": image.convolve(ee.Kernel.square(1)),
        "gaussian": smooth,
        "laplacian4": image.convolve(ee.Kernel.laplacian4()),
        "laplacian8": image.convolve(ee.Kernel.laplacian8()),
        "sobel_x": image.convolve(sobel),
        "sobel_y": image.convolve(sobel.rotate(1)),
        "prewitt": image.convolve(ee.Kernel.prewitt()),
        "roberts": image.convolve(ee.Kernel.roberts()),
        "sharpen": image.convolve(
            ee.Kernel.fixed(1, 1, [[1]]).add(ee.Kernel.laplacian8(magnitude=-1))
        ),
        "directional": image.convolve(ee.Kernel.fixed(3, 1, [[-1, 0, 1]], 0, 0)),
        "zero": image.convolve(ee.Kernel.fixed(1, 1, [[0]])),
        "smooth_edges": smooth.convolve(ee.Kernel.laplacian4()),
        "morphology": smooth.focalMax(1),
        "observations": collection.map(lambda item: item.select("nir").convolve(gaussian)),
        "multiband": collection.first().select(["nir", "red"]).convolve(gaussian),
    }


if __name__ == "__main__":
    outputs = build_workflow(ee, ee.ImageCollection("sentinel-2-l2a"))  # noqa: F821
    Map.addLayer(outputs["gaussian"], {"min": 0, "max": 1}, "Gaussian")  # noqa: F821
    Map.addLayer(outputs["sobel_x"], {"min": -1, "max": 1}, "Sobel")  # noqa: F821
    Export.image.toDrive(image=outputs["sharpen"], description="local_sharpen",  # noqa: F821
                         fileFormat="GeoTIFF")
