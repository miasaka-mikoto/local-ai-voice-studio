import { useMemo, useState } from "react";
import { useStudio } from "../StudioContext";
import { Icon } from "../components/Icon";
import { Badge, Button, EmptyState, PageHeader, Panel } from "../components/ui";
import { actionLabel, jobStatusLabel, jobStatusTone, relativeTime } from "../lib/format";
import type { JobStatus } from "../types";

const statusOptions: ("all" | JobStatus)[] = ["all", "running", "queued", "paused", "failed", "stale", "completed", "cancelled"];

export const TasksPage = () => {
  const { snapshot, actOnJob, operation } = useStudio();
  const [status, setStatus] = useState<"all" | JobStatus>("all");
  const [query, setQuery] = useState("");
  const jobs = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (snapshot?.jobs ?? []).filter((job) =>
      (status === "all" || job.status === status) &&
      (!normalized || `${job.label} ${job.stage} ${job.error ?? ""}`.toLowerCase().includes(normalized)),
    );
  }, [query, snapshot, status]);

  return (
    <>
      <PageHeader eyebrow="Recoverable queue" title="任务队列" description="排队、暂停、失败与过期任务都保留可解释状态和允许的恢复动作。" />
      <Panel className="toolbar-panel">
        <div className="search-box"><Icon name="search" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务、阶段或错误…" aria-label="搜索任务" /></div>
        <div className="filter-pills filter-pills--compact">
          {statusOptions.map((option) => <button key={option} type="button" className={status === option ? "is-active" : ""} onClick={() => setStatus(option)}>{option === "all" ? "全部" : jobStatusLabel[option]}</button>)}
        </div>
      </Panel>
      <Panel padded={false} className="table-panel">
        {jobs.length ? (
          <div className="task-list">
            <div className="task-list__header"><span>任务</span><span>阶段 / 进度</span><span>状态</span><span>更新时间</span><span>操作</span></div>
            {jobs.map((job) => (
              <article className="task-item" key={job.id}>
                <div className="task-item__identity">
                  <span className={`task-icon task-icon--${job.status}`}><Icon name={job.status === "failed" ? "alert" : job.status === "completed" ? "check" : job.status === "paused" ? "pause" : "activity"} /></span>
                  <div><strong>{job.label}</strong><small>{job.kind} · 尝试 {job.attempt}{job.engineId ? ` · ${job.engineId}` : ""}</small></div>
                </div>
                <div className="task-item__stage"><span>{job.stage}</span><div><div className="progress-track"><i style={{ width: `${job.progress}%` }} /></div><em>{job.progress}%</em></div>{job.error ? <small className="task-error"><Icon name="alert" size={13} />{job.error}</small> : null}</div>
                <div><Badge tone={jobStatusTone(job.status)} dot>{jobStatusLabel[job.status]}</Badge></div>
                <time>{relativeTime(job.updatedAt)}</time>
                <div className="task-item__actions">
                  {job.allowedActions.map((action) => <Button key={action} tone={action === "cancel" ? "ghost" : "default"} size="sm" icon={action === "pause" ? "pause" : action === "cancel" ? "close" : "retry"} busy={operation === "更新任务"} onClick={() => void actOnJob(job.id, action)}>{actionLabel[action]}</Button>)}
                  {!job.allowedActions.length ? <span className="muted">无需操作</span> : null}
                </div>
              </article>
            ))}
          </div>
        ) : <EmptyState icon="tasks" title="没有符合条件的任务" description="调整筛选或搜索词；历史任务不会被自动删除。" />}
      </Panel>
      <div className="info-strip"><Icon name="info" /><div><strong>任务恢复语义</strong><span>运行中任务可暂停或取消；失败任务重试会增加 attempt；上游改变后的 stale 任务只重新计算受影响产物。</span></div></div>
    </>
  );
};
