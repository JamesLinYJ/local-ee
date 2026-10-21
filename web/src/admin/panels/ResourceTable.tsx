import type { AdminRow } from "./models";
import type { Resource, Session } from "../providers";
import { AuditCells, DatasetCells, JobCells, UserCells } from "./ResourceRows";

interface ResourceTableProps {
  resource: Resource;
  rows: AdminRow[];
  loading: boolean;
  fetching: boolean;
  error: unknown;
  search: string;
  session: Session;
  onCancel: (row: AdminRow) => void;
  onManage: (row: AdminRow) => void;
  onFiles: (row: AdminRow) => void;
  errorMessage: (error: unknown) => string;
}

export default function ResourceTable({
  resource,
  rows,
  loading,
  fetching,
  error,
  search,
  session,
  onCancel,
  onManage,
  onFiles,
  errorMessage,
}: ResourceTableProps) {
  if (error)
    return (
      <p className="error" role="alert">
        {errorMessage(error)}
      </p>
    );

  const headings =
    resource === "datasets"
      ? ["数据集", "入库影像", "波段", "状态", "操作"]
      : resource === "users"
        ? ["账号", "角色", "状态", "创建时间", "操作"]
        : resource === "jobs"
          ? ["任务", "成员", "类型", "状态", "操作"]
          : ["时间", "操作者", "操作", "对象", "变更"];

  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead>
          <tr>
            {headings.map((name) => (
              <th key={name}>{name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              {resource === "datasets" ? (
                <DatasetCells row={row} onFiles={onFiles} onManage={onManage} />
              ) : resource === "users" ? (
                <UserCells row={row} session={session} onManage={onManage} />
              ) : resource === "jobs" ? (
                <JobCells row={row} fetching={fetching} onCancel={onCancel} />
              ) : (
                <AuditCells row={row} />
              )}
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={5} className="admin-empty">
                {loading
                  ? "正在加载…"
                  : search
                    ? "没有符合条件的记录"
                    : "暂无记录"}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
