package local.ee.classify

import scala.jdk.CollectionConverters._

/** Bounded immutable model parsed independently from the compiler's JSON contract. */
final class LocalEeClassifyModel private (
  val metric: String,
  val schema: Vector[String],
  val labels: Vector[Int],
  val centers: Vector[Vector[LocalEeRational]],
  val centerNorms: Vector[LocalEeRational]
) extends Serializable

object LocalEeClassifyModel {
  private val Fields = Set("version", "metric", "schema", "labels", "centers")
  private val MaxStringChars = 700
  private val MaxRationalBits = 2200
  private val MaxDoubleNumerator = ((BigInt(1) << 53) - 1) << 971

  /** Public entry point for the Java Map supplied by the openEO process adapter. */
  def fromJavaMap(value: java.util.Map[_, _]): LocalEeClassifyModel = {
    require(value != null && value.size() == Fields.size && value.keySet().asScala.toSet == Fields,
      "minimum-distance model must contain exactly version, metric, schema, labels and centers")
    require(integer(value.get("version"), "model version") == 1,
      "minimum-distance model version must be integer 1")
    val metric = string(value.get("metric"), "metric")
    require(Set("euclidean", "manhattan", "cosine")(metric), "unsupported minimum-distance metric")

    val schema = list(value.get("schema"), "schema")
    require(schema.size() >= 1 && schema.size() <= 8, "model schema must contain 1 to 8 bands")
    val names = schema.asScala.map(string(_, "schema entry")).toVector
    require(names.forall(name => name.nonEmpty && !name.contains(".")),
      "model schema entries must be nonempty flat band names")
    require(names.distinct.size == names.size, "model schema entries must be unique")

    val labelValues = list(value.get("labels"), "labels")
    require(labelValues.size() >= 1 && labelValues.size() <= 64, "model must contain 1 to 64 labels")
    val labels = labelValues.asScala.map { raw =>
      val parsed = integer(raw, "class label")
      require(parsed >= 0 && parsed <= 63, "class labels must be integers from 0 through 63")
      parsed.toInt
    }.toVector
    require(labels == labels.sorted && labels.distinct.size == labels.size,
      "model labels must be sorted and unique")

    val centerRows = list(value.get("centers"), "centers")
    require(centerRows.size() == labels.size, "model center count must match labels")
    val centers = centerRows.asScala.map { rawRow =>
      val row = list(rawRow, "center row")
      require(row.size() == names.size, "model center dimension must match schema")
      row.asScala.map(parseCenter).toVector
    }.toVector
    val norms = centers.map(_.iterator.map(_.square).foldLeft(LocalEeRational.Zero)(_ + _))
    if (metric == "cosine")
      require(norms.forall(_.signum != 0), "Cosine minimum-distance model rejects a zero-norm class center")
    new LocalEeClassifyModel(metric, names, labels, centers, norms)
  }

  private def parseCenter(value: Any): LocalEeRational = {
    val pair = list(value, "center rational")
    require(pair.size() == 2, "center rational must contain numerator and denominator")
    val numeratorText = fractionString(pair.get(0), "center numerator")
    val denominatorText = fractionString(pair.get(1), "center denominator")
    require(canonicalSignedInteger(numeratorText) && canonicalPositiveInteger(denominatorText),
      "center rational strings must be canonical decimal integers")
    val numerator = BigInt(numeratorText)
    val denominator = BigInt(denominatorText)
    require(numerator.abs.bitLength <= MaxRationalBits && denominator.bitLength <= MaxRationalBits,
      "center rational exceeds the 2200-bit limit")
    require(numerator.abs.gcd(denominator) == 1 && (numerator != 0 || denominator == 1),
      "center rational must be reduced and encode zero as 0/1")
    require(numerator.abs <= MaxDoubleNumerator * denominator,
      "class center must lie within the finite binary64 range")
    LocalEeRational(numerator, denominator)
  }

  private def canonicalSignedInteger(value: String): Boolean = {
    if (value == "0") true
    else {
      val digits = if (value.startsWith("-")) value.substring(1) else value
      digits.nonEmpty && digits.head >= '1' && digits.head <= '9' && digits.forall(ch => ch >= '0' && ch <= '9')
    }
  }

  private def canonicalPositiveInteger(value: String): Boolean =
    value.nonEmpty && value.head >= '1' && value.head <= '9' && value.forall(ch => ch >= '0' && ch <= '9')

  private def string(value: Any, name: String): String = value match {
    case text: String => text
    case _ => throw new IllegalArgumentException(s"$name must be a string")
  }

  private def fractionString(value: Any, name: String): String = {
    val text = string(value, name)
    require(text.length <= MaxStringChars, s"$name string exceeds the 700-character limit")
    text
  }

  private def list(value: Any, name: String): java.util.List[_] = value match {
    case items: java.util.List[_] => items
    case _ => throw new IllegalArgumentException(s"$name must be an array")
  }

  private def integer(value: Any, name: String): BigInt = value match {
    case number: java.lang.Byte => BigInt(number.longValue())
    case number: java.lang.Short => BigInt(number.longValue())
    case number: java.lang.Integer => BigInt(number.longValue())
    case number: java.lang.Long => BigInt(number.longValue())
    case number: java.math.BigInteger =>
      require(number.abs.bitLength <= 6, s"$name integer is outside the bounded model range")
      BigInt(number)
    case _ => throw new IllegalArgumentException(s"$name must be an integer")
  }
}
