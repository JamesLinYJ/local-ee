import { useState } from "react";
import Icon from "../Icon";
import { errorMessage } from "../../lib/api";
import type { ProcessGraph, ProcessSpec } from "../../types";

interface Props {
  title: string;
  onTitleChange: (title: string) => void;
  specs: ProcessSpec[];
  graph: ProcessGraph | null;
  submitting: boolean;
  onAdd: (process: string) => void;
  onImport: (value: string) => void;
  onNotice: (message: string) => void;
  onDownload: () => void;
  onSubmit: () => void;
}

export default function GraphToolbar({
  title,
  onTitleChange,
  specs,
  graph,
  submitting,
  onAdd,
  onImport,
  onNotice,
  onDownload,
  onSubmit,
}: Props) {
  const [process, setProcess] = useState("");

  return (
    <div className="graph-toolbar">
      <input
        value={title}
        onChange={(event) => onTitleChange(event.target.value)}
        aria-label="流程图标题"
      />
      <select
        value={process}
        onChange={(event) => setProcess(event.target.value)}
        aria-label="选择算子"
      >
        <option value="">添加算子…</option>
        {specs.map((spec) => (
          <option key={spec.id} value={spec.id}>
            {spec.id}
          </option>
        ))}
      </select>
      <button disabled={!graph || !process} onClick={() => onAdd(process)}>
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
              onNotice("进程图最大 1 MB");
              event.currentTarget.value = "";
              return;
            }
            const input = event.currentTarget;
            void file
              .text()
              .then(onImport)
              .catch((error: unknown) => onNotice(errorMessage(error)))
              .finally(() => {
                input.value = "";
              });
          }}
        />
      </label>
      <button onClick={onDownload} disabled={!graph}>
        <Icon name="download" />
        导出 JSON
      </button>
      <button
        className="primary"
        onClick={onSubmit}
        disabled={!graph || submitting}
      >
        <Icon name="play" />
        {submitting ? "提交中…" : "提交计算"}
      </button>
    </div>
  );
}
