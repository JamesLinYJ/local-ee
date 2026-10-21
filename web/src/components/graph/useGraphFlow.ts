import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { applyNodeChanges } from "@xyflow/react";
import type { Connection, Edge, NodeChange } from "@xyflow/react";
import { referencedNodes } from "../../lib/processGraph";
import type { Json, ProcessGraph, ProcessSpec } from "../../types";
import { edgesForGraph, nodesForGraph } from "./graphLayout";
import type { FlowNode } from "./types";

interface Options {
  graph: ProcessGraph | null;
  specs: ProcessSpec[];
  commit: (graph: ProcessGraph) => void;
  setNotice: (message: string) => void;
}

export default function useGraphFlow({
  graph,
  specs,
  commit,
  setNotice,
}: Options) {
  const [selected, setSelected] = useState<string | null>(null);
  const [nodes, setNodes] = useState<FlowNode[]>([]);
  const positions = useRef(new Map<string, { x: number; y: number }>());

  useEffect(() => {
    if (graph) setNodes(nodesForGraph(graph, specs, positions.current));
  }, [graph, specs]);

  const edges: Edge[] = useMemo(() => edgesForGraph(graph), [graph]);
  const change = useCallback((changes: NodeChange<FlowNode>[]) => {
    setNodes((previous) => applyNodeChanges(changes, previous));
    for (const item of changes)
      if (item.type === "position" && item.position)
        positions.current.set(item.id, item.position);
  }, []);

  const connect = useCallback(
    (connection: Connection) => {
      if (
        !graph ||
        !connection.source ||
        !connection.target ||
        !connection.targetHandle
      )
        return;
      const target = graph[connection.target];
      if (!target) return;
      commit({
        ...graph,
        [connection.target]: {
          ...target,
          arguments: {
            ...target.arguments,
            [connection.targetHandle]: { from_node: connection.source },
          },
        },
      });
    },
    [commit, graph],
  );

  const addProcess = useCallback(
    (process: string) => {
      if (!graph) return;
      const id = process + "_" + Date.now().toString(36);
      const args: Record<string, Json> = {};
      for (const parameter of specs.find((spec) => spec.id === process)
        ?.parameters || [])
        if (parameter.default !== undefined)
          args[parameter.name] = parameter.default;
      commit({ ...graph, [id]: { process_id: process, arguments: args } });
      setSelected(id);
    },
    [commit, graph, specs],
  );

  const deleteNodes = useCallback(
    (deleted: FlowNode[]) => {
      if (!graph) return;
      const ids = new Set(deleted.map((node) => node.id));
      const next: ProcessGraph = {};
      for (const [id, node] of Object.entries(graph))
        if (!ids.has(id))
          next[id] = {
            ...node,
            arguments: Object.fromEntries(
              Object.entries(node.arguments).filter(
                ([, value]) =>
                  !referencedNodes(value).some((reference) =>
                    ids.has(reference),
                  ),
              ),
            ),
          };
      if (Object.keys(next).length) commit(next);
      else {
        setNodes(deleted);
        setNotice("进程图至少保留一个节点。");
      }
    },
    [commit, graph, setNotice],
  );

  const deleteEdges = useCallback(
    (deleted: Edge[]) => {
      if (!graph) return;
      const next = structuredClone(graph);
      for (const edge of deleted)
        if (edge.targetHandle && next[edge.target])
          delete next[edge.target]!.arguments[edge.targetHandle];
      commit(next);
    },
    [commit, graph],
  );

  return {
    selected,
    setSelected,
    nodes,
    edges,
    change,
    connect,
    addProcess,
    deleteNodes,
    deleteEdges,
  };
}
