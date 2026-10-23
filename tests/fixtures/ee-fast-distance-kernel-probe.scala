package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, Tile}

import java.nio.{ByteBuffer, ByteOrder}
import java.security.MessageDigest
import scala.collection.mutable
import scala.jdk.CollectionConverters._

/** Trusted standalone GeoTrellis tile probe; no SparkContext, service, or user script. */
object EeFastDistanceKernelProbe {
  private val mapper = new ObjectMapper()

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected fast-distance fixture JSON path")
    val root = mapper.readTree(new java.io.File(args(0)))
    assert(root.get("schema").asText() == "local-ee-synthetic-fast-distance/v1")

    val kernels = root.get("kernel_cases").elements().asScala.toVector
    var kernelPixels = 0L
    var longLineLast = -1L
    kernels.foreach { testCase =>
      kernelPixels = Math.addExact(kernelPixels, runKernelCase(testCase))
      if (testCase.has("last_value")) longLineLast = testCase.get("last_value").asLong()
    }

    val sourceCases = root.get("source_cases").elements().asScala.toVector
    var observedKeys = 0L
    var evaluatedPixels = 0L
    var gridSlots = 0L
    var emittedFragments = 0L
    var defaultPlanCases = 0
    var twoHopCrosses = 0
    sourceCases.foreach { testCase =>
      val result = runSourceCase(testCase)
      observedKeys = Math.addExact(observedKeys, result.keys.toLong)
      evaluatedPixels = Math.addExact(evaluatedPixels, result.pixels)
      gridSlots = Math.addExact(gridSlots, result.gridSlots)
      emittedFragments = Math.addExact(emittedFragments, result.fragments)
      defaultPlanCases += result.defaultPlanCases
      twoHopCrosses += result.twoHopCrosses
    }

    val wireRejects = EeFastDistanceKernelControls.verifyWire(root.get("invalid_specs"))
    val guards = EeFastDistanceKernelControls.verifyTileAndFragmentGuards()
    val budget = EeFastDistanceKernelControls.verifyBudgetBoundaries()
    val capAtMaxNeighborhood = EeFastDistanceKernelControls.verifyPolicyBoundaries()

    assert(kernels.length == root.get("kernel_case_count").asInt())
    assert(sourceCases.length == root.get("source_case_count").asInt())
    assert(observedKeys == root.get("source_observed_keys").asLong())
    assert(evaluatedPixels == root.get("source_evaluated_pixels").asLong())
    assert(gridSlots == root.get("source_grid_slots").asLong())
    assert(defaultPlanCases == 3, "all three default N=256 metric plans must be exercised")
    assert(twoHopCrosses == 3, "all three metrics must send a real target across two tile hops")
    assert(emittedFragments > 0L)
    assert(longLineLast > Int.MaxValue.toLong)
    println(s"FAST_DISTANCE_KERNEL_OK kernel_cases=${kernels.length} kernel_pixels=$kernelPixels " +
      s"long_line_last=$longLineLast source_cases=${sourceCases.length} " +
      s"source_keys=$observedKeys source_pixels=$evaluatedPixels grid_slots=$gridSlots " +
      s"fragments=$emittedFragments default_plan_cases=$defaultPlanCases two_hop_crosses=$twoHopCrosses " +
      s"wire_rejects=$wireRejects tile_rejects=${guards.tileRejects} " +
      s"fragment_rejects=${guards.fragmentRejects} duplicate_center_rejects=${guards.duplicateCenterRejects} " +
      s"oversized_fragment_rejects=${guards.oversizedFragmentRejects} " +
      s"budget_boundary_keys=${budget.acceptedKeys} " +
      s"budget_boundary_work=${budget.acceptedWork} budget_rejects=${budget.rejects} " +
      s"max_neighborhood_cap=$capAtMaxNeighborhood")
  }

  private def runKernelCase(testCase: JsonNode): Long = {
    val width = testCase.get("width").asInt()
    val height = testCase.get("height").asInt()
    val cells = Math.multiplyExact(width, height)
    val targets = new Array[Boolean](cells)
    val targetNodes = testCase.get("targets").elements().asScala
    targetNodes.foreach { node =>
      val index = node.asInt()
      assert(index >= 0 && index < cells, s"${testCase.get("name").asText()}: bad target index")
      assert(!targets(index), s"${testCase.get("name").asText()}: duplicate target index")
      targets(index) = true
    }
    val metric = testCase.get("metric").asText()
    val actual = LocalEeFastDistanceTransform.apply(targets, width, height, metric)
    assert(actual.length == cells)

    if (testCase.has("expected")) {
      val expected = testCase.get("expected").elements().asScala.toVector
      assert(expected.length == actual.length)
      expected.indices.foreach { index =>
        assert(actual(index) == expected(index).asLong(),
          s"${testCase.get("name").asText()}[$index]: expected ${expected(index)}, got ${actual(index)}")
      }
    } else {
      assert(digestLongs(actual) == testCase.get("digest").asText(),
        s"${testCase.get("name").asText()}: 64-bit transform digest differs")
      assert(actual.last == testCase.get("last_value").asLong(),
        s"${testCase.get("name").asText()}: last squared distance differs")
    }
    if (testCase.get("name").asText().endsWith("-empty"))
      assert(actual.forall(_ == LocalEeFastDistanceTransform.NoTargetDistance))
    cells.toLong
  }

  private final case class Source(key: LocalEeFastDistanceHalo.Key, rawKey: Any, tile: Tile)
  private final case class SourceResult(
    keys: Int, pixels: Long, gridSlots: Long, fragments: Long,
    defaultPlanCases: Int, twoHopCrosses: Int
  )

  private def runSourceCase(testCase: JsonNode): SourceResult = {
    val name = testCase.get("name").asText()
    val cols = testCase.get("tile_cols").asInt()
    val rows = testCase.get("tile_rows").asInt()
    val metric = testCase.get("metric").asText()
    val spec = LocalEeFastDistanceSpec.parse(testCase.get("spec").asText())
    assert(spec.metric == metric && spec.neighborhood == testCase.get("neighborhood").asInt())
    val sources = testCase.get("tiles").elements().asScala.map { tileNode =>
      val rawKey = readRawKey(tileNode.get("key"))
      val kind = if (tileNode.get("key").get(3).asBoolean()) "temporal" else "spatial"
      Source(LocalEeFastDistanceHalo.fromAny(rawKey, kind), rawKey,
        readTile(tileNode, cols, rows))
    }.toVector
    val observed = sources.iterator.map(_.key).toSet
    assert(observed.size == sources.size, s"$name: fixture contains duplicate observed keys")
    assert(sources.iterator.map(_.rawKey).toSet.size == sources.size,
      s"$name: fixture raw keys are not unique")

    val plan = LocalEeFastDistanceBudget.plan(sources.size.toLong, cols, rows, spec)
    val bounds = LocalEeFastDistanceHalo.SpatialBounds(
      testCase.get("min_tile_col").asInt(), testCase.get("min_tile_row").asInt(),
      testCase.get("max_tile_col").asInt(), testCase.get("max_tile_row").asInt())
    val isDefaultPlan = name.startsWith("default-neighborhood-256-")
    if (isDefaultPlan) {
      assert(plan.totalWork == 362741850L, s"$name: default 3x3 budget work changed")
      assert(plan.aggregateDecodedCells == 18305280L,
        s"$name: default 3x3 decoded-cell plan changed")
    }
    if (name.startsWith("two-tile-hop")) assert(plan.hopCols >= 2)

    val groups = mutable.Map.empty[LocalEeFastDistanceHalo.Key,
      mutable.ArrayBuffer[LocalEeFastDistanceHalo.Piece]]
    var emittedFragments = 0L
    var twoHopCrosses = 0
    sources.foreach { source =>
      val targets = LocalEeFastDistanceHalo.targetsFromTile(source.tile, cols, rows)
      val emitted = LocalEeFastDistanceHalo.emitFragments(
        source.key, targets, observed, cols, rows, bounds, spec, plan).toVector
      assert(emitted.nonEmpty && emitted.head == (source.key -> LocalEeFastDistanceHalo.Center),
        s"$name: each observed source must emit exactly its center marker first")
      if (name.startsWith("two-tile-hop") && source.key.temporal &&
          source.key.instant == 1000L && source.key.col == 2 && source.key.row == 1) {
        val destinations = emitted.collect {
          case (key, _: LocalEeFastDistanceHalo.Fragment) => key
        }.toSet
        assert(destinations.contains(LocalEeFastDistanceHalo.Key(0, 1, 1000L, temporal = true)),
          s"$name: target fragment did not cross two tile hops")
        twoHopCrosses = 1
      }
      emitted.foreach { case (key, piece) =>
        val bucket = groups.getOrElseUpdate(key, mutable.ArrayBuffer.empty)
        bucket += piece
        if (piece.isInstanceOf[LocalEeFastDistanceHalo.Fragment])
          emittedFragments = Math.addExact(emittedFragments, 1L)
      }
    }

    val assembled = mutable.Map.empty[LocalEeFastDistanceHalo.Key, Tile]
    groups.foreach { case (key, pieces) =>
      LocalEeFastDistanceHalo.assemble(pieces.toVector, cols, rows, spec, plan)
        .foreach(tile => assembled.put(key, tile))
    }
    assert(assembled.keySet.toSet == observed,
      s"$name: assembled keys differ from the observed source keys")
    assert(assembled.size == observed.size,
      s"$name: output key count differs from the observed source key count")
    assert(assembled.keysIterator.map(LocalEeFastDistanceHalo.toAny).toSet ==
      sources.iterator.map(_.rawKey).toSet,
      s"$name: SpaceTimeKey/SpatialKey identity or time changed")

    val actual = assembled.toVector.sortBy { case (key, _) => sortKey(key) }
    val expectedTiles = testCase.get("expected_tiles").elements().asScala.toVector
    assert(actual.length == expectedTiles.length, s"$name: expected digest count differs")
    actual.zip(expectedTiles).foreach { case ((key, tile), expected) =>
      assert(readKey(expected.get("key")) == key,
        s"$name: expected key ${expected.get("key")}, got $key")
      val (digest, minimum, maximum, capCells) = summarizeTile(tile, cols, rows, spec.cap)
      assert(digest == expected.get("digest").asText(), s"$name $key: output digest differs")
      assert(minimum == expected.get("min").asInt() && maximum == expected.get("max").asInt(),
        s"$name $key: output range differs")
      assert(capCells == expected.get("cap_cells").asInt(),
        s"$name $key: capped-cell count differs")
    }

    testCase.get("probes").elements().asScala.foreach { probe =>
      val key = readKey(probe.get("key"))
      val tile = assembled.getOrElse(key,
        throw new AssertionError(s"$name: probe references absent output key $key"))
      val col = probe.get("col").asInt()
      val row = probe.get("row").asInt()
      assert(tile.get(col, row) == probe.get("value").asInt(),
        s"$name $key[$col,$row]: explicit readback differs")
    }

    val pixels = Math.multiplyExact(assembled.size.toLong, Math.multiplyExact(cols.toLong, rows.toLong))
    assert(pixels == testCase.get("evaluated_pixel_count").asLong())
    val gridSlots = testCase.get("grid_slot_count").asLong()
    assert(sources.size == testCase.get("observed_key_count").asInt())
    SourceResult(sources.size, pixels, gridSlots, emittedFragments,
      if (isDefaultPlan) 1 else 0, twoHopCrosses)
  }

  private def readTile(node: JsonNode, cols: Int, rows: Int): Tile = {
    val cells = Math.multiplyExact(cols, rows)
    val default = decodeDouble(node.get("default").asText())
    val values = Array.fill(cells)(default)
    node.get("overrides").elements().asScala.foreach { pair =>
      val index = pair.get(0).asInt()
      assert(index >= 0 && index < cells)
      values(index) = if (pair.get(1).isNull) Double.NaN else decodeDouble(pair.get(1).asText())
    }
    DoubleArrayTile(values, cols, rows, DoubleConstantNoDataCellType)
  }

  private def decodeDouble(bits: String): Double =
    java.lang.Double.longBitsToDouble(java.lang.Long.parseUnsignedLong(bits, 16))

  private def readRawKey(node: JsonNode): Any = {
    val col = node.get(0).asInt()
    val row = node.get(1).asInt()
    val instant = node.get(2).asLong()
    if (node.get(3).asBoolean()) SpaceTimeKey(col, row, instant) else SpatialKey(col, row)
  }

  private def readKey(node: JsonNode): LocalEeFastDistanceHalo.Key = {
    val raw = readRawKey(node)
    LocalEeFastDistanceHalo.fromAny(raw, if (node.get(3).asBoolean()) "temporal" else "spatial")
  }

  private def sortKey(key: LocalEeFastDistanceHalo.Key): (Boolean, Long, Int, Int) =
    (key.temporal, key.instant, key.row, key.col)

  private def summarizeTile(tile: Tile, cols: Int, rows: Int, cap: Int): (String, Int, Int, Int) = {
    val digest = MessageDigest.getInstance("SHA-256")
    val word = ByteBuffer.allocate(4).order(ByteOrder.BIG_ENDIAN)
    var minimum = Int.MaxValue
    var maximum = Int.MinValue
    var capCells = 0
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        val value = tile.get(col, row)
        assert(value >= 0 && value <= cap, s"native fast distance output escaped cap: $value")
        word.clear()
        word.putInt(value)
        digest.update(word.array())
        minimum = math.min(minimum, value)
        maximum = math.max(maximum, value)
        if (value == cap) capCells += 1
        col += 1
      }
      row += 1
    }
    (hex(digest.digest()), minimum, maximum, capCells)
  }

  private def digestLongs(values: Array[Long]): String = {
    val digest = MessageDigest.getInstance("SHA-256")
    val word = ByteBuffer.allocate(8).order(ByteOrder.BIG_ENDIAN)
    values.foreach { value =>
      word.clear()
      word.putLong(value)
      digest.update(word.array())
    }
    hex(digest.digest())
  }

  private def hex(bytes: Array[Byte]): String =
    bytes.iterator.map(byte => f"${byte & 0xff}%02x").mkString
}
