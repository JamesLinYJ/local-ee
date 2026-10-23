import type { ReferenceEntry } from "../types";

export const pythonTypedRasterDocs: ReferenceEntry[] = [
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
