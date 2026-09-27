import { useMemo, useState } from "react";
import { useStudio } from "../StudioContext";
import { Icon, type IconName } from "../components/Icon";
import { Badge, Button, EmptyState, PageHeader, Panel } from "../components/ui";
import { playAudioOrSpeech, playSpeech } from "../lib/audio";
import {
  JapaneseLearningApi,
  apiShadowingToUi,
  ensureJapaneseSession,
  type ShadowReferenceResponse,
  type ShadowingApiResponse,
} from "../lib/japaneseApi";
import { useRecorder } from "../lib/useRecorder";
import type { ShadowFeedback } from "../types";

const exercises = [
  { id: "ex-1", text: "新宿まで一枚お願いします。", translation: "请给我一张到新宿的票。", focus: "mora 节奏 · 促音前后时长", level: "N4" },
  { id: "ex-2", text: "今日はちょっと都合が悪いんです。", translation: "今天有点不方便。", focus: "长音 · 元音弱化", level: "N3" },
  { id: "ex-3", text: "もう一度ゆっくり話していただけますか。", translation: "可以再慢慢说一次吗？", focus: "音高重音 · 礼貌表达", level: "N4" },
];

const mockFeedback: ShadowFeedback = {
  source: "mock",
  content: { score: 92, evidence: "Mock：关键词完整；未检测到漏词。", confidence: 0.88 },
  rhythm: { score: 78, evidence: "Mock：「しんじゅく｜まで」之间停顿约长 120 ms。", confidence: 0.74 },
  pitch: { score: 71, evidence: "Mock：「いちまい」第二 mora 的 F0 下降过早。", confidence: 0.63 },
  mora: { score: 82, evidence: "Mock：「ん」持续时间略短，但仍可理解。", confidence: 0.69 },
  referenceF0: [42, 48, 55, 63, 67, 64, 58, 51, 49, 55, 62, 69, 72, 66, 58, 51, 45, 48, 55, 50],
  learnerF0: [40, 45, 52, 59, 61, 57, 51, 48, 45, 49, 54, 57, 54, 50, 47, 44, 42, 46, 50, 47],
  priorities: ["Mock：先拉长「ん」。", "Mock：让「いちまい」的音高下降稍晚一点。"],
};

const F0Chart = ({ reference, learner }: { reference: number[]; learner: number[] }) => {
  const combined = [...reference, ...learner];
  const low = Math.min(...combined);
  const high = Math.max(...combined);
  const padding = Math.max(1, (high - low) * 0.12);
  const min = low - padding;
  const max = high + padding;
  const points = (values: number[]) => values.map((value, index) => {
    const x = 24 + index * (476 / Math.max(1, values.length - 1));
    const y = 150 - ((value - min) / Math.max(0.001, max - min)) * 120;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return <svg className="f0-chart" viewBox="0 0 520 180" role="img" aria-label="参考音与学习者归一化 F0 半音走势对比"><g className="f0-grid">{[30, 60, 90, 120, 150].map((y) => <line key={y} x1="24" y1={y} x2="500" y2={y} />)}</g><polyline className="f0-reference" points={points(reference)} /><polyline className="f0-learner" points={points(learner)} /><g className="f0-labels"><text x="24" y="174">0%</text><text x="250" y="174">归一化时间</text><text x="482" y="174">100%</text></g></svg>;
};

const compactEvidence = (value: Record<string, unknown> | undefined) => {
  if (!value) return [];
  return Object.entries(value).slice(0, 6).map(([key, item]) => `${key}: ${Array.isArray(item) ? item.join(" / ") : String(item)}`);
};

export const ShadowingPage = () => {
  const { connectionMode, config, reconnect } = useStudio();
  const [exerciseId, setExerciseId] = useState(exercises[0].id);
  const [result, setResult] = useState<ShadowFeedback | null>(null);
  const [apiRawResult, setApiRawResult] = useState<ShadowingApiResponse | null>(null);
  const [reference, setReference] = useState<ShadowReferenceResponse | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [transcriptHint, setTranscriptHint] = useState("");
  const [phase, setPhase] = useState<"idle" | "reference" | "uploading" | "analyzing" | "error">("idle");
  const [apiError, setApiError] = useState<string | null>(null);
  const recorder = useRecorder();
  const api = useMemo(() => new JapaneseLearningApi(config.apiBaseUrl), [config.apiBaseUrl]);
  const exercise = exercises.find((item) => item.id === exerciseId) ?? exercises[0];
  const metrics = useMemo<Array<{ label: string; metric: ShadowFeedback["content"]; icon: IconName }>>(() => {
    if (!result) return [];
    const items: Array<{ label: string; metric: ShadowFeedback["content"]; icon: IconName }> = [
      { label: "内容", metric: result.content, icon: "check" },
      { label: "节奏", metric: result.rhythm, icon: "activity" },
      { label: "F0 音高", metric: result.pitch, icon: "waveform" },
    ];
    if (result.mora) items.push({ label: "Mora（仅 Mock）", metric: result.mora, icon: "message" });
    return items;
  }, [result]);
  const referenceAudioUrl = reference?.synthesis.audio_url ? api.assetUrl(reference.synthesis.audio_url) : null;

  const chooseExercise = (nextId: string) => {
    setExerciseId(nextId);
    setResult(null);
    setApiRawResult(null);
    setReference(null);
    setTranscriptHint("");
    setApiError(null);
    recorder.clear();
  };

  const prepareReference = async () => {
    if (connectionMode !== "api") {
      playSpeech(exercise.text, "ja-JP");
      return;
    }
    setApiError(null);
    setPhase("reference");
    try {
      const activeSession = await ensureJapaneseSession(api, {
        mode: "shadowing",
        coachMode: "strict",
        scenario: `影子跟读：${exercise.focus}`,
      });
      setSessionId(activeSession);
      const created = await api.createShadowingReference(activeSession, exercise.text);
      setReference(created);
      setPhase("idle");
      playAudioOrSpeech(api.assetUrl(created.synthesis.audio_url), exercise.text, "ja-JP");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "无法创建标准跟读参考。 ");
      setPhase("error");
    }
  };

  const submitAttempt = async () => {
    if (!recorder.audioBlob) return;
    setApiError(null);
    if (connectionMode !== "api") {
      setPhase("analyzing");
      window.setTimeout(() => {
        setResult(mockFeedback);
        setPhase("idle");
      }, 420);
      return;
    }
    if (!reference || !sessionId) {
      setApiError("请先通过真实 API 生成标准参考音，再提交跟读录音。 ");
      return;
    }
    try {
      setPhase("uploading");
      const extension = recorder.audioBlob.type.includes("ogg") ? "ogg" : recorder.audioBlob.type.includes("mp4") ? "m4a" : "webm";
      const upload = await api.uploadRecording(sessionId, recorder.audioBlob, `shadowing-${Date.now()}.${extension}`);
      setPhase("analyzing");
      const response = await api.submitShadowingAttempt(sessionId, reference.exercise.id, {
        recordingId: upload.recording_id,
        transcriptHint: transcriptHint.trim() || undefined,
      });
      const mapped = apiShadowingToUi(response);
      mapped.referenceAudioUrl = api.assetUrl(response.ab_playback.reference_audio_url);
      setApiRawResult(response);
      setResult(mapped);
      setPhase("idle");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "跟读分析请求失败；浏览器原始录音仍可重试。 ");
      setPhase("error");
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Listen · record · align · retry"
        title="影子跟读与 F0 / mora 反馈"
        description="真实模式先生成后端参考 WAV，再上传染色前原声进行 content、rhythm、pitch 分项分析；Mock 反馈始终明确标记。"
        actions={<Badge tone={connectionMode === "api" ? "success" : "warning"}>{connectionMode === "api" ? "真实 shadowing API" : "Mock UI · 未调用评分"}</Badge>}
      />

      {connectionMode === "api" ? <div className="info-strip api-contract-strip"><Icon name="check" /><div><strong>真实跟读契约</strong><span>references → 可播放 WAV → raw WebM/Opus upload → recording_id → exercises/{`{id}`}/attempts；后端锁定 browser_original_upload provenance，无 overall_score。</span></div></div> : <div className="info-strip api-contract-strip api-contract-strip--mock"><Icon name="info" /><div><strong>显式 Mock 后备</strong><span>下面的模拟 F0 曲线和 Mora 卡只用于 UI 验收，不会标记成后端分数。</span></div></div>}
      {apiError ? <div className="system-alert system-alert--danger"><Icon name="alert" /><div><strong>跟读 API 请求未完成</strong><span>{apiError}</span></div><Button size="sm" onClick={() => setApiError(null)}>保留录音并重试</Button>{connectionMode === "api" && config.mockAllowed ? <Button size="sm" tone="ghost" onClick={() => void reconnect({ requestedMode: "mock" })}>明确切换 Mock</Button> : null}</div> : null}

      <div className="shadow-layout">
        <aside className="exercise-list"><div className="section-heading section-heading--small"><div><h2>今日练习</h2><p>从最影响自然度的项目开始。</p></div></div>{exercises.map((item, index) => <button type="button" key={item.id} className={exerciseId === item.id ? "is-active" : ""} onClick={() => chooseExercise(item.id)}><span>{index + 1}</span><div><strong lang="ja">{item.text}</strong><small>{item.level} · {item.focus}</small></div><Icon name="chevron" size={15} /></button>)}</aside>
        <section className="shadow-main">
          <Panel className="phrase-card"><div className="phrase-card__top"><div><Badge tone="purple">{exercise.level}</Badge><span>{exercise.focus}</span>{reference ? <Badge tone="success">后端参考已创建</Badge> : null}</div><Button tone="ghost" size="sm" icon="play" busy={phase === "reference"} onClick={() => referenceAudioUrl ? playAudioOrSpeech(referenceAudioUrl, exercise.text, "ja-JP") : void prepareReference()}>{connectionMode === "api" && !reference ? "生成标准参考" : "播放标准示范"}</Button></div><h2 lang="ja">{exercise.text}</h2><p>{exercise.translation}</p><div className="mora-strip" aria-label="mora 分段"><span>し</span><span>ん</span><span>じゅ</span><span>く</span><i /><span>ま</span><span>で</span><i /><span>い</span><span>ち</span><span>ま</span><span>い</span><i /><span>お</span><span>ね</span><span>が</span><span>い</span></div></Panel>

          <Panel className="ab-recorder">
            <div className="ab-side"><small>A · {connectionMode === "api" ? "后端参考 WAV" : "浏览器 Mock 示范"}</small><button type="button" disabled={connectionMode === "api" && !referenceAudioUrl} onClick={() => referenceAudioUrl ? playAudioOrSpeech(referenceAudioUrl, exercise.text, "ja-JP") : playSpeech(exercise.text, "ja-JP")}><span><Icon name="play" /></span><div className="mini-wave">{Array.from({ length: 34 }, (_, index) => <i key={index} style={{ height: `${18 + (index * 17) % 68}%` }} />)}</div><em>{reference ? `${reference.synthesis.sample_rate / 1000}k ${reference.synthesis.subtype}` : "待创建参考"}</em></button></div>
            <div className="ab-divider"><span>A</span><i /><span>B</span></div>
            <div className="ab-side"><small>B · 染色前原始录音</small>{recorder.audioUrl ? <div className="user-audio"><audio controls src={recorder.audioUrl} /><em>{(recorder.durationMs / 1000).toFixed(1)} 秒 · {recorder.audioBlob?.type || "browser"}</em></div> : <div className="audio-empty"><Icon name="mic" /><span>录音后可 A/B 播放</span></div>}</div>
          </Panel>

          <Panel className={`record-action ${recorder.status === "recording" ? "is-recording" : ""}`}>
            {recorder.status === "recording" ? <><div className="live-wave">{Array.from({ length: 42 }, (_, index) => <i key={index} style={{ height: `${25 + (index * 23) % 70}%` }} />)}</div><div><strong>正在录音 · 跟读这一句</strong><small>保持自然节奏，评分只使用这段未染色原声</small></div><Button tone="danger" size="lg" icon="square" onClick={recorder.stop}>停止录音</Button></> : recorder.audioUrl ? <><span className="record-action__icon"><Icon name="headphones" size={23} /></span><div><strong>原始录音已保留，可上传分析</strong><small>{connectionMode === "api" ? "可选 transcript_hint 仅作为 ASR 测试证据" : "Mock 会返回明确标记的确定性反馈"}</small><input value={transcriptHint} onChange={(event) => setTranscriptHint(event.target.value)} placeholder="可选 transcript_hint" /></div><Button tone="primary" size="lg" icon="upload" busy={phase === "uploading" || phase === "analyzing"} disabled={connectionMode === "api" && !reference} onClick={() => void submitAttempt()}>{connectionMode === "api" ? "上传并分析" : "运行 Mock 分析"}</Button><Button tone="ghost" size="sm" onClick={() => { recorder.clear(); setResult(null); }}>重录</Button></> : <><span className="record-action__icon"><Icon name="mic" size={25} /></span><div><strong>{connectionMode === "api" && !reference ? "先创建标准参考音" : "准备好后录下一遍"}</strong><small>浏览器记录 MediaRecorder Blob 与 MIME，后端本机 FFmpeg 规范化</small></div><Button tone="primary" size="lg" icon="mic" busy={recorder.status === "requesting"} disabled={connectionMode === "api" && !reference} onClick={() => { setResult(null); setApiRawResult(null); void recorder.start(); }}>开始录音</Button></>}
            {recorder.error ? <div className="inline-error"><Icon name="alert" />{recorder.error}</div> : null}
          </Panel>

          {result ? <>
            <div className="feedback-metrics">{metrics.map(({ label, metric, icon }) => <Panel key={label}><span><Icon name={icon} /></span><div><small>{label}</small><strong>{metric.score ?? "—"}<em>{metric.score === null ? "证据不足" : "/100"}</em></strong></div><p>{metric.evidence}</p><footer>置信度 {Math.round(metric.confidence * 100)}% · {result.source === "api" ? "真实 API" : "Mock"}</footer></Panel>)}</div>
            {result.referenceF0 && result.learnerF0 ? <Panel className="f0-panel"><div className="panel-heading"><div><h2>{result.source === "api" ? "后端真实" : "Mock"}归一化 F0 走势</h2><p>{result.source === "api" ? "32 点半音偏移，各自按中位数归一；比较走势而非绝对音域。" : "仅用于 Mock UI 验收。"}</p></div><div className="chart-legend"><span><i className="reference" />参考</span><span><i className="learner" />原录音</span></div></div><F0Chart reference={result.referenceF0} learner={result.learnerF0} /></Panel> : result.source === "api" ? <Panel><EmptyState icon="waveform" title="F0 帧证据不足" description="后端未返回归一化半音数组；保持空态，不补造曲线。" /></Panel> : null}
            {result.source === "api" && result.expectedMoraSegmentsApprox && result.actualMoraSegmentsApprox ? <Panel className="mora-evidence-panel"><div className="panel-heading"><div><h2>Mora 分段近似证据</h2><p>小假名合并的启发式分段，尚未强制对齐；仅展示证据，不派生分数。</p></div><Badge tone="warning">heuristic</Badge></div><div className="mora-comparison"><div><strong>期望文本</strong><div>{result.expectedMoraSegmentsApprox.map((segment, index) => <span key={`${segment}-${index}`}>{segment}</span>)}</div></div><div><strong>ASR 转写</strong><div>{result.actualMoraSegmentsApprox.map((segment, index) => <span key={`${segment}-${index}`}>{segment}</span>)}</div></div></div></Panel> : null}
            {result.source === "api" ? <Panel className="api-score-evidence"><div className="panel-heading"><div><h2>后端原始分项证据</h2><p>按 OpenAPI 字段展示，不派生 Mora 或总分。</p></div><Badge tone="success">{result.scoringSourceKind}</Badge></div><div className="api-evidence-columns">{([result.content, result.rhythm, result.pitch] as const).map((metric, index) => <div key={index}><strong>{["content", "rhythm", "pitch"][index]}</strong><ul>{compactEvidence(metric.details).map((item) => <li key={item}>{item}</li>)}</ul>{metric.limitations?.map((limit) => <small key={limit}>{limit}</small>)}</div>)}</div>{apiRawResult ? <div className="api-path-evidence"><span>attempt {apiRawResult.attempt_id}</span><span>recording {apiRawResult.ab_playback.recording_id}</span><span>reference {apiRawResult.ab_playback.reference_audio_url}</span><span>{apiRawResult.review_item_ids.length} 个复习项</span></div> : null}</Panel> : null}
            <Panel className="retry-card"><div><span><Icon name="retry" /></span><div><h3>立即重说</h3><p>{result.priorities?.slice(0, 2).join("；") || "结合证据人工复听后再录一次。"}</p></div></div><Button tone="primary" icon="mic" onClick={() => { setResult(null); setApiRawResult(null); recorder.clear(); void recorder.start(); }}>按建议再录一次</Button></Panel>
          </> : <Panel><EmptyState icon="activity" title="等待一段原始录音" description={connectionMode === "api" ? "先创建参考并录音；提交后只显示后端返回的 content、rhythm、pitch 与限制。" : "完成录音后显示明确标为 Mock 的内容、节奏、F0 与 mora 反馈。"} /></Panel>}
        </section>
      </div>
    </>
  );
};
