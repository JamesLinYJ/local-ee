import { useState } from "react";
import type { FormEvent } from "react";
import { api, errorMessage } from "../../lib/api";
import { apiBase, type StoredFile } from "./models";

export default function useFileIngest({
  refresh,
  onChanged,
  setMessage,
  setError,
}: {
  refresh: () => Promise<void>;
  onChanged: () => void;
  setMessage: (message: string) => void;
  setError: (message: string) => void;
}) {
  const [selected, setSelected] = useState<StoredFile | null>(null);
  const [unit, setUnit] = useState("");
  const [bands, setBands] = useState("");
  const [ingesting, setIngesting] = useState(false);

  function select(file: StoredFile) {
    setSelected(file);
    setUnit(file.options?.unit ?? "");
    setBands(file.options?.bands?.join(", ") ?? "");
  }

  async function submitIngest(
    event: FormEvent<HTMLFormElement>,
  ): Promise<void> {
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
        `${apiBase}/uploads/${encodeURIComponent(selected.id)}/ingest`,
        "POST",
        {
          datetime: new Date(date + "Z").toISOString(),
          unit,
          bands: bands
            .split(",")
            .map((band) => band.trim())
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

  return {
    selected,
    setSelected,
    select,
    unit,
    setUnit,
    bands,
    setBands,
    ingesting,
    submitIngest,
  };
}
