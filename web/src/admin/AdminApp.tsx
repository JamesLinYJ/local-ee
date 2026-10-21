import { useMemo, useState } from "react";
import { Refine, useList } from "@refinedev/core";
import { AnimatePresence, motion } from "motion/react";
import { api, errorMessage } from "../lib/api";
import Icon from "../components/Icon";
import {
  adminResources,
  authProvider,
  dataProvider,
  roleNames,
} from "./providers";
import type { Resource, Session } from "./providers";
import "./admin.css";
import FileManager from "./FileManager";

interface Row {
  id: string;
  enabled?: boolean;
  revision?: number;
  ready?: boolean;
  item_count?: number;
  metadata?: {
    title?: string;
    description?: string;
    license?: string;
    "cube:dimensions"?: { bands?: { values?: string[] } };
  };
  role?: string;
  user_id?: string;
  title?: string;
  status?: string;
  kind?: string;
  created?: string;
  actor?: string;
  action?: string;
  object_type?: string;
  object_id?: string;
  changes?: unknown;
}
const statusNames: Record<string, string> = {
  created: "待启动",
  queued: "排队中",
  running: "计算中",
  finished: "已完成",
  error: "失败",
  canceled: "已取消",
};
const time = (value?: string) =>
  value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
export default function AdminApp({
  session,
  onLogout,
}: {
  session: Session;
  onLogout: () => Promise<void>;
}) {
  const auth = useMemo(() => authProvider(onLogout), [onLogout]);
  const available = adminResources.filter((resource) =>
    session.permissions.includes(resource.permission),
  );
  const [resource, setResource] = useState<Resource>(
    available[0]?.name ?? "datasets",
  );
  if (!available.length)
    return (
      <div className="workbench admin-denied">
        <Icon name="lock" />
        <h1>没有管理权限</h1>
        <a href="/">返回工作台</a>
      </div>
    );
  return (
    <Refine
      dataProvider={dataProvider}
      authProvider={auth}
      resources={available.map((r) => ({
        name: r.name,
        meta: { label: r.label },
      }))}
      accessControlProvider={{
        can: async ({ resource: name }) => ({
          can: available.some((r) => r.name === name),
        }),
      }}
      options={{
        disableTelemetry: true,
        mutationMode: "pessimistic",
        reactQuery: {
          clientConfig: {
            defaultOptions: {
              queries: { retry: false, refetchOnWindowFocus: true },
            },
          },
        },
      }}
    >
      <div className="workbench admin-shell">
        <header className="top">
          <a className="brand" href="/">
            <span className="brand-mark">
              <Icon name="layers" />
            </span>
            <b>遥感工作台</b>
          </a>
          <span className="admin-header-label">管理中心</span>
          <div className="top-right">
            <a className="admin-back" href="/">
              返回工作台 <Icon name="arrow" />
            </a>
            <span className="account-name">{session.user}</span>
            <span className="admin-role">{roleNames[session.role]}</span>
            <button
              className="icon-button"
              aria-label="退出账号"
              onClick={() => void onLogout()}
            >
              <Icon name="logout" />
            </button>
          </div>
        </header>
        <div className="admin-body">
          <aside className="admin-nav">
            <p>工作区管理</p>
            {available.map((item) => (
              <button
                key={item.name}
                aria-current={resource === item.name ? "page" : undefined}
                onClick={() => setResource(item.name)}
              >
                <Icon
                  name={
                    item.name === "datasets"
                      ? "layers"
                      : item.name === "users"
                        ? "lock"
                        : item.name === "jobs"
                          ? "clock"
                          : "book"
                  }
                />
                {item.label}
              </button>
            ))}
            <div className="admin-nav-foot">本地工作区</div>
          </aside>
          <section className="admin-content">
            <ResourcePage
              key={resource}
              resource={resource}
              session={session}
            />
          </section>
        </div>
      </div>
    </Refine>
  );
}

function ResourcePage({
  resource,
  session,
}: {
  resource: Resource;
  session: Session;
}) {
  const [fileDataset, setFileDataset] = useState<Row | null>(null);
  const [page, setPage] = useState(1),
    [q, setQ] = useState(""),
    [draft, setDraft] = useState<Row | "new" | null>(null),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const { query, result } = useList<Row>({
    resource,
    pagination: { currentPage: page, pageSize: 20 },
    filters: [{ field: "q", operator: "contains", value: q }],
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
  return (
    <>
      <div className="admin-title">
        <div>
          <span className="admin-eyebrow">管理中心 / {label}</span>
          <h1>{label}</h1>
          <p>
            {resource === "datasets"
              ? "维护目录信息与可用状态，入库后发布到工作台。"
              : resource === "users"
                ? "管理成员角色、账号状态和会话。"
                : resource === "jobs"
                  ? "查看成员的任务状态与队列，按需取消任务。"
                  : "查看服务端记录的管理操作与字段变更。"}
          </p>
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
            placeholder={
              resource === "datasets"
                ? "按数据集 ID 搜索"
                : resource === "users"
                  ? "搜索账号"
                  : "搜索账号或记录"
            }
            value={q}
            maxLength={100}
            onChange={(e) => {
              setQ(e.target.value);
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
      {query.error ? (
        <p className="error" role="alert">
          {errorMessage(query.error)}
        </p>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                {(resource === "datasets"
                  ? ["数据集", "入库影像", "波段", "状态", "操作"]
                  : resource === "users"
                    ? ["账号", "角色", "状态", "创建时间", "操作"]
                    : resource === "jobs"
                      ? ["任务", "成员", "类型", "状态", "操作"]
                      : ["时间", "操作者", "操作", "对象", "变更"]
                ).map((name) => (
                  <th key={name}>{name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.data.map((row) => (
                <tr key={row.id}>
                  {resource === "datasets" ? (
                    <>
                      <td>
                        <b>{row.metadata?.title ?? row.id}</b>
                        <small>{row.id}</small>
                      </td>
                      <td>{row.item_count ?? 0} 景</td>
                      <td className="admin-bands">
                        {row.metadata?.["cube:dimensions"]?.bands?.values?.join(
                          " · ",
                        ) ?? "待入库"}
                      </td>
                      <td>
                        <span
                          className={
                            "admin-badge " + (row.enabled ? "positive" : "")
                          }
                        >
                          {row.enabled
                            ? "已发布"
                            : row.ready
                              ? "已下架"
                              : "草稿"}
                        </span>
                      </td>
                      <td>
                        <button onClick={() => setFileDataset(row)}>
                          文件
                        </button>{" "}
                        <button onClick={() => setDraft(row)}>管理</button>
                      </td>
                    </>
                  ) : resource === "users" ? (
                    <>
                      <td>
                        <b>{row.id}</b>
                        {row.id === session.user && <small>当前账号</small>}
                      </td>
                      <td>{roleNames[row.role ?? ""] ?? row.role}</td>
                      <td>
                        <span
                          className={
                            "admin-badge " + (row.enabled ? "positive" : "")
                          }
                        >
                          {row.enabled ? "启用" : "已停用"}
                        </span>
                      </td>
                      <td>{time(row.created)}</td>
                      <td>
                        <button onClick={() => setDraft(row)}>管理</button>
                      </td>
                    </>
                  ) : resource === "jobs" ? (
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
                            "admin-badge " +
                            (row.status === "running" ? "positive" : "")
                          }
                        >
                          {statusNames[row.status ?? ""] ?? row.status}
                        </span>
                      </td>
                      <td>
                        {["created", "queued", "running"].includes(
                          row.status ?? "",
                        ) ? (
                          <button
                            disabled={busy}
                            onClick={() =>
                              void mutate(
                                () =>
                                  api(
                                    `/workbench/admin/v1/jobs/${encodeURIComponent(row.id)}/cancel`,
                                    "POST",
                                    {},
                                  ),
                                "任务已取消",
                              )
                            }
                          >
                            取消任务
                          </button>
                        ) : (
                          "—"
                        )}
                      </td>
                    </>
                  ) : (
                    <>
                      <td>{time(row.created)}</td>
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
                  )}
                </tr>
              ))}
              {!result.data.length && (
                <tr>
                  <td colSpan={5} className="admin-empty">
                    {query.isLoading
                      ? "正在加载…"
                      : q
                        ? "没有符合条件的记录"
                        : "暂无记录"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
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

function RecordForm({
  resource,
  row,
  onClose,
  onSaved,
}: {
  resource: Resource;
  row: Row | "new";
  onClose: () => void;
  onSaved: (message: string) => Promise<void>;
}) {
  const record = row === "new" ? null : row;
  const [id, setId] = useState(record?.id ?? ""),
    [title, setTitle] = useState(record?.metadata?.title ?? ""),
    [description, setDescription] = useState(
      record?.metadata?.description ?? "",
    ),
    [license, setLicense] = useState(record?.metadata?.license ?? ""),
    [role, setRole] = useState(record?.role ?? "researcher"),
    [enabled, setEnabled] = useState(record?.enabled ?? true),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const dataset = resource === "datasets";
  return (
    <motion.div
      className="admin-dialog-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <motion.form
        className="admin-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="admin-dialog-title"
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
            const first = elements[0],
              last = elements[elements.length - 1];
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault();
              last?.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first?.focus();
            }
          }
        }}
        onSubmit={(event) => {
          event.preventDefault();
          if (busy) return;
          setBusy(true);
          setError("");
          const values = dataset
            ? {
                title,
                description,
                license,
                ...(record ? { enabled, revision: record.revision } : { id }),
              }
            : {
                role,
                ...(record ? { enabled } : { id }),
                ...(password ? { password } : {}),
              };
          const operation = record
            ? dataProvider.update({
                resource,
                id: record.id,
                variables: values,
              })
            : dataProvider.create({ resource, variables: values });
          void operation
            .then(async () => {
              setPassword("");
              await onSaved(
                dataset
                  ? record
                    ? "数据集信息已保存。"
                    : "目录草稿已创建；完成数据入库后才能发布。"
                  : "账号信息已保存，现有会话已撤销。",
              );
            })
            .catch((reason) => setError(errorMessage(reason)))
            .finally(() => setBusy(false));
        }}
      >
        <header>
          <div>
            <span className="admin-eyebrow">
              {dataset ? "数据目录" : "账号与权限"}
            </span>
            <h2 id="admin-dialog-title">
              {record ? "管理" : "添加"}
              {dataset ? "数据集" : "账号"}
            </h2>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭管理表单"
            disabled={busy}
            onClick={onClose}
          >
            <Icon name="x" />
          </button>
        </header>
        <label>
          {dataset ? "数据集 ID" : "账号"}
          <input
            autoFocus
            value={id}
            disabled={!!record}
            maxLength={dataset ? 96 : 64}
            required
            pattern={
              dataset
                ? "[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}"
                : "[a-zA-Z0-9_.-]{1,64}"
            }
            onChange={(event) => setId(event.target.value)}
          />
        </label>
        {dataset ? (
          <>
            <label>
              名称
              <input
                value={title}
                required
                maxLength={200}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <label>
              说明
              <textarea
                value={description}
                maxLength={4000}
                rows={4}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label>
              许可证
              <input
                value={license}
                required
                maxLength={200}
                placeholder="例如 CC-BY-4.0；受限数据请写 proprietary"
                onChange={(e) => setLicense(e.target.value)}
              />
            </label>
            {record ? (
              <>
                <label>
                  发布状态
                  <select
                    value={enabled ? "yes" : "no"}
                    onChange={(e) => setEnabled(e.target.value === "yes")}
                  >
                    <option value="no">下架 / 草稿</option>
                    <option value="yes" disabled={!record.ready}>
                      发布到工作台
                    </option>
                  </select>
                </label>
                <p className="admin-form-note">
                  {record.ready
                    ? "下架会阻止新的检索与任务，已有快照和结果保留。"
                    : "此目录尚未入库。完成文件校验和影像登记后才能发布。"}
                </p>
                <dl className="admin-metadata">
                  <dt>入库影像</dt>
                  <dd>{record.item_count} 景</dd>
                  <dt>版本</dt>
                  <dd>{record.revision}</dd>
                  <dt>波段</dt>
                  <dd>
                    {record.metadata?.["cube:dimensions"]?.bands?.values?.join(
                      ", ",
                    ) ?? "待入库"}
                  </dd>
                </dl>
              </>
            ) : (
              <p className="admin-form-note">
                先创建目录草稿；当前数据入库仍由受控同步工具执行。网页文件上传尚未接入，不会生成可用影像。
              </p>
            )}
          </>
        ) : (
          <>
            <label>
              角色
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {Object.entries(roleNames).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <p className="admin-form-note">
              数据管理员可以维护目录；研究员可以运行计算；只读成员不能提交或修改任务。
            </p>
            {record && (
              <label>
                账号状态
                <select
                  value={enabled ? "yes" : "no"}
                  onChange={(e) => setEnabled(e.target.value === "yes")}
                >
                  <option value="yes">启用</option>
                  <option value="no">停用</option>
                </select>
              </label>
            )}
            <label>
              {record ? "重设密码（留空则保留）" : "初始密码"}
              <input
                type="password"
                autoComplete="new-password"
                value={password}
                required={!record}
                minLength={12}
                maxLength={1024}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <p className="admin-form-note">
              停用账号会撤销会话并取消其待处理任务。系统至少保留一个启用的管理员。
            </p>
          </>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <footer>
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button type="submit" className="primary" disabled={busy}>
            {busy
              ? "保存中…"
              : record
                ? "保存修改"
                : dataset
                  ? "创建草稿"
                  : "创建账号"}
          </button>
        </footer>
      </motion.form>
    </motion.div>
  );
}
