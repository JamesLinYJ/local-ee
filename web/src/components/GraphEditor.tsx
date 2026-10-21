import { useCallback, useEffect, useMemo, useState } from "react";
import "@xyflow/react/dist/style.css";
import CodeEditor from "./CodeEditor";
import Icon from "./Icon";
import GraphCanvas from "./graph/GraphCanvas";
import GraphProperties from "./graph/GraphProperties";
import GraphToolbar from "./graph/GraphToolbar";
import { initialGraph } from "./graph/defaultGraph";
import useGraphFlow from "./graph/useGraphFlow";
import { api, errorMessage } from "../lib/api";
import { graphToPython, parseGraph } from "../lib/processGraph";
import type { ProcessGraph, ProcessSpec } from "../types";
import "../styles/graph.css";

export default function GraphEditor({
  user,
  onLogout,
}: {
  user: string;
  onLogout: () => Promise<void>;
}) {
  const [text, setText] = useState(JSON.stringify(initialGraph, null, 2));
  const [title, setTitle] = useState("本地 NDVI 进程图");
  const [specs, setSpecs] = useState<ProcessSpec[]>([]);
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);
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
      .then((response) => setSpecs(response.processes))
      .catch((error) => setNotice(errorMessage(error)));
  }, []);

  const commit = useCallback((value: ProcessGraph) => {
    setText(JSON.stringify(value, null, 2));
  }, []);
  const flow = useGraphFlow({ graph, specs, commit, setNotice });

  const importGraph = useCallback((value: string) => {
    parseGraph(value);
    setText(value);
  }, []);
  const submit = useCallback(async () => {
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
  }, [graph, submitting, title]);

  const download = useCallback(() => {
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
  }, [graph]);

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
              void onLogout().catch((error) => setNotice(errorMessage(error)))
            }
          >
            <Icon name="logout" />
          </button>
        </div>
      </header>
      <GraphToolbar
        title={title}
        onTitleChange={setTitle}
        specs={specs}
        graph={graph}
        submitting={submitting}
        onAdd={flow.addProcess}
        onImport={importGraph}
        onNotice={setNotice}
        onDownload={download}
        onSubmit={() => void submit()}
      />
      {parsed.error && (
        <div className="graph-error" role="alert">
          {parsed.error}
        </div>
      )}
      <main className="graph-layout">
        <GraphProperties
          graph={graph}
          text={text}
          selected={flow.selected}
          specs={specs}
          onCommit={commit}
          onNotice={setNotice}
        />
        <GraphCanvas
          nodes={flow.nodes}
          edges={flow.edges}
          onNodesChange={flow.change}
          onNodesDelete={flow.deleteNodes}
          onConnect={flow.connect}
          onNodeClick={flow.setSelected}
          onEdgesDelete={flow.deleteEdges}
        />
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
