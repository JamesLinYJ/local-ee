import { roleNames } from "../providers";
import type { Session } from "../providers";
import { formatAdminTime, statusNames } from "./models";
import type { AdminRow } from "./models";

export function DatasetCells({
  row,
  onFiles,
  onManage,
}: {
  row: AdminRow;
  onFiles: (row: AdminRow) => void;
  onManage: (row: AdminRow) => void;
}) {
  return (
    <>
      <td>
        <b>{row.metadata?.title ?? row.id}</b>
        <small>{row.id}</small>
      </td>
      <td>{row.item_count ?? 0} 景</td>
      <td className="admin-bands">
        {row.metadata?.["cube:dimensions"]?.bands?.values?.join(" · ") ??
          "待入库"}
      </td>
      <td>
        <span className={"admin-badge " + (row.enabled ? "positive" : "")}>
          {row.enabled ? "已发布" : row.ready ? "已下架" : "草稿"}
        </span>
      </td>
      <td>
        <button onClick={() => onFiles(row)}>文件</button>{" "}
        <button onClick={() => onManage(row)}>管理</button>
      </td>
    </>
  );
}

export function UserCells({
  row,
  session,
  onManage,
}: {
  row: AdminRow;
  session: Session;
  onManage: (row: AdminRow) => void;
}) {
  return (
    <>
      <td>
        <b>{row.id}</b>
        {row.id === session.user && <small>当前账号</small>}
      </td>
      <td>{roleNames[row.role ?? ""] ?? row.role}</td>
      <td>
        <span className={"admin-badge " + (row.enabled ? "positive" : "")}>
          {row.enabled ? "启用" : "已停用"}
        </span>
      </td>
      <td>{formatAdminTime(row.created)}</td>
      <td>
        <button onClick={() => onManage(row)}>管理</button>
      </td>
    </>
  );
}

export function JobCells({
  row,
  fetching,
  onCancel,
}: {
  row: AdminRow;
  fetching: boolean;
  onCancel: (row: AdminRow) => void;
}) {
  const active = ["created", "queued", "running"].includes(row.status ?? "");
  return (
    <>
      <td>
        <b>{row.title}</b>
        <small>{row.id}</small>
      </td>
      <td>{row.user_id}</td>
      <td>
        {row.kind === "script"
          ? "脚本"
          : row.kind === "ingest"
            ? "数据入库"
            : "计算"}
      </td>
      <td>
        <span
          className={
            "admin-badge " + (row.status === "running" ? "positive" : "")
          }
        >
          {statusNames[row.status ?? ""] ?? row.status}
        </span>
      </td>
      <td>
        {active ? (
          <button disabled={fetching} onClick={() => onCancel(row)}>
            取消任务
          </button>
        ) : (
          "—"
        )}
      </td>
    </>
  );
}

export function AuditCells({ row }: { row: AdminRow }) {
  return (
    <>
      <td>{formatAdminTime(row.created)}</td>
      <td>{row.actor}</td>
      <td>
        <code>{row.action}</code>
      </td>
      <td>
        <b>{row.object_id}</b>
        <small>{row.object_type}</small>
      </td>
      <td>
        <details>
          <summary>查看变更</summary>
          <pre>{JSON.stringify(row.changes, null, 2)}</pre>
        </details>
      </td>
    </>
  );
}
