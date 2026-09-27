import { japaneseStages, scenarioById, type JapaneseStageId } from "../data/japaneseCurriculum";
import type { JapaneseLearningPathResponse, JapaneseProgressResponse } from "../lib/japaneseApi";
import { Badge, Panel } from "./ui";
import type { CSSProperties } from "react";

const metricLabels: Record<string, string> = {
  content: "内容",
  rhythm: "节奏",
  pitch: "音高",
};

const directionLabels: Record<string, string> = {
  improving: "上升",
  stable: "稳定",
  needs_attention: "需加强",
  insufficient_history: "样本不足",
  insufficient_evidence: "待采样",
};

export interface JapaneseLearningPathProps {
  path: JapaneseLearningPathResponse | null;
  progress: JapaneseProgressResponse | null;
  selectedStageId: JapaneseStageId;
  onStageChange(stageId: JapaneseStageId): void;
  onScenarioSelect(scenarioId: string): void;
  connectionMode: "api" | "mock";
}

export const JapaneseLearningPath = ({
  path,
  progress,
  selectedStageId,
  onStageChange,
  onScenarioSelect,
  connectionMode,
}: JapaneseLearningPathProps) => {
  const summary = path?.summary ?? {
    completed: 0,
    in_progress: 0,
    available: 20,
    locked: 18,
    total: 38,
    due_review_count: 0,
  };
  const curve = japaneseStages.map((stage) => {
    const actual = path?.curve.find((item) => item.stage_id === stage.id);
    return {
      ...stage,
      completed: actual?.completed ?? 0,
      total: actual?.total ?? (stage.id === "advanced_life" ? 8 : 10),
      ratio: actual?.ratio ?? 0,
    };
  });
  const recommendations = path?.recommendations ?? [
    {
      kind: "new_scenario",
      scenario_id: "station-ticket",
      title: "下一场：车站买票",
      reason: "Mock 路径建议；连接 API 后由持久化会话与到期复习决定。",
      evidence: {},
    },
  ];

  return (
    <Panel className="learning-path-panel">
      <div className="learning-path-panel__header">
        <div>
          <span className="learning-path-panel__eyebrow">ADAPTIVE LEARNING PATH</span>
          <h2>日语提升路径</h2>
          <p>场景完成、分项证据和间隔复习分开记录，不用单一总分制造“已掌握”的错觉。</p>
        </div>
        <Badge tone={connectionMode === "api" ? "success" : "warning"} dot>
          {connectionMode === "api" ? `持久化路径 · ${path?.placement_level ?? "N4"}` : "Mock 路径预览"}
        </Badge>
      </div>

      <div className="learning-curve" aria-label="N5 到 N1 学习阶段曲线">
        {curve.map((stage, index) => (
          <button
            type="button"
            key={stage.id}
            className={selectedStageId === stage.id ? "is-active" : ""}
            onClick={() => onStageChange(stage.id)}
            aria-pressed={selectedStageId === stage.id}
          >
            <span className="learning-curve__step">{index + 1}</span>
            <div>
              <small>{stage.levelRange}</small>
              <strong>{stage.title}</strong>
              <span>{stage.completed}/{stage.total} 场景</span>
            </div>
            <i style={{ "--stage-progress": `${Math.round(stage.ratio * 100)}%` } as CSSProperties} />
          </button>
        ))}
      </div>

      <div className="learning-path-grid">
        <div className="path-summary" aria-label="场景进度摘要">
          <div><strong>{summary.completed}</strong><span>已完成</span></div>
          <div><strong>{summary.in_progress}</strong><span>进行中</span></div>
          <div><strong>{summary.available}</strong><span>可练习</span></div>
          <div><strong>{summary.due_review_count}</strong><span>到期复习</span></div>
        </div>

        <div className="path-recommendations">
          <h3>今天先做什么</h3>
          {recommendations.slice(0, 3).map((recommendation, index) => {
            const scenario = recommendation.scenario_id ? scenarioById(recommendation.scenario_id) : undefined;
            return (
              <button
                type="button"
                key={`${recommendation.kind}-${recommendation.scenario_id ?? recommendation.review_id ?? index}`}
                disabled={!scenario}
                onClick={() => scenario && onScenarioSelect(scenario.id)}
              >
                <span>{recommendation.kind === "review" ? "复习" : recommendation.kind === "continue_scenario" ? "继续" : "新场景"}</span>
                <div><strong>{recommendation.title}</strong><small>{recommendation.reason}</small></div>
              </button>
            );
          })}
        </div>

        <div className="path-metrics">
          <h3>近期能力证据</h3>
          {Object.entries(metricLabels).map(([metric, label]) => {
            const evidence = progress?.metrics[metric];
            const percent = evidence?.recent_mean == null ? null : Math.round(evidence.recent_mean * 100);
            return (
              <div key={metric}>
                <span>{label}</span>
                <div className="quality-track"><i style={{ width: `${percent ?? 0}%` }} /></div>
                <strong>{percent == null ? "—" : `${percent}%`}</strong>
                <small>{directionLabels[evidence?.direction ?? "insufficient_evidence"] ?? evidence?.direction} · {evidence?.sample_count ?? 0} 样本</small>
              </div>
            );
          })}
        </div>
      </div>
      <p className="learning-path-policy">解锁依据：当前分级或已完成先修场景；推荐顺序：到期复习 → 未完成会话 → 当前级别新场景。完成率仅表示走完练习。</p>
    </Panel>
  );
};
