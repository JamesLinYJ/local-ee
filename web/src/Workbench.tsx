import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import Icon from "./components/Icon";
import MapPane, { parseBounds } from "./components/MapPane";
import type { MapHandle } from "./components/MapPane";
import ReferenceDialog from "./components/ReferenceDialog";
import useResources from "./hooks/useResources";
import useMapEvents from "./hooks/useMapEvents";
import useSplitLayout from "./hooks/useSplitLayout";
import { errorMessage } from "./lib/api";
import { isActive } from "./types";
import type { Job, RasterLayer, Snippet } from "./types";
import EditorPane from "./workbench/EditorPane";
import LibraryPane from "./workbench/LibraryPane";
import OutputPane from "./workbench/OutputPane";
import {
  WorkbenchHeader,
  WorkbenchStatusBar,
} from "./workbench/WorkbenchChrome";
import useWorkbenchDocument from "./workbench/useWorkbenchDocument";
import useWorkbenchJobs from "./workbench/useWorkbenchJobs";
import type { LibraryTab, OutputTab } from "./workbench/types";

export default function Workbench({
  user,
  onLogout,
  canManage = false,
}: {
  user: string;
  onLogout: () => Promise<void>;
  canManage?: boolean;
}) {
  const [notice, setNotice] = useState("");
  const notify = useCallback((message: string) => setNotice(message), []);
  const resources = useResources(notify);
  const {
    collections,
    jobs,
    scripts,
    examples,
    connected,
    connectionError,
    refresh,
  } = resources;
  const [leftTab, setLeftTab] = useState<LibraryTab>("scripts");
  const [rightTab, setRightTab] = useState<OutputTab>("console");
  const [search, setSearch] = useState("");
  const [scriptSearch, setScriptSearch] = useState("");
  const [selectedCollection, setSelectedCollection] = useState("");
  const [bbox, setBbox] = useState("113.55,22.30,113.57,22.32");
  const [start, setStart] = useState("2024-01-01");
  const [end, setEnd] = useState("2024-02-01");
  const [cursor, setCursor] = useState({ line: 1, column: 1 });
  const [showReference, setShowReference] = useState(false);
  const [mapExpanded, setMapExpanded] = useState(false);
  const [selectedRaster, setSelectedRaster] = useState<RasterLayer | null>(
    null,
  );
  const [inspection, setInspection] = useState({ position: "", pixel: "" });
  const [referenceEntry, setReferenceEntry] = useState("gee-start");
  const [reveal, setReveal] = useState<{
    line: number;
    column: number;
    sequence: number;
  }>();
  const map = useRef<MapHandle>(null);
  const workspace = useRef<HTMLElement>(null);
  const layout = useSplitLayout(workspace);
  const reduced = useReducedMotion();
  const document = useWorkbenchDocument({ user, refresh, notify });
  const runState = useWorkbenchJobs({
    jobs,
    document: document.document,
    refresh,
    map,
    notify,
    setOutputTab: setRightTab,
    clearInspection: () => setInspection({ position: "", pixel: "" }),
  });

  useMapEvents(jobs, map, runState.focusScript, notify);

  const filteredCollections = collections.filter((collection) =>
    (collection.title + " " + collection.id)
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const activeCount = jobs.filter(isActive).length;

  useEffect(() => {
    if (!selectedCollection && collections[0])
      setSelectedCollection(collections[0].id);
  }, [collections, selectedCollection]);

  const insertSnippet = (snippet: Snippet) => {
    document.insertSnippet(snippet);
    setShowReference(false);
  };

  const save = () => void document.save(runState.documentSaved);

  const showRaster = (job: Job, name: string) => {
    void map.current
      ?.showRaster(job, name)
      .catch((error) => notify(errorMessage(error)));
  };

  const insertCollection = () => {
    try {
      if (!selectedCollection) throw new Error("先选择已入库数据集");
      const [w, s, e, n] = parseBounds(bbox);
      const code =
        document.document.language === "javascript"
          ? `var roi = ee.Geometry.Rectangle(${JSON.stringify([w, s, e, n])});\nvar image = ee.ImageCollection(${JSON.stringify(selectedCollection)})\n  .filterDate(${JSON.stringify(start)}, ${JSON.stringify(end)}).filterBounds(roi).median().clip(roi);\nMap.centerObject(roi, 13);\nMap.addLayer(image, {}, '本地影像');\n`
          : `cube = connection.load_collection(\n    ${JSON.stringify(selectedCollection)},\n    spatial_extent={"west":${w},"south":${s},"east":${e},"north":${n}},\n    temporal_extent=[${JSON.stringify(start)},${JSON.stringify(end)}]\n)\njob = cube.save_result("GTiff").create_job(title="本地影像导出")\njob.start_job()\nprint("任务:", job.job_id)\n`;
      document.setDocument((previous) => ({ ...previous, code, dirty: true }));
      map.current?.fitArea();
    } catch (error) {
      notify(errorMessage(error));
    }
  };

  const inspect = useCallback((position: string, pixel: string) => {
    setInspection({ position, pixel });
    setRightTab("inspector");
  }, []);

  const reset = () => {
    map.current?.clear();
    runState.clearConsole();
    setInspection({ position: "", pixel: "" });
  };

  const separator = (kind: "left" | "right" | "top", label: string) => (
    <div
      className={"splitter " + (kind === "top" ? "horizontal" : "vertical")}
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-orientation={kind === "top" ? "horizontal" : "vertical"}
      aria-valuenow={Math.round(layout.size[kind])}
      aria-valuemin={kind === "left" ? 185 : kind === "right" ? 250 : 230}
      aria-valuemax={2000}
      onPointerDown={(event) => layout.start(kind, event)}
      onKeyDown={(event) => layout.key(kind, event)}
    >
      <i />
    </div>
  );

  return (
    <div
      className={
        "workbench is-logged-in" +
        (layout.dragging ? " is-resizing" : "") +
        (mapExpanded ? " map-expanded" : "")
      }
    >
      <WorkbenchHeader
        user={user}
        canManage={canManage}
        connected={connected}
        connectionError={connectionError}
        search={search}
        onSearchChange={(value) => {
          setSearch(value);
          setLeftTab("catalog");
        }}
        onSearchFocus={() => setLeftTab("catalog")}
        onLogout={() =>
          void onLogout().catch((error) => notify(errorMessage(error)))
        }
      />
      <main
        className="work-area"
        ref={workspace}
        style={
          {
            "--top-height": layout.size.top + "px",
            "--left-width": layout.size.left + "px",
            "--right-width": layout.size.right + "px",
          } as CSSProperties
        }
      >
        <div className="upper-workspace">
          <LibraryPane
            tab={leftTab}
            onTabChange={setLeftTab}
            document={document.document}
            user={user}
            scripts={scripts}
            examples={examples}
            collections={collections}
            filteredCollections={filteredCollections}
            search={search}
            onSearchChange={setSearch}
            scriptSearch={scriptSearch}
            onScriptSearchChange={setScriptSearch}
            selectedCollection={selectedCollection}
            onSelectCollection={setSelectedCollection}
            bbox={bbox}
            onBboxChange={setBbox}
            start={start}
            onStartChange={setStart}
            end={end}
            onEndChange={setEnd}
            onNewScript={document.createScript}
            onLoadScript={document.loadScript}
            onLoadExample={document.loadExample}
            onInsertSnippet={insertSnippet}
            onExpandReference={() => setShowReference(true)}
            onInsertCollection={insertCollection}
            onFitArea={() => map.current?.fitArea()}
            reducedMotion={!!reduced}
          />
          {separator("left", "调整资源面板宽度")}
          <EditorPane
            document={document.document}
            cursor={cursor}
            reveal={reveal}
            submitting={runState.submitting}
            duplicateRunning={runState.duplicateRunning}
            onTitleChange={document.updateTitle}
            onLanguageChange={document.changeLanguage}
            onSave={save}
            onRun={() => void runState.run()}
            onReset={reset}
            onCode={document.onCode}
            onCursor={(line, column) => setCursor({ line, column })}
            onSharedChange={document.updateShared}
          />
          {separator("right", "调整输出面板宽度")}
          <OutputPane
            tab={rightTab}
            onTabChange={setRightTab}
            activeCount={activeCount}
            currentRun={runState.currentRun}
            focusScript={runState.focusScript}
            computingCurrent={runState.computingCurrent}
            document={document.document}
            submittedCode={runState.submittedCode}
            logs={runState.logs}
            logJob={runState.logJob}
            selectedLog={runState.selectedLog}
            inspection={inspection}
            selectedRaster={selectedRaster}
            jobs={jobs}
            reducedMotion={!!reduced}
            onReveal={(location) =>
              setReveal({ ...location, sequence: Date.now() })
            }
            onReference={(id) => {
              setReferenceEntry(id);
              setShowReference(true);
            }}
            onClearConsole={runState.clearConsole}
            onExamples={() => setLeftTab("scripts")}
            onRefresh={() => void refresh()}
            onLogs={runState.showLogs}
            onCancel={(job) => void runState.jobAction(job, "cancel")}
            onRetry={(job) => void runState.jobAction(job, "retry")}
            onStart={(job) => void runState.jobAction(job, "start")}
            onRaster={showRaster}
          />
        </div>
        {separator("top", "调整编辑器与地图高度")}
        <MapPane
          ref={map}
          bbox={bbox}
          expanded={mapExpanded}
          onExpand={() => setMapExpanded(!mapExpanded)}
          onBounds={setBbox}
          onSelection={setSelectedRaster}
          onInspect={inspect}
          onError={notify}
        />
      </main>
      <WorkbenchStatusBar
        onShowTasks={() => setRightTab("tasks")}
        collectionCount={collections.length}
        jobs={jobs}
        language={document.document.language}
      />
      <AnimatePresence>
        {notice && (
          <motion.div
            className="toast"
            role="alert"
            key="notice"
            initial={{ opacity: 0, y: 7 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 7 }}
            onClick={() => setNotice("")}
          >
            <span>{notice}</span>
            <Icon name="x" />
          </motion.div>
        )}
        {showReference && (
          <ReferenceDialog
            key="reference"
            onClose={() => setShowReference(false)}
            onInsert={insertSnippet}
            onError={notify}
            initialEntry={referenceEntry}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
