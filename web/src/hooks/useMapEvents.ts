import { useEffect, useRef } from "react";
import type { RefObject } from "react";
import type { Job, MapEvent } from "../types";
import type { MapHandle } from "../components/MapPane";
import { errorMessage } from "../lib/api";
export interface EventDispatch {
  event: MapEvent;
  job?: Job;
  key: string;
}
export function readyMapEvents(
  jobs: Job[],
  handled: ReadonlySet<string>,
  focus?: string,
): EventDispatch[] {
  const parent = focus
    ? jobs.find((j) => j.id === focus)
    : jobs.find((j) => j.kind === "script" && j.events?.length);
  if (!parent) return [];
  const ready: EventDispatch[] = [];
  for (const [index, event] of (parent.events || []).entries()) {
    const key = parent.id + ":" + index;
    if (handled.has(key)) continue;
    if (event.type === "map_layer") {
      const job = jobs.find((j) => j.id === event.job_id);
      if (!job || !["finished", "error", "canceled"].includes(job.status))
        break;
      ready.push({ key, event, job });
    } else ready.push({ key, event });
  }
  return ready;
}
export default function useMapEvents(
  jobs: Job[],
  map: RefObject<MapHandle | null>,
  focus: string | undefined,
  notify: (message: string) => void,
) {
  const handled = useRef(new Set<string>()),
    processing = useRef(false);
  useEffect(() => {
    if (processing.current || !map.current) return;
    let disposed = false;
    processing.current = true;
    void (async () => {
      for (const item of readyMapEvents(jobs, handled.current, focus)) {
        if (disposed) break;
        try {
          if (!item.job || item.job.status === "finished")
            await map.current?.applyEvent(item.event, item.job);
          handled.current.add(item.key);
        } catch (error) {
          notify(errorMessage(error));
          handled.current.add(item.key);
        }
      }
    })().finally(() => {
      processing.current = false;
    });
    return () => {
      disposed = true;
    };
  }, [jobs, map, focus, notify]);
}
