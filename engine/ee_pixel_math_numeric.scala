package local.ee.math

import org.apache.commons.math3.special.{Erf, Gamma}
import geotrellis.raster.{FloatArrayTile, FloatConstantNoDataCellType, MultibandTile, Tile}

/** Actual Float32 input/output kernel for the closed local EE pixel-math contract. */
object LocalEePixelMathNumeric {
  private val OperationArities: Map[String, Int] = Map(
    "asin" -> 1,
    "acos" -> 1,
    "atan" -> 1,
    "atan2" -> 2,
    "sinh" -> 1,
    "cosh" -> 1,
    "tanh" -> 1,
    "cbrt" -> 1,
    "signum" -> 1,
    "gamma" -> 1,
    "digamma" -> 1,
    "trigamma" -> 1,
    "erf" -> 1,
    "erfc" -> 1,
    "erfInv" -> 1,
    "erfcInv" -> 1
  )

  def arity(operation: String): Int = {
    require(operation != null, "pixel math operation must be a string")
    OperationArities.getOrElse(operation,
      throw new IllegalArgumentException(s"unsupported pixel math operation: $operation"))
  }

  /** Apply one operation to ordered x or x,y Float32 bands; invalid outputs become NoData. */
  def applyTile(input: MultibandTile, operation: String): Tile = {
    val requiredBands = arity(operation)
    require(input != null && input.bandCount == requiredBands,
      s"pixel math $operation requires exactly $requiredBands input band(s)")
    require(input.cols > 0 && input.rows > 0, "pixel math input dimensions must be positive")
    val sources = Array.tabulate(requiredBands) { index =>
      val band = input.band(index)
      require(band.cellType == FloatConstantNoDataCellType,
        "pixel math input bands must use Float32 with NaN NoData")
      band
    }
    val cellCount = Math.multiplyExact(input.cols, input.rows)
    val output = new Array[Float](cellCount)
    var row = 0
    while (row < input.rows) {
      var col = 0
      while (col < input.cols) {
        val index = row * input.cols + col
        val x = sources(0).getDouble(col, row).toFloat
        if (!java.lang.Float.isFinite(x)) {
          output(index) = Float.NaN
        } else if (requiredBands == 2) {
          val y = sources(1).getDouble(col, row).toFloat
          if (!java.lang.Float.isFinite(y)) output(index) = Float.NaN
          else output(index) = floatResult(applyValue(x, y, operation))
        } else {
          output(index) = floatResult(applyValue(x, 0.0f, operation))
        }
        col += 1
      }
      row += 1
    }
    FloatArrayTile(output, input.cols, input.rows, FloatConstantNoDataCellType)
  }

  private def floatResult(value: Double): Float = {
    if (!java.lang.Double.isFinite(value)) Float.NaN
    else {
      val rounded = value.toFloat
      if (java.lang.Float.isFinite(rounded)) rounded else Float.NaN
    }
  }

  private def isNonPositiveInteger(value: Double): Boolean =
    value <= 0.0 && value == java.lang.Math.rint(value)

  /** Avoid Gamma.gamma's linear recurrence for negative poles and keep its loop bounded. */
  private def boundedGamma(value: Double): Double = {
    if (isNonPositiveInteger(value)) Double.NaN
    else Gamma.gamma(value)
  }

  /** Reduce with x-floor(x), retaining tiny signed fractions near zero. */
  private def reducedFraction(value: Double): Double = {
    val fractional = if (value > -0.5 && value < 0.5) value
      else value - java.lang.Math.floor(value)
    if (fractional > 0.5) fractional - 1.0
    else if (fractional < -0.5) fractional + 1.0
    else fractional
  }

  /** Reflection keeps negative arguments away from Commons Math's recursive recurrence. */
  private def boundedDigamma(value: Double): Double = {
    if (isNonPositiveInteger(value)) Double.NaN
    else if (value > 0.0) Gamma.digamma(value)
    else {
      val angle = java.lang.Math.PI * reducedFraction(value)
      Gamma.digamma(1.0 - value) - java.lang.Math.PI *
        java.lang.Math.cos(angle) / java.lang.Math.sin(angle)
    }
  }

  /** Trigamma reflection has the same bounded positive-side evaluation. */
  private def boundedTrigamma(value: Double): Double = {
    if (isNonPositiveInteger(value)) Double.NaN
    else if (value > 0.0) Gamma.trigamma(value)
    else {
      val sine = java.lang.Math.sin(java.lang.Math.PI * reducedFraction(value))
      java.lang.Math.PI * java.lang.Math.PI / (sine * sine) - Gamma.trigamma(1.0 - value)
    }
  }

  private def applyValue(x: Float, y: Float, operation: String): Double = operation match {
    case "asin" => java.lang.Math.asin(x.toDouble)
    case "acos" => java.lang.Math.acos(x.toDouble)
    case "atan" => java.lang.Math.atan(x.toDouble)
    // Earth Engine's operation receives (x, y); Java's atan2 takes (y, x).
    case "atan2" => java.lang.Math.atan2(y.toDouble, x.toDouble)
    case "sinh" => java.lang.Math.sinh(x.toDouble)
    case "cosh" => java.lang.Math.cosh(x.toDouble)
    case "tanh" => java.lang.Math.tanh(x.toDouble)
    case "cbrt" => java.lang.Math.cbrt(x.toDouble)
    case "signum" => java.lang.Math.signum(x.toDouble)
    case "gamma" => boundedGamma(x.toDouble)
    case "digamma" => boundedDigamma(x.toDouble)
    case "trigamma" => boundedTrigamma(x.toDouble)
    case "erf" => Erf.erf(x.toDouble)
    case "erfc" => Erf.erfc(x.toDouble)
    case "erfInv" => Erf.erfInv(x.toDouble)
    case "erfcInv" => Erf.erfcInv(x.toDouble)
  }
}
