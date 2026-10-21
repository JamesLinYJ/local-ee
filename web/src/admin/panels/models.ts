export interface AdminRow {
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

export const statusNames: Record<string, string> = {
  created: "待启动",
  queued: "排队中",
  running: "计算中",
  finished: "已完成",
  error: "失败",
  canceled: "已取消",
};

export const formatAdminTime = (value?: string) =>
  value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
