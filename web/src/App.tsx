import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api, ApiError, errorMessage } from "./lib/api";
import Icon from "./components/Icon";
import type { Session } from "./admin/providers";
const Workbench = lazy(() => import("./Workbench"));
const GraphEditor = lazy(() => import("./components/GraphEditor"));
const AdminApp = lazy(() => import("./admin/AdminApp"));
export default function App() {
  const [user, setUser] = useState<Session | null>(null),
    [loading, setLoading] = useState(true),
    [username, setUsername] = useState("researcher"),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [submitting, setSubmitting] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void api<Session>("/workbench/me", "GET", undefined, controller.signal)
      .then((me) => setUser(me))
      .catch((reason) => {
        if (
          !controller.signal.aborted &&
          !(reason instanceof ApiError && reason.status === 401)
        )
          setError(errorMessage(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);
  const logout = useCallback(async () => {
    await api("/workbench/logout", "POST", {});
    setUser(null);
    setPassword("");
    setError("");
  }, []);
  if (loading)
    return (
      <div className="workbench loading-screen" role="status">
        <span className="loading-mark">
          <Icon name="layers" />
        </span>
        正在连接本地工作区…
      </div>
    );
  if (user)
    return new URLSearchParams(location.search).get("view") === "admin" ? (
      <Suspense
        fallback={
          <div className="workbench loading-screen">正在加载管理中心…</div>
        }
      >
        <AdminApp session={user} onLogout={logout} />
      </Suspense>
    ) : new URLSearchParams(location.search).get("editor") === "graph" ? (
      <Suspense
        fallback={
          <div className="workbench loading-screen">正在加载流程图编辑器…</div>
        }
      >
        <GraphEditor user={user.user} onLogout={logout} />
      </Suspense>
    ) : (
      <Suspense
        fallback={
          <div className="workbench loading-screen">正在加载工作台…</div>
        }
      >
        <Workbench
          user={user.user}
          canManage={
            user.permissions?.some((p) => p.endsWith(":manage")) ?? false
          }
          onLogout={logout}
        />
      </Suspense>
    );
  return (
    <div className="workbench">
      <header className="top">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="layers" />
          </span>
          <b>遥感工作台</b>
        </div>
      </header>
      <main className="login-page">
        <form
          className="login-card"
          onSubmit={(event) => {
            event.preventDefault();
            if (submitting) return;
            setSubmitting(true);
            void api<Session>("/workbench/login", "POST", {
              username,
              password,
            })
              .then((me) => {
                setPassword("");
                setUser(me);
                setError("");
              })
              .catch((reason) => setError(errorMessage(reason)))
              .finally(() => setSubmitting(false));
          }}
        >
          <span className="login-symbol">
            <Icon name="layers" />
          </span>
          <h1>登录工作台</h1>
          <label>
            账号
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            密码
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              autoComplete="current-password"
              required
            />
          </label>
          <button className="primary" disabled={submitting} type="submit">
            {submitting ? "登录中…" : "登录"}
            <Icon name="arrow" />
          </button>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </form>
      </main>
    </div>
  );
}
