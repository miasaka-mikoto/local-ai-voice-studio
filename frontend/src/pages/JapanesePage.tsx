import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useStudio } from "../StudioContext";
import { companionStateFromConversation, DigitalCompanion } from "../components/DigitalCompanion";
import { Icon } from "../components/Icon";
import { JapaneseLearningPath } from "../components/JapaneseLearningPath";
import { Badge, Button, EmptyState, PageHeader, Panel, Segmented } from "../components/ui";
import {
  japaneseDomainLabels,
  japaneseScenarios,
  japaneseStages,
  scenarioById,
  type JapaneseStageId,
} from "../data/japaneseCurriculum";
import { playAudioOrSpeech } from "../lib/audio";
import { relativeTime } from "../lib/format";
import {
  clearStoredJapaneseSession,
  JapaneseLearningApi,
  apiTurnToUiTurns,
  ensureJapaneseSession,
  readStoredJapaneseLearner,
  readStoredJapaneseSession,
  type JapaneseLearningPathResponse,
  type JapaneseProgressResponse,
  type JapaneseTurnResponse,
} from "../lib/japaneseApi";
import { useRecorder } from "../lib/useRecorder";
import type { ConversationTurn } from "../types";

export { japaneseScenarios } from "../data/japaneseCurriculum";

export const JapanesePage = () => {
  const {
    snapshot,
    addConversationTurn,
    operation,
    connectionMode,
    config,
    reconnect,
  } = useStudio();
  const [scenario, setScenario] = useState("station-ticket");
  const [selectedStageId, setSelectedStageId] = useState<JapaneseStageId>("foundation");
  const [domainFilter, setDomainFilter] = useState("all");
  const [scenarioQuery, setScenarioQuery] = useState("");
  const [coachMode, setCoachMode] = useState<"flow" | "strict">("flow");
  const [draft, setDraft] = useState("");
  const [phase, setPhase] = useState<"idle" | "uploading" | "transcribing" | "thinking" | "playing" | "error">("idle");
  const [apiTurns, setApiTurns] = useState<ConversationTurn[]>([]);
  const [lastApiTurn, setLastApiTurn] = useState<JapaneseTurnResponse | null>(null);
  const [apiSessionId, setApiSessionId] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [learningPath, setLearningPath] = useState<JapaneseLearningPathResponse | null>(null);
  const [progress, setProgress] = useState<JapaneseProgressResponse | null>(null);
  const [mockCompletedScenarios, setMockCompletedScenarios] = useState<Set<string>>(() => new Set());
  const [completingScenario, setCompletingScenario] = useState(false);
  const playbackTimerRef = useRef<number | null>(null);
  const recorder = useRecorder();
  const api = useMemo(() => new JapaneseLearningApi(config.apiBaseUrl), [config.apiBaseUrl]);
  const selectedScenario = scenarioById(scenario) ?? japaneseScenarios[0];
  const filteredScenarios = useMemo(() => japaneseScenarios.filter((item) => {
    if (item.stageId !== selectedStageId) return false;
    if (domainFilter !== "all" && item.domain !== domainFilter) return false;
    const query = scenarioQuery.trim().toLocaleLowerCase();
    if (!query) return true;
    return `${item.title} ${item.japaneseTitle} ${item.goal}`.toLocaleLowerCase().includes(query);
  }), [domainFilter, scenarioQuery, selectedStageId]);
  const pathScenarioById = useMemo(() => new Map(
    learningPath?.stages.flatMap((stage) => stage.scenarios).map((item) => [item.id, item]) ?? [],
  ), [learningPath]);
  const completedTurnCount = connectionMode === "api"
    ? apiTurns.filter((turn) => turn.role === "learner").length
    : Math.floor((snapshot?.conversations.length ?? 0) / 2);
  const turns = connectionMode === "api" ? apiTurns : snapshot?.conversations ?? [];
  const latestFeedback = useMemo(() => [...turns].reverse().find((turn) => turn.feedback), [turns]);
  const latestTeacherTurn = useMemo(() => [...turns].reverse().find((turn) => turn.role === "teacher"), [turns]);
  const companionState = companionStateFromConversation({
    phase,
    recorderStatus: recorder.status,
    hasError: Boolean(apiError || recorder.error),
  });
  const companionEmotion = {
    idle: "放松",
    listening: "专注",
    thinking: "认真",
    speaking: "元气",
    error: "担心",
  }[companionState];
  const companionSubtitle = companionState === "listening"
    ? "うん、聞いているよ。ゆっくり話してね。"
    : companionState === "thinking"
      ? "ちょっと待って。今の言い方を整理しているよ。"
      : companionState === "error"
        ? "大丈夫。録音は残して、もう一度試してみよう。"
        : latestTeacherTurn?.text ?? selectedScenario.greeting;

  const selectScenario = useCallback((scenarioId: string) => {
    const next = scenarioById(scenarioId);
    if (!next) return;
    setScenario(next.id);
    setSelectedStageId(next.stageId);
    setApiError(null);
  }, []);

  const refreshLearningData = useCallback(async () => {
    if (connectionMode !== "api") {
      setLearningPath(null);
      setProgress(null);
      return;
    }
    const learnerId = readStoredJapaneseLearner(api.baseUrl);
    if (!learnerId) return;
    try {
      const [nextPath, nextProgress] = await Promise.all([
        api.learningPath(learnerId),
        api.progress(learnerId),
      ]);
      setLearningPath(nextPath);
      setProgress(nextProgress);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "无法读取日语学习路径。 ");
    }
  }, [api, connectionMode]);

  useEffect(() => {
    void refreshLearningData();
  }, [refreshLearningData]);

  useEffect(() => {
    setApiTurns([]);
    setLastApiTurn(null);
    setApiSessionId(null);
    if (connectionMode !== "api") return;
    const sessionId = readStoredJapaneseSession(api.baseUrl, "conversation", selectedScenario.id);
    if (!sessionId) return;
    let cancelled = false;
    setApiSessionId(sessionId);
    void api.listTurns(sessionId).then((persisted) => {
      if (cancelled) return;
      setApiTurns(persisted.flatMap((turn) => apiTurnToUiTurns(turn, api.baseUrl)));
      setLastApiTurn(persisted.at(-1) ?? null);
    }).catch((error: unknown) => {
      if (!cancelled) setApiError(error instanceof Error ? error.message : "无法恢复日语会话轮次。");
    });
    return () => { cancelled = true; };
  }, [api, connectionMode, selectedScenario.id]);

  useEffect(() => () => {
    if (playbackTimerRef.current !== null) window.clearTimeout(playbackTimerRef.current);
  }, []);

  const sendMockText = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft.trim()) return;
    if (connectionMode === "api") {
      setApiError("真实会话契约必须上传一段原始录音；文本框仅作为可选 transcript_hint。请先录音。 ");
      return;
    }
    setPhase("thinking");
    const ok = await addConversationTurn(draft, coachMode);
    setPhase(ok ? "idle" : "error");
    if (ok) setDraft("");
  };

  const processRecording = async () => {
    if (!recorder.audioBlob) return;
    setApiError(null);
    if (connectionMode !== "api") {
      setPhase("transcribing");
      const hint = draft.trim() || selectedScenario.suggestions[0];
      const ok = await addConversationTurn(hint, coachMode);
      setPhase(ok ? "idle" : "error");
      if (ok) {
        setDraft("");
        recorder.clear();
      }
      return;
    }

    try {
      setPhase("uploading");
      const sessionId = await ensureJapaneseSession(api, {
        mode: "conversation",
        coachMode: coachMode === "strict" ? "strict" : "fluent",
        scenario: selectedScenario.title,
        scenarioId: selectedScenario.id,
        metadata: {
          curriculum_version: "2026.08.daily-life-v1",
          curriculum_stage_id: selectedScenario.stageId,
          curriculum_level: selectedScenario.level,
          curriculum_domain: selectedScenario.domain,
        },
      });
      setApiSessionId(sessionId);
      const extension = recorder.audioBlob.type.includes("ogg") ? "ogg" : recorder.audioBlob.type.includes("mp4") ? "m4a" : "webm";
      const upload = await api.uploadRecording(sessionId, recorder.audioBlob, `conversation-${Date.now()}.${extension}`);
      setPhase("thinking");
      const result = await api.processTurn(sessionId, {
        recordingId: upload.recording_id,
        transcriptHint: draft.trim() || undefined,
        voiceRole: "standard_tokyo",
      });
      setLastApiTurn(result);
      setApiTurns((current) => [...current, ...apiTurnToUiTurns(result, api.baseUrl)]);
      setDraft("");
      recorder.clear();
      setPhase("idle");
      await refreshLearningData();
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "真实会话请求失败。原始录音仍保留在浏览器，可重试。 ");
      setPhase("error");
    }
  };

  const completeCurrentScenario = async () => {
    setApiError(null);
    if (completedTurnCount < 3) {
      setApiError(`完成场景前至少需要 3 轮有效练习；当前 ${completedTurnCount}/3。`);
      return;
    }
    if (connectionMode !== "api") {
      setMockCompletedScenarios((current) => new Set(current).add(selectedScenario.id));
      return;
    }
    if (!apiSessionId) {
      setApiError("当前场景尚未创建持久化会话，请先完成一轮录音。 ");
      return;
    }
    setCompletingScenario(true);
    try {
      await api.completeSession(apiSessionId);
      clearStoredJapaneseSession(api.baseUrl, "conversation", selectedScenario.id);
      setApiSessionId(null);
      await refreshLearningData();
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "场景完成状态保存失败。 ");
    } finally {
      setCompletingScenario(false);
    }
  };

  const speak = (text: string, audioUrl?: string) => {
    if (playbackTimerRef.current !== null) window.clearTimeout(playbackTimerRef.current);
    setPhase("playing");
    const started = playAudioOrSpeech(audioUrl, text, "ja-JP");
    if (!started) {
      setPhase("error");
      return;
    }
    const estimatedDuration = Math.min(9_000, Math.max(1_800, text.length * 135));
    playbackTimerRef.current = window.setTimeout(() => {
      setPhase("idle");
      playbackTimerRef.current = null;
    }, estimatedDuration);
  };

  return (
    <>
      <PageHeader
        eyebrow="Japanese learning loop"
        title="日语会话房间"
        description="从 N5 生存沟通到 N1 复杂表达，按真实生活场景、原声证据、间隔复习和手动完成记录持续推进。"
        actions={<Badge tone={connectionMode === "mock" ? "warning" : "success"} dot>{connectionMode === "mock" ? "Mock 教师 · UI 证据" : "真实 /api/japanese 契约"}</Badge>}
      />

      {connectionMode === "api" ? (
        <div className="info-strip api-contract-strip">
          <Icon name="check" />
          <div><strong>真实链路已启用</strong><span>raw WebM/Opus → POST /api/japanese/recordings → recording_id → sessions/turns。后端规范化为 48 kHz PCM-24，并核验不可变原录音 provenance。会话 {apiSessionId ?? "将在首次提交时创建"}。</span></div>
        </div>
      ) : (
        <div className="info-strip api-contract-strip api-contract-strip--mock">
          <Icon name="info" />
          <div><strong>显式 Mock 模式</strong><span>录音只在浏览器内播放，反馈来自确定性 mock；不会标记为真实 ASR、教师或后端评分。</span></div>
        </div>
      )}

      {apiError ? <div className="system-alert system-alert--danger"><Icon name="alert" /><div><strong>日语 API 请求未完成</strong><span>{apiError}</span></div><Button size="sm" onClick={() => setApiError(null)}>保留录音并重试</Button>{connectionMode === "api" && config.mockAllowed ? <Button size="sm" tone="ghost" onClick={() => void reconnect({ requestedMode: "mock" })}>明确切换 Mock</Button> : null}</div> : null}

      <JapaneseLearningPath
        path={learningPath}
        progress={progress}
        selectedStageId={selectedStageId}
        onStageChange={(stageId) => {
          setSelectedStageId(stageId);
          const first = japaneseScenarios.find((item) => item.stageId === stageId);
          if (first) selectScenario(first.id);
        }}
        onScenarioSelect={selectScenario}
        connectionMode={connectionMode === "api" ? "api" : "mock"}
      />

      <div className="learning-layout">
        <aside className="scenario-sidebar">
          <div className="section-heading section-heading--small"><div><h2>实战场景库</h2><p>38 个场景 · 13 类日常领域</p></div></div>
          <div className="scenario-filters">
            <input value={scenarioQuery} onChange={(event) => setScenarioQuery(event.target.value)} placeholder="搜索场景或目标" aria-label="搜索日语场景" />
            <select value={domainFilter} onChange={(event) => setDomainFilter(event.target.value)} aria-label="筛选场景领域">
              {Object.entries(japaneseDomainLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
            </select>
          </div>
          <div className="scenario-stage-caption">
            <strong>{japaneseStages.find((stage) => stage.id === selectedStageId)?.title}</strong>
            <span>{japaneseStages.find((stage) => stage.id === selectedStageId)?.outcome}</span>
          </div>
          <div className="scenario-list scenario-list--curriculum">{filteredScenarios.map((item) => {
            const pathState = pathScenarioById.get(item.id)?.status ?? (mockCompletedScenarios.has(item.id) ? "completed" : "available");
            return (
              <button
                type="button"
                key={item.id}
                className={`${scenario === item.id ? "is-active" : ""} scenario-status--${pathState}`}
                onClick={() => selectScenario(item.id)}
                disabled={pathState === "locked"}
              >
                <span>{item.icon}</span>
                <div><strong>{item.title}</strong><small>{item.level} · {japaneseDomainLabels[item.domain] ?? item.domain}</small></div>
                <em>{pathState === "completed" ? "完成" : pathState === "in_progress" ? "继续" : pathState === "locked" ? "未解锁" : "可练"}</em>
              </button>
            );
          })}</div>
          {!filteredScenarios.length ? <div className="scenario-empty">本阶段没有符合筛选条件的场景。</div> : null}
          <Panel className="today-card"><div className="today-card__ring"><strong>{learningPath?.summary.due_review_count ?? 0}</strong><span>到期</span></div><div><strong>今日闭环</strong><span>复习 → 未完成场景 → 新场景 → 跟读</span></div></Panel>
          <Panel className="profile-mini"><div className="panel-heading"><div><h3>学习者证据</h3><p>{learningPath?.placement_level ?? "N4"} · {connectionMode === "api" ? "持久化档案" : "Mock 预览"}</p></div><Badge tone="purple">{learningPath?.summary.completed ?? mockCompletedScenarios.size}/38</Badge></div><dl><div><dt>内容</dt><dd>{progress?.metrics.content.recent_mean == null ? "待原声样本" : `${Math.round(progress.metrics.content.recent_mean * 100)}% · ${progress.metrics.content.direction}`}</dd></div><div><dt>节奏</dt><dd>{progress?.metrics.rhythm.recent_mean == null ? "待跟读样本" : `${Math.round(progress.metrics.rhythm.recent_mean * 100)}% · ${progress.metrics.rhythm.direction}`}</dd></div><div><dt>复习债务</dt><dd>{learningPath?.summary.due_review_count ?? 0} 项到期</dd></div></dl></Panel>
        </aside>

        <section className="conversation-panel">
          <Panel className="conversation-header conversation-header--curriculum">
            <div><span className="scenario-emoji">{selectedScenario.icon}</span><div><small>{selectedScenario.level} · {japaneseDomainLabels[selectedScenario.domain]} · {selectedScenario.japaneseTitle}</small><h2>{selectedScenario.title}</h2><p>本场目标：{selectedScenario.goal}</p><div className="scenario-session-progress"><i style={{ width: `${Math.min(100, completedTurnCount / 3 * 100)}%` }} /><span>{completedTurnCount}/3 最低轮次</span></div></div></div>
            <div className="conversation-header__actions">
              <Segmented label="教练模式" value={coachMode} options={[{ value: "flow", label: "流畅对话" }, { value: "strict", label: "严格教练" }]} onChange={(value) => setCoachMode(value as "flow" | "strict")} />
              <Button
                size="sm"
                tone={pathScenarioById.get(selectedScenario.id)?.status === "completed" || mockCompletedScenarios.has(selectedScenario.id) ? "ghost" : "primary"}
                icon="check"
                busy={completingScenario}
                disabled={pathScenarioById.get(selectedScenario.id)?.status === "completed" || mockCompletedScenarios.has(selectedScenario.id)}
                onClick={() => void completeCurrentScenario()}
              >{pathScenarioById.get(selectedScenario.id)?.status === "completed" || mockCompletedScenarios.has(selectedScenario.id) ? "已完成" : "完成本场景"}</Button>
            </div>
          </Panel>

          <DigitalCompanion
            state={companionState}
            subtitle={companionSubtitle}
            emotion={companionEmotion}
            sceneTitle={selectedScenario.title}
            sceneImageUrl={selectedScenario.image}
            suggestions={selectedScenario.suggestions}
            onSuggestion={setDraft}
          />

          <Panel className="conversation-stream">
            <div className="conversation-context"><Icon name="info" /><span>半双工：教师播放时不录音。后端通过 recording_id 核验不可变原录音 provenance；浏览器回放不参与评分。</span></div>
            <div className="turns">
              {turns.length ? turns.map((turn) => (
                <article className={`turn turn--${turn.role}`} key={turn.id}>
                  <span className="turn__avatar">{turn.role === "teacher" ? "先生" : "YOU"}</span>
                  <div className="turn__content">
                    <header><strong>{turn.role === "teacher" ? "AI 教师" : "你的转写"}</strong><time>{relativeTime(turn.createdAt)}</time>{turn.role === "teacher" ? <button type="button" aria-label={turn.audioUrl ? "播放后端示范音频" : "用浏览器语音回放示范"} onClick={() => speak(turn.translation || turn.text, turn.audioUrl)}><Icon name="play" size={14} />{turn.audioUrl ? "后端示范" : "浏览器回放"}</button> : null}</header>
                    <p lang="ja">{turn.text}</p>
                    {turn.translation ? <small>{connectionMode === "api" ? `示范文本：${turn.translation}` : turn.translation}</small> : null}
                    {turn.feedback ? <div className="turn-feedback"><Icon name="spark" /><div><strong>{turn.role === "learner" && connectionMode === "api" ? "ASR 证据" : coachMode === "strict" ? "立即修复" : "本轮重点"}</strong><span>{turn.feedback}</span>{turn.confidence !== undefined ? <em>置信度 {Math.round(turn.confidence * 100)}%</em> : null}</div></div> : null}
                  </div>
                </article>
              )) : <EmptyState icon="message" title="开始第一轮会话" description={connectionMode === "api" ? "录下一句后上传，后端会持久化原始录音哈希、转写、反馈与示范。" : "输入或录下一句，Mock 教师会返回可验证反馈。"} />}
            </div>
            {phase !== "idle" && phase !== "error" || recorder.status === "requesting" ? <div className="phase-indicator"><span className="button__spinner" /><strong>{recorder.status === "requesting" ? "请求麦克风权限" : phase === "uploading" ? "上传原始 WebM/Opus 并归一化" : phase === "transcribing" ? "Mock 转写" : phase === "thinking" ? "ASR → 教师 → 标准示范" : "浏览器播放示范"}</strong><small>{phase === "uploading" ? "请求体是原始 Blob；后端限制 FFmpeg 输入并输出 PCM-24" : "完成后会保存轮次与证据"}</small></div> : null}
          </Panel>

          <Panel className="conversation-composer">
            {recorder.status === "recording" ? (
              <div className="recording-state"><span className="recording-pulse" /><div><strong>正在录音</strong><small>说完一句后停止；录音不会先做音色染色</small></div><Button tone="danger" icon="square" onClick={recorder.stop}>停止</Button></div>
            ) : recorder.audioUrl ? (
              <div className="recorded-turn-editor">
                <div className="recorded-state"><audio controls src={recorder.audioUrl} /><span>{(recorder.durationMs / 1000).toFixed(1)} 秒 · {recorder.audioBlob?.type || "browser audio"}</span></div>
                <label className="field"><span className="field__label">可选转写提示（只作为测试证据，不伪装 ASR）</span><textarea rows={2} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="留空让后端 ASR；Mock 模式可输入确定性 transcript_hint" /></label>
                <div className="recorded-turn-editor__actions"><Button tone="ghost" onClick={recorder.clear}>放弃并重录</Button><Button tone="primary" icon="upload" busy={phase === "uploading" || phase === "thinking"} onClick={() => void processRecording()}>{connectionMode === "api" ? "上传并完成本轮" : "使用 Mock 完成本轮"}</Button></div>
              </div>
            ) : (
              <form onSubmit={sendMockText}><textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={2} placeholder={connectionMode === "api" ? "真实 API 模式：这里可先写 transcript_hint，然后点击录音…" : "输入日语，或使用麦克风录一轮…"} lang="ja" /><div><Button type="button" tone="ghost" icon="mic" busy={recorder.status === "requesting"} onClick={() => void recorder.start()}>录音</Button><span>{connectionMode === "api" ? "真实会话必须上传原始录音" : coachMode === "flow" ? "保持流畅，只纠正关键一点" : "严格模式要求立即重说"}</span><Button type="submit" tone="primary" icon="arrow" disabled={!draft.trim() || connectionMode === "api"} busy={operation === "保存会话轮次"}>Mock 文本发送</Button></div></form>
            )}
            {recorder.error ? <div className="inline-error"><Icon name="alert" />{recorder.error}</div> : null}
          </Panel>
        </section>

        <aside className="feedback-sidebar">
          <Panel>
            <div className="panel-heading"><div><h2>{connectionMode === "api" ? "真实 API 证据" : "Mock UI 证据"}</h2><p>拆分来源和置信度，不显示伪造总分。</p></div></div>
            {connectionMode === "api" && lastApiTurn ? (
              <div className="api-evidence-stack">
                <div><span>不可变录音 provenance</span><strong>{lastApiTurn.recording_id}</strong><small>{lastApiTurn.scoring_source_kind} · SHA-256 {lastApiTurn.original_audio_sha256.slice(0, 12)}…</small></div>
                <div><span>转写</span><strong>{lastApiTurn.transcript.provider}{lastApiTurn.transcript.fallback_used ? " · fallback" : ""}</strong><small>置信度 {Math.round(lastApiTurn.transcript.confidence * 100)}% · {lastApiTurn.transcript.evidence.join("；") || "无附加证据"}</small></div>
                <div><span>教师</span><strong>{lastApiTurn.teacher.provider}{lastApiTurn.teacher.fallback_used ? " · fallback" : ""}</strong><small>置信度 {Math.round(lastApiTurn.teacher.confidence * 100)}% · {lastApiTurn.teacher.feedback.join("；")}</small></div>
                <div><span>示范产物</span><strong>{lastApiTurn.demonstration.sample_rate / 1000} kHz · {lastApiTurn.demonstration.subtype}</strong><small>{lastApiTurn.demonstration.provider} · {lastApiTurn.demonstration.audio_url ?? `/api/japanese/turns/${lastApiTurn.id}/demonstration`}</small></div>
              </div>
            ) : latestFeedback ? (
              <div className="evidence-stack"><div><span>内容正确度</span><strong>88</strong><div className="quality-track"><i style={{ width: "88%" }} /></div><small>Mock：关键词与目的地表达完整 · 置信度 82%</small></div><div><span>Mora / 音素</span><strong>76</strong><div className="quality-track"><i style={{ width: "76%" }} /></div><small>Mock：「しんじゅく」中 /N/ 时长偏短 · 置信度 67%</small></div><div><span>节奏与停顿</span><strong>81</strong><div className="quality-track"><i style={{ width: "81%" }} /></div><small>Mock：请求尾句略快 · 置信度 74%</small></div></div>
            ) : <EmptyState icon="activity" title="等待你的录音" description={connectionMode === "api" ? "上传完成后显示后端返回的实际 provider、fallback、哈希与置信度。" : "Mock 完成一轮后显示明确标记的模拟证据。"} />}
          </Panel>
          <Panel className="next-review"><span><Icon name="retry" /></span><div><h3>错项间隔复习</h3><p>真实 API 会把本轮问题写入 jp_ review 表。</p><small>预留 AnkiConnect 请求体导出</small></div></Panel>
        </aside>
      </div>
    </>
  );
};
