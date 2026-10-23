// Offline pinned-SDK workflow over the local reshape-scene fixture.
var collectionId = 'sentinel-2-l2a';
var payloadBands = ['blue', 'green', 'red', 'nir'];
var keyBands = ['b5', 'b4'];
var scoreBands = ['b4', 'b5', 'b6', 'b7'];
var matrixLabels = [
  ['row0', 'row1'],
  ['col0', 'col1']
];

function buildDoubleSelectionWorkflow(ee, image) {
  var source = ee.Image(image)
    .set('workflow', 'local-ee-synthetic-double-selection/v1');
  var matrixShape = ee.Image.constant(ee.Array([2, 2]));
  var keyShape = ee.Image.constant(ee.Array([1, 2]));
  var payloadDouble = source.select(payloadBands).toArray()
    .arrayReshape(matrixShape, 2).toDouble();
  var payloadFloat = source.select(payloadBands).toArray()
    .arrayReshape(matrixShape, 2).toFloat();
  var keysDouble = source.select(keyBands).toArray()
    .arrayReshape(keyShape, 2).toDouble();
  var keysAfterFloat32 = keysDouble.toFloat().toDouble();

  var scoreGrid = source.select(scoreBands).toArray()
    .arrayReshape(matrixShape, 2).toDouble();
  var scoreGridAfterFloat32 = scoreGrid.toFloat().toDouble();
  var scoreVector = source.select(scoreBands).toArray().toDouble();
  var orderedScores = scoreVector.arraySort();
  var middleScores = orderedScores.arraySlice(0, 1, 3);
  var trimmedMiddleMean = middleScores
    .arrayReduce(ee.Reducer.mean(), [0]).arrayGet([0])
    .rename('trimmed_middle_score_mean');

  return {
    sorted_double_payload: payloadDouble.arraySort(keysDouble)
      .arrayFlatten(matrixLabels),
    sorted_mixed_precision_payload: payloadFloat.arraySort(keysDouble)
      .arrayFlatten(matrixLabels),
    sorted_payload_after_float32_keys: payloadDouble.arraySort(keysAfterFloat32)
      .arrayFlatten(matrixLabels),
    first_max_double_coordinates: scoreGrid.arrayArgmax()
      .arrayFlatten([['max_row', 'max_column']]),
    first_max_after_float32_coordinates: scoreGridAfterFloat32.arrayArgmax()
      .arrayFlatten([['max_row', 'max_column']]),
    trimmed_middle_score_mean: trimmedMiddleMean
  };
}

var outputs = buildDoubleSelectionWorkflow(
  ee, ee.ImageCollection(collectionId).first());
