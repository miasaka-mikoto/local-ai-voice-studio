import { useEffect, useMemo, useState } from "react";
import { useStudio } from "../StudioContext";
import { Icon } from "../components/Icon";
import { Badge, Button, Field, PageHeader, Panel, Segmented } from "../components/ui";
import type { RuntimeConfig } from "../types";

const riskTone = (risk: "low" | "review" | "restricted") => risk === "low" ? "success" : risk === "review" ? "warning" : "danger";

export const SystemPage = () => {
  const { snapshot, config, connectionMode, connectionNotice, reconnect, resetMock, operation } = useStudio();
  const [draftBase, setDraftBase] = useState(config.apiBaseUrl);
  const [draftMode, setDraftMode] = useState<RuntimeConfig["requestedMode"]>(config.requestedMode);
  const [showTechnical, setShowTechnical] = useState(false);

  useEffect(() => {
    setDraftBase(config.apiBaseUrl);
    setDraftMode(config.requestedMode);
  }, [config]);

  const gpuPercent = snapshot ? Math.round(snapshot.system.gpuUsedMb / snapshot.system.gpuTotalMb * 100) : 0;
  const ramPercent = snapshot ? Math.round((1 - snapshot.system.ramAvailableGb / snapshot.system.ramTotalGb) * 100) : 0;
  const licenseCounts = useMemo(() => ({
    low: snapshot?.engines.filter((engine) => engine.licenseRisk === "low").length ?? 0,
    review: snapshot?.engines.filter((engine) => engine.licenseRisk === "review").length ?? 0,
    restricted: snapshot?.engines.filter((engine) => engine.licenseRisk === "restricted").length ?? 0,
  }), [snapshot]);

  return (
    <>
      <PageHeader
        eyebrow="Local runtime"
        title="系统、模型与诊断"
        description="这里仅显示部署和运行状态。任何模型启动都必须由用户在 7860 实验台显式执行。"
        actions={<a className="button button--default button--md" href="http://127.0.0.1:7860" target="_blank" rel="noreferrer"><Icon name="external" size={17} /><span>打开模型实验台</span></a>}
      />

      <div className="system-alert system-alert--danger"><Icon name="alert" /><div><strong>当前禁止真实模型加载</strong><span>{connectionMode === "mock" ? "以下资源数字是 Mock 种子快照，不代表机器实时遥测。" : `API 报告 GPU 已使用约 ${snapshot?.system.gpuUsedMb ?? "—"} / ${snapshot?.system.gpuTotalMb ?? "—"} MiB，系统可用内存约 ${snapshot?.system.ramAvailableGb ?? "—"} GB。`} 本前端只执行 Mock 与轻量验证。</span></div></div>

      <div className="system-grid">
        <Panel className="runtime-card">
          <div className="panel-heading"><div><h2>运行资源{connectionMode === "mock" ? " · Mock 快照" : ""}</h2><p>{snapshot?.system.gpuName ?? "等待后端状态"}</p></div><Badge tone={connectionMode === "mock" ? "warning" : snapshot?.system.gpuScheduler === "blocked" ? "danger" : "success"} dot>{connectionMode === "mock" ? "非实时遥测" : snapshot?.system.gpuScheduler === "blocked" ? "GPU 调度已阻止" : "GPU 调度可用"}</Badge></div>
          <div className="resource-row"><div><span>显存使用</span><strong>{gpuPercent}%</strong></div><div className="resource-bar resource-bar--danger"><i style={{ width: `${gpuPercent}%` }} /></div><small>{snapshot?.system.gpuUsedMb ?? 0} / {snapshot?.system.gpuTotalMb ?? 0} MiB</small></div>
          <div className="resource-row"><div><span>系统内存使用</span><strong>{ramPercent}%</strong></div><div className="resource-bar resource-bar--warning"><i style={{ width: `${ramPercent}%` }} /></div><small>可用 {snapshot?.system.ramAvailableGb ?? 0} / {snapshot?.system.ramTotalGb ?? 0} GB</small></div>
          <div className="runtime-facts"><div><Icon name="database" /><span>SQLite</span><strong>{snapshot?.system.databaseReady ? "就绪" : "不可用"}</strong></div><div><Icon name="waveform" /><span>FFmpeg</span><strong>{snapshot?.system.ffmpegReady ? "就绪" : "不可用"}</strong></div><div><Icon name="file" /><span>数据盘剩余</span><strong>{snapshot?.system.diskFreeGb ?? "—"} GB</strong></div></div>
        </Panel>

        <Panel className="connection-card">
          <div className="panel-heading"><div><h2>工作台 API</h2><p>8765 已被其他本机服务占用，Voice Studio 默认使用 8766。</p></div><Badge tone={connectionMode === "api" ? "success" : "warning"} dot>{connectionMode === "api" ? "真实 API" : "本地 MOCK"}</Badge></div>
          <div className="connection-form">
            <Field label="API 基址" hint="仅允许本机地址；默认 http://127.0.0.1:8766"><input value={draftBase} onChange={(event) => setDraftBase(event.target.value)} spellCheck={false} /></Field>
            <Field label="数据模式"><Segmented label="数据模式" value={draftMode} options={[{ value: "auto", label: "自动" }, { value: "api", label: "仅 API" }, { value: "mock", label: "仅 Mock" }]} onChange={(value) => setDraftMode(value as RuntimeConfig["requestedMode"])} /></Field>
            <div className="connection-form__actions"><Button tone="primary" icon="refresh" busy={operation === "同步最新状态"} onClick={() => void reconnect({ apiBaseUrl: draftBase, requestedMode: draftMode })}>保存并重连</Button>{connectionMode === "mock" ? <Button tone="ghost" icon="retry" onClick={() => void resetMock()}>重置 Mock 基线</Button> : null}</div>
          </div>
          {connectionNotice ? <div className="inline-notice"><Icon name="info" /><span>{connectionNotice}</span></div> : null}
          <button className="technical-toggle" type="button" onClick={() => setShowTechnical((value) => !value)}><Icon name="chevron" className={showTechnical ? "is-rotated" : ""} />{showTechnical ? "收起" : "查看"}连接契约</button>
          {showTechnical ? <pre className="contract-box">{`GET  ${draftBase}/api/v1/health\nGET  ${draftBase}/api/v1/bootstrap\nWS   ${draftBase.replace("http", "ws")}/api/v1/ws/tasks\n\nVITE_API_BASE_URL=${draftBase}\nVITE_DATA_MODE=${draftMode}`}</pre> : null}
        </Panel>
      </div>

      <div className="section-heading"><div><h2>统一引擎注册表</h2><p>部署验证与运行状态分开显示；本页不会自动启动、停止或探测重型模型。</p></div><div className="license-summary"><Badge tone="success">{licenseCounts.low} 低风险</Badge><Badge tone="warning">{licenseCounts.review} 需审查</Badge><Badge tone="danger">{licenseCounts.restricted} 有限制</Badge></div></div>
      <Panel padded={false} className="engine-table-wrap">
        <div className="engine-table">
          <div className="engine-table__header"><span>引擎</span><span>能力</span><span>部署</span><span>运行</span><span>许可证</span><span>采样率</span></div>
          {snapshot?.engines.map((engine) => (
            <article key={engine.id}>
              <div className="engine-name"><span><Icon name="waveform" /></span><div><strong>{engine.name}</strong><small>{engine.id}</small><p>{engine.role}</p></div></div>
              <div className="capability-list">{engine.capabilities.slice(0, 3).map((capability) => <span key={capability}>{capability}</span>)}</div>
              <div><Badge tone={engine.deploymentStatus === "validated" ? "success" : "info"}>{engine.deploymentStatus}</Badge></div>
              <div><Badge tone={engine.runtimeStatus === "running" ? "success" : engine.runtimeStatus === "unreachable" ? "danger" : "neutral"} dot>{engine.runtimeStatus === "running" ? "运行中" : engine.runtimeStatus === "stopped" ? "未运行" : engine.runtimeStatus === "unknown" ? "未知" : "不可达"}</Badge></div>
              <div className="license-cell"><Badge tone={riskTone(engine.licenseRisk)}>{engine.licenseRisk === "low" ? "低风险" : engine.licenseRisk === "review" ? "需审查" : "商用受限"}</Badge><small>{engine.license}</small></div>
              <div>{engine.sampleRate ? `${engine.sampleRate / 1000} kHz` : "—"}</div>
            </article>
          ))}
        </div>
      </Panel>
      <div className="system-notes">
        <Panel><span className="note-icon note-icon--warning"><Icon name="alert" /></span><div><h3>Seed-VC GPL-3.0</h3><p>集成方式和分发边界需要许可证审查，不直接复制到可能闭源的核心。</p></div></Panel>
        <Panel><span className="note-icon note-icon--danger"><Icon name="lock" /></span><div><h3>IndexTTS2 / MaskGCT</h3><p>默认 MaskGCT 依赖含 CC BY-NC 4.0，商业产物必须阻止或替换后重新验证。</p></div></Panel>
        <Panel><span className="note-icon"><Icon name="database" /></span><div><h3>密钥与诊断</h3><p>外部 API 密钥只从环境或本机密钥存储读取；日志和诊断包必须脱敏。</p></div></Panel>
      </div>
    </>
  );
};
