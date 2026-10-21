import Icon from "../components/Icon";
import type { Job, Language } from "../types";

interface HeaderProps {
  user: string;
  canManage: boolean;
  connected: boolean;
  connectionError: string;
  search: string;
  onSearchChange: (value: string) => void;
  onSearchFocus: () => void;
  onLogout: () => void;
}

interface StatusBarProps {
  onShowTasks: () => void;
  collectionCount: number;
  jobs: Job[];
  language: Language;
}

export function WorkbenchHeader({
  user,
  canManage,
  connected,
  connectionError,
  search,
  onSearchChange,
  onSearchFocus,
  onLogout,
}: HeaderProps) {
  return (
    <header className="top">
      <div className="brand">
        <span className="brand-mark">
          <Icon name="layers" />
        </span>
        <b>遥感工作台</b>
      </div>
      <div className="global-search">
        <Icon name="search" />
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          onFocus={onSearchFocus}
          placeholder="搜索本地数据集…"
          aria-label="搜索本地数据集"
        />
        <kbd>本地目录</kbd>
      </div>
      <div className="top-right">
        {canManage && (
          <a className="admin-entry" href="/?view=admin">
            管理中心
          </a>
        )}
        <span
          title={connectionError}
          className={"connection-state" + (!connected ? " offline" : "")}
        >
          <i />
          {connected
            ? "服务已连接"
            : connectionError
              ? "重新连接中"
              : "正在连接"}
        </span>
        <span className="account-avatar">{user.slice(0, 1).toUpperCase()}</span>
        <span className="account-name">{user}</span>
        <button
          className="icon-button"
          onClick={onLogout}
          aria-label="退出账号"
          title="退出"
        >
          <Icon name="logout" />
        </button>
      </div>
    </header>
  );
}

export function WorkbenchStatusBar({
  onShowTasks,
  collectionCount,
  jobs,
  language,
}: StatusBarProps) {
  const runningCount = jobs.filter((job) =>
    ["queued", "running"].includes(job.status),
  ).length;
  const exportCount = jobs.filter((job) => job.status === "created").length;

  return (
    <footer className="status-bar">
      <span>
        <i className="local-indicator" />
        本地工作区
      </span>
      <span>{collectionCount} 个数据集</span>
      <button onClick={onShowTasks}>
        {runningCount} 个运行中
        {exportCount ? " · " + exportCount + " 个导出待启动" : ""}
      </button>
      <span className="status-right">
        {language === "javascript"
          ? "Earth Engine JS · 本地适配"
          : "openEO · GeoTrellis"}
      </span>
    </footer>
  );
}
