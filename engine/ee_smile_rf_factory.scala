package local.ee.smile

import smile.classification.RandomForest
import smile.math.Math
import smile.util.MulticoreExecutor

/** Opaque serializable handle; its only constructor is private to this factory. */
@SerialVersionUID(1L)
final class LocalEeSmileRfModel private (
  val schema: Vector[String],
  private[smile] val forest: RandomForest,
  val classCount: Int,
  val actualTreeCount: Int,
  val maxDepthSum: Long,
  private[smile] val trainingRows: Vector[Vector[Double]],
  private[smile] val trainingLabels: Vector[Int],
  val variablesPerSplit: Int,
  val minLeafPopulation: Int,
  val bagFraction: Double,
  val maxNodes: Int,
  val seed: Int
) extends Serializable

object LocalEeSmileRfModel {
  private[smile] def fromForest(schema: Vector[String], forest: RandomForest,
                                classes: Int, treeCount: Int, depthSum: Long,
                                trainingRows: Vector[Vector[Double]], trainingLabels: Vector[Int],
                                variablesPerSplit: Int, minLeafPopulation: Int,
                                bagFraction: Double, maxNodes: Int, seed: Int): LocalEeSmileRfModel =
    new LocalEeSmileRfModel(schema, forest, classes, treeCount, depthSum,
      trainingRows, trainingLabels, variablesPerSplit, minLeafPopulation, bagFraction, maxNodes, seed)
}

/** Sole production factory for opaque Smile model instances. */
object LocalEeSmileRfFactory {
  /** Public JVM/Py4J boundary: only bounded canonical text enters the trainer. */
  def train(spec: String, rows: String): LocalEeSmileRfModel = synchronized {
    val checkedSpec = LocalEeSmileRfWire.parseSpec(spec)
    val checkedRows = LocalEeSmileRfWire.parseRows(rows, checkedSpec)
    val effectiveLeaves = checkedSpec.effectiveMaxNodes(checkedRows.y.length)

    // MulticoreExecutor caches its first setting. Refuse if another caller already
    // initialized it with a parallel pool; changing the property cannot repair it.
    System.setProperty("smile.threads", "1")
    require(MulticoreExecutor.getThreadPoolSize() == 1,
      "Smile RandomForest training requires a fresh single-thread executor")
    Math.setSeed(checkedSpec.seed.toLong)

    val trainer = new RandomForest.Trainer(checkedSpec.mtry, checkedSpec.trees)
      .setNodeSize(checkedSpec.minLeaf)
      .setSamplingRates(checkedSpec.bagFraction)
      .setMaxNodes(effectiveLeaves)
    val forest = trainer.train(checkedRows.x, checkedRows.y)
    val trees = forest.getTrees
    require(trees != null && trees.length == checkedSpec.trees,
      "Smile RandomForest returned an unexpected tree count")
    val depths = trees.map(_.maxDepth())
    require(depths.forall(depth => depth >= 1 && depth <= effectiveLeaves),
      "Smile RandomForest returned a tree outside the bounded leaf domain")
    val depthSum = depths.iterator.map(_.toLong).foldLeft(0L)(java.lang.Math.addExact)
    require(depthSum > 0L, "Smile RandomForest has no bounded decision-tree nodes")
    // Keep a detached immutable resubstitution sample inside the trusted model.
    // The mutable parser arrays are not retained by the JVM handle.
    val retainedRows = checkedRows.x.iterator.map(row => row.clone().toVector).toVector
    val retainedLabels = checkedRows.y.toVector
    LocalEeSmileRfModel.fromForest(checkedSpec.schema, forest, checkedRows.y.distinct.length,
      trees.length, depthSum, retainedRows, retainedLabels, checkedSpec.mtry,
      checkedSpec.minLeaf, checkedSpec.bagFraction, effectiveLeaves, checkedSpec.seed)
  }

  /** Predict only bounded canonical query rows through the retained real forest. */
  def predictRows(model: LocalEeSmileRfModel, rowsText: String): String = {
    require(model != null && model.forest != null && model.actualTreeCount > 0 && model.maxDepthSum > 0L,
      "Random forest predictions require a trusted trained model")
    val rows = LocalEeSmileRfWire.parseQueryRows(rowsText, model.schema.length).rows
    val work = java.lang.Math.multiplyExact(rows.length.toLong, model.maxDepthSum)
    require(work <= 1000000000L,
      "Random forest row prediction exceeds the 1000000000 node-visit budget")
    val labels = rows.map(values => LocalEeSmileRfNumeric.predictValue(values, model))
    labels.mkString("{\"predictions\":[", ",", "],\"version\":1}")
  }

  /** Predict each retained training row and return the resubstitution counts. */
  def confusionMatrix(model: LocalEeSmileRfModel): String = {
    require(model != null && model.forest != null && model.actualTreeCount > 0 && model.maxDepthSum > 0L,
      "Random forest confusionMatrix requires a trusted trained model")
    require(model.trainingRows != null && model.trainingLabels != null &&
      model.trainingRows.length == model.trainingLabels.length &&
      model.trainingRows.length >= 2 && model.trainingRows.length <= 1000,
      "Random forest model has invalid retained training rows")
    val work = java.lang.Math.multiplyExact(model.trainingRows.length.toLong, model.maxDepthSum)
    require(work <= 1000000000L,
      "Random forest resubstitution exceeds the 1000000000 node-visit budget")
    require(model.classCount >= 2 && model.classCount <= 64,
      "Random forest model has an invalid class count")
    val counts = Array.ofDim[Long](model.classCount, model.classCount)
    var index = 0
    while (index < model.trainingRows.length) {
      val actual = model.trainingLabels(index)
      require(actual >= 0 && actual < model.classCount &&
        model.trainingRows(index).length == model.schema.length,
        "Random forest model has an invalid retained training row")
      val predicted = LocalEeSmileRfNumeric.predictValue(model.trainingRows(index).toArray, model)
      counts(actual)(predicted) = java.lang.Math.addExact(counts(actual)(predicted), 1L)
      index += 1
    }
    val matrix = counts.iterator.map(_.mkString("[", ",", "]")).mkString("[", ",", "]")
    val order = (0 until model.classCount).mkString("[", ",", "]")
    s"{\"matrix\":$matrix,\"order\":$order,\"version\":1}"
  }

  /** Return only bounded raw values from the actual pinned Smile forest. */
  def explain(model: LocalEeSmileRfModel): String = {
    require(model != null && model.forest != null && model.schema != null &&
      model.schema.nonEmpty && model.schema.length <= 8 && model.actualTreeCount >= 1,
      "Random forest explanation requires a trusted trained model")
    val trees = model.forest.getTrees
    require(trees != null && trees.length == model.actualTreeCount &&
      model.forest.size() == model.actualTreeCount,
      "Random forest explanation tree count differs from the trained model")
    val importance = model.forest.importance()
    require(importance != null && importance.length == model.schema.length &&
      importance.forall(value => value.isFinite && value >= 0.0),
      "Random forest explanation importance differs from the model schema")
    val error = model.forest.error()
    require(error.isFinite && error >= 0.0 && error <= 1.0,
      "Random forest OOB error estimate is outside [0,1]")
    val importanceJson = importance.iterator.map(value => java.lang.Double.toString(value)).mkString("[", ",", "]")
    val errorJson = java.lang.Double.toString(error)
    s"{\"importance\":$importanceJson,\"number_of_trees\":${model.forest.size()}," +
      s"\"out_of_bag_error\":$errorJson,\"version\":1}"
  }
}
