"""Fit and predict a per-pixel linear trend from local image timestamps.

The caller supplies an ImageCollection with one scalar ``signal`` band and an
origin timestamp in milliseconds. Each observation contributes its actual
``system:time_start`` as a day offset. The versioned synthetic fixture tests
this path; the optional main block uses the caller's locally available
Sentinel-2 alias and never downloads imagery.
"""

SYNTHETIC_VERSION = "local-ee-synthetic-raster-linear-trend/v1"
DAY_MILLIS = 86_400_000


def build_linear_trend(
    ee,
    collection,
    origin_millis,
    target_millis,
    band="signal",
    fixture_version=SYNTHETIC_VERSION,
):
    """Return per-pixel ``scale``/``offset`` and a labeled target prediction.

    Timestamps come from each input image. A constant ``day`` band is bound
    to the corresponding signal image's local grid before reduction. The
    regression therefore sees ordered ``day, signal`` scalar bands for every
    frame and retains the signal mask as a complete regression-row condition.
    """

    def add_observation_day(image):
        signal = image.select(band)
        day = ee.Number(image.get("system:time_start")).subtract(origin_millis).divide(DAY_MILLIS)
        day_band = ee.Image.constant(day).rename("day")
        return signal.addBands(day_band).select(["day", band]).rename(["day", "signal"]).toFloat()

    fit = collection.map(add_observation_day).reduce(
        reducer=ee.Reducer.linearFit(), parallelScale=1
    )
    target_day = ee.Number(target_millis).subtract(origin_millis).divide(DAY_MILLIS)
    prediction = (
        fit.select("scale")
        .multiply(target_day)
        .add(fit.select("offset"))
        .rename("predicted_signal")
        .set("target_time_millis", target_millis)
        .set("fixtureVersion", fixture_version)
    )
    return {
        "coefficients": fit,
        "prediction": prediction,
        "target_day": target_day,
    }


if __name__ == "__main__":
    import ee

    ee.Initialize()
    local_signal = ee.ImageCollection("sentinel-2-l2a").select("nir").map(
        lambda image: image.rename("signal")
    )
    origin_millis = ee.Date("2020-01-01").millis()
    target_millis = ee.Date("2020-07-01").millis()
    outputs = build_linear_trend(
        ee, local_signal, origin_millis=origin_millis, target_millis=target_millis
    )
    print("Workflow fixture version:", SYNTHETIC_VERSION)
    print("target_day", outputs["target_day"].getInfo())
    print("coefficients", outputs["coefficients"].getInfo())
    print("prediction", outputs["prediction"].getInfo())
