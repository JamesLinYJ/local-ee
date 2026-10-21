import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  applyNodeChanges,
} from "@xyflow/react";
import type {
  Connection,
  Edge,
  Node,
  NodeChange,
  NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import CodeEditor from "./CodeEditor";
import Icon from "./Icon";
import { api, errorMessage } from "../lib/api";
import {
  graphToPython,
  parseGraph,
  referencedNodes,
} from "../lib/processGraph";
import type { Json, ProcessGraph, ProcessSpec } from "../types";
import "../styles/graph.css";
interface Data extends Record<string, unknown> {
  label: string;
  parameters: string[];
  result: boolean;
}
type FlowNode = Node<Data>;
const initialGraph: ProcessGraph = {
  load: {
    process_id: "load_collection",
    arguments: {
      id: "sentinel-2-l2a",
      spatial_extent: { west: 113.55, south: 22.3, east: 113.57, north: 22.32 },
      temporal_extent: ["2024-01-19", "2024-01-20"],
      bands: ["red", "nir"],
    },
  },
  ndvi: {
    process_id: "ndvi",
    arguments: { data: { from_node: "load" }, nir: "nir", red: "red" },
  },
  mean: {
    process_id: "reduce_dimension",
    arguments: {
      data: { from_node: "ndvi" },
      dimension: "t",
      reducer: {
        process_graph: {
          mean: {
            process_id: "mean",
            arguments: { data: { from_parameter: "data" } },
            result: true,
          },
        },
      },
    },
  },
  save: {
    process_id: "save_result",
    arguments: { data: { from_node: "mean" }, format: "GTiff" },
    result: true,
  },
};
function ProcessCard({ data }: NodeProps<FlowNode>) {
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
const nodeTypes = { process: ProcessCard };
export default function GraphEditor({
  user,
  onLogout,
}: {
  user: string;
  onLogout: () => Promise<void>;
}) {
  const [text, setText] = useState(JSON.stringify(initialGraph, null, 2)),
    [title, setTitle] = useState("本地 NDVI 进程图"),
    [specs, setSpecs] = useState<ProcessSpec[]>([]),
    [process, setProcess] = useState(""),
    [selected, setSelected] = useState<string | null>(null),
    [notice, setNotice] = useState(""),
    [submitting, setSubmitting] = useState(false),
    [nodes, setNodes] = useState<FlowNode[]>([]);
  const positions = useRef(new Map<string, { x: number; y: number }>());
  const parsed = useMemo(() => {
    try {
      return { graph: parseGraph(text), error: "" };
    } catch (error) {
      return { graph: null, error: errorMessage(error) };
    }
  }, [text]);
  const graph = parsed.graph;
  useEffect(() => {
    void api<{ processes: ProcessSpec[] }>("/openeo/1.2/processes")
      .then((r) => setSpecs(r.processes))
      .catch((e) => setNotice(errorMessage(e)));
  }, []);
  useEffect(() => {
    if (!graph) return;
    setNodes(
      Object.entries(graph).map(([id, node], index) => ({
        id,
        type: "process",
        position: positions.current.get(id) || {
          x: 50 + (index % 3) * 240,
          y: 50 + Math.floor(index / 3) * 220,
        },
        data: {
          label: node.process_id,
          parameters: (
            specs
              .find((s) => s.id === node.process_id)
              ?.parameters.map((p) => p.name) || Object.keys(node.arguments)
          ).filter((p) => !p.startsWith("_")),
          result: !!node.result,
        },
      })),
    );
  }, [graph, specs]);
  const edges: Edge[] = useMemo(
    () =>
      graph
        ? Object.entries(graph).flatMap(([id, node]) =>
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
          )
        : [],
    [graph],
  );
  const change = useCallback((changes: NodeChange<FlowNode>[]) => {
    setNodes((previous) => applyNodeChanges(changes, previous));
    for (const item of changes)
      if (item.type === "position" && item.position)
        positions.current.set(item.id, item.position);
  }, []);
  const commit = (value: ProcessGraph) =>
    setText(JSON.stringify(value, null, 2));
  const connect = (connection: Connection) => {
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
  };
  const selectedNode = selected && graph ? graph[selected] : null;
  const submit = async () => {
    if (!graph || submitting) return;
    setSubmitting(true);
    try {
      const response = await api<{ id: string }>("/workbench/jobs", "POST", {
        language: "python",
        title: "流程图 · " + title,
        code: graphToPython(graph, title),
      });
      setNotice(
        "已提交脚本任务 " +
          response.id +
          "；计算与结果可在工作台任务面板查看。",
      );
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };
  const download = () => {
    if (!graph) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify({ process_graph: graph }, null, 2)], {
        type: "application/json",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "process-graph.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <div className="workbench is-logged-in graph-workbench">
      <header className="top">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="flow" />
          </span>
          <b>流程图编辑器</b>
        </div>
        <a href="/">返回工作台</a>
        <div className="top-right">
          <span>{user}</span>
          <button
            className="icon-button"
            aria-label="退出账号"
            onClick={() =>
              void onLogout().catch((e) => setNotice(errorMessage(e)))
            }
          >
            <Icon name="logout" />
          </button>
        </div>
      </header>
      <div className="graph-toolbar">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          aria-label="流程图标题"
        />
        <select
          value={process}
          onChange={(e) => setProcess(e.target.value)}
          aria-label="选择算子"
        >
          <option value="">添加算子…</option>
          {specs.map((spec) => (
            <option key={spec.id} value={spec.id}>
              {spec.id}
            </option>
          ))}
        </select>
        <button
          disabled={!graph || !process}
          onClick={() => {
            if (!graph) return;
            const id = process + "_" + Date.now().toString(36);
            const args: Record<string, Json> = {};
            for (const param of specs.find((s) => s.id === process)
              ?.parameters || [])
              if (param.default !== undefined) args[param.name] = param.default;
            commit({
              ...graph,
              [id]: { process_id: process, arguments: args },
            });
            setSelected(id);
          }}
        >
          添加
        </button>
        <label className="file-button">
          <Icon name="upload" />
          导入 JSON
          <input
            type="file"
            hidden
            accept=".json"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              if (file.size > 1000000) {
                setNotice("进程图最大 1 MB");
                return;
              }
              void file
                .text()
                .then((value) => {
                  parseGraph(value);
                  setText(value);
                })
                .catch((error) => setNotice(errorMessage(error)));
              event.target.value = "";
            }}
          />
        </label>
        <button onClick={download} disabled={!graph}>
          <Icon name="download" />
          导出 JSON
        </button>
        <button
          className="primary"
          onClick={() => void submit()}
          disabled={!graph || submitting}
        >
          <Icon name="play" />
          {submitting ? "提交中…" : "提交计算"}
        </button>
      </div>
      {parsed.error && (
        <div className="graph-error" role="alert">
          {parsed.error}
        </div>
      )}
      <main className="graph-layout">
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
                  specs.find((s) => s.id === selectedNode.process_id)
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
                      commit({ ...graph!, ...copy });
                    } catch (error) {
                      setNotice(errorMessage(error));
                    }
                  }}
                />
              </label>
              <button
                onClick={() => {
                  if (!graph || !selected) return;
                  commit(
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
        <div className="graph-canvas">
          <ReactFlow<FlowNode>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={change}
            onNodesDelete={(deleted) => {
              if (!graph) return;
              const ids = new Set(deleted.map((n) => n.id));
              const next: ProcessGraph = {};
              for (const [id, node] of Object.entries(graph))
                if (!ids.has(id))
                  next[id] = {
                    ...node,
                    arguments: Object.fromEntries(
                      Object.entries(node.arguments).filter(
                        ([, value]) =>
                          !referencedNodes(value).some((ref) => ids.has(ref)),
                      ),
                    ),
                  };
              if (Object.keys(next).length) commit(next);
              else {
                setNodes(deleted);
                setNotice("进程图至少保留一个节点。");
              }
            }}
            onConnect={connect}
            onNodeClick={(_, node) => setSelected(node.id)}
            onEdgesDelete={(deleted) => {
              if (!graph) return;
              const next = structuredClone(graph);
              for (const edge of deleted) {
                if (edge.targetHandle && next[edge.target])
                  delete next[edge.target]!.arguments[edge.targetHandle];
              }
              commit(next);
            }}
            fitView
            deleteKeyCode={["Backspace", "Delete"]}
          >
            <Background color="#d6e2dc" gap={20} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <section className="graph-json">
          <header>openEO Process Graph</header>
          <CodeEditor
            value={text}
            language="json"
            onChange={setText}
            onRun={() => void submit()}
            onSave={download}
          />
        </section>
      </main>
      <footer className="status-bar">
        <span>
          <i className="local-indicator" />
          本地计算图
        </span>
        <span>{graph ? Object.keys(graph).length : 0} 个节点</span>
        <span className="status-right">React Flow · openEO</span>
      </footer>
      {notice && (
        <div className="toast" role="alert" onClick={() => setNotice("")}>
          {notice}
          <Icon name="x" />
        </div>
      )}
    </div>
  );
}
