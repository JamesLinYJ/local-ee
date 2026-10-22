import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, FloatArrayTile, FloatConstantNoDataCellType, IntConstantNoDataCellType, Tile}
import java.io.File
import local.ee.classify.{LocalEeClassifyModel, LocalEeClassifyNumeric, LocalEeRational}
import org.openeo.geotrelliscommon.CubeProcessProvider
import scala.jdk.CollectionConverters._

/** Trusted standalone kernel probe: no SparkContext, services or user scripts. */
object ClassifierKernelProbe {
  def main(args: Array[String]): Unit = {
    val mapper = new ObjectMapper()
    val fixture = mapper.readValue(new File(args(0)), classOf[java.util.Map[String, Object]])
    val providers = java.util.ServiceLoader.load(classOf[CubeProcessProvider]).stream().iterator().asScala
    val provider = providers.find(_.`type`().getName == "local.ee.classify.LocalEeClassifyCubeProcessProvider")
    assert(provider.isDefined, "classifier ServiceLoader provider missing from artifact")
    assert(provider.get.get().getInstance().isInstanceOf[local.ee.classify.LocalEeClassifyCubeProcesses])
    val predictions = fixture.get("predictions").asInstanceOf[java.util.List[java.util.Map[String, Object]]]
    predictions.asScala.zipWithIndex.foreach { case (row, index) =>
      var rejected = false
      try {
        val model = LocalEeClassifyModel.fromJavaMap(row.get("model").asInstanceOf[java.util.Map[_, _]])
        val values = row.get("query").asInstanceOf[java.util.List[String]].asScala
        val bands = values.map { value =>
          val number = if (value == null) Double.NaN else java.lang.Double.parseDouble(value)
          if (row.get("input_type") == "float32")
            FloatArrayTile(Array(number.toFloat), 1, 1, FloatConstantNoDataCellType).asInstanceOf[Tile]
          else DoubleArrayTile(Array(number), 1, 1, DoubleConstantNoDataCellType).asInstanceOf[Tile]
        }.toArray
        val output = LocalEeClassifyNumeric.classifyTile(ArrayMultibandTile(bands), bands.length, 1, 1, model)
        assert(output.cellType == IntConstantNoDataCellType, s"case $index output type")
        val expected = Option(row.get("expected")).map(_.asInstanceOf[Number].intValue()).getOrElse(Int.MinValue)
        assert(output.get(0, 0) == expected, s"case $index unexpected class or mask")
      } catch {
        case _: IllegalArgumentException => rejected = true
      }
      assert(rejected == java.lang.Boolean.TRUE.equals(row.get("reject")), s"case $index rejection mismatch")
    }
    val invalid = fixture.get("invalid_models").asInstanceOf[java.util.List[java.util.Map[_, _]]]
    invalid.asScala.zipWithIndex.foreach { case (model, index) =>
      var rejected = false
      try { LocalEeClassifyModel.fromJavaMap(model) }
      catch { case _: IllegalArgumentException => rejected = true }
      assert(rejected, s"invalid model $index was accepted")
    }
    val binary64 = fixture.get("binary64").asInstanceOf[java.util.List[java.util.Map[String, String]]]
    binary64.asScala.foreach { row =>
      val actual = LocalEeRational.fromDouble(java.lang.Double.parseDouble(row.get("input")))
      val expected = LocalEeRational(BigInt(row.get("numerator")), BigInt(row.get("denominator")))
      assert(actual == expected, "binary64 decoding differs from independent Fraction reference")
    }
    println(s"CLASSIFIER_KERNEL_OK predictions=${predictions.size()} invalid-models=${invalid.size()} binary64=${binary64.size()}")
  }
}
