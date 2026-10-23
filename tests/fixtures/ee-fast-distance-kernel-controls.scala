package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType}

import scala.jdk.CollectionConverters._

/** Negative and boundary controls shared by the trusted fast-distance probe. */
private[reduce] object EeFastDistanceKernelControls {
  final case class GuardEvidence(
    tileRejects: Int, fragmentRejects: Int, duplicateCenterRejects: Int,
    oversizedFragmentRejects: Int
  )
  final case class BudgetEvidence(acceptedKeys: Long, acceptedWork: Long, rejects: Int)

  def verifyWire(invalid: JsonNode): Int = {
    val rejects = invalid.elements().asScala.count(node => rejected {
      LocalEeFastDistanceSpec.parse(node.asText())
    })
    assert(rejects == invalid.size(), "all malformed/noncanonical wire fixtures must fail closed")
    rejects
  }

  def verifyTileAndFragmentGuards(): GuardEvidence = {
    val spec = LocalEeFastDistanceSpec.parse(wire("squared_euclidean", 1))
    val plan = LocalEeFastDistanceBudget.plan(1L, 2, 2, spec)
    val key = LocalEeFastDistanceHalo.Key(0, 0, 0L, temporal = false)
    val bounds = LocalEeFastDistanceHalo.SpatialBounds(0, 0, 0, 0)
    val wrongSize = DoubleArrayTile(Array(1.0d), 1, 1, DoubleConstantNoDataCellType)
    val infinite = DoubleArrayTile(Array(Double.PositiveInfinity, 0.0d, 0.0d, 0.0d),
      2, 2, DoubleConstantNoDataCellType)
    val tileAttempts = Seq[() => Any](
      () => LocalEeFastDistanceHalo.targetsFromTile(null, 2, 2),
      () => LocalEeFastDistanceHalo.targetsFromTile(wrongSize, 2, 2),
      () => LocalEeFastDistanceHalo.targetsFromTile(infinite, 2, 2),
      () => LocalEeFastDistanceHalo.emitFragments(key, new Array[Boolean](0), Set(key),
        2, 2, bounds, spec, plan).toVector
    )
    val tileRejects = tileAttempts.count(attempt => rejected(attempt()))
    assert(tileRejects == tileAttempts.length)

    val invalidFragments = Seq(
      LocalEeFastDistanceHalo.Fragment(-1, 0, 1, 1, Array(true)),
      LocalEeFastDistanceHalo.Fragment(plan.windowCols, 0, 1, 1, Array(true)),
      LocalEeFastDistanceHalo.Fragment(0, 0, 0, 1, new Array[Boolean](0)),
      LocalEeFastDistanceHalo.Fragment(0, 0, 2, 2, Array(true)),
      LocalEeFastDistanceHalo.Fragment(0, 0, 1, 1, null)
    )
    val fragmentRejects = invalidFragments.count(fragment => rejected {
      LocalEeFastDistanceHalo.assemble(Seq(LocalEeFastDistanceHalo.Center, fragment),
        2, 2, spec, plan)
    })
    assert(fragmentRejects == invalidFragments.length)

    // Valid fragment shapes can still exceed the count or aggregate-cell plan.
    val tooManyFragments = rejected {
      LocalEeFastDistanceHalo.assemble(Seq(LocalEeFastDistanceHalo.Center,
        LocalEeFastDistanceHalo.Fragment(0, 0, 1, 1, Array(true)),
        LocalEeFastDistanceHalo.Fragment(1, 0, 1, 1, Array(true))), 2, 2, spec, plan)
    }
    val groupPlan = LocalEeFastDistanceBudget.plan(2L, 2, 2, spec)
    val oversizedCells = rejected {
      LocalEeFastDistanceHalo.assemble(Seq(LocalEeFastDistanceHalo.Center,
        LocalEeFastDistanceHalo.Fragment(0, 0, 4, 3, new Array[Boolean](12)),
        LocalEeFastDistanceHalo.Fragment(0, 1, 4, 3, new Array[Boolean](12))),
        2, 2, spec, groupPlan)
    }
    assert(tooManyFragments && oversizedCells,
      "oversized fragment groups must fail before allocating the window target mask")
    assert(LocalEeFastDistanceHalo.assemble(Seq.empty, 2, 2, spec, plan).isEmpty,
      "markerless fragment groups must be discarded")
    val duplicateCenterRejects = if (rejected {
      LocalEeFastDistanceHalo.assemble(Seq(LocalEeFastDistanceHalo.Center,
        LocalEeFastDistanceHalo.Center), 2, 2, spec, plan)
    }) 1 else 0
    assert(duplicateCenterRejects == 1, "duplicate center markers must fail closed")
    GuardEvidence(tileRejects, fragmentRejects, duplicateCenterRejects,
      (if (tooManyFragments) 1 else 0) + (if (oversizedCells) 1 else 0))
  }

  def verifyBudgetBoundaries(): BudgetEvidence = {
    val wide = LocalEeFastDistanceSpec.parse(wire("squared_euclidean", 256))
    val representative = LocalEeFastDistanceBudget.plan(9L, 256, 256, wide)
    val acceptedKeys = LocalEeFastDistanceBudget.MaxAggregateWork / (representative.perTileWork + 1L)
    val accepted = LocalEeFastDistanceBudget.plan(acceptedKeys, 256, 256, wide)
    assert(accepted.totalWork <= LocalEeFastDistanceBudget.MaxAggregateWork)
    assert(accepted.totalWork == acceptedKeys * (representative.perTileWork + 1L))

    val unit = LocalEeFastDistanceSpec.parse(wire("manhattan", 1))
    val rejectedBoundaries = Seq[() => Any](
      () => LocalEeFastDistanceBudget.plan(acceptedKeys + 1L, 256, 256, wide),
      () => LocalEeFastDistanceBudget.plan(LocalEeFastDistanceBudget.MaxSourceKeys + 1L, 1, 1, unit),
      () => LocalEeFastDistanceBudget.plan(1L, 1200, 1200, unit),
      () => LocalEeFastDistanceBudget.plan(1L, 1, 1,
        LocalEeFastDistanceSpec.parse(wire("chebyshev", 2048)))
    )
    val rejects = rejectedBoundaries.count(attempt => rejected(attempt()))
    assert(rejects == rejectedBoundaries.length)
    BudgetEvidence(acceptedKeys, accepted.totalWork, rejects)
  }

  def verifyPolicyBoundaries(): Int = {
    val minimum = LocalEeFastDistanceSpec.parse(wire("squared_euclidean", 1))
    val default = LocalEeFastDistanceSpec.parse(wire("squared_euclidean", 256))
    val maximum = LocalEeFastDistanceSpec.parse(wire("squared_euclidean", 4096))
    val manhattan = LocalEeFastDistanceSpec.parse(wire("manhattan", 4096))
    assert(minimum.cap == 1 && default.cap == 256 * 256)
    assert(maximum.cap == 4096 * 4096 && maximum.cap <= Int.MaxValue)
    assert(manhattan.cap == 4096)
    maximum.cap
  }

  private def wire(metric: String, neighborhood: Int): String =
    s"{\"metric\":\"$metric\",\"neighborhood\":$neighborhood,\"v\":1}"

  private def rejected(body: => Any): Boolean = {
    try {
      body
      false
    } catch {
      case _: IllegalArgumentException => true
      case _: ArithmeticException => true
    }
  }
}
