import { useMemo, useState, type FormEvent } from "react";
import { useStudio } from "../StudioContext";
import { Icon } from "../components/Icon";
import { Badge, Button, EmptyState, Field, Metric, Modal, PageHeader, Panel } from "../components/ui";
import { jobStatusLabel, jobStatusTone, projectKindLabel, projectKindShort, relativeTime } from "../lib/format";
import { navigate } from "../lib/navigation";
import type { CreateProjectInput, ProjectKind } from "../types";

const kindAccent: Record<ProjectKind, string> = {
  video_dubbing: "teal",
  game_voice: "purple",
  voice_dataset: "amber",
  japanese_learning: "blue",
};

export const ProjectsPage = () => {
  const { snapshot, createProject, operation } = useStudio();
  const [createOpen, setCreateOpen] = useState(false);
  const [filter, setFilter] = useState<"all" | ProjectKind>("all");
  const [form, setForm] = useState<CreateProjectInput>({
    name: "",
    kind: "video_dubbing",
    description: "",
    locale: "zh-CN",
  });

  const projects = useMemo(
    () => snapshot?.projects.filter((project) => filter === "all" || project.kind === filter) ?? [],
    [filter, snapshot],
  );
  const activeJobs = snapshot?.jobs.filter((job) => ["queued", "running", "paused"].includes(job.status)) ?? [];
  const failedJobs = snapshot?.jobs.filter((job) => job.status === "failed").length ?? 0;
  const selected = snapshot?.projects.reduce((sum, project) => sum + project.selectedTakeCount, 0) ?? 0;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.name.trim()) return;
    const projectId = await createProject(form);
    if (projectId) {
      setCreateOpen(false);
      setForm({ name: "", kind: "video_dubbing", description: "", locale: "zh-CN" });
      navigate({ page: "workspace", projectId });
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Production workspace"
        title="今天要推进哪个项目？"
        description="项目、台词、候选 take 与任务状态都会持久化。Gradio 继续作为模型实验台独立运行。"
        actions={<Button tone="primary" icon="plus" onClick={() => setCreateOpen(true)}>新建项目</Button>}
      />

      <div className="metrics-grid">
        <Metric label="进行中的项目" value={snapshot?.projects.filter((project) => project.status === "active").length ?? 0} detail={`共 ${snapshot?.projects.length ?? 0} 个持久化项目`} icon="grid" />
        <Metric label="可恢复任务" value={activeJobs.length} detail="重启后从检查点同步" icon="tasks" accent="amber" />
        <Metric label="已选候选" value={selected} detail="人工选择不会被自动覆盖" icon="check" accent="purple" />
        <Metric label="需要处理" value={failedJobs} detail={failedJobs ? "失败任务有明确恢复动作" : "当前没有失败任务"} icon="alert" accent="blue" />
      </div>

      <div className="section-heading">
        <div><h2>项目</h2><p>四种项目共享同一套持久化、角色、任务与导出内核。</p></div>
        <div className="filter-pills" role="group" aria-label="项目类型筛选">
          <button type="button" className={filter === "all" ? "is-active" : ""} onClick={() => setFilter("all")}>全部</button>
          {(Object.keys(projectKindLabel) as ProjectKind[]).map((kind) => (
            <button type="button" key={kind} className={filter === kind ? "is-active" : ""} onClick={() => setFilter(kind)}>{projectKindShort[kind]}</button>
          ))}
        </div>
      </div>

      {projects.length ? (
        <div className="project-grid">
          {projects.map((project) => (
            <button className="project-card" type="button" key={project.id} onClick={() => navigate({ page: "workspace", projectId: project.id })}>
              <div className="project-card__top">
                <span className={`project-kind project-kind--${kindAccent[project.kind]}`}><Icon name={project.kind === "japanese_learning" ? "message" : project.kind === "voice_dataset" ? "database" : "waveform"} /></span>
                <Badge tone={project.status === "active" ? "success" : project.status === "blocked" ? "danger" : "neutral"} dot>{project.status === "active" ? "进行中" : project.status === "draft" ? "草稿" : project.status}</Badge>
              </div>
              <div className="project-card__body">
                <small>{projectKindLabel[project.kind]}</small>
                <h3>{project.name}</h3>
                <p>{project.description || "尚未添加项目说明。"}</p>
              </div>
              <div className="project-card__progress">
                <div><span>整体进度</span><strong>{project.progress}%</strong></div>
                <div className="progress-track"><i style={{ width: `${project.progress}%` }} /></div>
              </div>
              <footer>
                <span>{project.lineCount} 句台词</span><span>{project.selectedTakeCount} 已选</span><span>{relativeTime(project.updatedAt)}</span><Icon name="arrow" size={16} />
              </footer>
            </button>
          ))}
        </div>
      ) : (
        <Panel><EmptyState icon="grid" title="没有符合筛选的项目" description="新建一个项目，或切换筛选条件。" action={<Button tone="primary" icon="plus" onClick={() => setCreateOpen(true)}>新建项目</Button>} /></Panel>
      )}

      <div className="dashboard-lower">
        <Panel className="recent-jobs">
          <div className="panel-heading"><div><h2>正在恢复与运行</h2><p>操作来自任务状态机，不会在刷新时丢失。</p></div><Button tone="ghost" size="sm" onClick={() => navigate({ page: "tasks" })}>查看全部 <Icon name="arrow" size={14} /></Button></div>
          {activeJobs.length ? activeJobs.slice(0, 4).map((job) => (
            <div className="job-row" key={job.id}>
              <span className="job-row__icon"><Icon name={job.status === "running" ? "activity" : job.status === "paused" ? "pause" : "tasks"} /></span>
              <div className="job-row__main"><strong>{job.label}</strong><small>{job.stage}</small></div>
              <div className="job-row__progress"><div className="progress-track"><i style={{ width: `${job.progress}%` }} /></div><span>{job.progress}%</span></div>
              <Badge tone={jobStatusTone(job.status)}>{jobStatusLabel[job.status]}</Badge>
            </div>
          )) : <EmptyState icon="check" title="队列空闲" description="创建生成或导出任务后会在这里显示。" />}
        </Panel>
        <Panel className="safety-panel">
          <div className="panel-heading"><div><h2>本机安全边界</h2><p>当前开发会话只运行轻量前端验证。</p></div><span className="safety-panel__shield"><Icon name="lock" /></span></div>
          <ul className="check-list">
            <li><Icon name="check" /><span><strong>7860 保持运行</strong><small>模型实验台未被修改或停止</small></span></li>
            <li><Icon name="check" /><span><strong>API 默认 8766</strong><small>避开已被其他本机服务占用的 8765</small></span></li>
            <li><Icon name="check" /><span><strong>GPU 模型禁用</strong><small>mock 明确标识，不伪造真实生成</small></span></li>
            <li><Icon name="check" /><span><strong>所有服务只绑定本机</strong><small>127.0.0.1，不创建公网分享</small></span></li>
          </ul>
        </Panel>
      </div>

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="创建新项目"
        description="项目类型决定初始工作流，之后仍共享角色、任务和资产能力。"
        footer={<><Button tone="ghost" onClick={() => setCreateOpen(false)}>取消</Button><Button tone="primary" onClick={() => void submit(new Event("submit") as unknown as FormEvent)} busy={operation === "创建项目"} disabled={!form.name.trim()}>创建并进入</Button></>}
      >
        <form className="form-grid" onSubmit={submit}>
          <Field label="项目名称" className="span-2"><input autoFocus value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：雨夜电车 · 第 02 话" /></Field>
          <Field label="项目类型"><select value={form.kind} onChange={(event) => {
            const kind = event.target.value as ProjectKind;
            setForm({ ...form, kind, locale: kind === "japanese_learning" ? "ja-JP" : form.locale });
          }}>{(Object.keys(projectKindLabel) as ProjectKind[]).map((kind) => <option key={kind} value={kind}>{projectKindLabel[kind]}</option>)}</select></Field>
          <Field label="主要语言"><select value={form.locale} onChange={(event) => setForm({ ...form, locale: event.target.value })}><option value="zh-CN">中文（简体）</option><option value="ja-JP">日语</option><option value="en-US">英语</option><option value="multilingual">多语言</option></select></Field>
          <Field label="项目说明" className="span-2"><textarea rows={3} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="说明素材来源、交付目标或当前阶段。" /></Field>
        </form>
      </Modal>
    </>
  );
};
