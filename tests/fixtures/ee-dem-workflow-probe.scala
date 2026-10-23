package local.ee.reduce

import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.raster.GridBounds
import geotrellis.raster.io.geotiff.SinglebandGeoTiff
import geotrellis.raster.io.geotiff.reader.GeoTiffReader

/** Trusted one-file GeoTrellis terrain path; no SparkContext, service, or user code. */
object EeDemWorkflowProbe {
  private val mapper = new ObjectMapper()

  def main(args: Array[String]): Unit = {
    require(args.length == 4,
      "expected normalized COG, output GeoTIFF, canonical terrain spec, and selected item id")
    val inputPath = args(0)
    val outputPath = args(1)
    val spec = LocalEeTerrainSpec.parse(args(2))
    val selectedSourceItemId = args(3)
    val source = GeoTiffReader.readSingleband(inputPath)
    val input = source.tile
    require(input.cols > 2 && input.rows > 2, "DEM source must be larger than the terrain stencil")
    require(source.bandCount == 1, "normalized DEM COG must have exactly one band")

    val extent = source.extent
    val cellSize = source.cellSize
    val grid = LocalEeTerrainMetric.Grid(
      extent.xmin, extent.ymax, cellSize.width, cellSize.height,
      input.cols.toLong, input.rows.toLong)
    val result = LocalEeTerrainNumeric.applyBufferedTile(
      input,
      GridBounds[Int](0, 0, input.cols - 1, input.rows - 1),
      input.cols, input.rows, 0, 0, grid,
      LocalEeTerrainMetric.fromCrs(source.crs), spec)

    SinglebandGeoTiff(result.tile, extent, source.crs).write(outputPath)
    val readback = GeoTiffReader.readSingleband(outputPath)
    require(readback.cols == input.cols && readback.rows == input.rows,
      "GeoTrellis GeoTIFF readback changed the DEM grid dimensions")
    require(readback.extent == extent && readback.crs == source.crs,
      "GeoTrellis GeoTIFF readback changed the DEM extent or CRS")

    var inputNoData = 0
    var outputNoData = 0
    var outputZeros = 0
    var output255 = 0
    var minimum = Double.PositiveInfinity
    var maximum = Double.NegativeInfinity
    var row = 0
    while (row < input.rows) {
      var col = 0
      while (col < input.cols) {
        if (input.getDouble(col, row).isNaN) inputNoData += 1
        val value = readback.tile.getDouble(col, row)
        if (value.isNaN) outputNoData += 1
        else {
          if (value == 0.0d) outputZeros += 1
          if (value == 255.0d) output255 += 1
          minimum = math.min(minimum, value)
          maximum = math.max(maximum, value)
        }
        col += 1
      }
      row += 1
    }
    val report = mapper.createObjectNode()
    report.put("operation", spec.operation)
    report.put("selected_source_item_id", selectedSourceItemId)
    report.put("cols", input.cols)
    report.put("rows", input.rows)
    report.put("crs", source.crs.toString)
    report.put("cell_width", cellSize.width)
    report.put("cell_height", cellSize.height)
    report.put("input_nodata", inputNoData)
    report.put("output_nodata", outputNoData)
    report.put("output_valid", input.cols * input.rows - outputNoData)
    report.put("output_zero", outputZeros)
    report.put("output_255", output255)
    if (minimum.isFinite) report.put("minimum", minimum)
    if (maximum.isFinite) report.put("maximum", maximum)
    report.put("transform_calls", result.transformCalls)
    report.put("explicit_array_count", result.explicitArrayCount)
    report.put("explicit_array_bytes", result.explicitArrayBytes)
    println("DEM_GEO_TIFF_TERRAIN_OK " + mapper.writeValueAsString(report))
  }
}
