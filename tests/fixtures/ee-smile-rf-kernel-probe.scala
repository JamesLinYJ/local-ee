package local.ee.smile

import com.fasterxml.jackson.databind.{JsonNode, ObjectMapper}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, FloatArrayTile, FloatConstantNoDataCellType, IntArrayTile, IntConstantNoDataCellType, Tile}
import java.io.{ByteArrayInputStream, ByteArrayOutputStream, File, ObjectInputStream, ObjectOutputStream}
import local.ee.smile.LocalEeSmileRfWire.parseRows
import org.openeo.geotrelliscommon.CubeProcessProvider
import org.slf4j.LoggerFactory
import scala.jdk.CollectionConverters._

/** Trusted standalone Smile/GeoTrellis probe. It does not create a SparkContext. */
object EeSmileRfKernelProbe {
  private def requireRejected(label: String)(body: => Any): Unit = {
    var rejected = false
    try body catch { case _: IllegalArgumentException => rejected = true }
    assert(rejected, s"$label must reject")
  }

  private def text(node: JsonNode, name: String): String = {
    val value = node.get(name)
    assert(value != null && value.isTextual, s"fixture $name must be a string")
    value.textValue()
  }

  private def sameSeedPredictions(spec: String, rows: String, queries: Vector[Array[Double]]) = {
    val first = LocalEeSmileRfFactory.train(spec, rows)
    val second = LocalEeSmileRfFactory.train(spec, rows)
    val firstDepths = first.forest.getTrees.map(_.maxDepth())
    val secondDepths = second.forest.getTrees.map(_.maxDepth())
    val firstPredictions = queries.map(LocalEeSmileRfNumeric.predictValue(_, first))
    val secondPredictions = queries.map(LocalEeSmileRfNumeric.predictValue(_, second))
    assert(firstDepths.sameElements(secondDepths), "same seed must reproduce tree depth sequence")
    assert(firstPredictions == secondPredictions, "same seed must reproduce predictions")
    assert(first.actualTreeCount == first.forest.getTrees.length)
    assert(first.maxDepthSum == firstDepths.iterator.map(_.toLong).sum)
    (first, firstPredictions)
  }

  private def serializedBytes(model: LocalEeSmileRfModel): Array[Byte] = {
    val bytes = new ByteArrayOutputStream()
    val output = new ObjectOutputStream(bytes)
    output.writeObject(model)
    output.close()
    bytes.toByteArray
  }

  private def serializedForestBytes(model: LocalEeSmileRfModel): Array[Byte] = {
    val bytes = new ByteArrayOutputStream()
    val output = new ObjectOutputStream(bytes)
    output.writeObject(model.forest)
    output.close()
    bytes.toByteArray
  }

  def main(args: Array[String]): Unit = {
    if (args.length == 3 && args(0) == "--parallel-preinitialized") {
      System.setProperty("smile.threads", "2")
      assert(smile.util.MulticoreExecutor.getThreadPoolSize() == 2)
      var guarded = false
      try LocalEeSmileRfFactory.train(args(1), args(2))
      catch {
        case error: IllegalArgumentException if Option(error.getMessage).exists(_.contains("single-thread executor")) =>
          guarded = true
      }
      assert(guarded, "a cached multi-thread executor must be refused before training")
      println("SMILE_RF_PARALLEL_GUARD_OK initialized-threads=2 training-refused=true")
      return
    }
    require(args.length == 1, "expected one trusted fixture path")
    val mapper = new ObjectMapper()
    val fixture = mapper.readTree(new File(args(0)))
    val primarySpec = text(fixture, "primary_spec")
    val primaryRows = text(fixture, "primary_rows")
    val secondSeedSpec = text(fixture, "second_seed_spec")
    val repeatQueries = fixture.get("repeat_queries").elements().asScala.map { row =>
      Array(row.get(0).doubleValue(), row.get(1).doubleValue())
    }.toVector

    val (model, predictions) = sameSeedPredictions(primarySpec, primaryRows, repeatQueries)
    val otherSeed = LocalEeSmileRfFactory.train(secondSeedSpec, primaryRows)
    val otherPredictions = repeatQueries.map(LocalEeSmileRfNumeric.predictValue(_, otherSeed))
    val differentSeedChangedPrediction = predictions != otherPredictions ||
      !serializedForestBytes(model).sameElements(serializedForestBytes(otherSeed))
    assert(model.variablesPerSplit == 1 && model.minLeafPopulation == 2 &&
      model.bagFraction == 0.65 && model.maxNodes == 4 && model.seed == 41 &&
      model.actualTreeCount == 17, "all six Smile model parameters must reach the native trainer")
    assert(differentSeedChangedPrediction, "different seeds must change the trained randomized forest")
    val defaultModel = LocalEeSmileRfFactory.train(text(fixture, "default_spec"), primaryRows)
    assert(defaultModel.variablesPerSplit == 1 &&
      defaultModel.maxNodes == fixture.get("primary_row_count").intValue(),
      "null mtry/max_nodes must resolve to sqrt(dimensions) and the actual training-row count")

    // Internal-only Java serialization verifies the actual forest can travel in a
    // trusted Spark closure. No caller-provided serialized bytes are accepted.
    val roundTrip = new ObjectInputStream(new ByteArrayInputStream(serializedBytes(model)))
      .readObject().asInstanceOf[LocalEeSmileRfModel]
    assert(repeatQueries.map(LocalEeSmileRfNumeric.predictValue(_, roundTrip)) == predictions,
      "trusted model serialization must preserve forest predictions")

    val precisionSpec = text(fixture, "precision_spec")
    val precisionRows = text(fixture, "precision_rows")
    val preciseModel = LocalEeSmileRfFactory.train(precisionSpec, precisionRows)
    assert(preciseModel.variablesPerSplit == 1 && preciseModel.minLeafPopulation == 1 &&
      preciseModel.bagFraction == 1.0 && preciseModel.maxNodes == 2 && preciseModel.seed == 7 &&
      preciseModel.actualTreeCount == 9, "explicit precision-model parameters must reach Smile")
    val exactDouble = LocalEeSmileRfNumeric.predictValue(Array(16777217.0), preciseModel)
    val roundedFloat = LocalEeSmileRfNumeric.predictValue(Array(16777217.0.toFloat.toDouble), preciseModel)
    assert(exactDouble == 1 && roundedFloat == 0,
      s"Float64 classifier must distinguish 16777217 from its Float32 rounding: $exactDouble/$roundedFloat")
    val preciseInput = DoubleArrayTile(Array(16777217.0, Double.NaN), 2, 1,
      DoubleConstantNoDataCellType)
    val classified = LocalEeSmileRfNumeric.classifyTile(ArrayMultibandTile(Array[Tile](preciseInput)),
      1, 2, 1, preciseModel)
    assert(classified.cellType == IntConstantNoDataCellType, "classified output must be constant-NoData Int32")
    assert(classified.get(0, 0) == 1, "tile kernel must preserve Float64 precision above 2^24")
    assert(classified.get(1, 0) == Int.MinValue, "NaN NoData must remain masked")
    val floatInput = FloatArrayTile(Array(16777217.0.toFloat), 1, 1, FloatConstantNoDataCellType)
    val floatOutput = LocalEeSmileRfNumeric.classifyTile(ArrayMultibandTile(Array[Tile](floatInput)),
      1, 1, 1, preciseModel)
    assert(floatOutput.get(0, 0) == 0, "Float32 tiles must retain their actual rounded cell value")
    val floatNoData = FloatArrayTile(Array(Float.NaN), 1, 1, FloatConstantNoDataCellType)
    val floatMasked = LocalEeSmileRfNumeric.classifyTile(ArrayMultibandTile(Array[Tile](floatNoData)),
      1, 1, 1, preciseModel)
    assert(floatMasked.get(0, 0) == Int.MinValue, "Float32 NaN must remain NoData")
    val intNoData = IntArrayTile(Array(1, Int.MinValue), 2, 1, IntConstantNoDataCellType)
    val intMasked = LocalEeSmileRfNumeric.classifyTile(ArrayMultibandTile(Array[Tile](intNoData)),
      1, 2, 1, preciseModel)
    assert(intMasked.get(1, 0) == Int.MinValue, "Int32 NoData sentinel must remain masked")
    val multiBandMask = LocalEeSmileRfNumeric.classifyTile(ArrayMultibandTile(Array[Tile](
      DoubleArrayTile(Array(0.0), 1, 1, DoubleConstantNoDataCellType),
      DoubleArrayTile(Array(Double.NaN), 1, 1, DoubleConstantNoDataCellType))), 2, 1, 1, model)
    assert(multiBandMask.get(0, 0) == Int.MinValue,
      "NoData in any one of multiple selected bands must mask the classified cell")
    requireRejected("valid positive infinity") {
      LocalEeSmileRfNumeric.classifyTile(ArrayMultibandTile(Array[Tile](
        DoubleArrayTile(Array(Double.PositiveInfinity), 1, 1, DoubleConstantNoDataCellType))), 1, 1, 1,
        preciseModel)
    }
    requireRejected("valid negative infinity") {
      LocalEeSmileRfNumeric.classifyTile(ArrayMultibandTile(Array[Tile](
        DoubleArrayTile(Array(Double.NegativeInfinity), 1, 1, DoubleConstantNoDataCellType))), 1, 1, 1,
        preciseModel)
    }
    requireRejected("direct prediction NaN") {
      LocalEeSmileRfNumeric.predictValue(Array(Double.NaN), preciseModel)
    }

    val invalidSpecs = fixture.get("invalid_specs").elements().asScala.toVector
    invalidSpecs.foreach { invalid =>
      requireRejected("invalid spec") {
        LocalEeSmileRfFactory.train(invalid.textValue(), precisionRows)
      }
    }
    val invalidRows = fixture.get("invalid_rows").elements().asScala.toVector
    invalidRows.foreach { invalid =>
      requireRejected("invalid rows") {
        LocalEeSmileRfFactory.train(invalid.get("spec").textValue(), invalid.get("rows").textValue())
      }
    }

    val unicodeCases = fixture.get("unicode_cases").elements().asScala.toVector
    unicodeCases.foreach { unicodeCase =>
      val unicodeSpec = text(unicodeCase, "spec")
      val unicodeRows = text(unicodeCase, "rows")
      val unicodeModel = LocalEeSmileRfFactory.train(unicodeSpec, unicodeRows)
      val schemaName = text(unicodeCase, "schema_name")
      val classProperty = text(unicodeCase, "class_property")
      val codePoints = unicodeCase.get("code_points").intValue()
      assert(schemaName.codePointCount(0, schemaName.length) == codePoints &&
        classProperty.codePointCount(0, classProperty.length) == codePoints,
        "Unicode fixture names must use the declared supplementary-character count")
      assert(unicodeModel.schema == Vector(schemaName),
        "256 supplementary code points are legal schema and class-property names")
      assert(LocalEeSmileRfNumeric.predictValue(Array(0.0), unicodeModel) == 0 &&
        LocalEeSmileRfNumeric.predictValue(Array(1.0), unicodeModel) == 1,
        "supplementary-name spec must parse, train and predict correctly")
    }

    val exactRows = parseRows(text(fixture, "canonical_numeric_rows"),
      LocalEeSmileRfWire.parseSpec(precisionSpec))
    val canonicalValues = exactRows.x.flatten.toVector
    val expectedBits = fixture.get("canonical_numeric_bits").elements().asScala
      .map(node => java.lang.Long.parseUnsignedLong(node.textValue(), 16)).toVector
    assert(canonicalValues.map(java.lang.Double.doubleToRawLongBits) == expectedBits,
      "Python canonical Float64 spellings must decode to identical binary64 values")
    val halfMaxRows = parseRows(text(fixture, "half_max_rows"), LocalEeSmileRfWire.parseSpec(precisionSpec))
    val halfMaxBits = fixture.get("half_max_bits").elements().asScala
      .map(node => java.lang.Long.parseUnsignedLong(node.textValue(), 16)).toVector
    assert(halfMaxRows.x.flatten.toVector.map(java.lang.Double.doubleToRawLongBits) == halfMaxBits,
      "finite training values at +/-Double.MaxValue/2 must pass exact parsing")

    val scaleSpec = text(fixture, "scale_spec")
    val scaleRows = text(fixture, "scale_rows")
    val trainingStarted = System.nanoTime()
    val scaleModel = LocalEeSmileRfFactory.train(scaleSpec, scaleRows)
    val trainingMillis = (System.nanoTime() - trainingStarted) / 1000000L
    assert(scaleModel.schema.length == 8 && scaleModel.actualTreeCount == 100 &&
      scaleModel.variablesPerSplit == 2 && scaleModel.minLeafPopulation == 1 &&
      scaleModel.bagFraction == 0.5 && scaleModel.maxNodes == 1000 && scaleModel.seed == 42,
      "1000-row, 8-feature model must use the requested Smile parameters")
    assert(LocalEeSmileRfNumeric.predictValue(Array.fill(8)(0.0), scaleModel) == 0)
    assert(LocalEeSmileRfNumeric.predictValue(Array.fill(8)(1.0), scaleModel) == 1)
    val scaleCols = 256
    val scaleTileRows = 256
    val tilePixelCount = Math.multiplyExact(scaleCols, scaleTileRows)
    val scaleBands = (0 until 8).map { _ =>
      val values = new Array[Double](tilePixelCount)
      var index = 0
      while (index < tilePixelCount) {
        values(index) = if (index % 2 == 0) 0.0 else 1.0
        index += 1
      }
      DoubleArrayTile(values, scaleCols, scaleTileRows, DoubleConstantNoDataCellType): Tile
    }.toArray
    val predictionWork = Math.multiplyExact(tilePixelCount.toLong, scaleModel.maxDepthSum)
    assert(predictionWork <= 1000000000L,
      "256x256 pixels over one key must fit the actual tree-depth prediction bound")
    val predictionStarted = System.nanoTime()
    val scaleOutput = LocalEeSmileRfNumeric.classifyTile(ArrayMultibandTile(scaleBands), 8,
      scaleCols, scaleTileRows, scaleModel)
    val predictionMillis = (System.nanoTime() - predictionStarted) / 1000000L
    assert(scaleOutput.get(0, 0) == 0 && scaleOutput.get(1, 0) == 1 &&
      scaleOutput.get(scaleCols - 1, scaleTileRows - 1) == 1,
      "256x256 Float64 reflectance tile must classify low and high values")

    val providers = java.util.ServiceLoader.load(classOf[CubeProcessProvider]).stream().iterator().asScala
    assert(providers.exists(_.`type`().getName == "local.ee.smile.LocalEeSmileRfCubeProcessProvider"),
      "Smile adapter provider must be discoverable from the generated SPI JAR")
    assert(LoggerFactory.getLogger("local.ee.smile.probe") != null,
      "the locked Spark SLF4J API must load with Smile dependencies")

    println(s"SMILE_RF_KERNEL_OK same-seed=${predictions.size} different-seed-changed=$differentSeedChangedPrediction " +
      s"trees=${model.actualTreeCount} depth-sum=${model.maxDepthSum} invalid-specs=${invalidSpecs.size} " +
      s"invalid-rows=${invalidRows.size} canonical-floats=${canonicalValues.size} Float64-precision=verified NoData=verified")
    println(s"SMILE_RF_UNICODE_OK cases=${unicodeCases.size} codepoints=129,256 schema+class_property=train-predict")
    println(s"SMILE_RF_SCALE_OK rows=${fixture.get("scale_row_count").intValue()} features=8 " +
      s"trees=${scaleModel.actualTreeCount} mtry=${scaleModel.variablesPerSplit} " +
      s"bag=${scaleModel.bagFraction} maxNodes=${scaleModel.maxNodes} seed=${scaleModel.seed} " +
      s"depthSum=${scaleModel.maxDepthSum} predictionWork=$predictionWork " +
      s"trainingMs=$trainingMillis predictionMs=$predictionMillis low=0 high=1")
  }
}
