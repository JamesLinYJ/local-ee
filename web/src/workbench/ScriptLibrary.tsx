import Icon from "../components/Icon";
import type { Example, Script } from "../types";
import type { DocumentState } from "./types";

interface Props {
  document: DocumentState;
  user: string;
  scripts: Script[];
  examples: Example[];
  search: string;
  onSearchChange: (value: string) => void;
  onNewScript: () => void;
  onLoadScript: (script: Script) => void;
  onLoadExample: (example: Example) => void;
}

export default function ScriptLibrary({
  document,
  user,
  scripts,
  examples,
  search,
  onSearchChange,
  onNewScript,
  onLoadScript,
  onLoadExample,
}: Props) {
  const languageExamples = examples.filter(
    (example) => (example.language || "python") === document.language,
  );

  return (
    <div className="library-content">
      <div className="library-search">
        <Icon name="search" />
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="筛选脚本…"
          aria-label="筛选脚本"
        />
        <button
          className="icon-button"
          aria-label="新建脚本"
          onClick={onNewScript}
        >
          +
        </button>
      </div>
      <div className="library-group-title">
        <span>我的脚本</span>
        <small>
          {scripts.filter((script) => script.user_id === user).length}
        </small>
      </div>
      {scripts
        .filter((script) => script.title.includes(search))
        .map((script) => (
          <button
            key={script.id}
            className={
              "script-entry" + (document.id === script.id ? " selected" : "")
            }
            onClick={() => onLoadScript(script)}
          >
            <Icon name="code" />
            <span>
              {script.title}
              {script.user_id !== user && <small>共享</small>}
            </span>
            <i>{script.language === "javascript" ? "JS" : "PY"}</i>
          </button>
        ))}
      {!scripts.length && (
        <div className="wb-empty">保存后，脚本会显示在这里</div>
      )}
      <div className="library-group-title">
        <span>
          示例 ·{" "}
          {document.language === "javascript" ? "GEE JavaScript" : "Python"}
        </span>
        <small>{languageExamples.length}</small>
      </div>
      {languageExamples.map((example) => (
        <button
          key={example.name}
          className="script-entry"
          onClick={() => onLoadExample(example)}
        >
          <Icon name="code" />
          <span>{example.name}</span>
        </button>
      ))}
    </div>
  );
}
