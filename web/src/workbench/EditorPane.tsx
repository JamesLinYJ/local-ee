import type { Language } from "../types";
import Icon from "../components/Icon";
import CodeEditor from "../components/CodeEditor";
import type { DocumentState } from "./types";

interface Props {
  document: DocumentState;
  cursor: { line: number; column: number };
  reveal: { line: number; column: number; sequence: number } | undefined;
  submitting: boolean;
  duplicateRunning: boolean;
  onTitleChange: (title: string) => void;
  onLanguageChange: (language: Language) => void;
  onSave: () => void;
  onRun: () => void;
  onReset: () => void;
  onCode: (code: string) => void;
  onCursor: (line: number, column: number) => void;
  onSharedChange: (shared: boolean) => void;
}

export default function EditorPane({
  document,
  cursor,
  reveal,
  submitting,
  duplicateRunning,
  onTitleChange,
  onLanguageChange,
  onSave,
  onRun,
  onReset,
  onCode,
  onCursor,
  onSharedChange,
}: Props) {
  return (
    <section className="editor-pane wb-panel">
      <div className="editor-toolbar">
        <Icon name="code" />
        <input
          value={document.title}
          onChange={(event) => onTitleChange(event.target.value)}
          aria-label="脚本标题"
          placeholder="未命名脚本"
        />
        {document.dirty && (
          <span className="unsaved-dot" title="未保存" aria-label="未保存" />
        )}
        <select
          value={document.language}
          onChange={(event) => onLanguageChange(event.target.value as Language)}
          aria-label="脚本语言"
        >
          <option value="python">Python</option>
          <option value="javascript">GEE JavaScript</option>
        </select>
        <button onClick={onSave} aria-label="保存脚本" title="保存脚本">
          <Icon name="save" />
          <span>保存</span>
        </button>
        <button
          className="primary"
          disabled={submitting || duplicateRunning}
          title={
            duplicateRunning
              ? "本次计算尚未完成，修改代码后可提交新运行。"
              : "运行脚本"
          }
          onClick={onRun}
        >
          {submitting || duplicateRunning ? (
            <span className="button-spinner" />
          ) : (
            <Icon name="play" />
          )}
          {submitting ? "提交中" : duplicateRunning ? "计算中" : "运行"}
          <kbd>⌘ ↵</kbd>
        </button>
        <button
          className="icon-button"
          onClick={onReset}
          aria-label="重置地图与控制台"
          title="重置地图与控制台"
        >
          <Icon name="refresh" />
        </button>
      </div>
      <CodeEditor
        value={document.code}
        language={document.language}
        onChange={onCode}
        onCursor={onCursor}
        onRun={onRun}
        onSave={onSave}
        reveal={reveal}
      />
      <div className="editor-status">
        <span>
          Ln {cursor.line}, Col {cursor.column}
        </span>
        <label className="share-control">
          <Icon name={document.shared ? "folder" : "lock"} />
          <input
            type="checkbox"
            checked={document.shared}
            onChange={(event) => onSharedChange(event.target.checked)}
          />
          团队共享
        </label>
        <a href="/?editor=graph" target="_blank" rel="noopener">
          <Icon name="flow" />
          流程图
        </a>
        <span>
          {document.language === "javascript"
            ? "GEE JavaScript"
            : "Python 3.11"}
        </span>
      </div>
    </section>
  );
}
