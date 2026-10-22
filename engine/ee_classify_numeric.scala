package local.ee.classify

import geotrellis.raster.{DoubleConstantNoDataCellType, IntArrayTile, IntConstantNoDataCellType, MultibandTile, Tile}

/** Reduced exact fractions used by the native classifier; denominators stay positive. */
final class LocalEeRational private (val numerator: BigInt, val denominator: BigInt) extends Serializable {
  def +(other: LocalEeRational): LocalEeRational =
    LocalEeRational(numerator * other.denominator + other.numerator * denominator,
      denominator * other.denominator)
  def -(other: LocalEeRational): LocalEeRational =
    LocalEeRational(numerator * other.denominator - other.numerator * denominator,
      denominator * other.denominator)
  def *(other: LocalEeRational): LocalEeRational =
    LocalEeRational(numerator * other.numerator, denominator * other.denominator)
  def square: LocalEeRational = LocalEeRational(numerator * numerator, denominator * denominator)
  def abs: LocalEeRational = if (numerator.signum < 0) LocalEeRational(-numerator, denominator) else this
  def signum: Int = numerator.signum
  def compare(other: LocalEeRational): Int =
    (numerator * other.denominator).compare(other.numerator * denominator)

  override def equals(value: Any): Boolean = value match {
    case other: LocalEeRational => numerator == other.numerator && denominator == other.denominator
    case _ => false
  }
  override def hashCode(): Int = 31 * numerator.hashCode() + denominator.hashCode()
  override def toString: String = s"$numerator/$denominator"
}

object LocalEeRational {
  val Zero: LocalEeRational = new LocalEeRational(BigInt(0), BigInt(1))
  val One: LocalEeRational = new LocalEeRational(BigInt(1), BigInt(1))

  def apply(numerator: BigInt, denominator: BigInt): LocalEeRational = {
    require(denominator != 0, "rational denominator must be nonzero")
    if (numerator == 0) Zero
    else {
      val sign = if (denominator.signum < 0) -1 else 1
      val divisor = numerator.abs.gcd(denominator.abs)
      new LocalEeRational(numerator / divisor * sign, denominator.abs / divisor)
    }
  }

  /** Decode a finite Double from its IEEE-754 bits, including subnormals and signed zero. */
  def fromDouble(value: Double): LocalEeRational = {
    require(value.isFinite, "input pixels must be finite or NoData")
    val bits = java.lang.Double.doubleToRawLongBits(value)
    val negative = bits < 0L
    val exponentBits = ((bits >>> 52) & 0x7ffL).toInt
    val fraction = bits & 0x000fffffffffffffL
    if (exponentBits == 0 && fraction == 0L) return Zero
    val significand = if (exponentBits == 0) BigInt(fraction) else BigInt((1L << 52) | fraction)
    val signed = if (negative) -significand else significand
    val exponent = if (exponentBits == 0) -1074 else exponentBits - 1023 - 52
    if (exponent >= 0) apply(signed << exponent, BigInt(1))
    else apply(signed, BigInt(1) << -exponent)
  }
}

/** Exact ranking and per-tile implementation for local_ee_minimum_distance. */
object LocalEeClassifyNumeric {
  private val NoDataInt = Int.MinValue

  def predictExact(query: Seq[LocalEeRational], model: LocalEeClassifyModel): Int = {
    require(query.length == model.schema.length, "minimum-distance query dimension does not match model schema")
    if (model.metric == "cosine") {
      val queryNorm = query.iterator.map(_.square).foldLeft(LocalEeRational.Zero)(_ + _)
      require(queryNorm.signum != 0, "Cosine minimum-distance prediction rejects a zero-norm query")
    }

    var bestIndex = -1
    var bestScore: LocalEeRational = null
    var tied = false
    var classIndex = 0
    while (classIndex < model.labels.length) {
      val center = model.centers(classIndex)
      val dot = dotProduct(query, center)
      val score = model.metric match {
        case "euclidean" => dot * LocalEeRational(BigInt(2), BigInt(1)) - model.centerNorms(classIndex)
        case "manhattan" =>
          query.indices.iterator.map(index => (query(index) - center(index)).abs)
            .foldLeft(LocalEeRational.Zero)(_ + _)
        case "cosine" => dot
      }
      if (bestIndex < 0) {
        bestIndex = classIndex
        bestScore = score
      } else {
        val order = if (model.metric == "cosine")
          compareCosine(score, model.centerNorms(classIndex), bestScore, model.centerNorms(bestIndex))
        else if (model.metric == "manhattan") -score.compare(bestScore)
        else score.compare(bestScore)
        if (order > 0) {
          bestIndex = classIndex
          bestScore = score
          tied = false
        } else if (order == 0) tied = true
      }
      classIndex += 1
    }
    require(!tied, "Minimum-distance prediction is unsupported for equal-distance class centers")
    model.labels(bestIndex)
  }

  /** NoData in any selected band masks the result; valid infinities are rejected. */
  def classifyTile(tile: MultibandTile, bands: Int, cols: Int, rows: Int,
                   model: LocalEeClassifyModel): Tile = {
    require(tile.bandCount == bands && bands == model.schema.length && tile.cols == cols && tile.rows == rows,
      "tile band count or dimensions changed within the input cube")
    val source = Array.tabulate(bands)(band => tile.band(band).convert(DoubleConstantNoDataCellType))
    val values = new Array[Double](bands)
    val output = Array.fill(Math.multiplyExact(cols, rows))(NoDataInt)
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        var hasNoData = false
        var band = 0
        while (band < bands) {
          val value = source(band).getDouble(col, row)
          require(value.isNaN || value.isFinite, "input pixels must be finite or NoData")
          if (value.isNaN) hasNoData = true
          values(band) = value
          band += 1
        }
        if (!hasNoData) {
          val query = values.iterator.map(LocalEeRational.fromDouble).toVector
          output(row * cols + col) = predictExact(query, model)
        }
        col += 1
      }
      row += 1
    }
    IntArrayTile(output, cols, rows, IntConstantNoDataCellType)
  }

  private def dotProduct(left: Seq[LocalEeRational], right: Seq[LocalEeRational]): LocalEeRational =
    left.indices.iterator.map(index => left(index) * right(index)).foldLeft(LocalEeRational.Zero)(_ + _)

  /** Compare signed dot/sqrt(center norm) scores without sqrt or floating point. */
  private def compareCosine(leftDot: LocalEeRational, leftNorm: LocalEeRational,
                            rightDot: LocalEeRational, rightNorm: LocalEeRational): Int = {
    val leftSign = leftDot.signum
    val rightSign = rightDot.signum
    if (leftSign != rightSign) leftSign.compare(rightSign)
    else if (leftSign == 0) 0
    else {
      val leftCross = leftDot.square * rightNorm
      val rightCross = rightDot.square * leftNorm
      val order = leftCross.compare(rightCross)
      if (leftSign > 0) order else -order
    }
  }
}
