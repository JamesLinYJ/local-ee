import Icon from "../../components/Icon";
import {
  fileDownloadUrl,
  formatSize,
  statusLabels,
  type StoredFile,
} from "./models";

export default function StoredFilesTable({
  files,
  loading,
  busy,
  total,
  page,
  more,
  onRefresh,
  onPageChange,
  onIngest,
}: {
  files: StoredFile[];
  loading: boolean;
  busy: boolean;
  total: number;
  page: number;
  more: boolean;
  onRefresh: () => void;
  onPageChange: (page: number) => void;
  onIngest: (file: StoredFile) => void;
}) {
  return (
    <>
      <div className="file-section-heading">
        <h3>
          上传文件 <span>{total}</span>
        </h3>
        <button onClick={onRefresh}>
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
                  {file.error && <small className="error">{file.error}</small>}
                </td>
                <td>{formatSize(file.size)}</td>
                <td>
                  <span
                    className={
                      "admin-badge " +
                      (file.status === "ready" ? "positive" : "")
                    }
                  >
                    {statusLabels[file.status] ?? file.status}
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
                    <a href={fileDownloadUrl(file.id)} download={file.filename}>
                      <Icon name="download" />
                      下载原件
                    </a>
                  )}
                  {["stored", "error"].includes(file.status) &&
                    /\.tiff?$/i.test(file.filename) && (
                      <button disabled={busy} onClick={() => onIngest(file)}>
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
        <span>上传文件第 {page} 页 · 每页 50 个</span>
        <button disabled={page === 1} onClick={() => onPageChange(page - 1)}>
          前一页文件
        </button>
        <button disabled={!more} onClick={() => onPageChange(page + 1)}>
          后一页文件
        </button>
      </div>
    </>
  );
}
