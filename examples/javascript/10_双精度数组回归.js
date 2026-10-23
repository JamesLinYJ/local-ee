// 固定官方 JavaScript 客户端语法；源数据来自现有离线合成夹具。
var collectionId = 'sentinel-2-l2a';
var bands = ['red', 'nir', 'blue'];
var designValues = [[1, 0], [1, 1], [1, 2]];

function buildDoubleMatrixWorkflow(ee, image) {
  var source = ee.Image(image).select(bands)
    .set('workflow', 'local-ee-synthetic-double-matrix-workflow/v1');
  var observations = source.toDouble().toArray().arrayReshape(
    ee.Image.constant(ee.Array([3, 1])), 2);
  var design = ee.Image(ee.Array(designValues)).toDouble();
  var copied = [
    'workflow', 'system:index', 'system:time_start',
    'proj:code', 'proj:transform'
  ];
  var coefficients = ee.Image(design.matrixSolve(observations)
    .copyProperties(source, copied));
  var predictions = ee.Image(design.matrixMultiply(coefficients)
    .copyProperties(source, copied)).toDouble();
  var selectedPrediction = predictions.arrayGet(ee.Image.constant([1, 0]))
    .rename('prediction_at_x1');

  var blue = source.select(['blue']);
  var precisionControls = blue.toDouble().rename('blue_float64')
    .addBands(blue.toFloat().rename('blue_float32'))
    .addBands(blue.toFloat().toDouble().rename('blue_float32_then_float64'));

  return {
    coefficients: coefficients.arrayProject([0]).arrayFlatten([['intercept', 'slope']]),
    predictions: predictions.arrayProject([0]).arrayFlatten([['x0', 'x1', 'x2']]),
    prediction_frobenius_norm: predictions.matrixFnorm()
      .rename('prediction_frobenius_norm'),
    selected_prediction: selectedPrediction,
    observation_trace: observations.matrixToDiag().matrixTrace()
      .rename('observation_trace'),
    precision_controls: precisionControls
  };
}

var outputs = buildDoubleMatrixWorkflow(
  ee, ee.ImageCollection(collectionId).first());
