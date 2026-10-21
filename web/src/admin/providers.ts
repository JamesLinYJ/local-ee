import type {
  AuthProvider,
  DataProvider,
  BaseRecord,
  GetListParams,
  GetListResponse,
  CreateParams,
  CreateResponse,
  UpdateParams,
  UpdateResponse,
} from "@refinedev/core";
import { api, ApiError } from "../lib/api";

export interface Session {
  user: string;
  role: string;
  permissions: string[];
}
export const adminResources = [
  { name: "datasets", label: "数据集", permission: "datasets:manage" },
  { name: "users", label: "用户与权限", permission: "users:manage" },
  { name: "jobs", label: "任务队列", permission: "jobs:manage" },
  { name: "audit", label: "操作记录", permission: "audit:read" },
] as const;
export type Resource = (typeof adminResources)[number]["name"];
const base = "/workbench/admin/v1";
function resourcePath(resource: string) {
  if (!adminResources.some((item) => item.name === resource))
    throw new Error("未知管理资源");
  return `${base}/${resource}`;
}
async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  try {
    return await api<T>(path, method, body);
  } catch (error) {
    if (error instanceof ApiError)
      Object.assign(error, { statusCode: error.status });
    throw error;
  }
}
export const dataProvider: DataProvider = {
  getApiUrl: () => base,
  async getList<T extends BaseRecord>({
    resource,
    pagination,
    filters,
  }: GetListParams): Promise<GetListResponse<T>> {
    const query = filters?.find((f) => "field" in f && f.field === "q");
    const params = new URLSearchParams({
      page: String(pagination?.currentPage ?? 1),
      page_size: String(pagination?.pageSize ?? 25),
      q: query && "value" in query ? String(query.value) : "",
    });
    return request(`${resourcePath(resource)}?${params}`);
  },
  async getOne() {
    throw new Error("请从已加载的管理列表选择记录");
  },
  async create<T extends BaseRecord, V>({
    resource,
    variables,
  }: CreateParams<V>): Promise<CreateResponse<T>> {
    return request(resourcePath(resource), "POST", variables);
  },
  async update<T extends BaseRecord, V>({
    resource,
    id,
    variables,
  }: UpdateParams<V>): Promise<UpdateResponse<T>> {
    return request(
      `${resourcePath(resource)}/${encodeURIComponent(id)}`,
      "PATCH",
      variables,
    );
  },
  async deleteOne() {
    throw new Error("管理模块保留研究数据，不提供物理删除");
  },
};
export function authProvider(onLogout: () => Promise<void>): AuthProvider {
  return {
    login: async () => ({ success: false, redirectTo: "/" }),
    logout: async () => {
      await onLogout();
      return { success: true };
    },
    check: async () => {
      try {
        await api<Session>("/workbench/me");
        return { authenticated: true };
      } catch {
        return { authenticated: false };
      }
    },
    getIdentity: () => api<Session>("/workbench/me"),
    getPermissions: async () =>
      (await api<Session>("/workbench/me")).permissions,
    onError: async () => ({}),
  };
}
export const roleNames: Record<string, string> = {
  admin: "管理员",
  dataset_manager: "数据管理员",
  researcher: "研究员",
  viewer: "只读成员",
};
