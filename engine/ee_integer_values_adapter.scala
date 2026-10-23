package local.ee.reduce

import geotrellis.raster.{ArrayMultibandTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Bounded SPI adapter for actual per-pixel integer-value and Float64 comparison operations. */
final class LocalEeIntegerValuesCubeProcesses extends Serializable {
  private val MaxWorkPerTile = 100000000L
  private val MaxTotalWork = 1000000000L

  @OpenEOProcess(
    id = "local_ee_integer_values",
    description = "Apply a strict bitwise, cast, Float64 arithmetic, logical, or comparison operation to raster pixels.",
    returns = "datacube"
  )
  def localEeIntegerValues(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_integer_values requires only a spec argument")
    val wire = arguments.get("spec") match {
      case value: String => value
      case _ => throw new IllegalArgumentException("integer values spec must be a JSON string")
    }
    // Parse and reject malformed or noncanonical wire data before inspecting cube contents.
    val spec = LocalEeIntegerValuesSpec.parse(wire)
    val input = LocalEeReduceSupport.validate(data, "local_ee_integer_values")
    require(input.names.size == spec.inputBands,
      s"local_ee_integer_values ${spec.op} requires ${spec.inputBands} input band(s) in metadata order")

    val tilePixels = Math.multiplyExact(input.cols.toLong, input.rows.toLong)
    require(tilePixels > 0L, "local_ee_integer_values tile dimensions must be positive")

    // Shared validation performs bounded key/grid checks and reads one sample tile. This
    // additional capped key action obtains the count needed to precharge the whole lazy pass;
    // both actions occur before the first full pixel traversal is submitted.
    val keyCount = input.source.keys.take(100001).length.toLong
    require(keyCount > 0L && keyCount <= 100000L,
      "local_ee_integer_values supports 1 to 100000 tile keys")

    // Retain the conservative four cell-work units per input value from v1 for
    // source reads, mask checks and Float64 copies, then per-operand dispatch/checks,
    // band reads, operation work,
    // and output writes. Left shift has a fixed-width BigInt bound: inputs are at most
    // 2^53 and shifts at most 63, so magnitude is at most 2^116 (117 bits).
    // LocalEeReduceSupport has already enforced 10M decoded cells per tile and 100M total.
    val copyCellsPerPixel = Math.multiplyExact(input.names.size.toLong, 4L)
    val operandReadsPerPixel = spec.operands.count(_.isInstanceOf[LocalEeIntegerValuesSpec.Band]).toLong
    val operandWorkPerPixel = spec.operands.length.toLong
    val operationWorkPerPixel = LocalEeFloat64Values.workWeight(spec.op).getOrElse(spec.op match {
      case "left_shift" => 4L
      case "cast" => 2L
      case _ => 1L
    })
    val workPerPixel = Math.addExact(
      Math.addExact(Math.addExact(copyCellsPerPixel, operandReadsPerPixel), operandWorkPerPixel),
      Math.addExact(operationWorkPerPixel, 1L))
    val perTileWork = Math.multiplyExact(tilePixels, workPerPixel)
    require(perTileWork <= MaxWorkPerTile,
      s"local_ee_integer_values exceeds the $MaxWorkPerTile per-tile work budget")
    require(keyCount <= MaxTotalWork / perTileWork,
      s"local_ee_integer_values exceeds the $MaxTotalWork aggregate work budget")

    // Capture only immutable scalars/collections and the parsed immutable spec in the Spark
    // closure; never capture the cube, shared Input wrapper, or source RDD.
    val kind = input.kind
    val times = input.times.toSet
    val grid = input.grid
    val minSpatial = input.minSpatial
    val maxSpatial = input.maxSpatial
    val bands = spec.inputBands
    val cols = input.cols
    val rows = input.rows
    val output: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeReduceSupport.keyInGrid(key, kind, times, grid, minSpatial, maxSpatial),
        "local_ee_integer_values key lies outside declared grid bounds")
      require(tile != null && tile.bandCount == bands && tile.cols == cols && tile.rows == rows,
        "local_ee_integer_values tile band count or dimensions changed within the cube")
      key -> ArrayMultibandTile(Array[Tile](LocalEeIntegerValuesNumeric.applyTile(tile, spec)))
    }
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeReduceSupport.cubeMetadata(input.cube, Seq("v")))
  }
}

/** ServiceLoader entry point registered by the engine SPI manifest. */
final class LocalEeIntegerValuesCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeIntegerValuesCubeProcesses()
}
