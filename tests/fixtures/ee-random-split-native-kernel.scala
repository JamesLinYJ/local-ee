package ee_random_split_native

import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.layer.SpatialKey
import geotrellis.proj4.CRS
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import java.io.File
import local.ee.image.sample.{LocalEeImageSampleKernel, LocalEeImageSampleOptions}
import local.ee.sample.LocalEeSampleKernel

import scala.jdk.CollectionConverters._

/** Runs the actual GeoTrellis Image.sample tile kernel over the fixed raw raster fixture. */
final class SampleProbe {
  private val mapper = new ObjectMapper()

  private def number(value: Any): Double = value match {
    case raw: Number => raw.doubleValue()
    case _ => throw new IllegalArgumentException("raw fixture pixels must be numbers")
  }

  private def integer(value: Any): Int = value match {
    case raw: Number => raw.intValue()
    case _ => throw new IllegalArgumentException("raw fixture grid values must be integers")
  }

  def sample(fixturePath: String): String = {
    val fixture = mapper.readValue(new File(fixturePath), classOf[java.util.Map[String, Object]])
    require(integer(fixture.get("fixture_version")) == 1, "unsupported native random-split fixture")
    val metadata = fixture.get("grid").asInstanceOf[java.util.Map[String, Object]]
    val columns = integer(metadata.get("columns"))
    val rows = integer(metadata.get("rows"))
    val tileCols = integer(metadata.get("tile_cols"))
    val tileRows = integer(metadata.get("tile_rows"))
    val grid = LocalEeSampleKernel.Grid(
      number(metadata.get("xmin")), number(metadata.get("ymin")),
      number(metadata.get("xmax")), number(metadata.get("ymax")),
      columns.toLong, rows.toLong, tileCols, tileRows)

    val rawBands = fixture.get("bands").asInstanceOf[java.util.List[java.util.Map[String, Object]]]
    val bandNames = rawBands.asScala.map(_.get("name").asInstanceOf[String]).toVector
    require(bandNames == fixture.get("band_order").asInstanceOf[java.util.List[String]].asScala.toVector,
      "raw fixture band metadata must retain declared order")
    val tiles: Array[Tile] = rawBands.asScala.map { band =>
      val values = band.get("values").asInstanceOf[java.util.List[Any]].asScala.map(number).toArray
      require(values.length == tileCols * tileRows, "raw fixture band does not match tile shape")
      DoubleArrayTile(values, tileCols, tileRows, DoubleConstantNoDataCellType): Tile
    }.toArray
    val tile: MultibandTile = ArrayMultibandTile(tiles)

    val region = fixture.get("region_wkt").asInstanceOf[String]
    val geometry = LocalEeSampleKernel.parseAndProjectWkts(
      java.util.Arrays.asList(region), CRS.fromEpsgCode(integer(metadata.get("epsg")))).head
    val feature = LocalEeSampleKernel.prepareFeatures(Seq(geometry), grid).head
    val options = LocalEeImageSampleOptions.parse(mapper.writeValueAsString(fixture.get("options")))
    val maxKey = SpatialKey(columns / tileCols - 1, rows / tileRows - 1)
    val keys = LocalEeImageSampleKernel.candidateKeys(feature, grid, SpatialKey(0, 0), maxKey)
    val population = keys.iterator
      .flatMap(key => LocalEeImageSampleKernel.cellsInTile(key, grid, feature)).length.toLong
    val sampled = keys.iterator.flatMap { key =>
      LocalEeImageSampleKernel.sampleTileIterator(
        Some(tile), key, grid, feature, options, bandNames.length, population, (x, y) => (x, y))
    }.toVector
    LocalEeImageSampleKernel.rowsJson(sampled)
  }
}
