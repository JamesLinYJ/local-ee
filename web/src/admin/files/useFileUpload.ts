import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../../lib/api";
import { apiBase, type StoredFile } from "./models";

export default function useFileUpload({
  collectionId,
  refresh,
  onChanged,
  setFilePage,
  setError,
}: {
  collectionId: string;
  refresh: () => Promise<void>;
  onChanged: () => void;
  setFilePage: (page: number) => void;
  setError: (message: string) => void;
}) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const control = useRef<AbortController | null>(null);
  const hashWorker = useRef<Worker | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(
    () => () => {
      control.current?.abort();
      hashWorker.current?.terminate();
    },
    [],
  );

  async function upload(file: File) {
    if (busy) return;
    setError("");
    setFilePage(1);
    setBusy(true);
    setProgress(0);
    setMessage("计算文件校验值…");
    const abort = new AbortController();
    control.current = abort;
    try {
      if (!file.size || file.size > 512 * 1024 ** 2)
        throw new Error("单文件须为 1 字节至 512 MiB");
      const digest = await new Promise<string>((resolve, reject) => {
        const worker = new Worker(
          new URL("../fileHash.worker.ts", import.meta.url),
          { type: "module" },
        );
        hashWorker.current = worker;
        const stop = () => {
          worker.terminate();
          reject(new DOMException("Paused", "AbortError"));
        };
        abort.signal.addEventListener("abort", stop, { once: true });
        worker.onmessage = (
          event: MessageEvent<{
            progress?: number;
            sha256?: string;
            error?: string;
          }>,
        ) => {
          if (event.data.progress !== undefined)
            setProgress(event.data.progress * 100);
          if (event.data.sha256 || event.data.error) {
            abort.signal.removeEventListener("abort", stop);
            worker.terminate();
            hashWorker.current = null;
            if (event.data.sha256) resolve(event.data.sha256);
            else reject(new Error(event.data.error));
          }
        };
        worker.onerror = () => {
          worker.terminate();
          reject(new Error("文件校验进程失败"));
        };
        worker.postMessage(file);
      });
      if (abort.signal.aborted) throw new DOMException("Paused", "AbortError");
      const created = await api<{ data: StoredFile }>(
        `${apiBase}/datasets/${encodeURIComponent(collectionId)}/files`,
        "POST",
        { filename: file.name, size: file.size, sha256: digest },
        abort.signal,
      );
      const record = created.data;
      if (record.status !== "uploading") {
        setMessage("相同内容的文件已存在，无需重复上传。");
        await refresh();
        return;
      }
      let offset = record.received;
      setMessage(`正在上传 ${file.name}`);
      setProgress((offset / file.size) * 100);
      while (offset < file.size) {
        const chunk = file.slice(
          offset,
          Math.min(offset + 512 * 1024, file.size),
        );
        const response = await fetch(
          `${apiBase}/uploads/${encodeURIComponent(record.id)}/content`,
          {
            method: "PUT",
            credentials: "same-origin",
            headers: {
              "Content-Type": "application/octet-stream",
              "Upload-Offset": String(offset),
            },
            body: chunk,
            signal: abort.signal,
          },
        );
        if (!response.ok) {
          let details = "";
          try {
            details =
              ((await response.json()) as { message?: string }).message ?? "";
          } catch {
            /* Gateway body is not displayed. */
          }
          throw new Error(details || "上传暂停，请重新选择同一文件继续。");
        }
        const body = (await response.json()) as { received: number };
        offset = body.received;
        setProgress((offset / file.size) * 100);
      }
      setMessage("正在核对完整文件…");
      await api(
        `${apiBase}/uploads/${encodeURIComponent(record.id)}/complete`,
        "POST",
        {},
        abort.signal,
      );
      setMessage("文件上传完成，可以下载或配置入库。");
      await refresh();
      onChanged();
    } catch (reason) {
      if (abort.signal.aborted)
        setMessage("上传已暂停。重新选择同一文件可从已保存的位置继续。");
      else setError(errorMessage(reason));
      await refresh().catch(() => {});
    } finally {
      setBusy(false);
      control.current = null;
      hashWorker.current?.terminate();
      hashWorker.current = null;
      if (input.current) input.current.value = "";
    }
  }

  return {
    message,
    setMessage,
    busy,
    progress,
    input,
    abort: () => control.current?.abort(),
    upload,
  };
}
