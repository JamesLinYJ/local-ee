package local.ee.reduce

import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.layer.SpatialKey
import geotrellis.proj4.CRS
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, FloatArrayTile, FloatConstantNoDataCellType, MultibandTile, Tile}
import local.ee.image.sample.{LocalEeImageSampleKernel, LocalEeImageSampleOptions}
import local.ee.math.LocalEePixelMathNumeric
import local.ee.sample.LocalEeSampleKernel
import org.openeo.geotrelliscommon.{CubeProcessProvider, CubeProcessRegistry}

import scala.collection.mutable
import scala.jdk.CollectionConverters._

/** Actual local numeric tiles, mask kernels, and image sample rows for Wave66. */
object MaskMathKernelProbe {
  private val mapper = new ObjectMapper()
  private val Apply = LocalEeMaskWeightsSpec.parse("{\"op\":\"apply\",\"v\":1}")
  private val ResultValue = LocalEeMaskWeightsSpec.parse("{\"op\":\"result_value\",\"v\":1}")
  private val Validity = LocalEeMaskWeightsSpec.parse("{\"op\":\"validity\",\"v\":1}")
  private val Update = LocalEeMaskWeightsSpec.parse("{\"op\":\"update\",\"v\":1}")

  private final case class TileInput(raw: Map[String, Tile], weights: Map[String, Tile])
  private final case class Output(values: Tile, weights: Tile)

  private def number(value: Any): Double = value match {
    case null => Double.NaN
    case raw: String if raw == "NaN" => Double.NaN
    case raw: String if raw == "Infinity" => Double.PositiveInfinity
    case raw: String if raw == "-Infinity" => Double.NegativeInfinity
    case raw: String => java.lang.Double.parseDouble(raw)
    case raw: Number => raw.doubleValue()
    case _ => throw new IllegalArgumentException("fixture value must be numeric, null, or a special-value name")
  }

  private def rowValues(row: java.util.Map[String, Object]): Vector[Double] =
    row.get("values").asInstanceOf[java.util.List[Any]].asScala.map(number).toVector

  private def tile(values: Seq[Double], cols: Int, rows: Int): Tile =
    DoubleArrayTile(values.toArray, cols, rows, DoubleConstantNoDataCellType)

  private def asFloat(input: Tile): Tile = {
    val values = Array.tabulate(input.cols * input.rows) { index =>
      val value = input.getDouble(index % input.cols, index / input.cols)
      if (value.isNaN) Float.NaN else value.toFloat
    }
    FloatArrayTile(values, input.cols, input.rows, FloatConstantNoDataCellType)
  }

  private def one(band: Tile): MultibandTile = ArrayMultibandTile(Array[Tile](band))

  private def output(tile: Tile, weight: Tile): MultibandTile =
    ArrayMultibandTile(Array[Tile](tile, weight))

  private def constant(value: Double, cols: Int, rows: Int): Tile =
    DoubleArrayTile(Array.fill(cols * rows)(value), cols, rows, DoubleConstantNoDataCellType)

  private def readInput(fixture: java.util.Map[String, Object]): TileInput = {
    val grid = fixture.get("grid").asInstanceOf[java.util.Map[String, Object]]
    val cols = grid.get("tile_cols").asInstanceOf[Number].intValue()
    val rows = grid.get("tile_rows").asInstanceOf[Number].intValue()
    require(cols == 4 && rows == 2, "Wave66 kernel probe expects one 4x2 tile")
    val tileRow = fixture.get("tiles").asInstanceOf[java.util.List[java.util.Map[String, Object]]].get(0)
    val rawRows = tileRow.get("raw_bands").asInstanceOf[java.util.List[java.util.Map[String, Object]]].asScala
    val maskRows = tileRow.get("mask_bands").asInstanceOf[java.util.List[java.util.Map[String, Object]]].asScala
    val raw = rawRows.map(row => row.get("name").asInstanceOf[String] -> tile(rowValues(row), cols, rows)).toMap
    val weights = maskRows.map(row => row.get("name").asInstanceOf[String] -> tile(rowValues(row), cols, rows)).toMap
    require(raw.keys.map(_ + "_weight").toSet == weights.keySet,
      "Wave66 fixture must pair each raw band with its weight band")
    TileInput(raw, weights)
  }

  private def hexBits(value: Double): String = {
    val raw = java.lang.Long.toUnsignedString(java.lang.Double.doubleToRawLongBits(value), 16)
    ("0" * (16 - raw.length)) + raw
  }

  private def hexFloatBits(value: Float): String = {
    val raw = java.lang.Integer.toUnsignedString(java.lang.Float.floatToRawIntBits(value), 16)
    ("0" * (8 - raw.length)) + raw
  }

  private def atan2SignedZeroControls(): java.util.Map[String, Object] = {
    val x = FloatArrayTile(Array(-1.0f, -1.0f), 2, 1, FloatConstantNoDataCellType)
    val y = FloatArrayTile(Array(-0.0f, 0.0f), 2, 1, FloatConstantNoDataCellType)
    val result = LocalEePixelMathNumeric.applyTile(
      ArrayMultibandTile(Array[Tile](x, y)), "atan2")
    val row = new java.util.LinkedHashMap[String, Object]()
    row.put("x_bits", Seq(hexFloatBits(-1.0f), hexFloatBits(-1.0f)).asJava)
    row.put("y_bits", Seq(hexFloatBits(-0.0f), hexFloatBits(0.0f)).asJava)
    row.put("output_bits", Seq(
      hexFloatBits(result.getDouble(0, 0).toFloat),
      hexFloatBits(result.getDouble(1, 0).toFloat)).asJava)
    row.put("output_values", Seq(
      java.lang.Double.valueOf(result.getDouble(0, 0)),
      java.lang.Double.valueOf(result.getDouble(1, 0))).asJava)
    row
  }

  private def operand(band: Int): String = s"{\"band\":$band}"
  private def operand(value: Double): String = s"{\"constant\":\"${hexBits(value)}\"}"

  private def integerSpec(operation: String, operands: String*): LocalEeIntegerValuesSpec.Value = {
    val wire = s"{\"dtype\":null,\"op\":\"$operation\",\"operands\":[${operands.mkString(",")}],\"v\":1}"
    LocalEeIntegerValuesSpec.parse(wire)
  }

  private def guarded(raw: Tile): Tile =
    LocalEeMaskWeightsNumeric.applyTile(output(raw, constant(1.0, raw.cols, raw.rows)), Apply)

  /** Complete local policy pipeline: source guard, operation, result cleanup, weight update, apply. */
  private def finish(rawResult: Tile, oldWeight: Tile): Output = {
    val clean = LocalEeMaskWeightsNumeric.applyTile(one(rawResult), ResultValue)
    val valid = LocalEeMaskWeightsNumeric.applyTile(one(clean), Validity)
    val weight = LocalEeMaskWeightsNumeric.applyTile(output(valid, oldWeight), Update)
    val value = LocalEeMaskWeightsNumeric.applyTile(output(clean, weight), Apply)
    Output(value, weight)
  }

  private def unary(raw: Tile, weight: Tile, operation: String): Output = {
    val guardedRaw = guarded(raw)
    val name = operation match { case "abs" => "absolute"; case "Not" => "not"; case other => other }
    val result = LocalEeIntegerValuesNumeric.applyTile(one(guardedRaw), integerSpec(name, operand(0)))
    finish(result, weight)
  }

  private def binary(raw: Tile, weight: Tile, operation: String, scalar: Double,
                     scalarLeft: Boolean = false): Output = {
    val guardedRaw = guarded(raw)
    val (name, left, right) = operation match {
      case "pow" => ("power", if (scalarLeft) operand(scalar) else operand(0), if (scalarLeft) operand(0) else operand(scalar))
      case "And" => ("and", if (scalarLeft) operand(scalar) else operand(0), if (scalarLeft) operand(0) else operand(scalar))
      case "Or" => ("or", if (scalarLeft) operand(scalar) else operand(0), if (scalarLeft) operand(0) else operand(scalar))
      case "min" => ("min2", if (scalarLeft) operand(scalar) else operand(0), if (scalarLeft) operand(0) else operand(scalar))
      case "max" => ("max2", if (scalarLeft) operand(scalar) else operand(0), if (scalarLeft) operand(0) else operand(scalar))
      case other => (other, if (scalarLeft) operand(scalar) else operand(0), if (scalarLeft) operand(0) else operand(scalar))
    }
    val result = LocalEeIntegerValuesNumeric.applyTile(
      one(guardedRaw), integerSpec(name, left, right))
    finish(result, weight)
  }

  private def castFloat(raw: Tile, weight: Tile): Output = {
    val guardedRaw = guarded(raw)
    finish(asFloat(guardedRaw).convert(DoubleConstantNoDataCellType), weight)
  }

  private def pixelUnary(input: Output, operation: String): Output = {
    val f32 = asFloat(input.values)
    val result = LocalEePixelMathNumeric.applyTile(one(f32), operation)
    finish(result.convert(DoubleConstantNoDataCellType), input.weights)
  }

  private def pixelAtan2(input: Output, scalar: Double, scalarLeft: Boolean): Output = {
    val left = if (scalarLeft) asFloat(constant(scalar, input.values.cols, input.values.rows)) else asFloat(input.values)
    val right = if (scalarLeft) asFloat(input.values) else asFloat(constant(scalar, input.values.cols, input.values.rows))
    val result = LocalEePixelMathNumeric.applyTile(
      ArrayMultibandTile(Array[Tile](left, right)), "atan2")
    finish(result.convert(DoubleConstantNoDataCellType), input.weights)
  }

  private def pixels(tile: Tile): java.util.List[Object] = {
    val result = new java.util.ArrayList[Object]()
    var row = 0
    while (row < tile.rows) {
      var col = 0
      while (col < tile.cols) {
        val value = tile.getDouble(col, row)
        result.add(if (value.isNaN) null else java.lang.Double.valueOf(value))
        col += 1
      }
      row += 1
    }
    result
  }

  private def nativeOutput(value: Output): java.util.Map[String, Object] = {
    val result = new java.util.LinkedHashMap[String, Object]()
    result.put("values", pixels(value.values))
    result.put("weights", pixels(value.weights))
    result
  }

  private def sampleRows(values: Seq[Tile], cols: Int, rows: Int,
                         grid: LocalEeSampleKernel.Grid, polygonWkt: String): com.fasterxml.jackson.databind.JsonNode = {
    val geometry = LocalEeSampleKernel.parseAndProjectWkts(
      java.util.Arrays.asList(polygonWkt), CRS.fromEpsgCode(4326)).head
    val feature = LocalEeSampleKernel.prepareFeatures(Seq(geometry), grid).head
    val key = SpatialKey(0, 0)
    val multi = ArrayMultibandTile(values.toArray)
    val population = LocalEeImageSampleKernel.cellsInTile(key, grid, feature).length.toLong
    val options = LocalEeImageSampleOptions.Value(None, None, 0, dropNulls = false)
    val rowsOut = LocalEeImageSampleKernel.sampleTileIterator(
      Some(multi), key, grid, feature, options, values.length, population, (x, y) => (x, y)).toVector
    mapper.readTree(LocalEeImageSampleKernel.rowsJson(rowsOut))
  }

  private def resultValueControls(fixture: java.util.Map[String, Object]): java.util.Map[String, Object] = {
    val controls = fixture.get("result_value_controls").asInstanceOf[java.util.List[Any]].asScala.map(number).toVector
    val input = tile(controls, 4, 2)
    val output = LocalEeMaskWeightsNumeric.applyTile(one(input), ResultValue)
    val inputBits = controls.map(value => if (value.isNaN || value.isInfinite) null else hexBits(value))
    val outputBits = (0 until 8).map { index =>
      val value = output.getDouble(index % 4, index / 4)
      if (value.isNaN) null else hexBits(value)
    }
    val row = new java.util.LinkedHashMap[String, Object]()
    row.put("input_bits", inputBits.asJava)
    row.put("output_bits", outputBits.asJava)
    row.put("output_values", pixels(output))
    row
  }

  private def sourceInfinityGuard(fixture: java.util.Map[String, Object]): java.util.List[Object] = {
    val rejectedRows = new java.util.ArrayList[Object]()
    fixture.get("source_infinity_guard_controls")
      .asInstanceOf[java.util.List[java.util.Map[String, Object]]].asScala.foreach { row =>
        val raw = tile(Seq(number(row.get("value"))), 1, 1)
        val zeroWeight = tile(Seq(number(row.get("weight"))), 1, 1)
        var rejected = false
        try LocalEeMaskWeightsNumeric.applyTile(output(raw, constant(1.0, 1, 1)), Apply)
        catch { case _: IllegalArgumentException => rejected = true }
        require(zeroWeight.getDouble(0, 0) == 0.0, "source infinity control must have zero mask weight")
        rejectedRows.add(java.lang.Boolean.valueOf(rejected))
      }
    rejectedRows
  }

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "usage: MaskMathKernelProbe fixture.json")
    val fixture = mapper.readValue(new java.io.File(args(0)), classOf[java.util.Map[String, Object]])
    val input = readInput(fixture)
    val outputs = mutable.LinkedHashMap.empty[String, Output]
    val bands = fixture.get("bands").asInstanceOf[java.util.List[String]].asScala.toVector
    val unaryOps = fixture.get("operations").asInstanceOf[java.util.Map[String, Object]]
      .get("unary").asInstanceOf[java.util.List[String]].asScala.toVector
    bands.foreach { band => unaryOps.foreach { operation =>
      outputs.put(s"${band}_${operation.toLowerCase}", unary(input.raw(band), input.weights(s"${band}_weight"), operation))
    }}

    val operationRow = fixture.get("operations").asInstanceOf[java.util.Map[String, Object]]
    val scalar = number(operationRow.get("binary_constant"))
    val binaryOps = operationRow.get("binary").asInstanceOf[java.util.List[String]].asScala.toVector
    binaryOps.foreach { operation =>
      outputs.put(s"wide_${operation.toLowerCase}_right", binary(input.raw("wide"), input.weights("wide_weight"), operation, scalar))
      outputs.put(s"wide_${operation.toLowerCase}_left", binary(input.raw("wide"), input.weights("wide_weight"), operation, scalar, scalarLeft = true))
    }

    val zero = number(operationRow.get("logic_zero"))
    Vector("And", "Or").foreach { operation =>
      outputs.put(s"red_${operation.toLowerCase}_zero", binary(input.raw("red"), input.weights("red_weight"), operation, zero))
      outputs.put(s"red_zero_${operation.toLowerCase}", binary(input.raw("red"), input.weights("red_weight"), operation, zero, scalarLeft = true))
    }

    val clamp = operationRow.get("clamp").asInstanceOf[java.util.List[Any]].asScala.map(number).toVector
    val clampFirst = binary(input.raw("red"), input.weights("red_weight"), "max", clamp(0))
    outputs.put("red_clamp", binary(clampFirst.values, clampFirst.weights, "min", clamp(1)))
    val scale = operationRow.get("unit_scale").asInstanceOf[java.util.List[Any]].asScala.map(number).toVector
    val scaleFirst = binary(input.raw("red"), input.weights("red_weight"), "subtract", scale(0))
    outputs.put("red_unit_scale", binary(scaleFirst.values, scaleFirst.weights, "divide", scale(1) - scale(0)))

    val wideFloat = castFloat(input.raw("wide"), input.weights("wide_weight"))
    val pixelMathOps = operationRow.get("pixel_math_unary").asInstanceOf[java.util.List[String]].asScala.toVector
    pixelMathOps.foreach { operation =>
      outputs.put(s"wide_pixel_${operation.toLowerCase}", pixelUnary(wideFloat, operation))
    }
    val atan2Scalar = number(operationRow.get("atan2_constant"))
    outputs.put("wide_pixel_atan2_right", pixelAtan2(wideFloat, atan2Scalar, scalarLeft = false))
    outputs.put("wide_pixel_atan2_left", pixelAtan2(wideFloat, atan2Scalar, scalarLeft = true))

    outputs.put("wide_to_float", wideFloat)
    outputs.put("wide_float32_asin", pixelUnary(wideFloat, "asin"))

    val nativeOutputs = new java.util.LinkedHashMap[String, Object]()
    outputs.foreach { case (name, value) => nativeOutputs.put(name, nativeOutput(value)) }
    val sampleNames = fixture.get("sample_outputs").asInstanceOf[java.util.List[String]].asScala.toVector
    require(sampleNames.distinct.size == sampleNames.size && sampleNames.forall(outputs.contains),
      "sample_outputs must name distinct generated results")
    val gridRow = fixture.get("grid").asInstanceOf[java.util.Map[String, Object]]
    val grid = LocalEeSampleKernel.Grid(
      number(gridRow.get("xmin")), number(gridRow.get("ymin")),
      number(gridRow.get("xmax")), number(gridRow.get("ymax")),
      gridRow.get("columns").asInstanceOf[Number].longValue(),
      gridRow.get("rows").asInstanceOf[Number].longValue(),
      gridRow.get("tile_cols").asInstanceOf[Number].intValue(),
      gridRow.get("tile_rows").asInstanceOf[Number].intValue())
    val polygon = "POLYGON ((0 2, 4 2, 4 0, 0 0, 0 2))"
    val sampleValues = sampleRows(sampleNames.map(outputs(_).values), 4, 2, grid, polygon)
    val sampleWeights = sampleRows(sampleNames.map(outputs(_).weights), 4, 2, grid, polygon)

    val ids = CubeProcessRegistry.processIds().asScala.toSet
    require(ids.contains("local_ee_mask_weights") && ids.contains("local_ee_integer_values") &&
      ids.contains("local_ee_pixel_math") && ids.contains("local_ee_image_sample"),
      "Wave66 numeric or sampling SPI id is not registered")
    val providers = java.util.ServiceLoader.load(classOf[CubeProcessProvider])
      .stream().iterator().asScala.map(_.get()).toVector
    require(providers.nonEmpty, "audit JAR has no local cube process providers")

    val root = new java.util.LinkedHashMap[String, Object]()
    root.put("fixture_schema", fixture.get("schema"))
    root.put("outputs", nativeOutputs)
    root.put("result_value_controls", resultValueControls(fixture))
    root.put("source_infinity_guard_rejected", sourceInfinityGuard(fixture))
    root.put("atan2_signed_zero_controls", atan2SignedZeroControls())
    root.put("values_sample_rows", sampleValues)
    root.put("weights_sample_rows", sampleWeights)
    root.put("loaded_spi_ids", ids.toVector.sorted.asJava)
    println("MASK_MATH_NATIVE_RESULT " + mapper.writeValueAsString(root))
  }
}
