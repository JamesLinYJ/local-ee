import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../lib/api";
import type { Collection, Example, Job, Script } from "../types";
export default function useResources(notify: (message: string) => void) {
  const [collections, setCollections] = useState<Collection[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [scripts, setScripts] = useState<Script[]>([]),
    [examples, setExamples] = useState<Example[]>([]),
    [connected, setConnected] = useState(false),
    [connectionError, setConnectionError] = useState("");
  const mounted = useRef(false),
    pending = useRef<Promise<void> | null>(null);
  const refresh = useCallback(() => {
    if (pending.current) return pending.current;
    const task = (async () => {
      try {
        const [c, j, s] = await Promise.all([
          api<Collection[]>("/workbench/catalog"),
          api<Job[]>("/workbench/jobs"),
          api<Script[]>("/workbench/scripts"),
        ]);
        if (!mounted.current) return;
        setCollections(c);
        setJobs(j);
        setScripts(s);
        setConnected(true);
        setConnectionError("");
      } catch (error) {
        if (mounted.current) {
          setConnected(false);
          setConnectionError(errorMessage(error));
        }
      }
    })().finally(() => {
      pending.current = null;
    });
    pending.current = task;
    return task;
  }, [notify]);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    void api<Example[]>("/workbench/examples")
      .then((value) => {
        if (mounted.current) setExamples(value);
      })
      .catch((error) => notify(errorMessage(error)));
    const interval = setInterval(() => void refresh(), 3000);
    return () => {
      mounted.current = false;
      clearInterval(interval);
    };
  }, [notify, refresh]);
  return {
    collections,
    jobs,
    scripts,
    examples,
    connected,
    connectionError,
    refresh,
  };
}
