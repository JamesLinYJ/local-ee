import type { ReferenceEntry } from "../types";

export const pythonTypedRasterDocs: ReferenceEntry[] = [
  {
    id: "gee-python-pixel-matrices",
    category: "GEE Python",
    language: "python",
    title: "逐像元矩阵求逆、伪逆与动态求解",
    text: "固定二维 RasterArrayImage 支持 matrixInverse、matrixPseudoInverse 和动态 matrixSolve；矩阵元素可来自实际波段。每轴1–8，输入／输出各不超过64单元，规格最多8192字节；旧图、数组与工作预算仍适用，满足形状上限不保证最大组合可运行。任一元素缺测会掩膜整矩阵，输入有效Infinity拒绝，数值奇异逆矩阵为NoData。局部缩放SVD阈值和结果不代表Google数值一致性。原生物理值为Float64；全Float32输入由编译器显式转回Float32，嵌套Float32舍入会保留。",
    code: "source = image.select(['m00','m01','m10','m11','b0','b1'])\nA = source.select(['m00','m01','m10','m11']).toDouble().toArray()\\\n    .arrayReshape(ee.Image.constant(ee.Array([2,2])), 2)\nB = source.select(['b0','b1']).toDouble().toArray()\\\n    .arrayReshape(ee.Image.constant(ee.Array([2,1])), 2)\ninverse = A.matrixInverse()\npseudo = A.matrixPseudoInverse()\nsolution = A.matrixSolve(B)\nprediction = pseudo.matrixMultiply(B)",
  },
  {
    id: "gee-python-double-array-solve",
    category: "GEE Python",
    language: "python",
    title: "Double 数组与固定矩阵求解",
    text: "静态 Array.matrixSolve 仍处理固定静态数组；影像上的 Image.matrixSolve 另支持有界动态 RasterArrayImage，并可与 matrixInverse、matrixPseudoInverse 串联。任一输入为 Double 时保留 Double；全 Float32 输入按类型联合规则转回 Float32。数组需先 flatten/get 成标量波段才能导出，原有64元素、500节点和工作预算保持。",
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
    id: "gee-js-pixel-matrices",
    title: "逐像元矩阵求逆、伪逆与动态求解",
    text: "固定二维 RasterArrayImage 支持 matrixInverse、matrixPseudoInverse 和动态 matrixSolve；元素可来自实际影像波段。每轴1–8，输入／输出各不超过64单元，规格最多8192字节；已有图节点、数组和工作预算仍限制实际组合。任一元素缺测掩膜整矩阵，输入有效Infinity拒绝，数值奇异逆为NoData。局部缩放SVD阈值不承诺Google数值一致性。原生物理结果是Float64，但全Float32输入会显式转换回Float32；嵌套Float32舍入不会被Double恢复。",
    code: "var source = image.select(['m00','m01','m10','m11','b0','b1']);\nvar A = source.select(['m00','m01','m10','m11']).toDouble()\n  .toArray().arrayReshape(ee.Image.constant(ee.Array([2,2])), 2);\nvar B = source.select(['b0','b1']).toDouble()\n  .toArray().arrayReshape(ee.Image.constant(ee.Array([2,1])), 2);\nvar inverse = A.matrixInverse();\nvar pseudo = A.matrixPseudoInverse();\nvar solution = A.matrixSolve(B);\nvar prediction = pseudo.matrixMultiply(B);",
  },
  {
    id: "gee-js-double-array-solve",
    title: "Double 数组与固定矩阵求解",
    text: "静态 Array.matrixSolve 处理固定数组；影像上的 Image.matrixSolve 另支持有界动态 RasterArrayImage，并可与 Image.matrixInverse、matrixPseudoInverse 串联。Float64 输入保留 Double，全 Float32 输入按类型联合规则转回 Float32；超出数组、图节点或工作预算的表达式明确拒绝。矩阵先用 arrayFlatten 等方法转换为普通影像波段再导出。",
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
