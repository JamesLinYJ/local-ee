export type Language = "python" | "javascript";
export type JobStatus =
  "created" | "queued" | "running" | "finished" | "error" | "canceled";
export type Json =
  null | boolean | number | string | Json[] | { [key: string]: Json };
export interface Collection {
  id: string;
  title?: string;
  "cube:dimensions"?: { bands?: { values?: string[] } };
}
export interface Script {
  id: string;
  user_id: string;
  title: string;
  code: string;
  shared: boolean;
  language: Language;
  updated: string;
}
export interface Example {
  name: string;
  code: string;
  language: Language;
}
export interface VisParams {
  bands?: string[];
  min?: number | number[];
  max?: number | number[];
  gamma?: number | number[];
  palette?: string[];
}
export type MapEvent =
  | { type: "map_clear" }
  | { type: "map_view"; bounds?: number[]; center?: number[]; zoom?: number }
  | {
      type: "map_layer";
      job_id: string;
      name: string;
      vis_params: VisParams;
      shown: boolean;
      opacity: number;
    };
export interface Job {
  id: string;
  kind: "script" | "batch" | "ingest";
  title: string;
  status: JobStatus;
  created: string;
  error: string | null;
  language: Language;
  events: MapEvent[];
  assets: Record<string, { type: string; "file:size": number }>;
  context: Record<string, Json>;
}
export interface LogResult {
  logs: string;
  status: JobStatus;
  error: string | null;
}
export interface RasterInfo {
  bounds: number[];
  bands: number;
  crs: string;
  width: number;
  height: number;
  nodata: string;
}
export interface RasterLayer extends RasterInfo {
  id: string;
  name: string;
  jid: string;
  file: string;
  visible: boolean;
  vis?: VisParams;
}
export interface Snippet {
  code: string;
  language: Language;
}
export interface ReferenceEntry {
  id: string;
  category?: string;
  title: string;
  text: string;
  code?: string;
  language?: Language;
}
export interface ProcessNode {
  process_id: string;
  arguments: Record<string, Json>;
  result?: boolean;
  description?: string;
}
export type ProcessGraph = Record<string, ProcessNode>;
export interface ProcessSpec {
  id: string;
  description: string;
  parameters: {
    name: string;
    description: string;
    optional?: boolean;
    default?: Json;
    schema: Json;
  }[];
  returns?: { description: string; schema: Json };
}
export const statusLabels: Record<JobStatus, string> = {
  created: "已创建",
  queued: "排队中",
  running: "运行中",
  finished: "已完成",
  error: "失败",
  canceled: "已取消",
};
export const isActive = (job: Job) =>
  ["created", "queued", "running"].includes(job.status);
