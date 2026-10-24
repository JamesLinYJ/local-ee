package local.ee.reduce

import geotrellis.raster.MultibandTile

/** Precharged fixed-face SVD, bounded-precision scoring, decoded-cell, and key limits. */
private[reduce] object LocalEeSpectralUnmixBudget {
  val MaxTileWork = 100000000L
  val MaxTotalWork = 1000000000L
  val MaxTileKeys = 100000L
  val MaxTileDecodedCells = 10000000L
  val MaxDecodedCells = 100000000L

  final case class Admission(
    tilePixels: Long, keyCount: Long, precomputeWork: Long, perPixelWork: Long,
    inputDecodedCells: Long, outputDecodedCells: Long
  ) extends Serializable {
    val tileWork: Long = Math.addExact(precomputeWork, Math.multiplyExact(tilePixels, perPixelWork))
    val totalWork: Long = Math.addExact(precomputeWork,
      Math.multiplyExact(Math.multiplyExact(tilePixels, perPixelWork), keyCount))
  }

  def check(
    spec: LocalEeSpectralUnmixSpec.Value, cols: Int, rows: Int, keyCount: Long
  ): Admission = {
    require(cols > 0 && rows > 0, "spectral unmix tile dimensions must be positive")
    require(keyCount > 0L && keyCount <= MaxTileKeys,
      s"local_ee_unmix supports 1 to $MaxTileKeys tile keys")
    val pixels = Math.multiplyExact(cols.toLong, rows.toLong)
    val inputCells = Math.multiplyExact(pixels, spec.inputBands.toLong)
    val outputCells = Math.multiplyExact(pixels, spec.components.toLong)
    require(inputCells <= MaxTileDecodedCells && outputCells <= MaxTileDecodedCells,
      s"local_ee_unmix tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    require(keyCount <= MaxDecodedCells / inputCells && keyCount <= MaxDecodedCells / outputCells,
      s"local_ee_unmix exceeds the $MaxDecodedCells aggregate decoded-cell limit")
    val (sumComponents, sumSquares, sumCubes) = supportMoments(spec)
    val faces = supportCount(spec)
    val components = spec.components.toLong
    val bands = spec.inputBands.toLong
    val projectedCoordinates = if (spec.sumToOne) Math.subtractExact(sumComponents, faces) else sumComponents
    val coordinateProducts = Math.multiplyExact(bands, projectedCoordinates)
    val residualProducts = Math.multiplyExact(bands, sumComponents)
    val basisProducts = if (spec.sumToOne) Math.multiplyExact(sumSquares - sumComponents, 1L) else 0L
    val candidateOperations = Math.addExact(Math.addExact(
      Math.addExact(Math.multiplyExact(2L, coordinateProducts), Math.multiplyExact(2L, residualProducts)),
      Math.addExact(Math.multiplyExact(2L, basisProducts), sumComponents)),
      Math.addExact(Math.multiplyExact(4L, residualProducts), Math.multiplyExact(2L, sumSquares)))
    val bandComponent = Math.multiplyExact(bands, components)
    val bandComponentSquare = Math.multiplyExact(bandComponent, components)
    // Two independent KKT checks include residual/gradient construction, the
    // coefficient-error perturbation bound and output-rounding propagation.
    val kktOperations = Math.multiplyExact(2L,
      Math.addExact(Math.addExact(Math.multiplyExact(5L, bandComponentSquare),
        Math.addExact(Math.multiplyExact(15L, bandComponent), Math.multiplyExact(2L, bands))),
        Math.addExact(Math.multiplyExact(4L, components), 16L)))
    // Pixel arithmetic caps every binary64-derived BigDecimal at 80 significant digits.
    // IEEE binary64 conversion has <=1,074 decimal places and products/squares <=2,148;
    // precision context keeps multiplication operands to nine base-1e9 limbs. A 4,096
    // charge per counted arithmetic operation covers bounded scale alignment and copies.
    val pixelWork = Math.addExact(Math.multiplyExact(4096L,
      Math.addExact(candidateOperations, kktOperations)),
      Math.addExact(Math.multiplyExact(96L, bandComponent),
        Math.multiplyExact(64L, spec.inputBands.toLong + spec.components.toLong)))
    val faceFreeDimensions = if (spec.sumToOne) sumComponents - faces else sumComponents
    val svdSquare = Math.multiplyExact(bands, faceFreeDimensions)
    val freeSquares = if (spec.sumToOne) sumSquares - 2L * sumComponents + faces else sumSquares
    val svdCross = Math.multiplyExact(bands, freeSquares)
    val svdCubic = if (spec.sumToOne) Math.max(0L,
      sumCubes - 3L * sumSquares + 3L * sumComponents - faces) else sumCubes
    val rankSpan = LocalEeSpectralUnmixRank.operatorExponentSpan(spec.matrix, spec.sumToOne)
    val rankBits = Math.multiplyExact(Math.multiplyExact(bands, components), rankSpan)
    val rankWords = Math.addExact(rankBits, 31L) / 32L
    val rankWordProducts = Math.multiplyExact(rankWords, rankWords)
    val rankWork = Math.multiplyExact(64L, Math.multiplyExact(faces,
      Math.multiplyExact(bands, Math.multiplyExact(components,
        Math.multiplyExact(components, rankWordProducts)))))
    val precompute = Math.addExact(4096L, Math.addExact(rankWork,
      Math.multiplyExact(256L, Math.addExact(svdSquare,
        Math.addExact(svdCross, Math.addExact(svdCubic, sumSquares))))))
    val admission = Admission(pixels, keyCount, precompute, pixelWork, inputCells, outputCells)
    require(admission.tileWork <= MaxTileWork,
      s"local_ee_unmix exceeds the $MaxTileWork per-tile work budget")
    require(admission.totalWork <= MaxTotalWork,
      s"local_ee_unmix exceeds the $MaxTotalWork aggregate work budget")
    admission
  }

  /** Recheck actual tile limits and source finiteness before any tile copy or output allocation. */
  def recheckTile(
    tile: MultibandTile, spec: LocalEeSpectralUnmixSpec.Value,
    cols: Int, rows: Int, admission: Admission
  ): Unit = {
    require(admission.tilePixels == Math.multiplyExact(cols.toLong, rows.toLong) &&
      admission.inputDecodedCells == Math.multiplyExact(admission.tilePixels, spec.inputBands.toLong) &&
      admission.outputDecodedCells == Math.multiplyExact(admission.tilePixels, spec.components.toLong),
      "local_ee_unmix admission dimensions changed before tile evaluation")
    LocalEeSpectralUnmixNumeric.validateTileShape(tile, spec, cols, rows)
    var band = 0
    while (band < spec.inputBands) {
      var pixel = 0
      while (pixel < admission.tilePixels.toInt) {
        val value = tile.band(band).getDouble(pixel % cols, pixel / cols)
        require(value.isNaN || value.isFinite,
          "spectral unmix input contains an infinite Float64 cell")
        pixel += 1
      }
      band += 1
    }
  }

  private def supportCount(spec: LocalEeSpectralUnmixSpec.Value): Long =
    if (spec.nonNegative) (1L << spec.components) - (if (spec.sumToOne) 1L else 0L) else 1L

  private def supportMoments(spec: LocalEeSpectralUnmixSpec.Value): (Long, Long, Long) = {
    if (!spec.nonNegative) {
      val size = spec.components.toLong
      (size, Math.multiplyExact(size, size), Math.multiplyExact(Math.multiplyExact(size, size), size))
    } else {
      val size = spec.components.toLong
      val subsets = 1L << spec.components
      val firstMoment = Math.multiplyExact(size, subsets / 2L)
      val fallingTwo = if (size <= 1L) 0L else
        Math.multiplyExact(Math.multiplyExact(size, size - 1L), subsets / 4L)
      val fallingThree = if (size <= 2L) 0L else Math.multiplyExact(
        Math.multiplyExact(Math.multiplyExact(size, size - 1L), size - 2L), subsets / 8L)
      val secondMoment = Math.addExact(firstMoment, fallingTwo)
      val thirdMoment = Math.addExact(firstMoment,
        Math.addExact(Math.multiplyExact(3L, fallingTwo), fallingThree))
      (firstMoment, secondMoment, thirdMoment)
    }
  }
}
