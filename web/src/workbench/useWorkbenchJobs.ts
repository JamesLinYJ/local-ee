import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { api, errorMessage } from "../lib/api";
import { runTasks } from "../lib/run";
import type { Job, LogResult } from "../types";
import type { MapHandle } from "../components/MapPane";
import type { DocumentState, OutputTab } from "./types";

interface Options {
  jobs: Job[];
  document: DocumentState;
  refresh: () => Promise<void>;
  map: RefObject<MapHandle | null>;
  notify: (message: string) => void;
  setOutputTab: (tab: OutputTab) => void;
  clearInspection: () => void;
}

export default function useWorkbenchJobs({
  jobs,
  document,
  refresh,
  map,
  notify,
  setOutputTab,
  clearInspection,
}: Options) {
  const [logs, setLogs] = useState("");
  const [selectedLog, setSelectedLog] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [focusScript, setFocusScript] = useState<string>();
  const submittedCode = useRef("");
  const currentRun = focusScript ? runTasks(jobs, focusScript) : [];
  const computingCurrent = currentRun.some((job) =>
    ["queued", "running"].includes(job.status),
  );
  const duplicateRunning =
    computingCurrent && document.code === submittedCode.current;
  const logJob = jobs.find((job) => job.id === selectedLog);

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
        clearInspection();
      }
      setSelectedLog(result.id);
      setLogs("脚本已排队。");
      setOutputTab("console");
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
    setOutputTab("console");
  };

  const clearConsole = () => {
    setSelectedLog(null);
    setLogs("");
  };

  const documentSaved = (shared: boolean) => {
    setLogs("脚本已保存。" + (shared ? "本地团队可读。" : "仅自己可见。"));
    setSelectedLog(null);
    setOutputTab("console");
  };

  return {
    logs,
    selectedLog,
    submitting,
    focusScript,
    currentRun,
    computingCurrent,
    duplicateRunning,
    submittedCode: submittedCode.current,
    logJob,
    run,
    jobAction,
    showLogs,
    clearConsole,
    documentSaved,
  };
}
