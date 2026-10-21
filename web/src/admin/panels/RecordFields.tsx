import type { Dispatch, SetStateAction } from "react";
import { roleNames } from "../providers";
import type { AdminRow } from "./models";

interface RecordFieldsProps {
  dataset: boolean;
  record: AdminRow | null;
  id: string;
  setId: Dispatch<SetStateAction<string>>;
  title: string;
  setTitle: Dispatch<SetStateAction<string>>;
  description: string;
  setDescription: Dispatch<SetStateAction<string>>;
  license: string;
  setLicense: Dispatch<SetStateAction<string>>;
  role: string;
  setRole: Dispatch<SetStateAction<string>>;
  enabled: boolean;
  setEnabled: Dispatch<SetStateAction<boolean>>;
  password: string;
  setPassword: Dispatch<SetStateAction<string>>;
}

export default function RecordFields(props: RecordFieldsProps) {
  return (
    <>
      <label>
        {props.dataset ? "数据集 ID" : "账号"}
        <input
          autoFocus
          value={props.id}
          disabled={!!props.record}
          maxLength={props.dataset ? 96 : 64}
          required
          pattern={
            props.dataset
              ? "[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}"
              : "[a-zA-Z0-9_.-]{1,64}"
          }
          onChange={(event) => props.setId(event.target.value)}
        />
      </label>
      {props.dataset ? <DatasetFields {...props} /> : <UserFields {...props} />}
    </>
  );
}

function DatasetFields(props: RecordFieldsProps) {
  return (
    <>
      <label>
        名称
        <input
          value={props.title}
          required
          maxLength={200}
          onChange={(event) => props.setTitle(event.target.value)}
        />
      </label>
      <label>
        说明
        <textarea
          value={props.description}
          maxLength={4000}
          rows={4}
          onChange={(event) => props.setDescription(event.target.value)}
        />
      </label>
      <label>
        许可证
        <input
          value={props.license}
          required
          maxLength={200}
          placeholder="例如 CC-BY-4.0；受限数据请写 proprietary"
          onChange={(event) => props.setLicense(event.target.value)}
        />
      </label>
      {props.record ? (
        <>
          <label>
            发布状态
            <select
              value={props.enabled ? "yes" : "no"}
              onChange={(event) =>
                props.setEnabled(event.target.value === "yes")
              }
            >
              <option value="no">下架 / 草稿</option>
              <option value="yes" disabled={!props.record.ready}>
                发布到工作台
              </option>
            </select>
          </label>
          <p className="admin-form-note">
            {props.record.ready
              ? "下架会阻止新的检索与任务，已有快照和结果保留。"
              : "此目录尚未入库。完成文件校验和影像登记后才能发布。"}
          </p>
          <dl className="admin-metadata">
            <dt>入库影像</dt>
            <dd>{props.record.item_count} 景</dd>
            <dt>版本</dt>
            <dd>{props.record.revision}</dd>
            <dt>波段</dt>
            <dd>
              {props.record.metadata?.["cube:dimensions"]?.bands?.values?.join(
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
  );
}

function UserFields(props: RecordFieldsProps) {
  return (
    <>
      <label>
        角色
        <select
          value={props.role}
          onChange={(event) => props.setRole(event.target.value)}
        >
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
      {props.record && (
        <label>
          账号状态
          <select
            value={props.enabled ? "yes" : "no"}
            onChange={(event) => props.setEnabled(event.target.value === "yes")}
          >
            <option value="yes">启用</option>
            <option value="no">停用</option>
          </select>
        </label>
      )}
      <label>
        {props.record ? "重设密码（留空则保留）" : "初始密码"}
        <input
          type="password"
          autoComplete="new-password"
          value={props.password}
          required={!props.record}
          minLength={12}
          maxLength={1024}
          onChange={(event) => props.setPassword(event.target.value)}
        />
      </label>
      <p className="admin-form-note">
        停用账号会撤销会话并取消其待处理任务。系统至少保留一个启用的管理员。
      </p>
    </>
  );
}
