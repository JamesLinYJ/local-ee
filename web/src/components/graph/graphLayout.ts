import type { Edge } from "@xyflow/react";
import type { ProcessGraph, ProcessSpec } from "../../types";
import { referencedNodes } from "../../lib/processGraph";
import type { FlowNode } from "./types";

export function nodesForGraph(
  graph: ProcessGraph,
  specs: ProcessSpec[],
  positions: Map<string, { x: number; y: number }>,
): FlowNode[] {
  return Object.entries(graph).map(([id, node], index) => ({
    id,
    type: "process",
    position: positions.get(id) || {
      x: 50 + (index % 3) * 240,
      y: 50 + Math.floor(index / 3) * 220,
    },
    data: {
      label: node.process_id,
      parameters: (
        specs
          .find((spec) => spec.id === node.process_id)
          ?.parameters.map((parameter) => parameter.name) ||
        Object.keys(node.arguments)
      ).filter((parameter) => !parameter.startsWith("_")),
      result: !!node.result,
    },
  }));
}

export function edgesForGraph(graph: ProcessGraph | null): Edge[] {
  if (!graph) return [];
  return Object.entries(graph).flatMap(([id, node]) =>
    Object.entries(node.arguments).flatMap(([parameter, value]) =>
      referencedNodes(value)
        .filter((source) => source in graph)
        .map((source) => ({
          id: source + "|" + id + "|" + parameter,
          source,
          target: id,
          targetHandle: parameter,
          sourceHandle: "result",
          type: "smoothstep",
        })),
    ),
  );
}
