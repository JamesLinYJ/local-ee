import type { ReferenceEntry } from "../types";

export const pythonTypedRasterDocs: ReferenceEntry[] = [
  {
    id: "gee-python-double-array-solve",
    category: "GEE Python",
    language: "python",
    title: "Double 数组与固定矩阵求解",
    text: "单个固定数组可逐元素 toDouble()。matrixSolve 当前接受满列秩的字面量设计矩阵，任一输入为 Double 时保留 Double；动态设计仍拒绝。数组需先 flatten/get 成标量波段才能导出，64元素、500节点和工作预算保持。",
    code: "design = ee.Image.constant(ee.Array(\n    [[1,0], [1,1], [1,2]])).toDouble()\nrhs = image.select(['red','nir','blue'])\\\n    .toArray().toArray(1).toDouble()\nfit = design.matrixSolve(rhs)\ncoefficients = fit.arrayFlatten(\n    [['intercept','slope'], ['value']])",
  },
  {
    id: "gee-python-double-array-selection",
    category: "GEE Python",
    language: "python",
    title: "Double 数组排序与最大值坐标",
    text: "Image.arraySort 的本地固定数组路径要求值数组与 keys 各自具有统一显式顶层 toFloat() 或 toDouble()；两者精度可不同，并用条件选择移动完整 payload 切片。Image.arrayArgmax 同样要求统一顶层 cast，返回行优先首个最大值坐标，本地坐标值为 Float32 整数。Float32 转换会丢失相邻 Double keys 的差异。64单元、50000工作量和500图节点上限不保证最大形状组合一定可编译；见官方 Image.arraySort 与 Image.arrayArgmax 文档。",
    code: "payload = image.select(['blue','green','red','nir'])\\\n    .toArray().arrayReshape(ee.Image.constant(ee.Array([2,2])), 2)\\\n    .toDouble()\nkeys = image.select(['b5','b4']).toArray()\\\n    .arrayReshape(ee.Image.constant(ee.Array([1,2])), 2).toDouble()\nordered = payload.arraySort(keys)\ncoordinates = score_grid.toDouble().arrayArgmax()",
  },
  {
    id: "gee-python-image-float64-arithmetic",
    category: "GEE Python",
    language: "python",
    title: "Double 影像算术",
    text: "先用 toDouble() 声明 Float64。有限输入按掩膜交集计算；定义域错误与溢出为 NoData，除零返回0，round 半值按本地规则向正无穷。未带 Double 操作数的旧图仍走 Float32；完整算子与精度边界见 Float64 算术文档。",
    code: "nir = image.select('nir').toDouble()\nred = image.select('red').toDouble()\nndvi = nir.subtract(red).divide(nir.add(red))\nsigned = image.expression(\n    '(nir-red)/(nir+red)', {'nir':nir, 'red':red})",
  },
  {
    id: "gee-python-image-integer-double-qa",
    category: "GEE Python",
    language: "python",
    title: "整数 QA 与后续算术",
    text: "本地整数 casts、位运算和 bitCount 保留 Double 精度标记，可直接继续普通算术，不必插入 toFloat()。位输入／结果限制在 ±2^53，移位数为0–63且不回绕，int64 限于精确 Double 整数域。请定义自己的位布局；它不表示 QA60 或 Landsat QA_PIXEL 等价。",
    code: "scl = image.select('SCL').toUint8()\nqa = scl.eq(8).leftShift(0).bitwiseOr(\n    scl.eq(9).leftShift(1))\nqa_score = qa.toUint8().multiply(2).add(1)",
  },
];

export const javascriptTypedRasterDocs: ReferenceEntry[] = [
  {
    id: "gee-js-double-array-solve",
    title: "Double 数组与固定矩阵求解",
    text: "单个固定数组可逐元素 toDouble()。matrixSolve 目前仅接受满列秩的字面量设计，任一输入 Double 则保留 Double；动态设计及超预算图明确拒绝。数组先 flatten/get 成标量再导出。",
    code: "var design = ee.Image.constant(ee.Array(\n  [[1,0], [1,1], [1,2]])).toDouble();\nvar rhs = image.select(['red','nir','blue'])\n  .toArray().toArray(1).toDouble();\nvar fit = design.matrixSolve(rhs);\nvar coefficients = fit.arrayFlatten(\n  [['intercept','slope'], ['value']]);",
  },
  {
    id: "gee-js-double-array-selection",
    title: "Double 数组排序与最大值坐标",
    text: "Image.arraySort 的本地固定数组路径要求值数组与 keys 各自具有统一显式顶层 toFloat() 或 toDouble()；两者精度可不同，并用条件选择移动完整 payload 切片。Image.arrayArgmax 同样要求统一顶层 cast，返回行优先首个最大值坐标，本地坐标值为 Float32 整数。Float32 转换会丢失相邻 Double keys 的差异。64单元、50000工作量和500图节点上限不保证最大形状组合一定可编译；见官方 Image.arraySort 与 Image.arrayArgmax 文档。",
    code: "var payload = image.select(['blue','green','red','nir'])\n  .toArray().arrayReshape(ee.Image.constant(ee.Array([2,2])), 2)\n  .toDouble();\nvar keys = image.select(['b5','b4']).toArray()\n  .arrayReshape(ee.Image.constant(ee.Array([1,2])), 2).toDouble();\nvar ordered = payload.arraySort(keys);\nvar coordinates = scoreGrid.toDouble().arrayArgmax();",
  },
  {
    id: "gee-js-image-float64-arithmetic",
    title: "Double 影像算术",
    text: "先调用 toDouble() 声明 Float64。有限输入按掩膜交集计算；定义域错误与溢出为 NoData，除零返回0，round 半值采用本地稳定规则。旧 Float32 图保持原路径，除非有 Double 操作数；仅支持固定算子集。",
    code: "var nir = image.select('nir').toDouble();\nvar red = image.select('red').toDouble();\nvar ndvi = nir.subtract(red).divide(nir.add(red));\nvar signed = image.expression('(nir-red)/(nir+red)',\n  {nir:nir, red:red});",
  },
  {
    id: "gee-js-image-integer-double-qa",
    title: "整数 QA 与后续算术",
    text: "整数 casts、位运算和 bitCount 保留 Double 精度标记，后续 QA 算术无需 toFloat()。位输入／结果限制在 ±2^53，移位数为0–63且不回绕。示例位布局是用户定义的合成 QA，不等于任何数据产品的质量波段。",
    code: "var scl = image.select('SCL').toUint8();\nvar qa = scl.eq(8).leftShift(0)\n  .bitwiseOr(scl.eq(9).leftShift(1));\nvar qaScore = qa.toUint8().multiply(2).add(1);",
  },
];
