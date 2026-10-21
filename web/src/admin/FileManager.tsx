import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { api, errorMessage } from "../lib/api";
import Icon from "../components/Icon";
import "./files.css";

interface StoredFile {
  id: string;
  filename: string;
  size: number;
  received: number;
  sha256: string;
  status: string;
  error: string | null;
  item_id: string | null;
  options: { datetime?: string; unit?: string; bands?: string[] };
}
interface Asset {
  item_id: string;
  band: string;
  datetime: string;
  active: boolean;
  metadata: { "file:size"?: number };
}
const labels: Record<string, string> = {
  uploading: "上传未完成",
  stored: "已存储",
  queued: "等待入库",
  processing: "正在入库",
  ready: "已入库",
  error: "入库失败",
  canceled: "已取消",
};
const sizeLabel = (size: number) =>
  size >= 1024 ** 2
    ? (size / 1024 ** 2).toFixed(1) + " MiB"
    : (size / 1024).toFixed(1) + " KiB";
const base = "/workbench/admin/v1";
export default function FileManager({
  cid,
  title,
  onClose,
  onChanged,
}: {
  cid: string;
  title: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [files, setFiles] = useState<StoredFile[]>([]),
    [assets, setAssets] = useState<Asset[]>([]),
    [error, setError] = useState(""),
    [loadError, setLoadError] = useState(""),
    [loading, setLoading] = useState(true),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [progress, setProgress] = useState(0),
    [filePage, setFilePage] = useState(1),
    [fileTotal, setFileTotal] = useState(0),
    [moreFiles, setMoreFiles] = useState(false),
    [ingesting, setIngesting] = useState(false),
    [selected, setSelected] = useState<StoredFile | null>(null),
    [unit, setUnit] = useState(""),
    [bands, setBands] = useState(""),
    [assetPage, setAssetPage] = useState(1),
    [hasMore, setHasMore] = useState(false);
  const control = useRef<AbortController | null>(null),
    hashWorker = useRef<Worker | null>(null),
    input = useRef<HTMLInputElement>(null);
  const refresh = useCallback(async () => {
    const [uploads, rasters] = await Promise.all([
      api<{ data: StoredFile[]; total: number; has_more: boolean }>(
        `${base}/datasets/${encodeURIComponent(cid)}/files?page=${filePage}`,
      ),
      api<{ data: Asset[]; has_more: boolean }>(
        `${base}/datasets/${encodeURIComponent(cid)}/assets?page=${assetPage}`,
      ),
    ]);
    setFiles(uploads.data);
    setLoadError("");
    setLoading(false);
    setFileTotal(uploads.total);
    setMoreFiles(uploads.has_more);
    setAssets(rasters.data);
    setHasMore(rasters.has_more);
  }, [cid, assetPage, filePage]);
  useEffect(() => {
    let alive = true;
    const update = () =>
      void refresh().catch((e) => {
        if (alive) {
          setLoadError(errorMessage(e));
          setLoading(false);
        }
      });
    update();
    const timer = setInterval(update, 3000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [refresh]);
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
          new URL("./fileHash.worker.ts", import.meta.url),
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
        `${base}/datasets/${encodeURIComponent(cid)}/files`,
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
          `${base}/uploads/${encodeURIComponent(record.id)}/content`,
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
        `${base}/uploads/${encodeURIComponent(record.id)}/complete`,
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
  async function submitIngest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || ingesting) return;
    setIngesting(true);
    setError("");
    const date = String(
      new FormData(event.currentTarget).get("observation_datetime") ?? "",
    );
    try {
      if (!date) throw new Error("请填写观测时间");
      await api(
        `${base}/uploads/${encodeURIComponent(selected.id)}/ingest`,
        "POST",
        {
          datetime: new Date(date + "Z").toISOString(),
          unit,
          bands: bands
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
        },
      );
      setSelected(null);
      setMessage("入库任务已排队；完成后可在文件列表查看状态，再发布数据集。");
      await refresh();
      onChanged();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setIngesting(false);
    }
  }
  return (
    <motion.div
      className="admin-dialog-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <motion.section
        className="admin-dialog file-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="file-dialog-title"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 8 }}
        onKeyDown={(e) => {
          if (e.key === "Escape" && !busy) onClose();
          if (e.key === "Tab") {
            const elements = Array.from(
              e.currentTarget.querySelectorAll<HTMLElement>(
                "button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href]",
              ),
            );
            if (e.shiftKey && document.activeElement === elements[0]) {
              e.preventDefault();
              elements.at(-1)?.focus();
            } else if (
              !e.shiftKey &&
              document.activeElement === elements.at(-1)
            ) {
              e.preventDefault();
              elements[0]?.focus();
            }
          }
        }}
      >
        <header>
          <div>
            <span className="admin-eyebrow">{cid}</span>
            <h2 id="file-dialog-title">{title} · 文件</h2>
          </div>
          <button
            autoFocus
            className="icon-button"
            aria-label="关闭文件管理"
            onClick={onClose}
            disabled={busy}
          >
            <Icon name="x" />
          </button>
        </header>
        <div
          className="file-upload-zone"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            const file = event.dataTransfer.files[0];
            if (file) void upload(file);
          }}
        >
          <Icon name="upload" />
          <div>
            <b>上传数据文件</b>
            <p>
              拖入或选择文件 · 单文件最多 512 MiB · 支持分块续传与 SHA-256 校验
            </p>
            <small>
              GeoTIFF 可标准化入库；NetCDF、CSV、GeoJSON、JSON 可先存储和下载。
            </small>
          </div>
          <label className="file-button">
            <input
              ref={input}
              type="file"
              aria-label="上传数据文件"
              accept=".tif,.tiff,.nc,.csv,.geojson,.json"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void upload(file);
              }}
            />
            选择文件
          </label>
        </div>
        {(busy || message) && (
          <div className="file-progress">
            <span role="status">{message}</span>
            {busy && (
              <>
                <progress max={100} value={progress} />
                <span>{Math.round(progress)}%</span>
                <button onClick={() => control.current?.abort()}>暂停</button>
              </>
            )}
          </div>
        )}
        {(error || loadError) && (
          <p className="error" role="alert">
            {error || loadError}
          </p>
        )}
        <div className="file-section-heading">
          <h3>
            上传文件 <span>{fileTotal}</span>
          </h3>
          <button
            onClick={() =>
              void refresh().catch((e) => setError(errorMessage(e)))
            }
          >
            <Icon name="refresh" />
            刷新
          </button>
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>文件</th>
                <th>大小</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.id}>
                  <td>
                    <b>{file.filename}</b>
                    <small title={file.sha256}>
                      SHA-256 {file.sha256.slice(0, 16)}…
                    </small>
                    {file.error && (
                      <small className="error">{file.error}</small>
                    )}
                  </td>
                  <td>{sizeLabel(file.size)}</td>
                  <td>
                    <span
                      className={
                        "admin-badge " +
                        (file.status === "ready" ? "positive" : "")
                      }
                    >
                      {labels[file.status] ?? file.status}
                    </span>
                    {file.status === "uploading" && (
                      <small>
                        {Math.round((file.received / file.size) * 100)}% ·
                        选择同一文件继续
                      </small>
                    )}
                  </td>
                  <td className="file-actions">
                    {[
                      "stored",
                      "queued",
                      "processing",
                      "ready",
                      "error",
                    ].includes(file.status) && (
                      <a
                        href={`${base}/uploads/${encodeURIComponent(file.id)}/download`}
                        download={file.filename}
                      >
                        <Icon name="download" />
                        下载原件
                      </a>
                    )}
                    {["stored", "error"].includes(file.status) &&
                      /\.tiff?$/i.test(file.filename) && (
                        <button
                          disabled={busy}
                          onClick={() => {
                            setSelected(file);
                            setUnit(file.options?.unit ?? "");
                            setBands(file.options?.bands?.join(", ") ?? "");
                          }}
                        >
                          配置入库
                        </button>
                      )}
                  </td>
                </tr>
              ))}
              {!files.length && (
                <tr>
                  <td colSpan={4} className="file-empty">
                    {loading ? "正在读取文件…" : "尚未上传文件"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="admin-pagination">
          <span>上传文件第 {filePage} 页 · 每页 50 个</span>
          <button
            disabled={filePage === 1}
            onClick={() => setFilePage(filePage - 1)}
          >
            前一页文件
          </button>
          <button
            disabled={!moreFiles}
            onClick={() => setFilePage(filePage + 1)}
          >
            后一页文件
          </button>
        </div>
        {selected && (
          <form
            key={selected.id}
            className="file-ingest-form"
            onSubmit={(event) => void submitIngest(event)}
          >
            <h3>配置入库 · {selected.filename}</h3>
            <div className="file-ingest-grid">
              <label>
                观测时间（UTC）
                <input
                  type="datetime-local"
                  name="observation_datetime"
                  required
                  defaultValue={selected.options?.datetime?.slice(0, 16) ?? ""}
                />
              </label>
              <label>
                物理单位
                <input
                  required
                  maxLength={64}
                  placeholder="例如 1、m、K、mm"
                  value={unit}
                  onChange={(e) => setUnit(e.target.value)}
                />
              </label>
              <label>
                波段名（按文件顺序，可选）
                <input
                  placeholder="用英文逗号分隔；留空读取文件描述"
                  value={bands}
                  onChange={(e) => setBands(e.target.value)}
                />
              </label>
            </div>
            <p>
              入库会应用原文件 scale/offset，保留掩膜并标准化为 float32
              COG；不自动去云。精度变化写入影像处理记录。已有数据集须保持相同波段和单位。
            </p>
            <div>
              <button type="button" onClick={() => setSelected(null)}>
                取消
              </button>
              <button className="primary" type="submit" disabled={ingesting}>
                校验并入库
              </button>
            </div>
          </form>
        )}
        <div className="file-section-heading">
          <h3>已入库影像资产</h3>
          <small>包括供应方同步和本地上传的 COG</small>
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>影像 / 波段</th>
                <th>观测时间</th>
                <th>版本状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.item_id + asset.band}>
                  <td>
                    <b>{asset.band}.tif</b>
                    <small>{asset.item_id}</small>
                  </td>
                  <td>{asset.datetime}</td>
                  <td>
                    <span
                      className={
                        "admin-badge " + (asset.active ? "positive" : "")
                      }
                    >
                      {asset.active ? "当前版本" : "保留旧版"}
                    </span>
                  </td>
                  <td>
                    <a
                      className="file-download"
                      href={`${base}/datasets/${encodeURIComponent(cid)}/assets/${encodeURIComponent(asset.item_id)}/${encodeURIComponent(asset.band)}/download`}
                      download
                    >
                      <Icon name="download" />
                      下载 COG
                    </a>
                  </td>
                </tr>
              ))}
              {!assets.length && (
                <tr>
                  <td colSpan={4} className="file-empty">
                    暂无入库资产
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <footer>
          <span>资产第 {assetPage} 页</span>
          <button
            disabled={assetPage === 1}
            onClick={() => setAssetPage(assetPage - 1)}
          >
            上一页
          </button>
          <button
            disabled={!hasMore}
            onClick={() => setAssetPage(assetPage + 1)}
          >
            下一页
          </button>
          <button
            disabled={busy}
            onClick={() => {
              onChanged();
              onClose();
            }}
          >
            完成
          </button>
        </footer>
      </motion.section>
    </motion.div>
  );
}
