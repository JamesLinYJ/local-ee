import { useMemo, useState } from "react";
import Icon from "./Icon";
import docs from "../docs/local-docs";
import type { Language, ReferenceEntry, Snippet } from "../types";
export default function ReferenceBrowser({
  language,
  onInsert,
  onExpand,
}: {
  language: Language;
  onInsert: (snippet: Snippet) => void;
  onExpand: () => void;
}) {
  const [query, setQuery] = useState(""),
    [selected, setSelected] = useState<ReferenceEntry | null>(null);
  const filtered = useMemo(
    () =>
      docs
        .filter((d) =>
          (d.title + " " + d.category + " " + d.text)
            .toLowerCase()
            .includes(query.toLowerCase()),
        )
        .sort(
          (a, b) =>
            Number((b.language || "python") === language) -
            Number((a.language || "python") === language),
        ),
    [language, query],
  );
  return (
    <div className="reference-browser">
      <div className="library-search">
        <Icon name="search" />
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSelected(null);
          }}
          placeholder="搜索语法与方法"
          aria-label="搜索语法与方法"
        />
      </div>
      {selected ? (
        <article className="reference-detail">
          <button className="back-link" onClick={() => setSelected(null)}>
            ‹ 返回目录
          </button>
          <small>{selected.category}</small>
          <h2>{selected.title}</h2>
          <p>{selected.text}</p>
          {selected.code && (
            <>
              <pre>{selected.code}</pre>
              <button
                className="wide"
                onClick={() =>
                  onInsert({
                    code: selected.code!,
                    language: selected.language || "python",
                  })
                }
              >
                <Icon name="code" />
                插入编辑器
              </button>
            </>
          )}
        </article>
      ) : (
        <div className="reference-list">
          <button className="reference-full" onClick={onExpand}>
            打开完整 API 文档
            <Icon name="arrow" />
          </button>
          {filtered.map((doc) => (
            <button key={doc.id} onClick={() => setSelected(doc)}>
              <small>{doc.category}</small>
              <b>{doc.title}</b>
            </button>
          ))}
          {!filtered.length && <p className="wb-empty">未找到匹配条目</p>}
        </div>
      )}
    </div>
  );
}
