import { useState } from "react";
import { motion } from "motion/react";
import { errorMessage } from "../../lib/api";
import Icon from "../../components/Icon";
import { dataProvider } from "../providers";
import type { Resource } from "../providers";
import type { AdminRow } from "./models";
import RecordFields from "./RecordFields";

interface RecordFormProps {
  resource: Resource;
  row: AdminRow | "new";
  onClose: () => void;
  onSaved: (message: string) => Promise<void>;
}

export default function RecordForm({
  resource,
  row,
  onClose,
  onSaved,
}: RecordFormProps) {
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

  function save(event: React.FormEvent<HTMLFormElement>) {
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
      ? dataProvider.update({ resource, id: record.id, variables: values })
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
  }

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
        onKeyDown={(event) => {
          if (event.key === "Escape" && !busy) onClose();
          if (event.key === "Tab") {
            const elements = Array.from(
              event.currentTarget.querySelectorAll<HTMLElement>(
                "button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href]",
              ),
            );
            const first = elements[0],
              last = elements[elements.length - 1];
            if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last?.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first?.focus();
            }
          }
        }}
        onSubmit={save}
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
        <RecordFields
          dataset={dataset}
          record={record}
          id={id}
          setId={setId}
          title={title}
          setTitle={setTitle}
          description={description}
          setDescription={setDescription}
          license={license}
          setLicense={setLicense}
          role={role}
          setRole={setRole}
          enabled={enabled}
          setEnabled={setEnabled}
          password={password}
          setPassword={setPassword}
        />
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
