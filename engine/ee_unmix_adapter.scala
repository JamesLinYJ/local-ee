package local.ee.reduce

import geotrellis.raster.{DoubleConstantNoDataCellType, MultibandTile}
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Bounded native GeoTrellis SPI for actual per-pixel spectral unmixing. */
final class LocalEeSpectralUnmixCubeProcesses extends Serializable {
  @OpenEOProcess(
    id = "local_ee_unmix",
    description = "Unmix each actual pixel against a bounded fixed endmember matrix.",
    returns = "datacube"
  )
  def localEeUnmix(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_unmix requires only a spec argument")
    val wire = arguments.get("spec") match {
      case value: String => value
      case _ => throw new IllegalArgumentException("spectral unmix spec must be a JSON string")
    }
    val spec = LocalEeSpectralUnmixSpec.parse(wire)
    val input = LocalEeReduceSupport.validate(data, "local_ee_unmix")
    val expected = (0 until spec.inputBands).map(index => s"band$index")
    require(input.names == expected,
      s"local_ee_unmix requires ordered input bands ${expected.mkString(",")}")

    // All input/output copies, support faces and SVD operators are charged before
    // allocating either the immutable solver plan or tile/output arrays.
    val keyCount = input.source.keys.take((LocalEeSpectralUnmixBudget.MaxTileKeys + 1L).toInt).length.toLong
    val admission = LocalEeSpectralUnmixBudget.check(spec, input.cols, input.rows, keyCount)
    val solver = LocalEeSpectralUnmixSolver.build(spec)

    // Capture only bounded immutable metadata/spec/solver values in the Spark closure.
    val kind = input.kind
    val times = input.times.toSet
    val grid = input.grid
    val minimum = input.minSpatial
    val maximum = input.maxSpatial
    val cols = input.cols
    val rows = input.rows
    val output: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeReduceSupport.keyInGrid(key, kind, times, grid, minimum, maximum),
        "local_ee_unmix key lies outside declared grid bounds")
      LocalEeSpectralUnmixBudget.recheckTile(tile, spec, cols, rows, admission)
      key -> LocalEeSpectralUnmixNumeric.applyTile(tile, spec, solver)
    }
    val outputNames = (0 until spec.components).map(index => s"unmix$index")
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeReduceSupport.cubeMetadata(input.cube, outputNames))
  }
}

/** ServiceLoader entry point for the independent bounded unmix process. */
final class LocalEeSpectralUnmixCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeSpectralUnmixCubeProcesses()
}
