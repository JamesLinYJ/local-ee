import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import Icon from "../Icon";
import type { FlowNode } from "./types";

export function ProcessCard({ data }: NodeProps<FlowNode>) {
  return (
    <div className={"process-card" + (data.result ? " result" : "")}>
      <header>
        <Icon name="flow" />
        {data.label}
        {data.result && <small>结果</small>}
      </header>
      <div className="process-inputs">
        {data.parameters.map((name) => (
          <div key={name}>
            <Handle type="target" position={Position.Left} id={name} />
            <span>{name}</span>
          </div>
        ))}
      </div>
      <Handle type="source" position={Position.Right} id="result" />
    </div>
  );
}

export const nodeTypes = { process: ProcessCard };
