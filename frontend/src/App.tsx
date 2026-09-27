import { useEffect, useState } from "react";
import { AppShell } from "./components/AppShell";
import { Icon } from "./components/Icon";
import { Badge, Button, Panel } from "./components/ui";
import { useStudio } from "./StudioContext";
import { useAppRoute } from "./lib/navigation";
import { JapanesePage } from "./pages/JapanesePage";
import { LibraryPage } from "./pages/LibraryPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ShadowingPage } from "./pages/ShadowingPage";
import { SystemPage } from "./pages/SystemPage";
import { TasksPage } from "./pages/TasksPage";
import { WorkspacePage } from "./pages/WorkspacePage";

const BootScreen = () => (
  <div className="boot-screen">
    <div className="boot-logo"><Icon name="waveform" size={31} /></div>
    <h1>Local AI Voice Studio</h1>
    <p>正在连接本机项目内核并恢复任务状态…</p>
    <div className="boot-progress"><i /></div>
    <small>只连接 127.0.0.1，不会自动加载模型</small>
  </div>
);

const ConnectionRecovery = () => {
  const { error, technicalError, config, reconnect } = useStudio();
  const [base, setBase] = useState(config.apiBaseUrl);
  const [showDetails, setShowDetails] = useState(false);
  return (
    <div className="recovery-screen">
      <div className="recovery-brand"><span><Icon name="waveform" /></span><strong>Local AI Voice Studio</strong></div>
      <Panel className="recovery-card">
        <span className="recovery-card__icon"><Icon name="alert" size={26} /></span>
        <div className="eyebrow">Connection required</div>
        <h1>工作台 API 暂不可达</h1>
        <p>{error ?? "无法载入项目数据。"}</p>
        <label className="field"><span className="field__label">API 基址</span><input value={base} onChange={(event) => setBase(event.target.value)} spellCheck={false} /></label>
        <div className="recovery-actions"><Button tone="primary" icon="refresh" onClick={() => void reconnect({ apiBaseUrl: base, requestedMode: "api" })}>重试真实 API</Button>{config.mockAllowed ? <Button icon="database" onClick={() => void reconnect({ apiBaseUrl: base, requestedMode: "mock" })}>明确进入本地 Mock</Button> : null}</div>
        <div className="recovery-safety"><Icon name="lock" /><span>Mock 数据只保存在当前浏览器，不运行模型，也不会修改真实项目数据库。</span></div>
        <button className="technical-toggle" type="button" onClick={() => setShowDetails((value) => !value)}><Icon name="chevron" className={showDetails ? "is-rotated" : ""} />{showDetails ? "隐藏" : "查看"}技术详情</button>
        {showDetails ? <pre className="contract-box">{technicalError ?? "没有附加错误信息。"}</pre> : null}
      </Panel>
      <small>Voice Studio 后端默认端口 8766 · 7860 模型实验台保持独立运行</small>
    </div>
  );
};

export default function App() {
  const route = useAppRoute();
  const { loading, snapshot, error, connectionMode, connectionNotice, operation, toast, dismissToast } = useStudio();

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(dismissToast, 3600);
    return () => window.clearTimeout(timeout);
  }, [dismissToast, toast]);

  if (loading && !snapshot) return <BootScreen />;
  if (error && !snapshot) return <ConnectionRecovery />;

  const page = (() => {
    if (route.page === "workspace") return <WorkspacePage projectId={route.projectId} />;
    if (route.page === "tasks") return <TasksPage />;
    if (route.page === "library") return <LibraryPage />;
    if (route.page === "japanese") return <JapanesePage />;
    if (route.page === "shadowing") return <ShadowingPage />;
    if (route.page === "system") return <SystemPage />;
    return <ProjectsPage />;
  })();

  return (
    <AppShell activePage={route.page === "workspace" ? "projects" : route.page}>
      {connectionNotice ? <div className={`connection-banner connection-banner--${connectionMode}`}><Icon name={connectionMode === "mock" ? "info" : "check"} /><span>{connectionNotice}</span>{connectionMode === "mock" ? <Badge tone="warning">无真实模型</Badge> : null}</div> : null}
      {page}
      {operation ? <div className="global-operation"><span className="button__spinner" /><strong>{operation}</strong><small>请保持此页面打开</small></div> : null}
      {toast ? <div className={`toast toast--${toast.tone}`} role="status"><Icon name={toast.tone === "success" ? "check" : toast.tone === "danger" ? "alert" : "info"} /><span>{toast.message}</span><button type="button" onClick={dismissToast} aria-label="关闭提示"><Icon name="close" size={15} /></button></div> : null}
    </AppShell>
  );
}
