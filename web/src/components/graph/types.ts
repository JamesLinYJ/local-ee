import type { Node } from "@xyflow/react";

export interface ProcessNodeData extends Record<string, unknown> {
  label: string;
  parameters: string[];
  result: boolean;
}

export type FlowNode = Node<ProcessNodeData>;
