package local.ee.smile

import com.fasterxml.jackson.databind.{JsonNode, ObjectMapper}
import java.io.File
import scala.jdk.CollectionConverters._

/** Real Smile row prediction and retained-training resubstitution component probe. */
object EeSmileRfValidationKernelProbe {
  private val Mapper = new ObjectMapper()

  private def text(node: JsonNode, key: String): String = {
    require(node.has(key) && node.get(key).isTextual, s"fixture field $key must be text")
    node.get(key).textValue()
  }

  private def rejected(label: String)(operation: => Any): Unit = {
    var rejected = false
    try operation
    catch {
      case _: IllegalArgumentException => rejected = true
    }
    assert(rejected, s"$label must be rejected by the JVM query boundary")
  }

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one validation fixture path")
    val fixture = Mapper.readTree(new File(args(0)))
    val model = LocalEeSmileRfFactory.train(text(fixture, "spec"), text(fixture, "training_rows"))
    assert(model.classCount == 2 && model.trainingRows.length == 32 && model.trainingLabels.length == 32,
      "trusted model must retain the exact bounded training rows and labels")

    val predictions = LocalEeSmileRfFactory.predictRows(model, text(fixture, "query_rows"))
    assert(predictions == "{\"predictions\":[0,1],\"version\":1}",
      s"actual Float64 feature predictions must match the trained forest: $predictions")
    assert(LocalEeSmileRfFactory.predictRows(model, text(fixture, "empty_query_rows")) ==
      "{\"predictions\":[],\"version\":1}", "zero feature rows must preserve an empty result")

    val expected = Array.ofDim[Long](model.classCount, model.classCount)
    var index = 0
    while (index < model.trainingRows.length) {
      val predicted = model.forest.predict(model.trainingRows(index).toArray)
      expected(model.trainingLabels(index))(predicted) =
        expected(model.trainingLabels(index))(predicted) + 1L
      index += 1
    }
    val matrix = LocalEeSmileRfFactory.confusionMatrix(model)
    val expectedJson = expected.iterator.map(_.mkString("[", ",", "]")).mkString("[", ",", "]")
    assert(matrix == s"{\"matrix\":$expectedJson,\"order\":[0,1],\"version\":1}",
      s"resubstitution matrix must re-predict every retained training row: $matrix")
    assert(expected.map(_.sum).sum == 32L,
      "independent frequency reference must count every original training row once")

    fixture.get("invalid_queries").elements().asScala.foreach { item =>
      rejected("invalid query envelope") {
        LocalEeSmileRfFactory.predictRows(model, item.textValue())
      }
    }
    println("SMILE_RF_VALIDATION_OK trusted-feature-predictions=2 Float64=preserved empty=accepted " +
      "resubstitution-rows=32 matrix=independent-frequency-reference invalid-query-cases=" +
      fixture.get("invalid_queries").size())
  }
}
