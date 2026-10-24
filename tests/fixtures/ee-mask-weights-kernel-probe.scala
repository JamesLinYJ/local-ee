package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile,
  DoubleConstantNoDataCellType, MultibandTile, Tile}

import java.io.File
import scala.jdk.CollectionConverters._

/** Direct numeric acceptance over actual GeoTrellis DoubleArrayTile inputs. */
object EeMaskWeightsKernelProbe {
  private val Mapper = new ObjectMapper()

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one mask-weight fixture")
    val root = Mapper.readTree(new File(args(0)))
    require(root.get("schema").asText() == "local-ee-mask-weights-wave64/v1",
      "unexpected fixture schema")
    var pixels = 0
    val cases = root.get("cases").elements().asScala.toVector
    cases.foreach { row =>
      val spec = LocalEeMaskWeightsSpec.parse(row.get("spec").asText())
      val output = LocalEeMaskWeightsNumeric.applyTile(tileFrom(row), spec)
      val expected = row.get("expected").elements().asScala.map(parseValue).toArray
      checkTile(row.get("name").asText(), output, expected)
      pixels += expected.length
    }

    val updateSpec = LocalEeMaskWeightsSpec.parse("{\"op\":\"update\",\"v\":1}")
    val composite = root.get("composite")
    var weights = composite.get("initial_weights").elements().asScala.map(parseValue).toArray
    val updates = composite.get("new_masks").elements().asScala.toVector
    updates.zipWithIndex.foreach { case (maskNode, step) =>
      val mask = maskNode.elements().asScala.map(parseValue).toArray
      val output = LocalEeMaskWeightsNumeric.applyTile(
        twoBands(weights, mask), updateSpec,
      )
      val independent = weights.zip(mask).map { case (oldWeight, newMask) =>
        if (oldWeight == 0.0d) 0.0d else if (newMask.isNaN) 0.0d else newMask
      }
      checkTile(s"replacement update $step", output, independent)
      weights = output.toArrayDouble()
    }
    val expectedWeights = composite.get("expected_weights").elements().asScala.map(parseValue).toArray
    require(sameArray(weights, expectedWeights), "composite replacement weights differ")

    val raw = composite.get("raw_values").elements().asScala.map(parseValue).toArray
    val applySpec = LocalEeMaskWeightsSpec.parse("{\"op\":\"apply\",\"v\":1}")
    val compositeOutput = LocalEeMaskWeightsNumeric.applyTile(
      twoBands(raw, weights), applySpec,
    )
    val expectedValues = composite.get("expected_values").elements().asScala.map(parseValue).toArray
    checkTile("replacement chain raw-value application", compositeOutput, expectedValues)
    pixels += expectedValues.length

    var invalidSpecs = 0
    root.get("invalid_specs").elements().asScala.foreach { node =>
      var rejected = false
      try LocalEeMaskWeightsSpec.parse(node.asText())
      catch { case _: IllegalArgumentException => rejected = true }
      require(rejected, s"native parser accepted invalid spec ${node.asText()}")
      invalidSpecs += 1
    }

    var invalidTiles = 0
    root.get("invalid_tile_cases").elements().asScala.foreach { row =>
      var rejected = false
      try {
        val spec = LocalEeMaskWeightsSpec.parse(row.get("spec").asText())
        LocalEeMaskWeightsNumeric.applyTile(tileFrom(row), spec)
      } catch { case _: IllegalArgumentException => rejected = true }
      require(rejected, s"native kernel accepted invalid tile ${row.get("name").asText()}")
      invalidTiles += 1
    }

    require(root.get("case_count").intValue() == cases.length + 1,
      "case count must include the composite replacement control")
    println(s"MASK_WEIGHTS_KERNEL_OK cases=${cases.length} pixels=$pixels " +
      s"invalid_specs=$invalidSpecs invalid_tiles=$invalidTiles " +
      s"composite_updates=${updates.length}")
  }

  private def tileFrom(row: JsonNode): MultibandTile = {
    val bands = row.get("bands").elements().asScala.map { band =>
      val values = band.elements().asScala.map(parseValue).toArray
      require(values.nonEmpty, "mask-weight fixture bands must not be empty")
      DoubleArrayTile(values, values.length, 1, DoubleConstantNoDataCellType)
    }.toArray
    require(bands.nonEmpty, "mask-weight fixture requires at least one band")
    require(bands.forall(tile => tile.cols == bands(0).cols && tile.rows == bands(0).rows),
      "mask-weight fixture bands must have matching dimensions")
    ArrayMultibandTile(bands)
  }

  private def twoBands(first: Array[Double], second: Array[Double]): MultibandTile = {
    require(first.nonEmpty && first.length == second.length,
      "composite inputs must be equal positive widths")
    ArrayMultibandTile(Array[Tile](
      DoubleArrayTile(first, first.length, 1, DoubleConstantNoDataCellType),
      DoubleArrayTile(second, second.length, 1, DoubleConstantNoDataCellType),
    ))
  }

  private def parseValue(value: JsonNode): Double = {
    if (value.isNumber) value.doubleValue()
    else value.asText() match {
      case "NaN" => Double.NaN
      case "Infinity" => Double.PositiveInfinity
      case "-Infinity" => Double.NegativeInfinity
      case "-0.0" => -0.0d
      case other => throw new IllegalArgumentException(s"unsupported numeric fixture value: $other")
    }
  }

  private def checkTile(label: String, actual: Tile, expected: Array[Double]): Unit = {
    require(actual.cellType == DoubleConstantNoDataCellType,
      s"$label output must preserve physical Float64 NaN NoData")
    require(actual.cols == expected.length && actual.rows == 1,
      s"$label output dimensions changed")
    var index = 0
    while (index < expected.length) {
      val value = actual.getDouble(index, 0)
      require(same(value, expected(index)),
        s"$label pixel $index differs: $value != ${expected(index)}")
      index += 1
    }
  }

  private def sameArray(left: Array[Double], right: Array[Double]): Boolean =
    left.length == right.length && left.zip(right).forall { case (a, b) => same(a, b) }

  private def same(left: Double, right: Double): Boolean =
    left.isNaN && right.isNaN ||
      java.lang.Double.doubleToRawLongBits(left) == java.lang.Double.doubleToRawLongBits(right)
}
