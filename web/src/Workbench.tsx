import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import Icon from "./components/Icon";
import Tabs from "./components/Tabs";
import CodeEditor from "./components/CodeEditor";
import MapPane, { parseBounds } from "./components/MapPane";
import type { MapHandle } from "./components/MapPane";
import TaskPanel from "./components/TaskPanel";
import ReferenceBrowser from "./components/ReferenceBrowser";
import ReferenceDialog from "./components/ReferenceDialog";
import ConsolePanel from "./components/ConsolePanel";
import useResources from "./hooks/useResources";
import useMapEvents from "./hooks/useMapEvents";
import useSplitLayout from "./hooks/useSplitLayout";
import { api, errorMessage } from "./lib/api";
import { runTasks, runSummary } from "./lib/run";
import { isActive } from "./types";
import type {
  Example,
  Job,
  Language,
  LogResult,
  RasterLayer,
  Script,
  Snippet,
} from "./types";
interface DocumentState extends Snippet {
  id: string | null;
  title: string;
  shared: boolean;
  dirty: boolean;
}
const initial = (language: Language): DocumentState => ({
  id: null,
  title: "未命名分析",
  shared: false,
  dirty: false,
  language,
  code:
    language === "javascript"
      ? "// 选择左侧示例，或从数据目录插入代码。\nvar roi = ee.Geometry.Rectangle([113.55,22.30,113.57,22.32]);\n"
      : "# connection 已连接本地 openEO API，无需填写密码。\nprint(connection.list_collection_ids())\n",
});
type LibraryTab = "scripts" | "catalog" | "docs";
type OutputTab = "inspector" | "console" | "tasks";
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
  const [document, setDocument] = useState<DocumentState>(() =>
      initial("javascript"),
    ),
    [leftTab, setLeftTab] = useState<LibraryTab>("scripts"),
    [rightTab, setRightTab] = useState<OutputTab>("console"),
    [search, setSearch] = useState(""),
    [scriptSearch, setScriptSearch] = useState(""),
    [selectedCollection, setSelectedCollection] = useState(""),
    [bbox, setBbox] = useState("113.55,22.30,113.57,22.32"),
    [start, setStart] = useState("2024-01-01"),
    [end, setEnd] = useState("2024-02-01"),
    [cursor, setCursor] = useState({ line: 1, column: 1 }),
    [logs, setLogs] = useState(""),
    [selectedLog, setSelectedLog] = useState<string | null>(null),
    [submitting, setSubmitting] = useState(false),
    [showReference, setShowReference] = useState(false),
    [mapExpanded, setMapExpanded] = useState(false),
    [selectedRaster, setSelectedRaster] = useState<RasterLayer | null>(null),
    [inspection, setInspection] = useState({ position: "", pixel: "" }),
    [focusScript, setFocusScript] = useState<string>();
  const [referenceEntry, setReferenceEntry] = useState("gee-start");
  const [reveal, setReveal] = useState<{
    line: number;
    column: number;
    sequence: number;
  }>();
  const submittedCode = useRef("");
  const drafts = useRef<Partial<Record<Language, DocumentState>>>({}),
    map = useRef<MapHandle>(null),
    workspace = useRef<HTMLElement>(null);
  const layout = useSplitLayout(workspace);
  const reduced = useReducedMotion();
  useMapEvents(jobs, map, focusScript, notify);
  const currentRun = focusScript ? runTasks(jobs, focusScript) : [];
  const computingCurrent = currentRun.some((j) =>
    ["queued", "running"].includes(j.status),
  );
  const duplicateRunning =
    computingCurrent && document.code === submittedCode.current;
  const logJob = jobs.find((j) => j.id === selectedLog);
  useEffect(() => {
    if (!selectedCollection && collections[0])
      setSelectedCollection(collections[0].id);
  }, [collections, selectedCollection]);
  useEffect(() => {
    if (!selectedLog) return;
    const controller = new AbortController();
    void api<LogResult>(
      `/workbench/jobs/${selectedLog}/logs`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((result) =>
        setLogs(
          (result.logs ||
            {
              queued: "脚本已排队。",
              running: "正在运行…",
              finished: "任务已完成。",
              created: "任务已创建。",
              canceled: "任务已取消。",
              error: "任务失败。",
            }[result.status]) + (result.error ? "\n" + result.error : ""),
        ),
      )
      .catch((error) => {
        if (!controller.signal.aborted) notify(errorMessage(error));
      });
    return () => controller.abort();
  }, [jobs, selectedLog, notify]);
  useEffect(() => {
    if (!document.dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [document.dirty]);
  const onCode = useCallback(
    (code: string) =>
      setDocument((previous) =>
        previous.code === code ? previous : { ...previous, code, dirty: true },
      ),
    [],
  );
  const languageExamples = examples.filter(
      (e) => (e.language || "python") === document.language,
    ),
    filteredCollections = collections.filter((c) =>
      (c.title + " " + c.id).toLowerCase().includes(search.toLowerCase()),
    ),
    activeCount = jobs.filter(isActive).length;
  const changeLanguage = (language: Language) => {
    drafts.current[document.language] = document;
    setDocument(drafts.current[language] || initial(language));
  };
  const loadScript = (script: Script) => {
    drafts.current[document.language] = document;
    setDocument({
      id: script.user_id === user ? script.id : null,
      title: script.title,
      code: script.code,
      language: script.language || "python",
      shared: script.user_id === user && script.shared,
      dirty: false,
    });
  };
  const loadExample = (example: Example) => {
    drafts.current[document.language] = document;
    setDocument({
      id: null,
      title: example.name,
      code: example.code,
      language: example.language || "python",
      shared: false,
      dirty: false,
    });
  };
  const insertSnippet = (snippet: Snippet) => {
    drafts.current[document.language] = document;
    const base =
      snippet.language === document.language
        ? document
        : drafts.current[snippet.language] || initial(snippet.language);
    setDocument({
      ...base,
      code: base.code + "\n" + snippet.code + "\n",
      dirty: true,
    });
    setShowReference(false);
  };
  const save = async () => {
    try {
      const result = await api<{ id?: string }>(
        document.id
          ? "/workbench/scripts/" + document.id
          : "/workbench/scripts",
        document.id ? "PUT" : "POST",
        { ...document },
      );
      setDocument((previous) => ({
        ...previous,
        id: result.id || previous.id,
        dirty: previous.code !== document.code,
      }));
      setLogs(
        "脚本已保存。" + (document.shared ? "本地团队可读。" : "仅自己可见。"),
      );
      setSelectedLog(null);
      setRightTab("console");
      await refresh();
    } catch (error) {
      notify(errorMessage(error));
    }
  };
  const run = async () => {
    if (submitting || duplicateRunning) return;
    setSubmitting(true);
    try {
      const result = await api<{ id: string }>("/workbench/jobs", "POST", {
        title: document.title,
        code: document.code,
        language: document.language,
      });
      setFocusScript(result.id);
      submittedCode.current = document.code;
      if (document.language === "javascript") {
        map.current?.clear();
        setInspection({ position: "", pixel: "" });
      }
      setSelectedLog(result.id);
      setLogs("脚本已排队。");
      setRightTab("console");
      await refresh();
    } catch (error) {
      notify(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };
  const jobAction = async (job: Job, action: "start" | "cancel" | "retry") => {
    try {
      await api(`/workbench/jobs/${job.id}/${action}`, "POST", {});
      await refresh();
    } catch (error) {
      notify(errorMessage(error));
    }
  };
  const showLogs = (job: Job) => {
    setSelectedLog(job.id);
    setRightTab("console");
  };
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
        document.language === "javascript"
          ? `var roi = ee.Geometry.Rectangle(${JSON.stringify([w, s, e, n])});\nvar image = ee.ImageCollection(${JSON.stringify(selectedCollection)})\n  .filterDate(${JSON.stringify(start)}, ${JSON.stringify(end)}).filterBounds(roi).median().clip(roi);\nMap.centerObject(roi, 13);\nMap.addLayer(image, {}, '本地影像');\n`
          : `cube = connection.load_collection(\n    ${JSON.stringify(selectedCollection)},\n    spatial_extent={"west":${w},"south":${s},"east":${e},"north":${n}},\n    temporal_extent=[${JSON.stringify(start)},${JSON.stringify(end)}]\n)\njob = cube.save_result("GTiff").create_job(title="本地影像导出")\njob.start_job()\nprint("任务:", job.job_id)\n`;
      setDocument((previous) => ({ ...previous, code, dirty: true }));
      map.current?.fitArea();
    } catch (error) {
      notify(errorMessage(error));
    }
  };
  const inspect = useCallback((position: string, pixel: string) => {
    setInspection({ position, pixel });
    setRightTab("inspector");
  }, []);
  const clearConsole = () => {
    setSelectedLog(null);
    setLogs("");
  };
  const reset = () => {
    map.current?.clear();
    clearConsole();
    setInspection({ position: "", pixel: "" });
  };
  const panelMotion = {
    initial: { opacity: 0, y: reduced ? 0 : 4 },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: reduced ? 0 : -2 },
    transition: { duration: reduced ? 0 : 0.14 },
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
      <header className="top">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="layers" />
          </span>
          <b>遥感工作台</b>
        </div>
        <div className="global-search">
          <Icon name="search" />
          <input
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setLeftTab("catalog");
            }}
            onFocus={() => setLeftTab("catalog")}
            placeholder="搜索本地数据集…"
            aria-label="搜索本地数据集"
          />
          <kbd>本地目录</kbd>
        </div>
        <div className="top-right">
          {canManage && (
            <a className="admin-entry" href="/?view=admin">
              管理中心
            </a>
          )}
          <span
            title={connectionError}
            className={"connection-state" + (!connected ? " offline" : "")}
          >
            <i />
            {connected
              ? "服务已连接"
              : connectionError
                ? "重新连接中"
                : "正在连接"}
          </span>
          <span className="account-avatar">
            {user.slice(0, 1).toUpperCase()}
          </span>
          <span className="account-name">{user}</span>
          <button
            className="icon-button"
            onClick={() =>
              void onLogout().catch((error) => notify(errorMessage(error)))
            }
            aria-label="退出账号"
            title="退出"
          >
            <Icon name="logout" />
          </button>
        </div>
      </header>
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
          <aside className="library-pane wb-panel">
            <Tabs
              value={leftTab}
              onChange={setLeftTab}
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
                  key={leftTab}
                  id={"library-panel-" + leftTab}
                  aria-labelledby={"library-" + leftTab}
                  {...panelMotion}
                >
                  {leftTab === "scripts" ? (
                    <div className="library-content">
                      <div className="library-search">
                        <Icon name="search" />
                        <input
                          value={scriptSearch}
                          onChange={(e) => setScriptSearch(e.target.value)}
                          placeholder="筛选脚本…"
                          aria-label="筛选脚本"
                        />
                        <button
                          className="icon-button"
                          aria-label="新建脚本"
                          onClick={() => {
                            drafts.current[document.language] = document;
                            setDocument({
                              ...initial(document.language),
                              title: "未命名脚本",
                            });
                          }}
                        >
                          +
                        </button>
                      </div>
                      <div className="library-group-title">
                        <span>我的脚本</span>
                        <small>
                          {scripts.filter((s) => s.user_id === user).length}
                        </small>
                      </div>
                      {scripts
                        .filter((s) => s.title.includes(scriptSearch))
                        .map((script) => (
                          <button
                            key={script.id}
                            className={
                              "script-entry" +
                              (document.id === script.id ? " selected" : "")
                            }
                            onClick={() => loadScript(script)}
                          >
                            <Icon name="code" />
                            <span>
                              {script.title}
                              {script.user_id !== user && <small>共享</small>}
                            </span>
                            <i>
                              {script.language === "javascript" ? "JS" : "PY"}
                            </i>
                          </button>
                        ))}
                      {!scripts.length && (
                        <div className="wb-empty">保存后，脚本会显示在这里</div>
                      )}
                      <div className="library-group-title">
                        <span>
                          示例 ·{" "}
                          {document.language === "javascript"
                            ? "GEE JavaScript"
                            : "Python"}
                        </span>
                        <small>{languageExamples.length}</small>
                      </div>
                      {languageExamples.map((example) => (
                        <button
                          key={example.name}
                          className="script-entry"
                          onClick={() => loadExample(example)}
                        >
                          <Icon name="code" />
                          <span>{example.name}</span>
                        </button>
                      ))}
                    </div>
                  ) : leftTab === "catalog" ? (
                    <div className="library-content catalog-content">
                      <div className="library-search">
                        <Icon name="search" />
                        <input
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                          placeholder="搜索数据集…"
                          aria-label="搜索数据集"
                        />
                      </div>
                      <div className="library-group-title">
                        <span>已入库数据</span>
                        <small>{filteredCollections.length}</small>
                      </div>
                      {!filteredCollections.length && (
                        <div className="wb-empty">暂无匹配的数据集</div>
                      )}
                      {filteredCollections.map((c) => (
                        <button
                          key={c.id}
                          className={
                            "collection" +
                            (selectedCollection === c.id ? " selected" : "")
                          }
                          onClick={() => setSelectedCollection(c.id)}
                        >
                          <span className="dataset-icon">
                            <Icon name="layers" />
                          </span>
                          <span>
                            <b>{c.title || c.id}</b>
                            <small>{c.id}</small>
                            <small>
                              {(c["cube:dimensions"]?.bands?.values || []).join(
                                " · ",
                              )}
                            </small>
                          </span>
                          <span className="selection-dot" />
                        </button>
                      ))}
                      <div className="aoi-fields">
                        <div className="library-group-title">
                          <span>研究区与时间</span>
                          <button
                            className="icon-button"
                            onClick={() => map.current?.fitArea()}
                            aria-label="定位研究区"
                          >
                            <Icon name="pin" />
                          </button>
                        </div>
                        <label>
                          范围<span className="field-unit">W, S, E, N</span>
                          <input
                            className="coordinates-input"
                            value={bbox}
                            onChange={(e) => setBbox(e.target.value)}
                            aria-label="研究区范围"
                          />
                        </label>
                        <div className="date-pair">
                          <label>
                            开始
                            <input
                              type="date"
                              value={start}
                              onChange={(e) => setStart(e.target.value)}
                              aria-label="开始日期"
                            />
                          </label>
                          <label>
                            结束（不含）
                            <input
                              type="date"
                              value={end}
                              onChange={(e) => setEnd(e.target.value)}
                              aria-label="结束日期（不含）"
                            />
                          </label>
                        </div>
                        <button
                          className="wide insert-button"
                          onClick={insertCollection}
                        >
                          <Icon name="code" />
                          插入数据代码
                          <Icon name="arrow" />
                        </button>
                      </div>
                    </div>
                  ) : (
                    <ReferenceBrowser
                      language={document.language}
                      onInsert={insertSnippet}
                      onExpand={() => setShowReference(true)}
                    />
                  )}
                </motion.div>
              </AnimatePresence>
            </div>
          </aside>
          {separator("left", "调整资源面板宽度")}
          <section className="editor-pane wb-panel">
            <div className="editor-toolbar">
              <Icon name="code" />
              <input
                value={document.title}
                onChange={(e) =>
                  setDocument({
                    ...document,
                    title: e.target.value,
                    dirty: true,
                  })
                }
                aria-label="脚本标题"
                placeholder="未命名脚本"
              />
              {document.dirty && (
                <span
                  className="unsaved-dot"
                  title="未保存"
                  aria-label="未保存"
                />
              )}
              <select
                value={document.language}
                onChange={(e) => changeLanguage(e.target.value as Language)}
                aria-label="脚本语言"
              >
                <option value="python">Python</option>
                <option value="javascript">GEE JavaScript</option>
              </select>
              <button
                onClick={() => void save()}
                aria-label="保存脚本"
                title="保存脚本"
              >
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
                onClick={() => void run()}
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
                onClick={reset}
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
              onCursor={(line, column) => setCursor({ line, column })}
              onRun={() => void run()}
              onSave={() => void save()}
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
                  onChange={(e) =>
                    setDocument({
                      ...document,
                      shared: e.target.checked,
                      dirty: true,
                    })
                  }
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
          {separator("right", "调整输出面板宽度")}
          <aside className="output-pane wb-panel">
            <Tabs
              value={rightTab}
              onChange={setRightTab}
              id="output"
              label="输出面板"
              tabs={[
                { id: "inspector", label: "检查器" },
                { id: "console", label: "控制台" },
                { id: "tasks", label: "任务", count: activeCount || undefined },
              ]}
            />
            {focusScript && currentRun.length > 0 && (
              <button
                className="current-run-summary"
                onClick={() => setRightTab("tasks")}
                title={currentRun.find((j) => j.id === focusScript)?.title}
              >
                {computingCurrent ? (
                  <span className="button-spinner" />
                ) : (
                  <Icon name="layers" />
                )}
                <span>
                  {document.code !== submittedCode.current ? "上次运行 · " : ""}
                  {runSummary(currentRun)}
                </span>
                <Icon name="arrow" />
              </button>
            )}
            <div className="panel-stage">
              <AnimatePresence initial={false} mode="sync">
                <motion.div
                  className="panel-section"
                  role="tabpanel"
                  key={rightTab}
                  id={"output-panel-" + rightTab}
                  aria-labelledby={"output-" + rightTab}
                  {...panelMotion}
                >
                  {rightTab === "console" ? (
                    <ConsolePanel
                      logs={logs}
                      job={logJob}
                      canReveal={
                        selectedLog === focusScript &&
                        document.code === submittedCode.current
                      }
                      onReveal={(location) =>
                        setReveal({ ...location, sequence: Date.now() })
                      }
                      onReference={(id) => {
                        setReferenceEntry(id);
                        setShowReference(true);
                      }}
                      onClear={clearConsole}
                      onExamples={() => setLeftTab("scripts")}
                    />
                  ) : rightTab === "inspector" ? (
                    <div className="inspector-panel">
                      <div className="inspector-intro">
                        <Icon name="pin" />
                        <p>
                          {inspection.position ||
                            "点击地图，查看位置与图层像素值。"}
                        </p>
                      </div>
                      {selectedRaster ? (
                        <>
                          <div className="inspector-title">
                            {selectedRaster.name}
                          </div>
                          <dl>
                            <dt>坐标系</dt>
                            <dd>{selectedRaster.crs}</dd>
                            <dt>波段数</dt>
                            <dd>{selectedRaster.bands}</dd>
                            <dt>图像大小</dt>
                            <dd>
                              {selectedRaster.width} × {selectedRaster.height}
                            </dd>
                            <dt>像素值</dt>
                            <dd>{inspection.pixel || "点击影像查询"}</dd>
                          </dl>
                        </>
                      ) : (
                        <div className="wb-empty">
                          图层计算完成后可查询原始数值。
                        </div>
                      )}
                    </div>
                  ) : (
                    <TaskPanel
                      jobs={jobs}
                      selected={selectedLog}
                      currentRun={focusScript}
                      staleRun={document.code !== submittedCode.current}
                      onRefresh={() => void refresh()}
                      onLogs={showLogs}
                      onCancel={(job) => void jobAction(job, "cancel")}
                      onRetry={(job) => void jobAction(job, "retry")}
                      onStart={(job) => void jobAction(job, "start")}
                      onRaster={showRaster}
                    />
                  )}
                </motion.div>
              </AnimatePresence>
            </div>
          </aside>
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
      <footer className="status-bar">
        <span>
          <i className="local-indicator" />
          本地工作区
        </span>
        <span>{collections.length} 个数据集</span>
        <button onClick={() => setRightTab("tasks")}>
          {jobs.filter((j) => ["queued", "running"].includes(j.status)).length}{" "}
          个运行中
          {jobs.some((j) => j.status === "created")
            ? " · " +
              jobs.filter((j) => j.status === "created").length +
              " 个导出待启动"
            : ""}
        </button>
        <span className="status-right">
          {document.language === "javascript"
            ? "Earth Engine JS · 本地适配"
            : "openEO · GeoTrellis"}
        </span>
      </footer>
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
