import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { api, errorMessage } from "../lib/api";
import docs from "../docs/local-docs";
import Icon from "./Icon";
import type { ProcessSpec, ReferenceEntry, Snippet } from "../types";
export default function ReferenceDialog({
  onClose,
  onInsert,
  onError,
  initialEntry = "gee-start",
}: {
  onClose: () => void;
  onInsert: (snippet: Snippet) => void;
  onError: (message: string) => void;
  initialEntry?: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState(""),
    [selected, setSelected] = useState(initialEntry),
    [processes, setProcesses] = useState<ProcessSpec[]>([]);
  useEffect(() => {
    dialog.current?.showModal();
    void api<{ processes: ProcessSpec[] }>("/openeo/1.2/processes")
      .then((r) => setProcesses(r.processes))
      .catch((e) => onError(errorMessage(e)));
    return () => dialog.current?.close();
  }, [onError]);
  const all: ReferenceEntry[] = [
    ...docs,
    ...processes.map((p) => ({
      id: "process-" + p.id,
      title: p.id,
      category: "本站算子参数",
      text: p.description,
    })),
  ];
  const filtered = all.filter((d) =>
    (d.title + " " + d.text + " " + d.category)
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const current = filtered.find((d) => d.id === selected) || filtered[0];
  const spec = current
    ? processes.find((p) => "process-" + p.id === current.id)
    : undefined;
  return (
    <motion.dialog
      ref={dialog}
      className="reference-dialog"
      aria-label="语法与 API 文档"
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
      initial={{ opacity: 0, y: 8, scale: 0.99 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8 }}
    >
      <header>
        <div>
          <h2>语法与 API 文档</h2>
          <small>GEE JavaScript · Python · openEO 算子参数</small>
        </div>
        <button onClick={onClose} aria-label="关闭文档">
          <Icon name="x" />
        </button>
      </header>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="搜索文档"
        aria-label="搜索完整文档"
      />
      <div className="reference-dialog-layout">
        <nav>
          {filtered.map((doc) => (
            <button
              key={doc.id}
              className={current?.id === doc.id ? "active" : ""}
              onClick={() => setSelected(doc.id)}
            >
              <small>{doc.category}</small>
              {doc.title}
            </button>
          ))}
        </nav>
        <article>
          {current && (
            <>
              <small>{current.category}</small>
              <h2>{current.title}</h2>
              <p>{current.text}</p>
              {current.code && (
                <>
                  <pre>{current.code}</pre>
                  <button
                    onClick={() =>
                      onInsert({
                        code: current.code!,
                        language: current.language || "python",
                      })
                    }
                  >
                    插入编辑器
                  </button>
                </>
              )}
              {spec && (
                <>
                  <h3>参数</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>名称</th>
                        <th>要求</th>
                        <th>说明</th>
                      </tr>
                    </thead>
                    <tbody>
                      {spec.parameters.map((p) => (
                        <tr key={p.name}>
                          <td>
                            <code>{p.name}</code>
                          </td>
                          <td>{p.optional ? "可选" : "必填"}</td>
                          <td>
                            {p.description}
                            <pre>{JSON.stringify(p.schema, null, 2)}</pre>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <h3>返回值</h3>
                  <pre>{JSON.stringify(spec.returns, null, 2)}</pre>
                </>
              )}
            </>
          )}
        </article>
      </div>
    </motion.dialog>
  );
}
