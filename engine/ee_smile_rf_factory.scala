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
  val variablesPerSplit: Int,
  val minLeafPopulation: Int,
  val bagFraction: Double,
  val maxNodes: Int,
  val seed: Int
) extends Serializable

object LocalEeSmileRfModel {
  private[smile] def fromForest(schema: Vector[String], forest: RandomForest,
                                classes: Int, treeCount: Int, depthSum: Long,
                                variablesPerSplit: Int, minLeafPopulation: Int,
                                bagFraction: Double, maxNodes: Int, seed: Int): LocalEeSmileRfModel =
    new LocalEeSmileRfModel(schema, forest, classes, treeCount, depthSum, variablesPerSplit,
      minLeafPopulation, bagFraction, maxNodes, seed)
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
    LocalEeSmileRfModel.fromForest(checkedSpec.schema, forest, checkedRows.y.distinct.length,
      trees.length, depthSum, checkedSpec.mtry, checkedSpec.minLeaf, checkedSpec.bagFraction,
      effectiveLeaves, checkedSpec.seed)
  }
}
