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
    id: "gee-python-matrix-factors",
    category: "GEE Python",
    language: "python",
    title: "逐像元 Cholesky 与 LU 分解",
    text: "有界 rank-2 方阵支持 matrixCholeskyDecomposition 和 matrixLUDecomposition，参数名为 image。Cholesky 返回命名数组因子 L；LU 返回 L、U、P，并满足 P×A=L×U。先 select 因子，再 arrayFlatten 或参与矩阵运算；每组因子共享一个本地矩阵生产者。每轴1–8；LU返回三个方阵，合计最多64单元，因此 LU 最大为4×4。Cholesky 要求严格对称和严格正主元；LU 使用首个最大值部分主元，精确零主元或无法表示的非有限因子使整组结果为 NoData。缺测传播到整矩阵，有效源 Infinity 拒绝。Float32 输入先舍入到 Float32，Float32 输出转换本身仍可能溢出为 Infinity。示例消费 U 的逆和 Cholesky 求解；SDK 引用共享后，2×2 完整因子逆组合可编译，大型组合仍受现有50000步工作预算约束。Fraction/50位 Decimal 参考及本地消元规则不表示 Google 数值或完整 Spark 一致性。",
    code: "matrix = image.select(['m00','m01','m10','m11']).toDouble()\\\n    .toArray().arrayReshape(ee.Image.constant(ee.Array([2,2])), 2)\nchol = matrix.matrixCholeskyDecomposition()\nL = chol.select('L')\nlu = matrix.matrixLUDecomposition()\nP = lu.select('P')\nL_lu = lu.select('L')\nU = lu.select('U')\nleft = P.matrixMultiply(matrix)\nright = L_lu.matrixMultiply(U)",
  },
  {
    id: "gee-python-matrix-orthogonal",
    category: "GEE Python",
    language: "python",
    title: "逐像元紧凑 QR 与 SVD",
    text: "矩形显式 Float32/Double 矩阵支持 Image.matrixQRDecomposition 和 Image.matrixSingularValueDecomposition。令 p=min(m,n)，本地返回紧凑 Q(m,p)/R(p,n) 及 U(m,p)/S(p,p)/V(n,p)，因子按行优先串接；此尺寸约定为本地政策，官方矩形因子形状未明确。秩亏、零矩阵和重奇异值可输入；用重建、正交性及非负降序奇异值验证，不比较不同库的符号或重奇异值基。有限输入不保证因子均能以有限 Float64 表示，极端动态范围仍可能被拒绝。独立 NumPy 参考以精确二进制秩规范真实零值；若它丢失正奇异方向，则报告无参考。每轴1–8、输入及合计输出各至多64单元，仍受50000步和500节点限制。3×2／2×3 的 p=2 SVD全重建可编译，但保留两个奇异值是完整重建，不是降秩近似；3×3 的 U/S/V 因子可编译，从三个奇异值中选两个的真实秩二组合因静态数组工作预算被拒绝。Float32舍入后转Double的矩形SVD重建也逐像元验证；每个通过的组合图只有一个矩阵值生产者。QR正规残差组合仍会触及工作预算。",
    code: "A = image.select(['a00','a01','a10','a11','a20','a21'])\\\n    .toDouble().toArray()\\\n    .arrayReshape(ee.Image.constant(ee.Array([3,2])), 2)\nqr = A.matrixQRDecomposition()\nQ, R = qr.select('Q'), qr.select('R')\nsvd = A.matrixSingularValueDecomposition()\nU, S, V = svd.select('U'), svd.select('S'), svd.select('V')\nreconstructed = U.matrixMultiply(S).matrixMultiply(V.matrixTranspose())",
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
  {
    id: "gee-python-feature-preparation",
    category: "GEE Python",
    language: "python",
    title: "要素属性筛选与几何整理",
    text: "本地合成示例按字符串前后缀、数值闭区间、年积日和空间范围筛选站点；再以字面字段名和一个锚定正则选字段并重命名，用 getNumber/getArray/getString/toArray/toDictionary 读取属性，保留 Feature ID，并由显式经纬度重建点几何。固定目录元数据示例展示影像集合属性筛选。限于内联合成要素和已声明目录元数据，不读取真实像素或请求 Google；动态缺字段和类型检查不能从空集合推断。较大的多正则组合仍会受共享50,000工作预算限制。详见 docs/gee-python/feature-preparation.md。",
    code: "selected = stations.filter(ee.Filter.And(\n    ee.Filter.stringStartsWith('station_code', 'CN-'),\n    ee.Filter.stringEndsWith('station_code', '-QA'),\n    ee.Filter.gte('reading', 5), ee.Filter.lte('reading', 12),\n    ee.Filter.calendarRange(91, 120, field='day_of_year')))\nprepared = selected.filterBounds(region).map(\n    lambda feature: ee.Feature(feature.select(\n        ['station_code', '^station_name$'], ['site_code', 'station_name']))\n        .set('reading_value', feature.getNumber('reading'))\n        .setGeometry(ee.Geometry.Point(\n            [feature.getNumber('longitude'), feature.getNumber('latitude')])))",
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
    id: "gee-js-matrix-factors",
    title: "逐像元 Cholesky 与 LU 分解",
    text: "有界 rank-2 方阵支持 matrixCholeskyDecomposition 和 matrixLUDecomposition，参数名为 image。Cholesky 返回命名数组因子 L；LU 返回 L、U、P，并满足 P×A=L×U。先 select 因子，再 arrayFlatten 或参与矩阵运算；每组因子共享一个本地矩阵生产者。每轴1–8；LU返回三个方阵，合计最多64单元，因此 LU 最大为4×4。Cholesky 要求严格对称和严格正主元；LU 使用首个最大值部分主元，精确零主元或无法表示的非有限因子使整组结果为 NoData。缺测传播到整矩阵，有效源 Infinity 拒绝。Float32 输入先舍入到 Float32，Float32 输出转换本身仍可能溢出为 Infinity。示例消费 U 的逆和 Cholesky 求解；SDK 引用共享后，2×2 完整因子逆组合可编译，大型组合仍受现有50000步工作预算约束。Fraction/50位 Decimal 参考及本地消元规则不表示 Google 数值或完整 Spark 一致性。",
    code: "var matrix = image.select(['m00','m01','m10','m11']).toDouble()\n  .toArray().arrayReshape(ee.Image.constant(ee.Array([2,2])), 2);\nvar chol = matrix.matrixCholeskyDecomposition();\nvar L = chol.select('L');\nvar lu = matrix.matrixLUDecomposition();\nvar P = lu.select('P');\nvar L_lu = lu.select('L');\nvar U = lu.select('U');\nvar left = P.matrixMultiply(matrix);\nvar right = L_lu.matrixMultiply(U);",
  },
  {
    id: "gee-js-matrix-orthogonal",
    title: "逐像元紧凑 QR 与 SVD",
    text: "矩形显式 Float32/Double 矩阵支持 Image.matrixQRDecomposition 和 Image.matrixSingularValueDecomposition。令 p=min(m,n)，本地返回紧凑 Q(m,p)/R(p,n) 及 U(m,p)/S(p,p)/V(n,p)，因子按行优先串接；官方文档未明确矩形因子形状，此约定只描述本地实现。秩亏、零矩阵和重奇异值允许输入；以重建、正交性及非负降序奇异值验证，不要求不同数值库返回相同符号或基。有限输入不保证因子均能以有限 Float64 表示，极端动态范围仍可能被拒绝。独立 NumPy 参考以精确二进制秩规范真实零值；若它丢失正奇异方向，则报告无参考。每轴1–8，输入及合计输出各至多64单元；50000步和500节点限制保持。3×2／2×3 的 p=2 SVD全重建可编译，但保留两个奇异值是完整重建，不是降秩近似；3×3 的 U/S/V 因子可编译，从三个奇异值中选两个的真实秩二组合因静态数组工作预算被拒绝。Float32舍入后转Double的矩形SVD重建也逐像元验证；每个通过的组合图只有一个矩阵值生产者。QR正规残差组合仍会触及工作预算。",
    code: "var A = image.select(['a00','a01','a10','a11','a20','a21'])\n  .toDouble().toArray()\n  .arrayReshape(ee.Image.constant(ee.Array([3,2])), 2);\nvar qr = A.matrixQRDecomposition();\nvar Q = qr.select('Q');\nvar R = qr.select('R');\nvar svd = A.matrixSingularValueDecomposition();\nvar U = svd.select('U');\nvar S = svd.select('S');\nvar V = svd.select('V');\nvar reconstructed = U.matrixMultiply(S).matrixMultiply(V.matrixTranspose());",
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
  {
    id: "gee-js-feature-preparation",
    title: "要素属性筛选与几何整理",
    text: "本地合成示例按字符串前后缀、数值闭区间、年积日和空间范围筛选站点；再以字面字段名和一个锚定正则选字段并重命名，用 getNumber/getArray/getString/toArray/toDictionary 读取属性，保留 Feature ID，并由显式经纬度重建点几何。固定目录元数据示例展示影像集合属性筛选。限于内联合成要素和已声明目录元数据，不读取真实像素或请求 Google；动态缺字段和类型检查不能从空集合推断。较大的多正则组合仍会受共享50,000工作预算限制。详见 docs/gee-python/feature-preparation.md。",
    code: "var selected = stations.filter(ee.Filter.and(\n  ee.Filter.stringStartsWith('station_code', 'CN-'),\n  ee.Filter.stringEndsWith('station_code', '-QA'),\n  ee.Filter.gte('reading', 5), ee.Filter.lte('reading', 12),\n  ee.Filter.calendarRange(91, 120, 'day_of_year')));\nvar prepared = selected.filterBounds(region).map(function (feature) {\n  return ee.Feature(feature.select(['station_code', '^station_name$'],\n    ['site_code', 'station_name'])).set('reading_value',\n      feature.getNumber('reading')).setGeometry(ee.Geometry.Point([\n        feature.getNumber('longitude'), feature.getNumber('latitude')]));\n});",
  },
];
