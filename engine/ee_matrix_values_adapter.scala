package local.ee.reduce

import geotrellis.raster.{DoubleConstantNoDataCellType, MultibandTile}
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Bounded SPI adapter for actual fixed-shape per-pixel matrix operations. */
final class LocalEeMatrixValuesCubeProcesses extends Serializable {
  @OpenEOProcess(
    id = "local_ee_matrix_values",
    description = "Solve, invert, or factor fixed per-pixel matrices with bounded Float64 output.",
    returns = "datacube"
  )
  def localEeMatrixValues(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_matrix_values requires only a spec argument")
    val wire = arguments.get("spec") match {
      case value: String => value
      case _ => throw new IllegalArgumentException("matrix values spec must be a JSON string")
    }
    val spec = LocalEeMatrixValuesSpec.parse(wire)
    val input = LocalEeReduceSupport.validate(data, "local_ee_matrix_values")
    val expectedBandNames = (0 until spec.inputBands).map(index => s"band$index")
    require(input.names == expectedBandNames,
      s"local_ee_matrix_values requires ordered input bands ${expectedBandNames.mkString(",")}")

    val tilePixels = Math.multiplyExact(input.cols.toLong, input.rows.toLong)
    require(tilePixels > 0L, "local_ee_matrix_values tile dimensions must be positive")
    val keyCount = input.source.keys.take(100001).length.toLong
    val factorBudget = if (spec.op == "lu") {
      Some(LocalEeMatrixFactorizationBudget.admitSource(
        input.source, keyCount, spec, input.cols, input.rows))
    } else {
      LocalEeMatrixValuesBudget.check(tilePixels, keyCount, spec)
      None
    }

    // Capture immutable metadata and the parsed spec only; never capture Input, cube or RDD.
    val kind = input.kind
    val times = input.times.toSet
    val grid = input.grid
    val minSpatial = input.minSpatial
    val maxSpatial = input.maxSpatial
    val cols = input.cols
    val rows = input.rows
    val output: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeReduceSupport.keyInGrid(key, kind, times, grid, minSpatial, maxSpatial),
        "local_ee_matrix_values key lies outside declared grid bounds")
      LocalEeMatrixValuesNumeric.validateTileShape(tile, spec, cols, rows)
      factorBudget.foreach(envelope =>
        LocalEeMatrixFactorizationBudget.requireWithinEnvelope(tile, spec, cols, rows, envelope))
      key -> LocalEeMatrixValuesNumeric.applyTile(tile, spec)
    }
    val outputNames = (0 until spec.outputCells).map(index => s"matrix$index")
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeReduceSupport.cubeMetadata(input.cube, outputNames))
  }
}

/** ServiceLoader entry point for the atomic matrix-values adapter JAR. */
final class LocalEeMatrixValuesCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeMatrixValuesCubeProcesses()
}

private[reduce] object LocalEeMatrixValuesBudget {
  val MaxTileWork = 100000000L
  val MaxTotalWork = 1000000000L
  val MaxTileKeys = 100000L

  def workPerPixel(spec: LocalEeMatrixValuesSpec.Value): Long = {
    val rows = spec.rows.toLong
    val cols = spec.cols.toLong
    if (spec.op == "cholesky") {
      val cells = Math.multiplyExact(rows, cols)
      val cubic = Math.multiplyExact(cells, rows)
      val exactMatrixCopies = Math.multiplyExact(128L, cells)
      val factorArithmetic = Math.multiplyExact(512L, cubic)
      val divisions = Math.multiplyExact(128L, cells)
      val roots = Math.multiplyExact(256L, rows)
      val outputCopies = Math.multiplyExact(32L, spec.outputCells.toLong)
      return Math.addExact(exactMatrixCopies,
        Math.addExact(factorArithmetic,
          Math.addExact(divisions, Math.addExact(roots, outputCopies))))
    }
    val rhsCols = if (spec.op == "solve") spec.rhsCols.toLong else 0L
    val factorization = Math.multiplyExact(32L,
      Math.multiplyExact(Math.multiplyExact(rows, cols), math.min(rows, cols)))
    val rhsWork = Math.multiplyExact(16L,
      Math.multiplyExact(Math.multiplyExact(rows, cols), rhsCols))
    val outputWork = Math.multiplyExact(32L, spec.outputCells.toLong)
    // Exact BigDecimal centering/dots use at most eight terms per output cell;
    // charge constant-column scans, multiply/adds, restores and divisions up front.
    val constantColumnScan = if (spec.op == "solve") Math.multiplyExact(16L,
      Math.multiplyExact(rows, cols)) else 0L
    val bigDecimalProducts = Math.multiplyExact(384L,
      Math.multiplyExact(Math.multiplyExact(rows, cols), rhsCols))
    val bigDecimalDivisions = Math.multiplyExact(128L,
      Math.multiplyExact(cols, rhsCols))
    val anchorRestore = Math.multiplyExact(256L, rhsCols)
    val copies = Math.multiplyExact(4L, spec.inputBands.toLong)
    Math.addExact(Math.addExact(factorization, rhsWork),
      Math.addExact(Math.addExact(outputWork, copies),
        Math.addExact(constantColumnScan,
          Math.addExact(bigDecimalProducts, Math.addExact(bigDecimalDivisions, anchorRestore)))))
  }

  def check(tilePixels: Long, keyCount: Long, spec: LocalEeMatrixValuesSpec.Value): Unit = {
    require(keyCount > 0L && keyCount <= MaxTileKeys,
      s"local_ee_matrix_values supports 1 to $MaxTileKeys tile keys")
    val perPixelWorkEstimate = workPerPixel(spec)
    val perTileWork = Math.multiplyExact(tilePixels, perPixelWorkEstimate)
    require(tilePixels > 0L && perTileWork <= MaxTileWork,
      s"local_ee_matrix_values exceeds the $MaxTileWork per-tile work budget")
    require(keyCount <= MaxTotalWork / perTileWork,
      s"local_ee_matrix_values exceeds the $MaxTotalWork aggregate work budget")
  }
}
