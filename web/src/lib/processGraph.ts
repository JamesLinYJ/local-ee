import type { Json, ProcessGraph } from "../types";
export function parseGraph(text: string): ProcessGraph {
  const value: unknown = JSON.parse(text);
  const candidate =
    value && typeof value === "object" && "process_graph" in value
      ? value.process_graph
      : value;
  if (!candidate || typeof candidate !== "object" || Array.isArray(candidate))
    throw new Error("需要 process_graph 对象");
  const entries = Object.entries(candidate);
  if (!entries.length || entries.length > 500)
    throw new Error("进程图需要 1–500 个节点");
  for (const [id, node] of entries) {
    if (
      !id ||
      !node ||
      typeof node !== "object" ||
      !("process_id" in node) ||
      typeof node.process_id !== "string" ||
      !("arguments" in node) ||
      !node.arguments ||
      typeof node.arguments !== "object" ||
      Array.isArray(node.arguments)
    )
      throw new Error("每个节点需要 process_id 和 arguments 对象");
  }
  return candidate as ProcessGraph;
}
export function referencedNodes(value: Json): string[] {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    if ("process_graph" in value) return [];
    if (typeof value.from_node === "string") return [value.from_node];
    return Object.values(value).flatMap(referencedNodes);
  }
  if (Array.isArray(value)) return value.flatMap(referencedNodes);
  return [];
}
export function graphToPython(graph: ProcessGraph, title: string): string {
  return `import json\ngraph = json.loads(${JSON.stringify(JSON.stringify(graph))})\njob = connection.create_job(process_graph=graph, title=${JSON.stringify(title)})\njob.start_job()\nprint("已提交 GeoTrellis 任务:", job.job_id)\n`;
}
