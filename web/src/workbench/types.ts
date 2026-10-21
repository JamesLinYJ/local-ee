import type { Language, Snippet } from "../types";

export interface DocumentState extends Snippet {
  id: string | null;
  title: string;
  shared: boolean;
  dirty: boolean;
}

export const initialDocument = (language: Language): DocumentState => ({
  id: null,
  title: "未命名分析",
  shared: false,
  dirty: false,
  language,
  code:
    language === "javascript"
      ? "// 选择左侧示例，或从数据目录插入代码。\nvar roi = ee.Geometry.Rectangle([113.55,22.30,113.57,22.32]);\n"
      : "# connection 已连接本地 openEO API，无需填写密码。\nprint(connection.list_collection_ids())\n",
});

export type LibraryTab = "scripts" | "catalog" | "docs";
export type OutputTab = "inspector" | "console" | "tasks";
