// 使用版本化合成波段编译逐像元 Cholesky 和 LU 分解。
// This compile-only workflow uses a declared synthetic scene and no service data.
var collectionId = 'sentinel-2-l2a';
var matrixBands = ['m00', 'm01', 'm10', 'm11'];
var rhsBands = ['b0', 'b1'];
var sourceBands = matrixBands.concat(rhsBands);
var matrixShape = [2, 2];
var rhsShape = [2, 1];
var properties = [
  'workflow', 'system:index', 'system:time_start', 'proj:code', 'proj:transform'
];
var syntheticVersion = 'local-ee-synthetic-matrix-factors/v1';

function matrixFromBands(ee, image, precision) {
  var values = image.select(matrixBands);
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
    ee.Image.constant(ee.Array(matrixShape)), 2);
}

function rhsFromBands(ee, image) {
  return image.select(rhsBands).toDouble().toArray().arrayReshape(
    ee.Image.constant(ee.Array(rhsShape)), 2);
}

function flatten(ee, array, source, rowLabels, columnLabels) {
  return ee.Image(array.arrayFlatten([rowLabels, columnLabels])
    .copyProperties(source, properties));
}

function buildMatrixFactorWorkflow(ee, image) {
  var source = ee.Image(image).select(sourceBands)
    .set('workflow', syntheticVersion);
  var matrix = matrixFromBands(ee, source, 'double');
  var rhs = rhsFromBands(ee, source);

  var cholesky = matrix.matrixCholeskyDecomposition();
  var lower = cholesky.select('L');
  var lowerT = lower.matrixTranspose();
  var lu = matrix.matrixLUDecomposition();
  var luLower = lu.select('L');
  var upper = lu.select('U');
  var permutation = lu.select('P');
  var float32Upper = matrixFromBands(ee, source, 'float32')
    .matrixLUDecomposition().select('U');

  var luFactors = flatten(ee, luLower, source, ['L0', 'L1'], ['C0', 'C1'])
    .addBands(flatten(ee, upper, source, ['U0', 'U1'], ['C0', 'C1']))
    .addBands(flatten(ee, permutation, source, ['P0', 'P1'], ['C0', 'C1']));

  return {
    cholesky_L: flatten(ee, lower, source, ['L0', 'L1'], ['C0', 'C1']),
    cholesky_reconstruction: flatten(ee,
      lower.matrixMultiply(lowerT), source, ['R0', 'R1'], ['C0', 'C1']),
    cholesky_float32_L: flatten(ee,
      matrixFromBands(ee, source, 'float32')
        .matrixCholeskyDecomposition().select('L'),
      source, ['L0', 'L1'], ['C0', 'C1']),
    cholesky_float32_then_double_L: flatten(ee,
      matrixFromBands(ee, source, 'float32_then_double')
        .matrixCholeskyDecomposition().select('L'),
      source, ['L0', 'L1'], ['C0', 'C1']),
    lu_float32_U: flatten(ee, float32Upper, source,
      ['U0', 'U1'], ['C0', 'C1']).toFloat(),
    lu_factors: luFactors,
    lu_left_product: flatten(ee,
      permutation.matrixMultiply(matrix), source, ['R0', 'R1'], ['C0', 'C1']),
    lu_right_product: flatten(ee,
      luLower.matrixMultiply(upper), source, ['R0', 'R1'], ['C0', 'C1']),
    lu_upper_inverse: flatten(ee, upper.matrixInverse(), source,
      ['R0', 'R1'], ['C0', 'C1']),
    cholesky_solve_from_factors: flatten(ee,
      lowerT.matrixSolve(lower.matrixSolve(rhs)),
      source, ['X0', 'X1'], ['rhs'])
  };
}

var outputs = buildMatrixFactorWorkflow(
  ee, ee.ImageCollection(collectionId).first());
