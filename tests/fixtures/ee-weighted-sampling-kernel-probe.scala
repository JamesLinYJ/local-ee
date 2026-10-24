package local.ee.reduce

import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.layer.SpatialKey
import geotrellis.proj4.CRS
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, FloatArrayTile, FloatConstantNoDataCellType, MultibandTile, Tile}
import local.ee.image.sample.{LocalEeImageSampleKernel, LocalEeImageSampleOptions}
import local.ee.sample.LocalEeSampleKernel
import org.openeo.geotrelliscommon.{CubeProcessProvider, CubeProcessRegistry}

import scala.jdk.CollectionConverters._

/** Compose the actual mask-apply numeric tile kernel with the existing sample kernels. */
object WeightedSamplingKernelProbe {
  private val mapper = new ObjectMapper()
  private val Apply = LocalEeMaskWeightsSpec.parse("{\"op\":\"apply\",\"v\":1}")

  private final case class InputTile(key: SpatialKey, raw: Vector[Tile], masks: Vector[Tile], names: Vector[String])

  private def number(value: Any): Double = value match {
    case null => Double.NaN
    case raw: Number => raw.doubleValue()
    case _ => throw new IllegalArgumentException("fixture pixel must be a number or null")
  }

  private def values(row: java.util.Map[String, Object]): Vector[Double] =
    row.get("values").asInstanceOf[java.util.List[Any]].asScala.map(number).toVector

  private def tile(row: java.util.Map[String, Object], noDataValue: Double = Double.NaN): Tile = {
    val input = values(row).map(value => if (value.isNaN) noDataValue else value).toArray
    row.get("cell_type") match {
      case "float32-stage" =>
        val staged = input.map(_.toFloat)
        FloatArrayTile(staged, 2, 2, FloatConstantNoDataCellType)
          .convert(DoubleConstantNoDataCellType)
      case "float32" => FloatArrayTile(input.map(_.toFloat), 2, 2, FloatConstantNoDataCellType)
      case _ => DoubleArrayTile(input, 2, 2, DoubleConstantNoDataCellType)
    }
  }

  private def readInputs(fixture: java.util.Map[String, Object]): Vector[InputTile] =
    fixture.get("tiles").asInstanceOf[java.util.List[java.util.Map[String, Object]]].asScala.map { row =>
      val rawRows = row.get("raw_bands").asInstanceOf[java.util.List[java.util.Map[String, Object]]].asScala.toVector
      val maskRows = row.get("mask_bands").asInstanceOf[java.util.List[java.util.Map[String, Object]]].asScala.toVector
      val names = rawRows.map(_.get("name").asInstanceOf[String])
      require(names.nonEmpty && names.length == maskRows.length && maskRows.forall(_.get("name") != null),
        "fixture raw and mask bands must be paired")
      InputTile(
        SpatialKey(row.get("col").asInstanceOf[Number].intValue(),
          row.get("row").asInstanceOf[Number].intValue()),
        rawRows.map(tile(_)), maskRows.map(tile(_, 0d)), names)
    }.toVector

  private def applyMasks(input: InputTile, mode: String): MultibandTile = {
    val result = input.raw.indices.map { index =>
      val weight = mode match {
        case "fractional" => input.masks(index)
        case "all_positive" => DoubleArrayTile(Array.fill(input.raw(index).cols * input.raw(index).rows)(1d),
          input.raw(index).cols, input.raw(index).rows, DoubleConstantNoDataCellType)
        case "all_zero" => DoubleArrayTile(Array.fill(input.raw(index).cols * input.raw(index).rows)(0d),
          input.raw(index).cols, input.raw(index).rows, DoubleConstantNoDataCellType)
        case other => throw new IllegalArgumentException(s"unknown fixture mask mode: $other")
      }
      LocalEeMaskWeightsNumeric.applyTile(ArrayMultibandTile(Array[Tile](input.raw(index), weight)), Apply)
    }.toArray
    ArrayMultibandTile(result)
  }

  private def projectedValues(tile: MultibandTile, names: Vector[String]): java.util.Map[String, Object] = {
    val output = new java.util.LinkedHashMap[String, Object]()
    names.indices.foreach { band =>
      val pixels = new java.util.ArrayList[Object]()
      var row = 0
      while (row < tile.rows) {
        var col = 0
        while (col < tile.cols) {
          val value = tile.band(band).getDouble(col, row)
          pixels.add(if (value.isNaN) null else java.lang.Double.valueOf(value))
          col += 1
        }
        row += 1
      }
      output.put(names(band), pixels)
    }
    output
  }

  private def imageSampleRows(
    inputs: Vector[InputTile], grid: LocalEeSampleKernel.Grid, region: String,
    options: LocalEeImageSampleOptions.Value, tiles: Map[SpatialKey, MultibandTile]
  ): Vector[LocalEeImageSampleKernel.Row] = {
    val geometry = LocalEeSampleKernel.parseAndProjectWkts(
      java.util.Arrays.asList(region), CRS.fromEpsgCode(4326)).head
    val feature = LocalEeSampleKernel.prepareFeatures(Seq(geometry), grid).head
    val minKey = SpatialKey(0, 0)
    val maxKey = SpatialKey(grid.columns.toInt / grid.tileCols - 1, grid.rows.toInt / grid.tileRows - 1)
    val keys = LocalEeImageSampleKernel.candidateKeys(feature, grid, minKey, maxKey)
    val population = if (options.numPixels.contains(0)) 0L else
      keys.iterator.flatMap(key => LocalEeImageSampleKernel.cellsInTile(key, grid, feature)).length.toLong
    keys.iterator.flatMap { key =>
      LocalEeImageSampleKernel.sampleTileIterator(tiles.get(key), key, grid, feature,
        options, inputs.head.names.length, population, (x, y) => (x, y))
    }.toVector.sortBy(row => (row.feature, row.row, row.col))
  }

  private def sampleRegionsRows(
    inputs: Vector[InputTile], tiles: Map[SpatialKey, MultibandTile], grid: LocalEeSampleKernel.Grid,
    wkts: Vector[String]
  ): Vector[LocalEeSampleKernel.SampleRow] = {
    val geometries = LocalEeSampleKernel.parseAndProjectWkts(wkts.asJava, CRS.fromEpsgCode(4326))
    val features = LocalEeSampleKernel.prepareFeatures(geometries, grid)
    inputs.iterator.flatMap { input =>
      LocalEeSampleKernel.sampleTile(tiles(input.key), input.key, grid, features, (x, y) => (x, y))
    }.toVector.sortBy(row => (row.feature, row.row, row.col))
  }

  private def rowArray(json: String): com.fasterxml.jackson.databind.JsonNode = mapper.readTree(json)

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "usage: WeightedSamplingKernelProbe fixture.json")
    val fixture = mapper.readValue(new java.io.File(args(0)), classOf[java.util.Map[String, Object]])
    val inputs = readInputs(fixture)
    val gridRow = fixture.get("grid").asInstanceOf[java.util.Map[String, Object]]
    val grid = LocalEeSampleKernel.Grid(
      number(gridRow.get("xmin")), number(gridRow.get("ymin")),
      number(gridRow.get("xmax")), number(gridRow.get("ymax")),
      gridRow.get("columns").asInstanceOf[Number].longValue(),
      gridRow.get("rows").asInstanceOf[Number].longValue(),
      gridRow.get("tile_cols").asInstanceOf[Number].intValue(),
      gridRow.get("tile_rows").asInstanceOf[Number].intValue())

    val stagedByMode = Vector("fractional", "all_positive", "all_zero").map { mode =>
      mode -> inputs.map(input => input.key -> applyMasks(input, mode)).toMap
    }.toMap
    val projected = new java.util.LinkedHashMap[String, Object]()
    val projectedPositive = new java.util.LinkedHashMap[String, Object]()
    inputs.foreach { input =>
      projected.put(s"${input.key.col},${input.key.row}",
        projectedValues(stagedByMode("fractional")(input.key), input.names))
      projectedPositive.put(s"${input.key.col},${input.key.row}",
        projectedValues(stagedByMode("all_positive")(input.key), input.names))
    }

    val region = fixture.get("sample_region").asInstanceOf[java.util.Map[String, Object]]
    val polygon = "POLYGON ((0 2, 4 2, 4 0, 0 0, 0 2))"
    val cases = fixture.get("image_sample_cases")
      .asInstanceOf[java.util.List[java.util.Map[String, Object]]].asScala.map { row =>
        val mode = row.get("mask_mode").asInstanceOf[String]
        val options = LocalEeImageSampleOptions.parse(mapper.writeValueAsString(row.get("options")))
        val sampleRows = imageSampleRows(inputs, grid, polygon, options, stagedByMode(mode))
        val output = new java.util.LinkedHashMap[String, Object]()
        output.put("name", row.get("name"))
        output.put("mask_mode", mode)
        output.put("rows", rowArray(LocalEeImageSampleKernel.rowsJson(sampleRows)))
        output
      }.toVector

    val wkts = fixture.get("regions_wkt").asInstanceOf[java.util.List[String]].asScala.toVector
    val regionTiles = stagedByMode(fixture.get("sample_regions_options")
      .asInstanceOf[java.util.Map[String, Object]].get("mask_mode").asInstanceOf[String])
    val nativeRegions = sampleRegionsRows(inputs, regionTiles, grid, wkts)

    val providers = java.util.ServiceLoader.load(classOf[CubeProcessProvider]).stream().iterator().asScala
      .map(_.get()).toVector
    require(providers.exists(_.isInstanceOf[LocalEeMaskWeightsCubeProcessProvider]),
      "mask-weight ServiceLoader provider is missing from the audit JAR")
    require(providers.exists(_.isInstanceOf[local.ee.image.sample.LocalEeImageSampleCubeProcessProvider]),
      "Image.sample ServiceLoader provider is missing from the audit JAR")
    require(providers.exists(_.isInstanceOf[local.ee.sample.LocalEeSampleCubeProcessProvider]),
      "sampleRegions ServiceLoader provider is missing from the audit JAR")
    val ids = CubeProcessRegistry.processIds().asScala.toSet
    require(ids.contains("local_ee_mask_weights") && ids.contains("local_ee_image_sample") &&
      ids.contains("local_ee_sample_regions"), "native sampling or mask-weight SPI id is not registered")

    val output = new java.util.LinkedHashMap[String, Object]()
    output.put("fixture_schema", fixture.get("schema"))
    output.put("projected_fractional_tiles", projected)
    output.put("projected_all_positive_tiles", projectedPositive)
    output.put("image_sample_cases", cases.asJava)
    output.put("sample_regions_rows", rowArray(LocalEeSampleKernel.rowsJson(nativeRegions)))
    output.put("loaded_spi_ids", ids.toVector.sorted.asJava)
    println("WEIGHTED_SAMPLING_NATIVE_RESULT " + mapper.writeValueAsString(output))
  }
}
