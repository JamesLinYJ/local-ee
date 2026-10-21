"""Nearest temporal neighbors and linear interpolation through local EE graphs.

Call build_interpolation with local ImageCollections carrying numeric
system:time_start properties and a common signal band. The versioned synthetic
test fixture supplies these collections; no imagery or Google computation is
implied by this example. Pixels require valid values in both neighbors.
"""


def build_interpolation(ee, targets, observations, window_ms, band="signal"):
    within_window = ee.Filter.maxDifference(
        difference=window_ms,
        leftField="system:time_start",
        rightField="system:time_start",
    )
    previous_condition = ee.Filter.And(
        within_window,
        ee.Filter.greaterThan(leftField="system:time_start", rightField="system:time_start"),
    )
    next_condition = ee.Filter.And(
        within_window,
        ee.Filter.lessThan(leftField="system:time_start", rightField="system:time_start"),
    )
    previous = ee.Join.saveBest("previous", "previous_distance").apply(
        targets, observations, previous_condition)
    paired = ee.ImageCollection(ee.Join.saveBest("following", "following_distance").apply(
        previous, observations, next_condition))

    def estimate(target):
        left = ee.Image(target.get("previous"))
        right = ee.Image(target.get("following"))
        left_time = ee.Number(left.get("system:time_start"))
        span = ee.Number(right.get("system:time_start")).subtract(left_time)
        weight = ee.Number(target.get("system:time_start")).subtract(left_time).divide(span)
        result = left.select(band).add(
            right.select(band).subtract(left.select(band)).multiply(weight))
        return result.rename("interpolated").copyProperties(target, ["system:time_start"])

    return paired.map(estimate)
