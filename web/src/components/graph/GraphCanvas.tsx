import { Background, Controls, ReactFlow } from "@xyflow/react";
import type { Connection, Edge, NodeChange } from "@xyflow/react";
import { nodeTypes } from "./ProcessCard";
import type { FlowNode } from "./types";

interface Props {
  nodes: FlowNode[];
  edges: Edge[];
  onNodesChange: (changes: NodeChange<FlowNode>[]) => void;
  onNodesDelete: (deleted: FlowNode[]) => void;
  onConnect: (connection: Connection) => void;
  onNodeClick: (id: string) => void;
  onEdgesDelete: (deleted: Edge[]) => void;
}

export default function GraphCanvas({
  nodes,
  edges,
  onNodesChange,
  onNodesDelete,
  onConnect,
  onNodeClick,
  onEdgesDelete,
}: Props) {
  return (
    <div className="graph-canvas">
      <ReactFlow<FlowNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodesDelete={onNodesDelete}
        onConnect={onConnect}
        onNodeClick={(_, node) => onNodeClick(node.id)}
        onEdgesDelete={onEdgesDelete}
        fitView
        deleteKeyCode={["Backspace", "Delete"]}
      >
        <Background color="#d6e2dc" gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
