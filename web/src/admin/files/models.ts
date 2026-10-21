export interface StoredFile {
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

export interface Asset {
  item_id: string;
  band: string;
  datetime: string;
  active: boolean;
  metadata: { "file:size"?: number };
}

export const apiBase = "/workbench/admin/v1";

export const statusLabels: Record<string, string> = {
  uploading: "上传未完成",
  stored: "已存储",
  queued: "等待入库",
  processing: "正在入库",
  ready: "已入库",
  error: "入库失败",
  canceled: "已取消",
};

export function formatSize(size: number) {
  return size >= 1024 ** 2
    ? (size / 1024 ** 2).toFixed(1) + " MiB"
    : (size / 1024).toFixed(1) + " KiB";
}

export const fileDownloadUrl = (id: string) =>
  `${apiBase}/uploads/${encodeURIComponent(id)}/download`;

export const assetDownloadUrl = (
  collectionId: string,
  itemId: string,
  band: string,
) =>
  `${apiBase}/datasets/${encodeURIComponent(collectionId)}/assets/${encodeURIComponent(itemId)}/${encodeURIComponent(band)}/download`;
