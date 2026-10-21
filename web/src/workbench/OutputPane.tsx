import { AnimatePresence, motion } from "motion/react";
import Icon from "../components/Icon";
import Tabs from "../components/Tabs";
import TaskPanel from "../components/TaskPanel";
import ConsolePanel from "../components/ConsolePanel";
import type { Job, RasterLayer } from "../types";
import { runSummary } from "../lib/run";
import type { DocumentState, OutputTab } from "./types";

interface Props {
  tab: OutputTab;
  onTabChange: (tab: OutputTab) => void;
  activeCount: number;
  currentRun: Job[];
  focusScript?: string;
  computingCurrent: boolean;
  document: DocumentState;
  submittedCode: string;
  logs: string;
  logJob: Job | undefined;
  selectedLog: string | null;
  inspection: { position: string; pixel: string };
  selectedRaster: RasterLayer | null;
  jobs: Job[];
  reducedMotion: boolean;
  onReveal: (location: { line: number; column: number }) => void;
  onReference: (id: string) => void;
  onClearConsole: () => void;
  onExamples: () => void;
  onRefresh: () => void;
  onLogs: (job: Job) => void;
  onCancel: (job: Job) => void;
  onRetry: (job: Job) => void;
  onStart: (job: Job) => void;
  onRaster: (job: Job, name: string) => void;
}

export default function OutputPane({
  tab,
  onTabChange,
  activeCount,
  currentRun,
  focusScript,
  computingCurrent,
  document,
  submittedCode,
  logs,
  logJob,
  selectedLog,
  inspection,
  selectedRaster,
  jobs,
  reducedMotion,
  onReveal,
  onReference,
  onClearConsole,
  onExamples,
  onRefresh,
  onLogs,
  onCancel,
  onRetry,
  onStart,
  onRaster,
}: Props) {
  const panelMotion = {
    initial: { opacity: 0, y: reducedMotion ? 0 : 4 },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: reducedMotion ? 0 : -2 },
    transition: { duration: reducedMotion ? 0 : 0.14 },
  };

  return (
    <aside className="output-pane wb-panel">
      <Tabs
        value={tab}
        onChange={onTabChange}
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
          onClick={() => onTabChange("tasks")}
          title={currentRun.find((job) => job.id === focusScript)?.title}
        >
          {computingCurrent ? (
            <span className="button-spinner" />
          ) : (
            <Icon name="layers" />
          )}
          <span>
            {document.code !== submittedCode ? "上次运行 · " : ""}
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
            key={tab}
            id={"output-panel-" + tab}
            aria-labelledby={"output-" + tab}
            {...panelMotion}
          >
            {tab === "console" ? (
              <ConsolePanel
                logs={logs}
                job={logJob}
                canReveal={
                  selectedLog === focusScript && document.code === submittedCode
                }
                onReveal={onReveal}
                onReference={onReference}
                onClear={onClearConsole}
                onExamples={onExamples}
              />
            ) : tab === "inspector" ? (
              <div className="inspector-panel">
                <div className="inspector-intro">
                  <Icon name="pin" />
                  <p>
                    {inspection.position || "点击地图，查看位置与图层像素值。"}
                  </p>
                </div>
                {selectedRaster ? (
                  <>
                    <div className="inspector-title">{selectedRaster.name}</div>
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
                  <div className="wb-empty">图层计算完成后可查询原始数值。</div>
                )}
              </div>
            ) : (
              <TaskPanel
                jobs={jobs}
                selected={selectedLog}
                currentRun={focusScript}
                staleRun={document.code !== submittedCode}
                onRefresh={onRefresh}
                onLogs={onLogs}
                onCancel={onCancel}
                onRetry={onRetry}
                onStart={onStart}
                onRaster={onRaster}
              />
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </aside>
  );
}
