import { useMemo, useState } from "react";
import { Refine } from "@refinedev/core";
import Icon from "../components/Icon";
import {
  adminResources,
  authProvider,
  dataProvider,
  roleNames,
} from "./providers";
import type { Resource, Session } from "./providers";
import ResourcePage from "./panels/ResourcePage";
import "./admin.css";

export default function AdminApp({
  session,
  onLogout,
}: {
  session: Session;
  onLogout: () => Promise<void>;
}) {
  const auth = useMemo(() => authProvider(onLogout), [onLogout]);
  const available = adminResources.filter((resource) =>
    session.permissions.includes(resource.permission),
  );
  const [resource, setResource] = useState<Resource>(
    available[0]?.name ?? "datasets",
  );

  if (!available.length)
    return (
      <div className="workbench admin-denied">
        <Icon name="lock" />
        <h1>没有管理权限</h1>
        <a href="/">返回工作台</a>
      </div>
    );

  return (
    <Refine
      dataProvider={dataProvider}
      authProvider={auth}
      resources={available.map((item) => ({
        name: item.name,
        meta: { label: item.label },
      }))}
      accessControlProvider={{
        can: async ({ resource: name }) => ({
          can: available.some((item) => item.name === name),
        }),
      }}
      options={{
        disableTelemetry: true,
        mutationMode: "pessimistic",
        reactQuery: {
          clientConfig: {
            defaultOptions: {
              queries: { retry: false, refetchOnWindowFocus: true },
            },
          },
        },
      }}
    >
      <div className="workbench admin-shell">
        <AdminHeader session={session} onLogout={onLogout} />
        <div className="admin-body">
          <AdminNavigation
            available={available}
            current={resource}
            onSelect={setResource}
          />
          <section className="admin-content">
            <ResourcePage
              key={resource}
              resource={resource}
              session={session}
            />
          </section>
        </div>
      </div>
    </Refine>
  );
}

function AdminHeader({
  session,
  onLogout,
}: {
  session: Session;
  onLogout: () => Promise<void>;
}) {
  return (
    <header className="top">
      <a className="brand" href="/">
        <span className="brand-mark">
          <Icon name="layers" />
        </span>
        <b>遥感工作台</b>
      </a>
      <span className="admin-header-label">管理中心</span>
      <div className="top-right">
        <a className="admin-back" href="/">
          返回工作台 <Icon name="arrow" />
        </a>
        <span className="account-name">{session.user}</span>
        <span className="admin-role">{roleNames[session.role]}</span>
        <button
          className="icon-button"
          aria-label="退出账号"
          onClick={() => void onLogout()}
        >
          <Icon name="logout" />
        </button>
      </div>
    </header>
  );
}

function AdminNavigation({
  available,
  current,
  onSelect,
}: {
  available: (typeof adminResources)[number][];
  current: Resource;
  onSelect: (resource: Resource) => void;
}) {
  return (
    <aside className="admin-nav">
      <p>工作区管理</p>
      {available.map((item) => (
        <button
          key={item.name}
          aria-current={current === item.name ? "page" : undefined}
          onClick={() => onSelect(item.name)}
        >
          <Icon name={resourceIcon(item.name)} />
          {item.label}
        </button>
      ))}
      <div className="admin-nav-foot">本地工作区</div>
    </aside>
  );
}

function resourceIcon(resource: Resource) {
  return resource === "datasets"
    ? "layers"
    : resource === "users"
      ? "lock"
      : resource === "jobs"
        ? "clock"
        : "book";
}
