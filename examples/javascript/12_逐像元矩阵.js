// 使用本地声明的版本化合成影像波段构造逐像元矩阵。
// The compile-only fixture uses an existing local source-resolver ID; its
// versioned catalog and band values remain synthetic and grant no new dataset acceptance.
var collectionId = 'sentinel-2-l2a';
var matrixBands = ['m00', 'm01', 'm10', 'm11'];
var rightHandSideBands = ['b0', 'b1'];
var sourceBands = matrixBands.concat(rightHandSideBands);
var matrixShape = [2, 2];
var rightHandSideShape = [2, 1];
var matrixRows = ['row0', 'row1'];
var matrixColumns = ['col0', 'col1'];
var solutionColumns = ['x0', 'x1'];
var copiedProperties = [
  'workflow', 'system:index', 'system:time_start', 'proj:code', 'proj:transform'
];
var syntheticVersion = 'local-ee-synthetic-pixel-matrices/v1';

function matrixFromBands(ee, image, bands, shape, precision) {
  var values = image.select(bands);
  if (precision === 'double') {
    values = values.toDouble();
  } else if (precision === 'float32') {
    values = values.toFloat();
  } else if (precision === 'float32_then_double') {
    // Keep the nested Float32 rounding before promoting the rounded values.
    values = values.toFloat().toDouble();
  } else {
    throw Error('Unsupported example precision: ' + precision);
  }
  return values.toArray().arrayReshape(
    ee.Image.constant(ee.Array(shape)), 2);
}

function flatten(matrix, source, rowNames, columnNames) {
  return matrix.arrayFlatten([rowNames, columnNames])
    .copyProperties(source, copiedProperties);
}

function buildPixelMatrixWorkflow(ee, image) {
  var source = ee.Image(image).select(sourceBands)
    .set('workflow', syntheticVersion);
  var matrix = matrixFromBands(
    ee, source, matrixBands, matrixShape, 'double');
  var rightHandSide = matrixFromBands(
    ee, source, rightHandSideBands, rightHandSideShape, 'double');

  var inverse = matrix.matrixInverse();
  var pseudoInverse = matrix.matrixPseudoInverse();
  var solution = matrix.matrixSolve(rightHandSide);
  var roundedMatrix = matrixFromBands(
    ee, source, matrixBands, matrixShape, 'float32_then_double');
  var roundedInverse = roundedMatrix.matrixInverse();
  var float32Matrix = matrixFromBands(
    ee, source, matrixBands, matrixShape, 'float32');

  return {
    matrix_inverse: flatten(inverse, source, matrixRows, matrixColumns),
    matrix_pseudoinverse: flatten(
      pseudoInverse, source, matrixRows, matrixColumns),
    matrix_solve: flatten(solution, source, solutionColumns, ['rhs']),
    inverse_reconstruction: flatten(
      inverse.matrixMultiply(matrix), source, matrixRows, matrixColumns),
    pseudoinverse_projection: flatten(
      pseudoInverse.matrixMultiply(matrix), source, matrixRows, matrixColumns),
    pseudoinverse_prediction: flatten(
      pseudoInverse.matrixMultiply(rightHandSide),
      source, solutionColumns, ['rhs']),
    float64_matrix: flatten(matrix, source, matrixRows, matrixColumns),
    float32_then_float64_matrix: flatten(
      roundedMatrix, source, matrixRows, matrixColumns),
    float32_then_float64_inverse: flatten(
      roundedInverse, source, matrixRows, matrixColumns),
    float32_matrix: flatten(
      float32Matrix, source, matrixRows, matrixColumns),
    float32_inverse: flatten(
      float32Matrix.matrixInverse(), source, matrixRows, matrixColumns)
  };
}

var outputs = buildPixelMatrixWorkflow(
  ee, ee.ImageCollection(collectionId).first());
