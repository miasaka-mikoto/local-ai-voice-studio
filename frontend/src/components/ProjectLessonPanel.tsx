import { useEffect, useMemo, useState } from "react";
import { useStudio } from "../StudioContext";
import { JapaneseLearningApi, ensureJapaneseLearner, readStoredJapaneseLearner } from "../lib/japaneseApi";
import type {
  JapaneseExerciseResponse,
  JapaneseSessionResponse,
  JapaneseTurnResponse,
  ProjectLessonMode,
  ShadowingApiResponse,
} from "../lib/japaneseApi";
import { useRecorder } from "../lib/useRecorder";
import type { Character, DialogueLine, Project } from "../types";
import { Badge, Button, Field, Panel } from "./ui";

const modeLabel: Record<ProjectLessonMode, string> = {
  dictation: "听写",
  shadowing: "影子跟读",
  role_play: "角色扮演",
};

const recordingFilename = (blob: Blob, prefix: string) => {
  const extension = blob.type.includes("ogg") ? "ogg" : blob.type.includes("mp4") ? "m4a" : "webm";
  return `${prefix}.${extension}`;
};

export const ProjectLessonPanel = ({
  project,
  lines,
  characters,
}: {
  project: Project;
  lines: DialogueLine[];
  characters: Character[];
}) => {
  const { config, connectionMode } = useStudio();
  const api = useMemo(() => new JapaneseLearningApi(config.apiBaseUrl), [config.apiBaseUrl]);
  const recorder = useRecorder();
  const [mode, setMode] = useState<ProjectLessonMode>("shadowing");
  const [sceneId, setSceneId] = useState("all");
  const [sessions, setSessions] = useState<JapaneseSessionResponse[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [exercises, setExercises] = useState<JapaneseExerciseResponse[]>([]);
  const [exerciseId, setExerciseId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<ShadowingApiResponse | null>(null);
  const [rolePlayTurns, setRolePlayTurns] = useState<JapaneseTurnResponse[]>([]);
  const [showAnswer, setShowAnswer] = useState(false);

  const japaneseLines = useMemo(
    () => lines.filter((line) => line.text.trim() && line.locale.toLowerCase().startsWith("ja")),
    [lines],
  );
  const sceneIds = useMemo(
    () => [...new Set(japaneseLines.map((line) => line.sceneId))].sort(),
    [japaneseLines],
  );
  const selectedLines = useMemo(
    () => japaneseLines.filter((line) => sceneId === "all" || line.sceneId === sceneId),
    [japaneseLines, sceneId],
  );
  const activeSession = sessions.find((session) => session.id === sessionId);
  const activeExercise = exercises.find((exercise) => exercise.id === exerciseId);
  const activeMode = activeSession?.metadata.lesson_mode as ProjectLessonMode | undefined;
  const exerciseRolePlayTurns = rolePlayTurns.filter((turn) => turn.exercise_id === exerciseId);

  useEffect(() => {
    if (connectionMode !== "api") {
      setSessions([]);
      setSessionId("");
      return;
    }
    const learnerId = readStoredJapaneseLearner(api.baseUrl);
    if (!learnerId) return;
    let cancelled = false;
    void api.listSessions(learnerId).then((items) => {
      if (cancelled) return;
      const matching = items
        .filter((item) => item.mode === "project_lesson" && item.metadata.source_project_id === project.id)
        .sort((a, b) => b.started_at.localeCompare(a.started_at));
      setSessions(matching);
      setSessionId((current) => matching.some((item) => item.id === current) ? current : matching[0]?.id ?? "");
    }).catch((caught) => {
      if (!cancelled) setError(caught instanceof Error ? caught.message : "无法读取已有课程。");
    });
    return () => { cancelled = true; };
  }, [api, connectionMode, project.id]);

  useEffect(() => {
    if (!sessionId || connectionMode !== "api") {
      setExercises([]);
      setExerciseId("");
      setRolePlayTurns([]);
      return;
    }
    let cancelled = false;
    void api.listSessionExercises(sessionId).then((items) => {
      if (cancelled) return;
      setExercises(items);
      setExerciseId((current) => items.some((item) => item.id === current) ? current : items[0]?.id ?? "");
    }).catch((caught) => {
      if (!cancelled) setError(caught instanceof Error ? caught.message : "无法读取课程练习。");
    });
    return () => { cancelled = true; };
  }, [api, connectionMode, sessionId]);

  useEffect(() => {
    if (!sessionId || connectionMode !== "api" || activeMode !== "role_play") {
      setRolePlayTurns([]);
      return;
    }
    let cancelled = false;
    void api.listTurns(sessionId).then((items) => {
      if (!cancelled) setRolePlayTurns(items);
    }).catch((caught) => {
      if (!cancelled) setError(caught instanceof Error ? caught.message : "无法读取角色扮演记录。");
    });
    return () => { cancelled = true; };
  }, [api, activeMode, connectionMode, sessionId]);

  const createLesson = async () => {
    if (connectionMode !== "api" || !selectedLines.length || selectedLines.length > 100) return;
    setBusy(true);
    setError(null);
    setFeedback(null);
    try {
      const learnerId = await ensureJapaneseLearner(api);
      const result = await api.createProjectLesson(learnerId, {
        sourceProjectId: project.id,
        lessonMode: mode,
        scenario: sceneId === "all" ? project.name : `${project.name} · ${sceneId}`,
        lines: selectedLines.map((line) => ({
          line_id: line.lineId,
          scene_id: line.sceneId,
          text: line.text,
          speaker: characters.find((character) => character.id === line.speakerId)?.name ?? undefined,
          listener: line.listener || undefined,
          context: [line.intent, line.subtext].filter(Boolean).join("；") || undefined,
          locale: line.locale,
        })),
      });
      setSessions((current) => [result.session, ...current]);
      setSessionId(result.session.id);
      setExercises(result.exercises);
      setExerciseId(result.exercises[0]?.id ?? "");
      setRolePlayTurns([]);
      recorder.clear();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "项目课程创建失败，请重试。");
    } finally {
      setBusy(false);
    }
  };

  const submitShadowing = async () => {
    if (!activeExercise || !sessionId || !recorder.audioBlob || activeMode !== "shadowing") return;
    setBusy(true);
    setError(null);
    setFeedback(null);
    try {
      const recording = await api.uploadRecording(
        sessionId, recorder.audioBlob, recordingFilename(recorder.audioBlob, "project-lesson-recording"),
      );
      const result = await api.submitShadowingAttempt(sessionId, activeExercise.id, {
        recordingId: recording.recording_id,
      });
      setFeedback(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "跟读提交失败，请检查录音并重试。");
    } finally {
      setBusy(false);
    }
  };

  const submitRolePlay = async () => {
    if (!activeExercise || !sessionId || !recorder.audioBlob || activeMode !== "role_play") return;
    setBusy(true);
    setError(null);
    try {
      const recording = await api.uploadRecording(
        sessionId, recorder.audioBlob, recordingFilename(recorder.audioBlob, "project-role-play"),
      );
      const turn = await api.submitRolePlayTurn(sessionId, activeExercise.id, recording.recording_id);
      setRolePlayTurns((current) => [...current, turn]);
      recorder.clear();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "角色扮演提交失败；录音仍可重试。");
    } finally {
      setBusy(false);
    }
  };

  const selectExercise = (id: string) => {
    setExerciseId(id);
    setFeedback(null);
    setShowAnswer(false);
    recorder.clear();
  };

  return (
    <div className="io-grid">
      <Panel className="import-card">
        <div className="panel-heading"><div><h2>项目台词转日语课程</h2><p>保留项目、场景、台词与角色来源；示范音使用标准参考声。</p></div></div>
        <p>检测到 {japaneseLines.length} 条日语台词。仅纳入 locale 以 ja 开头且文本非空的台词；每次最多 100 条。</p>
        <Field label="课程模式"><select value={mode} onChange={(event) => setMode(event.target.value as ProjectLessonMode)}>
          {Object.entries(modeLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></Field>
        <Field label="来源场景"><select value={sceneId} onChange={(event) => setSceneId(event.target.value)}>
          <option value="all">全部日语场景</option>
          {sceneIds.map((id) => <option key={id} value={id}>{id || "未命名场景"}</option>)}
        </select></Field>
        <p>本次将创建 {selectedLines.length} 条练习。{selectedLines.length > 100 ? "超过单次 100 条上限，请选择一个场景。" : ""}</p>
        <Button tone="primary" busy={busy} disabled={connectionMode !== "api" || !selectedLines.length || selectedLines.length > 100 || busy} onClick={() => void createLesson()}>
          创建并保存课程
        </Button>
        {connectionMode !== "api" ? <p>当前是浏览器 Mock；连接本地 API 后才能创建持久课程。</p> : null}
        {!japaneseLines.length ? <p>先导入日语台词，或把需要练习的台词 locale 改为 ja-JP。</p> : null}
      </Panel>

      <Panel className="export-card">
        <div className="panel-heading"><div><h2>已保存课程与练习</h2><p>刷新页面后仍可从学习者记录恢复。</p></div><Badge tone={sessions.length ? "success" : "neutral"}>{sessions.length} 门</Badge></div>
        {sessions.length ? <Field label="选择课程"><select value={sessionId} onChange={(event) => {
          setSessionId(event.target.value);
          setFeedback(null);
          recorder.clear();
        }}>
          {sessions.map((session) => <option key={session.id} value={session.id}>
            {session.scenario} · {modeLabel[session.metadata.lesson_mode as ProjectLessonMode] ?? "课程"}
          </option>)}
        </select></Field> : <p>尚无已保存课程。</p>}
        {exercises.length ? <div>
          <p>共 {exercises.length} 条练习。参考音只通过受控媒体接口播放；评分只使用新上传的原录音。</p>
          <Field label="选择练习"><select value={exerciseId} onChange={(event) => selectExercise(event.target.value)}>
            {exercises.map((exercise, index) => <option key={exercise.id} value={exercise.id}>
              {index + 1}. {exercise.expected_text}
            </option>)}
          </select></Field>
          {activeExercise?.reference_audio_url ? <div><p>参考音 A</p><audio controls src={api.assetUrl(activeExercise.reference_audio_url)} /></div> : null}
          {activeMode === "dictation" ? <div>
            <Field label="听写输入"><textarea aria-label="听写输入" placeholder="先听参考音，再写下听到的台词。" /></Field>
            <Button onClick={() => setShowAnswer((value) => !value)}>{showAnswer ? "隐藏参考答案" : "显示参考答案"}</Button>
            {showAnswer ? <p>参考答案：{activeExercise?.expected_text}</p> : null}
            <p>听写输入仅供自查；此版本不保存或评分听写结果。</p>
          </div> : null}
          {activeMode === "role_play" ? <div>
            <p>角色台词：{activeExercise?.expected_text}</p>
            <p>场景证据：{String(activeExercise?.metadata.source_scene_id ?? "未记录")}；对话对象：{String(activeExercise?.metadata.listener ?? "未记录")}</p>
            {recorder.status === "recording"
              ? <Button onClick={recorder.stop}>结束录音</Button>
              : <Button onClick={() => void recorder.start()} disabled={busy}>录制角色回应</Button>}
            {recorder.audioUrl ? <div><p>原录音 B（未染色）</p><audio controls src={recorder.audioUrl} /></div> : null}
            <Button tone="primary" busy={busy} disabled={!recorder.audioBlob || busy} onClick={() => void submitRolePlay()}>
              提交原声并获取教师回应
            </Button>
            {recorder.error ? <p role="alert">{recorder.error}</p> : null}
            <p>该练习已保存 {exerciseRolePlayTurns.length} 轮。回复与纠错来自配置的教师或 Mock 后备，不代表客观口语准确率。</p>
            {exerciseRolePlayTurns.map((turn) => <div key={turn.id}>
              <p>第 {turn.sequence} 轮：{turn.transcript.text}（转写置信度 {turn.transcript.confidence.toFixed(2)}）</p>
              <p>教师：{turn.teacher.reply_text}</p>
              {turn.teacher.feedback.length ? <p>建议：{turn.teacher.feedback.join("；")}</p> : null}
              {turn.demonstration.audio_url ? <audio controls src={api.assetUrl(turn.demonstration.audio_url)} /> : null}
            </div>)}
          </div> : null}
          {activeMode === "shadowing" ? <div>
            <p>跟读台词：{activeExercise?.expected_text}</p>
            {recorder.status === "recording"
              ? <Button onClick={recorder.stop}>结束录音</Button>
              : <Button onClick={() => void recorder.start()} disabled={busy}>开始原声录音</Button>}
            {recorder.audioUrl ? <div><p>原录音 B（未染色）</p><audio controls src={recorder.audioUrl} /></div> : null}
            <Button tone="primary" busy={busy} disabled={!recorder.audioBlob || busy} onClick={() => void submitShadowing()}>
              提交原声并获取分项反馈
            </Button>
            {recorder.error ? <p role="alert">{recorder.error}</p> : null}
            {feedback ? <div>
              <p>已保存跟读尝试。以下是启发式证据，不是绝对准确率或总分。</p>
              {(["content", "mora", "rhythm", "pitch"] as const).map((key) => {
                const item = feedback.feedback[key];
                return item ? <p key={key}>{key}：{item.summary}（置信度 {item.confidence.toFixed(2)}；{item.value === null ? "无可用数值" : `参考值 ${item.value.toFixed(2)}`}）</p> : null;
              })}
              {feedback.feedback.priorities.length ? <p>优先重说：{feedback.feedback.priorities.join("；")}</p> : null}
            </div> : null}
          </div> : null}
        </div> : null}
        {error ? <p role="alert">{error}</p> : null}
      </Panel>
    </div>
  );
};
