import type { FormEvent } from "react";
import type { StoredFile } from "./models";

export default function IngestForm({
  selected,
  unit,
  bands,
  ingesting,
  onUnitChange,
  onBandsChange,
  onCancel,
  onSubmit,
}: {
  selected: StoredFile;
  unit: string;
  bands: string;
  ingesting: boolean;
  onUnitChange: (unit: string) => void;
  onBandsChange: (bands: string) => void;
  onCancel: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form
      key={selected.id}
      className="file-ingest-form"
      onSubmit={(event) => onSubmit(event)}
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
            onChange={(event) => onUnitChange(event.target.value)}
          />
        </label>
        <label>
          波段名（按文件顺序，可选）
          <input
            placeholder="用英文逗号分隔；留空读取文件描述"
            value={bands}
            onChange={(event) => onBandsChange(event.target.value)}
          />
        </label>
      </div>
      <p>
        入库会应用原文件 scale/offset，保留掩膜并标准化为 float32
        COG；不自动去云。精度变化写入影像处理记录。已有数据集须保持相同波段和单位。
      </p>
      <div>
        <button type="button" onClick={onCancel}>
          取消
        </button>
        <button className="primary" type="submit" disabled={ingesting}>
          校验并入库
        </button>
      </div>
    </form>
  );
}
