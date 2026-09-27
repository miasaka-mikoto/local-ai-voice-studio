import { useMemo, useState, type PropsWithChildren } from "react";
import { useStudio } from "../StudioContext";
import { navigate, type AppRoute } from "../lib/navigation";
import { Icon, type IconName } from "./Icon";
import { Badge, Button } from "./ui";

const navigation: { page: AppRoute["page"]; label: string; icon: IconName; group?: string }[] = [
  { page: "projects", label: "项目首页", icon: "grid", group: "工作台" },
  { page: "tasks", label: "任务队列", icon: "tasks" },
  { page: "library", label: "角色与声音", icon: "users" },
  { page: "japanese", label: "日语会话", icon: "message", group: "学习" },
  { page: "shadowing", label: "影子跟读", icon: "waveform" },
  { page: "system", label: "系统与模型", icon: "activity", group: "管理" },
];

const routeFromPage = (page: AppRoute["page"]): AppRoute => {
  if (page === "projects") return { page };
  if (page === "tasks") return { page };
  if (page === "library") return { page };
  if (page === "japanese") return { page };
  if (page === "shadowing") return { page };
  return { page: "system" };
};

export const AppShell = ({ children, activePage }: PropsWithChildren<{ activePage: AppRoute["page"] }>) => {
  const { snapshot, connectionMode, config, operation, refresh } = useStudio();
  const [mobileOpen, setMobileOpen] = useState(false);
  const activeJobs = useMemo(
    () => snapshot?.jobs.filter((job) => ["queued", "running", "paused"].includes(job.status)).length ?? 0,
    [snapshot],
  );

  const go = (page: AppRoute["page"]) => {
    navigate(routeFromPage(page));
    setMobileOpen(false);
  };

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileOpen ? "is-open" : ""}`}>
        <div className="brand">
          <span className="brand__mark"><Icon name="waveform" size={23} /></span>
          <div><strong>Voice Studio</strong><small>LOCAL PRODUCTION</small></div>
        </div>
        <nav className="sidebar__nav" aria-label="主导航">
          {navigation.map((item, index) => (
            <div key={item.page}>
              {item.group ? <div className={`nav-group ${index ? "nav-group--spaced" : ""}`}>{item.group}</div> : null}
              <button className={activePage === item.page ? "is-active" : ""} type="button" onClick={() => go(item.page)}>
                <Icon name={item.icon} />
                <span>{item.label}</span>
                {item.page === "tasks" && activeJobs ? <em>{activeJobs}</em> : null}
              </button>
            </div>
          ))}
        </nav>
        <div className="sidebar__footer">
          <div className="resource-mini">
            <div><span>GPU 安全状态</span><strong>{snapshot?.system.gpuScheduler === "blocked" ? "已阻止" : "受控"}</strong></div>
            <div className="resource-mini__bar"><i style={{ width: `${snapshot ? Math.min(100, snapshot.system.gpuUsedMb / snapshot.system.gpuTotalMb * 100) : 0}%` }} /></div>
            <small>{snapshot ? `${snapshot.system.gpuUsedMb} / ${snapshot.system.gpuTotalMb} MiB` : "等待状态"}</small>
          </div>
          <a href="http://127.0.0.1:7860" target="_blank" rel="noreferrer" className="lab-link">
            <Icon name="external" size={15} /><span>打开 7860 模型实验台</span>
          </a>
        </div>
      </aside>
      {mobileOpen ? <button type="button" className="sidebar-scrim" aria-label="关闭导航" onClick={() => setMobileOpen(false)} /> : null}
      <div className="app-main">
        <header className="topbar">
          <button type="button" className="icon-button mobile-menu" aria-label="打开导航" onClick={() => setMobileOpen(true)}><Icon name="menu" /></button>
          <div className="topbar__crumb"><span>Local AI Voice Studio</span><i>/</i><strong>{navigation.find((item) => item.page === activePage)?.label ?? "项目"}</strong></div>
          <div className="topbar__actions">
            <Badge tone={connectionMode === "api" ? "success" : connectionMode === "mock" ? "warning" : "danger"} dot>
              {connectionMode === "api" ? "API 已连接" : connectionMode === "mock" ? "本地 MOCK" : "未连接"}
            </Badge>
            <span className="api-address" title={config.apiBaseUrl}>{config.apiBaseUrl.replace(/^https?:\/\//, "")}</span>
            <Button tone="ghost" size="sm" icon="refresh" busy={operation === "同步最新状态"} onClick={() => void refresh()}>同步</Button>
          </div>
        </header>
        <main className="page-content">{children}</main>
      </div>
    </div>
  );
};
