"""Fit an intercept and one predictor to two aligned raster responses."""

SYNTHETIC_VERSION = "local-ee-synthetic-raster-regression/v1"


def fit_source(ee, source):
    def design_row(image):
        image = ee.Image(image).select(["x", "signal", "temperature"])
        return image.addBands(ee.Image.constant(1).rename("intercept")).select(
            ["intercept", "x", "signal", "temperature"]).toFloat()

    return source.map(design_row).reduce(ee.Reducer.linearRegression(2, 2))


def build_prediction(ee, source, target_x=2):
    fit = fit_source(ee, source)
    coefficients = fit.select("coefficients").arrayFlatten([
        ["offset", "scale"], ["signal", "temperature"]])
    residuals = fit.select("residuals").arrayFlatten([["signal_rms", "temperature_rms"]])
    signal = coefficients.select("offset_signal").add(
        coefficients.select("scale_signal").multiply(target_x)).rename("predicted_signal")
    temperature = coefficients.select("offset_temperature").add(
        coefficients.select("scale_temperature").multiply(target_x)).rename("predicted_temperature")
    return {
        # The common fit retains both responses in its complete-case mask.
        # Materialize responses separately to stay within the graph budget.
        "coefficients_signal": coefficients.select(["offset_signal", "scale_signal"]),
        "coefficients_temperature": coefficients.select(["offset_temperature", "scale_temperature"]),
        "residual_signal": residuals.select("signal_rms"),
        "residual_temperature": residuals.select("temperature_rms"),
        "prediction_signal": signal.set({"fixtureVersion": SYNTHETIC_VERSION, "target_x": target_x}),
        "prediction_temperature": temperature.set({"fixtureVersion": SYNTHETIC_VERSION, "target_x": target_x}),
    }


if __name__ == "__main__":
    import ee

    ee.Initialize()
    # Supply a local collection with the three documented scalar bands.
    outputs = build_prediction(ee, ee.ImageCollection("sentinel-2-l2a"))
    for name, image in outputs.items():
        print(name, image.bandNames().getInfo())
