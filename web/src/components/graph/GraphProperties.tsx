import { parseGraph } from "../../lib/processGraph";
import { errorMessage } from "../../lib/api";
import type { ProcessGraph, ProcessSpec } from "../../types";

interface Props {
  graph: ProcessGraph | null;
  text: string;
  selected: string | null;
  specs: ProcessSpec[];
  onCommit: (graph: ProcessGraph) => void;
  onNotice: (message: string) => void;
}

export default function GraphProperties({
  graph,
  text,
  selected,
  specs,
  onCommit,
  onNotice,
}: Props) {
  const selectedNode = selected && graph ? graph[selected] : null;

  return (
    <aside className="graph-properties">
      <h2>节点参数</h2>
      {selectedNode ? (
        <>
          <div className="graph-selected-name">
            {selectedNode.process_id}
            <small>{selected}</small>
          </div>
          <p>
            {
              specs.find((spec) => spec.id === selectedNode.process_id)
                ?.description
            }
          </p>
          <label>
            节点 JSON
            <textarea
              aria-label="节点 JSON"
              key={text + "|" + selected}
              defaultValue={JSON.stringify(selectedNode, null, 2)}
              onBlur={(event) => {
                try {
                  const node: unknown = JSON.parse(event.target.value);
                  const copy = parseGraph(
                    JSON.stringify({ [selected!]: node }),
                  );
                  onCommit({ ...graph!, ...copy });
                } catch (error) {
                  onNotice(errorMessage(error));
                }
              }}
            />
          </label>
          <button
            onClick={() => {
              if (!graph || !selected) return;
              onCommit(
                Object.fromEntries(
                  Object.entries(graph).map(([key, node]) => [
                    key,
                    { ...node, result: key === selected },
                  ]),
                ) as ProcessGraph,
              );
            }}
          >
            设为结果节点
          </button>
        </>
      ) : (
        <p>
          点击节点查看参数；连接输出与参数端口可建立引用。复杂 reducer
          和嵌套参数可在右侧 JSON 中编辑。
        </p>
      )}
    </aside>
  );
}
