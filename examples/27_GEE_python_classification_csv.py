"""工作台示例：训练、独立验证，并将分类要素导出为本地 CSV。

使用与示例 26 相同的合成数值，不代表实际卫星采样或影像分类。
在本地工作台运行；toDrive 在这里表示本地任务结果下载。
"""
import ee


ee.Initialize()

training = ee.FeatureCollection([
    ee.Feature(None, {"nir": 2, "red": 0, "landcover": 0}),
    ee.Feature(None, {"nir": 4, "red": 0, "landcover": 0}),
    ee.Feature(None, {"nir": 1, "red": 1, "landcover": 1}),
    ee.Feature(None, {"nir": 3, "red": 3, "landcover": 1}),
])

observations = [
    (0.25, 0.25, 0, "diag-small"),
    (2, 2, 1, "diag-unit"),
    (8, 3.6, 1, "shallow-large"),
    (6, 0, 1, "positive-axis"),
    (-2, -2, 0, "negative-diagonal"),
    (0, 4, 1, "positive-red-axis"),
]
validation = ee.FeatureCollection([
    ee.Feature(ee.Geometry.Point([100 + index * 0.01, 30]), {
        "nir": nir, "red": red, "landcover": label,
        "sample_id": name, "system:index": f"held-{index + 1:02d}",
    })
    for index, (nir, red, label, name) in enumerate(observations)
])

for metric in ("euclidean", "manhattan", "cosine"):
    classifier = ee.Classifier.minimumDistance(metric).train(
        features=training, classProperty="landcover", inputProperties=["nir", "red"],
    )
    predicted = validation.classify(classifier, "predicted")
    matrix = predicted.errorMatrix("landcover", "predicted", [0, 1])
    print(metric, "验证准确率", matrix.accuracy().getInfo())

    task = ee.batch.Export.table.toDrive(
        collection=predicted,
        description=f"classification_{metric}",
        fileNamePrefix=f"classification_{metric}",
        fileFormat="CSV",
        selectors=["system:index", "sample_id", "landcover", "predicted", "nir", "red", ".geo"],
    )
    task.start()
    print("本地导出任务", task.id, task.status()["state"])
