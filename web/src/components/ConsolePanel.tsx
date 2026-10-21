import { failureInfo, readableLog } from "../lib/run";
import Icon from "./Icon";
import type { Job } from "../types";
export default function ConsolePanel({
  logs,
  job,
  canReveal,
  onReveal,
  onReference,
  onClear,
  onExamples,
}: {
  logs: string;
  job: Job | undefined;
  canReveal: boolean;
  onReveal: (location: { line: number; column: number }) => void;
  onReference: (id: string) => void;
  onClear: () => void;
  onExamples: () => void;
}) {
  const failed = job?.status === "error";
  const problem = failed ? failureInfo(logs) : null;
  const clean = readableLog(logs);
  return (
    <div className="console-panel">
      <div className="console-toolbar">
        <span>{job ? "运行输出" : "输出"}</span>
        <button onClick={onClear}>清空</button>
      </div>
      {problem ? (
        <>
          <section className="run-problem" role="status">
            <strong>{problem.title}</strong>
            <p>{problem.detail}</p>
            <p>{problem.suggestion}</p>
            <div>
              {problem.location && canReveal && (
                <button onClick={() => onReveal(problem.location!)}>
                  定位第 {problem.location.line} 行
                </button>
              )}
              <button onClick={() => onReference(problem.doc)}>
                <Icon name="book" />
                查看对应文档
              </button>
            </div>
          </section>
          <details className="log-details">
            <summary>完整日志</summary>
            <pre>{logs}</pre>
          </details>
        </>
      ) : (
        <pre>{clean.output || "使用 print(...) 输出到控制台。"}</pre>
      )}
      {!failed && clean.warnings.length > 0 && (
        <details className="log-details">
          <summary>{clean.warnings.length} 条数据与兼容说明</summary>
          <pre>{clean.warnings.join("\n\n")}</pre>
        </details>
      )}
      {!logs && (
        <div className="console-tip">
          <Icon name="terminal" />
          <p>运行脚本后，在这里查看输出与日志。</p>
          <button onClick={onExamples}>
            查看示例脚本
            <Icon name="arrow" />
          </button>
        </div>
      )}
    </div>
  );
}
