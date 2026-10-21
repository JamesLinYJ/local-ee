import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import Icon from "./Icon";
import { assetUrl } from "../lib/api";
import { isActive, statusLabels } from "../types";
import type { Job } from "../types";
import { runTasks, runSummary } from "../lib/run";
interface Props {
  jobs: Job[];
  selected: string | null;
  currentRun?: string;
  staleRun?: boolean;
  onRefresh: () => void;
  onLogs: (job: Job) => void;
  onCancel: (job: Job) => void;
  onRetry: (job: Job) => void;
  onStart: (job: Job) => void;
  onRaster: (job: Job, name: string) => void;
}
const date = (value: string) =>
  new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
export default function TaskPanel(props: Props) {
  const [filter, setFilter] = useState("all");
  const [scope, setScope] = useState("run");
  const parent =
    props.jobs.find((j) => j.id === props.currentRun) ||
    props.jobs.find((j) => j.kind === "script");
  const group = parent ? runTasks(props.jobs, parent.id) : [];
  const candidates = scope === "run" && parent ? group : props.jobs;
  const active = candidates.filter(isActive).length;
  useEffect(() => {
    if (props.currentRun) {
      setScope("run");
      setFilter("all");
    }
  }, [props.currentRun]);
  const visible = useMemo(
    () =>
      candidates.filter(
        (j) =>
          filter === "all" ||
          (filter === "active"
            ? isActive(j)
            : filter === "error"
              ? ["error", "canceled"].includes(j.status)
              : j.status === "finished"),
      ),
    [candidates, filter],
  );
  return (
    <div className="task-panel">
      <div className="task-scope" aria-label="任务范围">
        <button
          className={scope === "run" ? "selected" : ""}
          onClick={() => setScope("run")}
          aria-pressed={scope === "run"}
        >
          {props.currentRun
            ? props.staleRun
              ? "上次运行"
              : "本次运行"
            : "最近运行"}
        </button>
        <button
          className={scope === "all" ? "selected" : ""}
          onClick={() => setScope("all")}
          aria-pressed={scope === "all"}
        >
          所有任务
        </button>
      </div>
      {scope === "run" && parent && (
        <div className="run-heading">
          <strong title={parent.title}>{parent.title}</strong>
          <span>{runSummary(group)}</span>
        </div>
      )}
      <div className="task-tools">
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="筛选任务状态"
        >
          <option value="all">全部状态 · {candidates.length}</option>
          <option value="active">待处理 · {active}</option>
          <option value="finished">已完成</option>
          <option value="error">失败 / 已取消</option>
        </select>
        <span>并行 1</span>
        <button
          className="icon-button"
          onClick={props.onRefresh}
          aria-label="刷新任务"
        >
          <Icon name="refresh" />
        </button>
      </div>
      <div className="task-scroll">
        <AnimatePresence initial={false}>
          {!visible.length && (
            <motion.div
              key="empty"
              className="wb-empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              暂无符合条件的任务
            </motion.div>
          )}
          {visible.map((job) => (
            <motion.article
              layout="position"
              key={job.id}
              className={
                "task-card" + (props.selected === job.id ? " selected" : "")
              }
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
            >
              <div className="task-card-title">
                <Icon name={job.kind === "script" ? "code" : "layers"} />
                <button
                  className="task-name"
                  title={job.title}
                  onClick={() => props.onLogs(job)}
                >
                  {job.title}
                </button>
                <i className={"status " + job.status}>
                  {statusLabels[job.status]}
                </i>
              </div>
              <div className="task-card-meta">
                <span>
                  {job.kind === "script"
                    ? job.language === "javascript"
                      ? "GEE JavaScript"
                      : "Python"
                    : job.kind === "ingest"
                      ? "数据入库"
                      : job.context.result_kind === "map"
                        ? "地图图层"
                        : job.context.result_kind === "export"
                          ? "本地导出"
                          : job.context.result_kind === "region"
                            ? "区域统计"
                            : "计算任务"}
                </span>
                <time>{date(job.created)}</time>
                <button onClick={() => props.onLogs(job)}>日志</button>
                {isActive(job) ? (
                  <button onClick={() => props.onCancel(job)}>取消</button>
                ) : (
                  <button onClick={() => props.onRetry(job)}>重提</button>
                )}
              </div>
              {job.error && (
                <p className="task-error" title={job.error}>
                  {job.error}
                </p>
              )}
              {(job.status === "created" ||
                Object.keys(job.assets || {}).length > 0) && (
                <div className="task-results">
                  {job.status === "created" && (
                    <button
                      className="task-start"
                      onClick={() => props.onStart(job)}
                    >
                      <Icon name="play" />
                      开始导出
                    </button>
                  )}
                  {job.status === "finished" &&
                    Object.keys(job.assets).map((name) => (
                      <span className="asset-actions" key={name}>
                        {/\.tiff?$/i.test(name) && (
                          <button onClick={() => props.onRaster(job, name)}>
                            <Icon name="map" />
                            地图
                          </button>
                        )}
                        <a
                          href={assetUrl(job.id, name)}
                          aria-label={"下载 " + name}
                          title={name}
                          download
                        >
                          <Icon name="download" />
                          <span>{name}</span>
                        </a>
                      </span>
                    ))}
                </div>
              )}
            </motion.article>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
