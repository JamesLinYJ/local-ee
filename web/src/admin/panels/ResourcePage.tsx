import { useState } from "react";
import { AnimatePresence } from "motion/react";
import { useList } from "@refinedev/core";
import { api, errorMessage } from "../../lib/api";
import Icon from "../../components/Icon";
import FileManager from "../FileManager";
import type { Resource, Session } from "../providers";
import { adminResources } from "../providers";
import type { AdminRow } from "./models";
import RecordForm from "./RecordForm";
import ResourceTable from "./ResourceTable";

const adminBase = "/workbench/admin/v1";

export default function ResourcePage({
  resource,
  session,
}: {
  resource: Resource;
  session: Session;
}) {
  const [fileDataset, setFileDataset] = useState<AdminRow | null>(null);
  const [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [draft, setDraft] = useState<AdminRow | "new" | null>(null),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const { query, result } = useList<AdminRow>({
    resource,
    pagination: { currentPage: page, pageSize: 20 },
    filters: [{ field: "q", operator: "contains", value: search }],
  });
  const label = adminResources.find((item) => item.name === resource)?.label;

  const mutate = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true);
    setNotice("");
    try {
      await action();
      setNotice(message);
      await query.refetch();
    } catch (reason) {
      setNotice(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const cancelJob = (row: AdminRow) =>
    void mutate(
      () =>
        api(
          `${adminBase}/jobs/${encodeURIComponent(row.id)}/cancel`,
          "POST",
          {},
        ),
      "任务已取消",
    );

  return (
    <>
      <div className="admin-title">
        <div>
          <span className="admin-eyebrow">管理中心 / {label}</span>
          <h1>{label}</h1>
          <p>{resourceDescription(resource)}</p>
        </div>
        {(resource === "datasets" || resource === "users") && (
          <button className="primary" onClick={() => setDraft("new")}>
            <Icon name="upload" />
            {resource === "datasets" ? "添加数据集" : "创建账号"}
          </button>
        )}
      </div>
      <div className="admin-toolbar">
        <label className="admin-search">
          <Icon name="search" />
          <input
            aria-label="搜索管理记录"
            placeholder={searchPlaceholder(resource)}
            value={search}
            maxLength={100}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
          />
        </label>
        <span>{result.total ?? 0} 条记录</span>
        <button
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          <Icon name="refresh" />
          刷新
        </button>
      </div>
      {notice && (
        <p className="admin-notice" role="status">
          {notice}
          <button aria-label="关闭操作提示" onClick={() => setNotice("")}>
            <Icon name="x" />
          </button>
        </p>
      )}
      <ResourceTable
        resource={resource}
        rows={result.data}
        loading={query.isLoading}
        fetching={busy}
        error={query.error}
        search={search}
        session={session}
        onCancel={cancelJob}
        onManage={setDraft}
        onFiles={setFileDataset}
        errorMessage={errorMessage}
      />
      <footer className="admin-pagination">
        <span>第 {page} 页 · 每页 20 条</span>
        <button
          disabled={page <= 1 || query.isFetching}
          onClick={() => setPage(page - 1)}
        >
          上一页
        </button>
        <button
          disabled={page * 20 >= (result.total ?? 0) || query.isFetching}
          onClick={() => setPage(page + 1)}
        >
          下一页
        </button>
      </footer>
      <AnimatePresence>
        {fileDataset && (
          <FileManager
            cid={fileDataset.id}
            title={fileDataset.metadata?.title ?? fileDataset.id}
            onClose={() => setFileDataset(null)}
            onChanged={() => void query.refetch()}
          />
        )}
        {draft !== null && (
          <RecordForm
            resource={resource}
            row={draft}
            onClose={() => setDraft(null)}
            onSaved={async (message) => {
              setDraft(null);
              setNotice(message);
              await query.refetch();
            }}
          />
        )}
      </AnimatePresence>
    </>
  );
}

function resourceDescription(resource: Resource) {
  return resource === "datasets"
    ? "维护目录信息与可用状态，入库后发布到工作台。"
    : resource === "users"
      ? "管理成员角色、账号状态和会话。"
      : resource === "jobs"
        ? "查看成员的任务状态与队列，按需取消任务。"
        : "查看服务端记录的管理操作与字段变更。";
}

function searchPlaceholder(resource: Resource) {
  return resource === "datasets"
    ? "按数据集 ID 搜索"
    : resource === "users"
      ? "搜索账号"
      : "搜索账号或记录";
}
