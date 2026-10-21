import { AnimatePresence, motion } from "motion/react";
import Tabs from "../components/Tabs";
import ReferenceBrowser from "../components/ReferenceBrowser";
import type { Collection, Example, Script, Snippet } from "../types";
import DatasetCatalog from "./DatasetCatalog";
import ScriptLibrary from "./ScriptLibrary";
import type { DocumentState, LibraryTab } from "./types";

interface Props {
  tab: LibraryTab;
  onTabChange: (tab: LibraryTab) => void;
  document: DocumentState;
  user: string;
  scripts: Script[];
  examples: Example[];
  collections: Collection[];
  filteredCollections: Collection[];
  search: string;
  onSearchChange: (value: string) => void;
  scriptSearch: string;
  onScriptSearchChange: (value: string) => void;
  selectedCollection: string;
  onSelectCollection: (id: string) => void;
  bbox: string;
  onBboxChange: (value: string) => void;
  start: string;
  onStartChange: (value: string) => void;
  end: string;
  onEndChange: (value: string) => void;
  onNewScript: () => void;
  onLoadScript: (script: Script) => void;
  onLoadExample: (example: Example) => void;
  onInsertSnippet: (snippet: Snippet) => void;
  onExpandReference: () => void;
  onInsertCollection: () => void;
  onFitArea: () => void;
  reducedMotion: boolean;
}

export default function LibraryPane({
  tab,
  onTabChange,
  document,
  user,
  scripts,
  examples,
  collections,
  filteredCollections,
  search,
  onSearchChange,
  scriptSearch,
  onScriptSearchChange,
  selectedCollection,
  onSelectCollection,
  bbox,
  onBboxChange,
  start,
  onStartChange,
  end,
  onEndChange,
  onNewScript,
  onLoadScript,
  onLoadExample,
  onInsertSnippet,
  onExpandReference,
  onInsertCollection,
  onFitArea,
  reducedMotion,
}: Props) {
  return (
    <aside className="library-pane wb-panel">
      <Tabs
        value={tab}
        onChange={onTabChange}
        id="library"
        label="资源面板"
        tabs={[
          { id: "scripts", label: "脚本" },
          { id: "catalog", label: "数据", count: collections.length },
          { id: "docs", label: "文档" },
        ]}
      />
      <div className="panel-stage">
        <AnimatePresence initial={false} mode="sync">
          <motion.div
            className="panel-section"
            role="tabpanel"
            key={tab}
            id={"library-panel-" + tab}
            aria-labelledby={"library-" + tab}
            initial={{ opacity: 0, y: reducedMotion ? 0 : 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: reducedMotion ? 0 : -2 }}
            transition={{ duration: reducedMotion ? 0 : 0.14 }}
          >
            {tab === "scripts" ? (
              <ScriptLibrary
                document={document}
                user={user}
                scripts={scripts}
                examples={examples}
                search={scriptSearch}
                onSearchChange={onScriptSearchChange}
                onNewScript={onNewScript}
                onLoadScript={onLoadScript}
                onLoadExample={onLoadExample}
              />
            ) : tab === "catalog" ? (
              <DatasetCatalog
                filteredCollections={filteredCollections}
                search={search}
                onSearchChange={onSearchChange}
                selectedCollection={selectedCollection}
                onSelectCollection={onSelectCollection}
                bbox={bbox}
                onBboxChange={onBboxChange}
                start={start}
                onStartChange={onStartChange}
                end={end}
                onEndChange={onEndChange}
                onInsertCollection={onInsertCollection}
                onFitArea={onFitArea}
              />
            ) : (
              <ReferenceBrowser
                language={document.language}
                onInsert={onInsertSnippet}
                onExpand={onExpandReference}
              />
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </aside>
  );
}
