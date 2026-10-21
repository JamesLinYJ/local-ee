export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//"))
    throw new Error("API 只允许同源路径");
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal,
  });
  if (!response.ok) {
    let message = await response.text();
    try {
      const data: unknown = JSON.parse(message);
      if (
        data &&
        typeof data === "object" &&
        "message" in data &&
        typeof data.message === "string"
      )
        message = data.message;
    } catch {
      /* Non-JSON gateway errors are bounded below. */
    }
    throw new ApiError(
      response.status,
      response.status >= 500
        ? "服务暂时不可用，请稍后重试。已提交的任务会保留。"
        : response.status === 401
          ? "账号或密码错误，或登录已过期"
          : `${response.status}: ${message.slice(0, 400)}`,
    );
  }
  return response.status === 204
    ? (undefined as T)
    : (response.json() as Promise<T>);
}
export const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
export const assetUrl = (jid: string, name: string, kind = "files") =>
  `/workbench/jobs/${encodeURIComponent(jid)}/${kind}/${encodeURIComponent(name)}`;
