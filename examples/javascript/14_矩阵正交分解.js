// 使用声明的合成波段编译逐像元紧凑 QR 和 SVD；不访问 Earth Engine 服务。
var collectionId = 'sentinel-2-l2a';
var tallBands = ['a00', 'a01', 'a10', 'a11', 'a20', 'a21'];
var wideBands = ['a00', 'a10', 'a20', 'a01', 'a11', 'a21'];
var truncationBands = ['a00', 'a01', 'b0', 'a10', 'a11', 'b1', 'a20', 'a21', 'b2'];
var rhsBands = ['b0', 'b1', 'b2'];
var sourceBands = tallBands.concat(rhsBands.filter(function (name) {
  return tallBands.indexOf(name) < 0;
}));
var properties = [
  'workflow', 'system:index', 'system:time_start', 'proj:code', 'proj:transform'
];
var syntheticVersion = 'local-ee-synthetic-matrix-orthogonal/v1';

function matrixFromBands(ee, image, bands, shape, precision) {
  var values = image.select(bands);
  if (precision === 'double') {
    values = values.toDouble();
  } else if (precision === 'float32') {
    values = values.toFloat();
  } else if (precision === 'float32_then_double') {
    values = values.toFloat().toDouble();
  } else {
    throw Error('Unsupported matrix precision: ' + precision);
  }
  return values.toArray().arrayReshape(
    ee.Image.constant(ee.Array(shape)), 2);
}

function rhsFromBands(ee, image) {
  return image.select(rhsBands).toDouble().toArray().arrayReshape(
    ee.Image.constant(ee.Array([3, 1])), 2);
}

function flatten(ee, source, array, rows, columns) {
  return ee.Image(array.arrayFlatten([rows, columns])
    .copyProperties(source, properties));
}

function buildMatrixOrthogonalWorkflow(ee, image) {
  var source = ee.Image(image).select(sourceBands)
    .set('workflow', syntheticVersion);
  var tall = matrixFromBands(ee, source, tallBands, [3, 2], 'double');
  var wide = matrixFromBands(ee, source, wideBands, [2, 3], 'double');
  var rhs = rhsFromBands(ee, source);

  var qrTall = tall.matrixQRDecomposition();
  var qTall = qrTall.select('Q');
  var rTall = qrTall.select('R');
  var qtb = qTall.matrixTranspose().matrixMultiply(rhs).toDouble();
  var coefficients = rTall.matrixSolve(qtb);
  var fit = tall.matrixMultiply(coefficients);
  var projection = qTall.matrixMultiply(qtb);

  var svdTall = tall.matrixSingularValueDecomposition();
  var uTall = svdTall.select('U');
  var sTall = svdTall.select('S');
  var vTall = svdTall.select('V');
  var uTall1 = uTall.arraySlice(1, 0, 1);
  var sTall1 = sTall.arraySlice(0, 0, 1).arraySlice(1, 0, 1);
  var vTall1 = vTall.arraySlice(1, 0, 1);
  var uTall2 = uTall.arraySlice(1, 0, 2);
  var sTall2 = sTall.arraySlice(0, 0, 2).arraySlice(1, 0, 2);
  var vTall2 = vTall.arraySlice(1, 0, 2);
  var qrWide = wide.matrixQRDecomposition();
  var qWide = qrWide.select('Q');
  var rWide = qrWide.select('R');
  var svdWide = wide.matrixSingularValueDecomposition();
  var uWide = svdWide.select('U');
  var sWide = svdWide.select('S');
  var vWide = svdWide.select('V');
  var wideRank1 = uWide.arraySlice(1, 0, 1)
    .matrixMultiply(sWide.arraySlice(0, 0, 1).arraySlice(1, 0, 1))
    .matrixMultiply(vWide.arraySlice(1, 0, 1).matrixTranspose());
  var wideRank2 = uWide.arraySlice(1, 0, 2)
    .matrixMultiply(sWide.arraySlice(0, 0, 2).arraySlice(1, 0, 2))
    .matrixMultiply(vWide.arraySlice(1, 0, 2).matrixTranspose());
  var truncationMatrix = matrixFromBands(
    ee, source, truncationBands, [3, 3], 'double');
  var svdTruncation = truncationMatrix.matrixSingularValueDecomposition();
  var uTruncation = svdTruncation.select('U');
  var sTruncation = svdTruncation.select('S');
  var vTruncation = svdTruncation.select('V');
  var square = matrixFromBands(
    ee, source, ['a00', 'a01', 'a10', 'a11'], [2, 2], 'double');
  var svdSquare = square.matrixSingularValueDecomposition();
  var uSquare = svdSquare.select('U');
  var sSquare = svdSquare.select('S');
  var vSquare = svdSquare.select('V');
  var squareRank1 = uSquare.arraySlice(1, 0, 1)
    .matrixMultiply(sSquare.arraySlice(0, 0, 1).arraySlice(1, 0, 1))
    .matrixMultiply(vSquare.arraySlice(1, 0, 1).matrixTranspose());
  var squareRank2 = uSquare.arraySlice(1, 0, 2)
    .matrixMultiply(sSquare.arraySlice(0, 0, 2).arraySlice(1, 0, 2))
    .matrixMultiply(vSquare.arraySlice(1, 0, 2).matrixTranspose());
  var tall32 = matrixFromBands(
    ee, source, tallBands, [3, 2], 'float32_then_double');
  var qrTall32 = tall32.matrixQRDecomposition();
  var svdTall32 = tall32.matrixSingularValueDecomposition();

  return {
    qr_tall_q: flatten(ee, source, qTall, ['r0', 'r1', 'r2'], ['c0', 'c1']),
    qr_tall_r: flatten(ee, source, rTall, ['r0', 'r1'], ['c0', 'c1']),
    qr_tall_reconstruction: flatten(ee, source,
      qTall.matrixMultiply(rTall), ['r0', 'r1', 'r2'], ['c0', 'c1']),
    qr_tall_projection: flatten(ee, source, projection,
      ['r0', 'r1', 'r2'], ['value']),
    qr_tall_least_squares: flatten(ee, source, coefficients,
      ['c0', 'c1'], ['value']),
    qr_tall_fit: flatten(ee, source, fit, ['r0', 'r1', 'r2'], ['value']),
    svd_tall_u: flatten(ee, source, uTall, ['r0', 'r1', 'r2'], ['k0', 'k1']),
    svd_tall_s: flatten(ee, source, sTall, ['k0', 'k1'], ['k0', 'k1']),
    svd_tall_v: flatten(ee, source, vTall, ['c0', 'c1'], ['k0', 'k1']),
    svd_tall_rank1: flatten(ee, source,
      uTall1.matrixMultiply(sTall1).matrixMultiply(vTall1.matrixTranspose()),
      ['r0', 'r1', 'r2'], ['c0', 'c1']),
    svd_tall_reconstruction: flatten(ee, source,
      uTall.matrixMultiply(sTall).matrixMultiply(vTall.matrixTranspose()),
      ['r0', 'r1', 'r2'], ['c0', 'c1']),
    svd_tall_rank2: flatten(ee, source,
      uTall2.matrixMultiply(sTall2).matrixMultiply(vTall2.matrixTranspose()),
      ['r0', 'r1', 'r2'], ['c0', 'c1']),
    svd_square_u: flatten(ee, source, uSquare, ['r0', 'r1'], ['k0', 'k1']),
    svd_square_s: flatten(ee, source, sSquare, ['k0', 'k1'], ['k0', 'k1']),
    svd_square_v: flatten(ee, source, vSquare, ['c0', 'c1'], ['k0', 'k1']),
    svd_square_reconstruction: flatten(ee, source,
      uSquare.matrixMultiply(sSquare).matrixMultiply(vSquare.matrixTranspose()),
      ['r0', 'r1'], ['c0', 'c1']),
    svd_square_rank1: flatten(ee, source, squareRank1, ['r0', 'r1'], ['c0', 'c1']),
    svd_square_rank2: flatten(ee, source, squareRank2, ['r0', 'r1'], ['c0', 'c1']),
    qr_wide_q: flatten(ee, source, qWide, ['r0', 'r1'], ['c0', 'c1']),
    qr_wide_r: flatten(ee, source, rWide, ['r0', 'r1'], ['c0', 'c1', 'c2']),
    qr_wide_reconstruction: flatten(ee, source,
      qWide.matrixMultiply(rWide), ['r0', 'r1'], ['c0', 'c1', 'c2']),
    svd_wide_u: flatten(ee, source, uWide, ['r0', 'r1'], ['k0', 'k1']),
    svd_wide_s: flatten(ee, source, sWide, ['k0', 'k1'], ['k0', 'k1']),
    svd_wide_v: flatten(ee, source, vWide, ['c0', 'c1', 'c2'], ['k0', 'k1']),
    svd_wide_rank1: flatten(ee, source, wideRank1,
      ['r0', 'r1'], ['c0', 'c1', 'c2']),
    svd_wide_reconstruction: flatten(ee, source,
      uWide.matrixMultiply(sWide).matrixMultiply(vWide.matrixTranspose()),
      ['r0', 'r1'], ['c0', 'c1', 'c2']),
    svd_wide_rank2: flatten(ee, source, wideRank2,
      ['r0', 'r1'], ['c0', 'c1', 'c2']),
    svd_truncation_u: flatten(ee, source, uTruncation,
      ['r0', 'r1', 'r2'], ['k0', 'k1', 'k2']),
    svd_truncation_s: flatten(ee, source, sTruncation,
      ['k0', 'k1', 'k2'], ['k0', 'k1', 'k2']),
    svd_truncation_v: flatten(ee, source, vTruncation,
      ['c0', 'c1', 'c2'], ['k0', 'k1', 'k2']),
    qr_float32_then_double_reconstruction: flatten(ee, source,
      qrTall32.select('Q').matrixMultiply(qrTall32.select('R')),
      ['r0', 'r1', 'r2'], ['c0', 'c1']),
    svd_float32_then_double_reconstruction: flatten(ee, source,
      svdTall32.select('U').matrixMultiply(
        svdTall32.select('S').matrixMultiply(
          svdTall32.select('V').matrixTranspose())),
      ['r0', 'r1', 'r2'], ['c0', 'c1'])
  };
}

function buildBudgetLimitedCompositions(ee, image) {
  var source = ee.Image(image).select(sourceBands);
  var tall = matrixFromBands(ee, source, tallBands, [3, 2], 'double');
  var rhs = rhsFromBands(ee, source);
  var qrTall = tall.matrixQRDecomposition();
  var qTall = qrTall.select('Q');
  var rTall = qrTall.select('R');
  var qtb = qTall.matrixTranspose().matrixMultiply(rhs).toDouble();
  var coefficients = rTall.matrixSolve(qtb);
  var fit = tall.matrixMultiply(coefficients);
  var truncationMatrix = matrixFromBands(
    ee, source, truncationBands, [3, 3], 'double');
  var svdTruncation = truncationMatrix.matrixSingularValueDecomposition();
  var uTruncation = svdTruncation.select('U');
  var sTruncation = svdTruncation.select('S');
  var vTruncation = svdTruncation.select('V');
  return {
    qr_tall_normal_residual: flatten(ee, source,
      qTall.matrixTranspose().matrixMultiply(rhs.subtract(fit)),
      ['c0', 'c1'], ['value']),
    svd_truncation_reconstruction: flatten(ee, source,
      uTruncation.matrixMultiply(sTruncation).matrixMultiply(vTruncation.matrixTranspose()),
      ['r0', 'r1', 'r2'], ['c0', 'c1', 'c2']),
    svd_truncation_rank2: flatten(ee, source,
      uTruncation.arraySlice(1, 0, 2)
        .matrixMultiply(sTruncation.arraySlice(0, 0, 2).arraySlice(1, 0, 2))
        .matrixMultiply(vTruncation.arraySlice(1, 0, 2).matrixTranspose()),
      ['r0', 'r1', 'r2'], ['c0', 'c1', 'c2'])
  };
}

var outputs = buildMatrixOrthogonalWorkflow(
  ee, ee.ImageCollection(collectionId).first());
