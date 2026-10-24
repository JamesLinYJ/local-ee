package local.ee.reduce

import com.fasterxml.jackson.databind.{JsonNode, ObjectMapper}
import geotrellis.layer.{Bounds, LayoutDefinition, SpatialKey, TileLayerMetadata}
import geotrellis.proj4.CRS
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile, TileLayout}
import geotrellis.raster.mapalgebra.local.{And, Equal, Greater, Less, Not, Or, Unequal}
import geotrellis.vector.Extent
import local.ee.image.sample.{LocalEeImageSampleKernel, LocalEeImageSampleOptions}
import local.ee.mask.LocalEeMaskCubeProcesses
import local.ee.sample.LocalEeSampleKernel
import org.apache.spark.{SparkConf, SparkContext}
import org.openeo.geotrelliscommon.{OpenEORasterCube, OpenEORasterCubeMetadata}

import scala.jdk.CollectionConverters._

/** Tiny local[1] probe for Wave67 expressions, setter fill, and Image.sample rows. */
object EmptyExpressionKernelProbe {
  private val mapper = new ObjectMapper()
  private val key = SpatialKey(0, 0)
  private val Apply = LocalEeMaskWeightsSpec.parse("{\"op\":\"apply\",\"v\":1}")
  private val Update = LocalEeMaskWeightsSpec.parse("{\"op\":\"update\",\"v\":1}")
  private val Validity = LocalEeMaskWeightsSpec.parse("{\"op\":\"validity\",\"v\":1}")

  private def numbers(node: JsonNode): Vector[Double] = node.elements().asScala.map { value =>
    if (value == null || value.isNull) Double.NaN else value.doubleValue()
  }.toVector

  private def tile(values: Seq[Double], cols: Int, rows: Int): Tile =
    DoubleArrayTile(values.toArray, cols, rows, DoubleConstantNoDataCellType)

  private def one(value: Tile): MultibandTile = ArrayMultibandTile(Array[Tile](value))
  private def many(values: Tile*): MultibandTile = ArrayMultibandTile(values.toArray)
  private def constant(value: Double, cols: Int, rows: Int): Tile =
    tile(Vector.fill(cols * rows)(value), cols, rows)

  private def operand(index: Int): String = s"{\"band\":$index}"
  private def operand(value: Double): String = {
    val bits = java.lang.Long.toUnsignedString(java.lang.Double.doubleToRawLongBits(value), 16)
    s"{\"constant\":\"${("0" * (16 - bits.length)) + bits}\"}"
  }
  private def integer(operation: String, operands: String*): LocalEeIntegerValuesSpec.Value =
    LocalEeIntegerValuesSpec.parse(
      s"{\"dtype\":null,\"op\":\"$operation\",\"operands\":[${operands.mkString(",")}],\"v\":1}")

  private def pixels(source: Tile): java.util.List[Object] = {
    val result = new java.util.ArrayList[Object]()
    var row = 0
    while (row < source.rows) {
      var col = 0
      while (col < source.cols) {
        val value = source.getDouble(col, row)
        result.add(if (value.isNaN) null else java.lang.Double.valueOf(value))
        col += 1
      }
      row += 1
    }
    result
  }

  private def geotrellisBooleanControl(): java.util.Map[String, Object] = {
    val r = geotrellis.raster.FloatArrayTile(
      Array(1f, 2f, Float.NaN), 3, 1, geotrellis.raster.FloatConstantNoDataCellType)
    val n = geotrellis.raster.FloatArrayTile(
      Array(3f, Float.NaN, 5f), 3, 1, geotrellis.raster.FloatConstantNoDataCellType)
    val greaterR = Greater(r, 0d)
    val greaterN = Greater(n, 0d)
    val lessR = Less(r, 0d)
    val lessN = Less(n, 0d)
    val positiveBoth = And(greaterR, greaterN)
    // Equivalent to the callback's is_nodata/if guard: retain the actual
    // GeoTrellis comparison/And result for valid tuples, then restore NoData
    // wherever either original Float32 operand was missing.
    val inputMissing = Array.tabulate(r.cols * r.rows) { index =>
      val col = index % r.cols
      val row = index / r.cols
      if (r.getDouble(col, row).isNaN || n.getDouble(col, row).isNaN) 1f else 0f
    }
    val nodataGuardedPositive = geotrellis.raster.FloatArrayTile(
      Array.tabulate(r.cols * r.rows) { index =>
        if (inputMissing(index) != 0f) Float.NaN
        else positiveBoth.getDouble(index % r.cols, index / r.cols).toFloat
      }, r.cols, r.rows, geotrellis.raster.FloatConstantNoDataCellType)
    val result = new java.util.LinkedHashMap[String, Object]()
    result.put("input_r", pixels(r))
    result.put("input_n", pixels(n))
    result.put("greater_r", pixels(greaterR))
    result.put("greater_n", pixels(greaterN))
    result.put("less_r", pixels(lessR))
    result.put("less_n", pixels(lessN))
    result.put("and_positive", pixels(positiveBoth))
    result.put("input_missing_mask", pixels(geotrellis.raster.FloatArrayTile(
      inputMissing, r.cols, r.rows, geotrellis.raster.FloatConstantNoDataCellType)))
    result.put("and_positive_input_nodata_preserved", pixels(nodataGuardedPositive))
    result
  }

  private def geotrellisLogicalNonBinaryControl(): java.util.Map[String, Object] = {
    val x = geotrellis.raster.FloatArrayTile(
      Array(2f, -3f, 0f), 3, 1, geotrellis.raster.FloatConstantNoDataCellType)
    val y = geotrellis.raster.FloatArrayTile(
      Array(-3f, 2f, 2f), 3, 1, geotrellis.raster.FloatConstantNoDataCellType)
    val xNonzero = Unequal(x, 0d)
    val yNonzero = Unequal(y, 0d)
    val logicalNotX = Equal(x, 0d)
    val result = new java.util.LinkedHashMap[String, Object]()
    result.put("input_x", pixels(x))
    result.put("input_y", pixels(y))
    result.put("and_raw", pixels(And(x, y)))
    result.put("or_raw", pixels(Or(x, y)))
    result.put("not_x_raw", pixels(Not(x)))
    result.put("x_nonzero", pixels(xNonzero))
    result.put("y_nonzero", pixels(yNonzero))
    result.put("and_x_nonzero", pixels(And(xNonzero, yNonzero)))
    result.put("or_x_nonzero", pixels(Or(xNonzero, yNonzero)))
    result.put("not_x_equal_zero", pixels(logicalNotX))
    result
  }

  private def spatialCube(sc: SparkContext, extent: Extent, layout: LayoutDefinition,
                          values: Tile, name: String): OpenEORasterCube[SpatialKey] = {
    val metadata = TileLayerMetadata(DoubleConstantNoDataCellType, layout, extent,
      CRS.fromEpsgCode(4326), Bounds(key, key))
    new OpenEORasterCube[SpatialKey](sc.parallelize(Seq(key -> one(values)), 1), metadata,
      new OpenEORasterCubeMetadata(Seq(name)))
  }

  private def sample(values: Seq[Tile], regionWkt: String,
                     grid: LocalEeSampleKernel.Grid): JsonNode = {
    val geometry = LocalEeSampleKernel.parseAndProjectWkts(
      java.util.Arrays.asList(regionWkt), CRS.fromEpsgCode(4326)).head
    val feature = LocalEeSampleKernel.prepareFeatures(Seq(geometry), grid).head
    val tileValue = many(values: _*)
    val population = LocalEeImageSampleKernel.cellsInTile(key, grid, feature).length.toLong
    val options = LocalEeImageSampleOptions.Value(None, None, 0, dropNulls = false)
    val rows = LocalEeImageSampleKernel.sampleTileIterator(
      Some(tileValue), key, grid, feature, options, values.length, population,
      (x, y) => (x, y)).toVector
    mapper.readTree(LocalEeImageSampleKernel.rowsJson(rows))
  }

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "usage: EmptyExpressionKernelProbe fixture.json")
    val fixture = mapper.readTree(new java.io.File(args(0)))
    val gridJson = fixture.get("grid")
    val cols = gridJson.get("tile_cols").intValue()
    val rows = gridJson.get("tile_rows").intValue()
    require(cols == 4 && rows == 4, "Wave67 probe requires one fixed 4x4 tile")
    val count = cols * rows
    val grid = LocalEeSampleKernel.Grid(0d, 0d, 4d, 4d, 4L, 4L, cols, rows)
    val red = tile(numbers(fixture.path("source_values").path("red")), cols, rows)
    val nir = tile(numbers(fixture.path("source_values").path("nir")), cols, rows)
    val twoBands = many(nir, red)
    val sum = LocalEeIntegerValuesNumeric.applyTile(twoBands, integer("add", operand(0), operand(1)))
    val redPlusTwo = LocalEeIntegerValuesNumeric.applyTile(
      one(red), integer("add", operand(0), operand(2d)))
    val difference = LocalEeIntegerValuesNumeric.applyTile(
      twoBands, integer("subtract", operand(0), operand(1)))
    val ratioInput = many(difference, sum)
    val unweightedNd = LocalEeIntegerValuesNumeric.applyTile(
      ratioInput, integer("divide", operand(0), operand(1)))
    val redValid = numbers(fixture.path("source_values").path("red")).map(v => !v.isNaN && v >= 0d)
    val nirValid = numbers(fixture.path("source_values").path("nir")).map(v => !v.isNaN && v >= 0d)
    val sumValues = pixels(sum).asScala.map(value => if (value == null) Double.NaN else value.asInstanceOf[Number].doubleValue()).toVector
    val conditions = tile(sumValues.indices.map { index =>
      if (redValid(index) && nirValid(index) && sumValues(index) != 0d) 1d else 0d
    }, cols, rows)
    val invalidBranch = tile(Vector.fill(count)(Double.NaN), cols, rows)
    val normalized = LocalEeIntegerValuesNumeric.applyTile(
      many(conditions, unweightedNd, invalidBranch),
      integer("select", operand(0), operand(1), operand(2)))

    val transitions = fixture.path("mask_transitions")
    val science = tile(numbers(transitions.path("science")), cols, rows)
    val old = tile(numbers(transitions.path("old_weights")), cols, rows)
    val replacement = tile(numbers(transitions.path("new_weights")), cols, rows)
    val rawValidity = LocalEeMaskWeightsNumeric.applyTile(one(science), Validity)
    val effectiveOld = LocalEeMaskWeightsNumeric.applyTile(many(rawValidity, old), Update)
    val oldScience = LocalEeMaskWeightsNumeric.applyTile(many(science, effectiveOld), Apply)

    val recoveryRaw = tile(numbers(fixture.path("source_values").path("red")), cols, rows)
    val recoveryValidity = LocalEeMaskWeightsNumeric.applyTile(one(recoveryRaw), Validity)
    val fractionalWeight = constant(0.25d, cols, rows)
    val hiddenFractionalWeight = LocalEeMaskWeightsNumeric.applyTile(
      many(recoveryValidity, fractionalWeight), Update)
    val hiddenZeroWeight = LocalEeMaskWeightsNumeric.applyTile(
      many(hiddenFractionalWeight, constant(0d, cols, rows)), Update)
    val hiddenFractionalScience = LocalEeMaskWeightsNumeric.applyTile(
      many(recoveryRaw, hiddenZeroWeight), Apply)

    val conf = new SparkConf().setMaster("local[1]").setAppName("local-ee-wave67-native-probe")
      .set("spark.ui.enabled", "false").set("spark.driver.host", "127.0.0.1")
      .set("spark.driver.bindAddress", "127.0.0.1").set("spark.driver.memory", "1g")
    val sc = new SparkContext(conf)
    sc.setLogLevel("ERROR")
    try {
      val extent = Extent(0d, 0d, 4d, 4d)
      val layout = LayoutDefinition(extent, TileLayout(1, 1, cols, rows))
      val input = spatialCube(sc, extent, layout, oldScience, "science")
      val zeros = spatialCube(sc, extent, layout, constant(0d, cols, rows), "zero")
      val unmaskArgs = new java.util.HashMap[String, Object]()
      unmaskArgs.put("value", zeros)
      unmaskArgs.put("same_footprint", java.lang.Boolean.TRUE)
      val filledCube = new LocalEeMaskCubeProcesses().localEeUnmask(input, unmaskArgs)
        .asInstanceOf[OpenEORasterCube[SpatialKey]]
      val filled = filledCube.first()._2.band(0)
      val newBaseValidity = LocalEeMaskWeightsNumeric.applyTile(one(filled), Validity)
      val setterWeight = LocalEeMaskWeightsNumeric.applyTile(many(newBaseValidity, replacement), Update)
      val setterValue = LocalEeMaskWeightsNumeric.applyTile(many(filled, setterWeight), Apply)

      val updateWeight = LocalEeMaskWeightsNumeric.applyTile(many(effectiveOld, replacement), Update)
      val updateValue = LocalEeMaskWeightsNumeric.applyTile(many(science, updateWeight), Apply)

      val recoveryInput = spatialCube(sc, extent, layout, hiddenFractionalScience,
        "fractional_hidden_recovery")
      val recoveryUnmaskArgs = new java.util.HashMap[String, Object]()
      recoveryUnmaskArgs.put("value", zeros)
      recoveryUnmaskArgs.put("same_footprint", java.lang.Boolean.TRUE)
      val recoveryFilledCube = new LocalEeMaskCubeProcesses()
        .localEeUnmask(recoveryInput, recoveryUnmaskArgs)
        .asInstanceOf[OpenEORasterCube[SpatialKey]]
      val recoveryFilled = recoveryFilledCube.first()._2.band(0)
      val recoveryBaseValidity = LocalEeMaskWeightsNumeric.applyTile(one(recoveryFilled), Validity)
      val recoveryWeight = LocalEeMaskWeightsNumeric.applyTile(
        many(recoveryBaseValidity, constant(1d, cols, rows)), Update)
      val recoveryValue = LocalEeMaskWeightsNumeric.applyTile(
        many(recoveryFilled, recoveryWeight), Apply)

      val region = "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))"
      val outputs = new java.util.LinkedHashMap[String, Object]()
      outputs.put("map_sample_rows", sample(
        Seq(sum, red, red, nir, redPlusTwo, unweightedNd, normalized), region, grid))
      outputs.put("default_value_sample_rows", sample(
        Seq.fill(4)(invalidBranch), region, grid))
      outputs.put("default_weight_sample_rows", sample(
        Seq.fill(4)(constant(0d, cols, rows)), region, grid))
      outputs.put("setter_value_sample_rows", sample(Seq(setterValue), region, grid))
      outputs.put("setter_weight_sample_rows", sample(Seq(setterWeight), region, grid))
      outputs.put("update_mask_value_sample_rows", sample(Seq(updateValue), region, grid))
      outputs.put("update_mask_weight_sample_rows", sample(Seq(updateWeight), region, grid))
      outputs.put("fractional_hidden_recovery_value_sample_rows", sample(Seq(recoveryValue), region, grid))
      outputs.put("fractional_hidden_recovery_weight_sample_rows", sample(Seq(recoveryWeight), region, grid))
      outputs.put("old_effective_weights", pixels(effectiveOld))
      outputs.put("filled_science", pixels(filled))
      outputs.put("setter_values", pixels(setterValue))
      outputs.put("setter_weights", pixels(setterWeight))
      outputs.put("update_mask_values", pixels(updateValue))
      outputs.put("update_mask_weights", pixels(updateWeight))
      outputs.put("fractional_hidden_recovery_values", pixels(recoveryValue))
      outputs.put("fractional_hidden_recovery_weights", pixels(recoveryWeight))
      outputs.put("geotrellis_boolean_control", geotrellisBooleanControl())
      outputs.put("geotrellis_logical_nonbinary_control", geotrellisLogicalNonBinaryControl())
      println("EMPTY_EXPRESSION_NATIVE_RESULT " + mapper.writeValueAsString(outputs))
    } finally sc.stop()
  }
}
