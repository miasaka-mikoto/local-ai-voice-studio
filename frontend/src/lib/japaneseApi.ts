import type { ConversationTurn, ShadowFeedback } from "../types";

export type ApiCoachMode = "fluent" | "strict";
export type ApiLearningMode = "conversation" | "shadowing" | "pronunciation_clinic" | "sentence_repair" | "project_lesson";
export type ProjectLessonMode = "dictation" | "shadowing" | "role_play";

export interface JapaneseLearnerResponse {
  id: string;
  display_name: string;
  level: string;
  goals: string[];
  interests: string[];
  created_at: string;
  updated_at: string;
}

export interface JapaneseSessionResponse {
  id: string;
  learner_id: string;
  mode: ApiLearningMode;
  coach_mode: ApiCoachMode;
  scenario: string;
  status: "active" | "completed" | "cancelled";
  metadata: Record<string, unknown>;
  started_at: string;
  ended_at: string | null;
}

export interface JapaneseExerciseResponse {
  id: string;
  learner_id: string;
  session_id: string | null;
  exercise_type: ProjectLessonMode | "pronunciation" | "sentence_repair";
  expected_text: string;
  reference_audio_path: string | null;
  reference_audio_url: string | null;
  metadata: Record<string, unknown>;
}

export interface ProjectLessonLineInput {
  line_id?: string;
  scene_id?: string;
  text: string;
  speaker?: string;
  listener?: string;
  context?: string;
  locale?: string;
}

export interface ProjectLessonResponse {
  session: JapaneseSessionResponse;
  source_project_id: string;
  lesson_mode: ProjectLessonMode;
  exercises: JapaneseExerciseResponse[];
  policy: string;
}

export type CurriculumScenarioStatus = "completed" | "in_progress" | "available" | "locked";

export interface JapaneseCurriculumScenario {
  id: string;
  stage_id: string;
  level: "N5" | "N4" | "N3" | "N2" | "N1";
  domain: string;
  title: string;
  japanese_title: string;
  objective: string;
  grammar_targets: string[];
  sample_utterances: string[];
  prerequisites: string[];
  lesson_steps: string[];
  completion_policy: {
    minimum_turns: number;
    requires_manual_complete: boolean;
    meaning: string;
  };
}

export interface JapaneseCurriculumStage {
  id: string;
  order: number;
  title: string;
  level_range: string;
  outcome: string;
  weekly_shape: { conversation: number; shadowing: number; review: number };
}

export interface JapaneseCurriculumResponse {
  version: string;
  stages: JapaneseCurriculumStage[];
  scenarios: JapaneseCurriculumScenario[];
  coverage: { scenario_count: number; domains: string[]; levels: string[]; scope_note: string };
}

export interface JapaneseLearningPathScenario extends JapaneseCurriculumScenario {
  status: CurriculumScenarioStatus;
  missing_prerequisites: string[];
  evidence: {
    session_ids: string[];
    completed_session_count: number;
    active_session_count: number;
    turn_count: number;
    last_started_at: string | null;
  };
}

export interface JapaneseLearningPathResponse {
  catalog_version: string;
  learner_id: string;
  placement_level: string;
  summary: {
    completed: number;
    in_progress: number;
    available: number;
    locked: number;
    total: number;
    due_review_count: number;
  };
  stages: Array<JapaneseCurriculumStage & {
    scenarios: JapaneseLearningPathScenario[];
    completion: { completed: number; total: number; ratio: number; meaning: string };
  }>;
  recommendations: Array<{
    kind: "review" | "continue_scenario" | "new_scenario";
    title: string;
    reason: string;
    scenario_id?: string;
    review_id?: string;
    evidence: Record<string, unknown>;
  }>;
  curve: Array<{ stage_id: string; label: string; completed: number; total: number; ratio: number }>;
  policy: Record<string, string>;
  generated_at: string;
}

export interface JapaneseProgressResponse {
  learner_id: string;
  level: string;
  counts: Record<string, number>;
  due_review_count: number;
  metrics: Record<string, {
    recent_mean: number | null;
    mean_confidence: number;
    sample_count: number;
    direction: string;
    evidence_window: string;
  }>;
  today_priorities: Array<Record<string, unknown>>;
  policy: string;
  generated_at: string;
}

export interface RecordingUploadResponse {
  id: string;
  recording_id: string;
  session_id: string;
  storage_path: string;
  sha256: string;
  source_type: "browser_original_upload" | "imported_original" | "generated_reference" | "voice_colored";
  upload_entry: string;
  original_filename: string;
  content_type: string;
  byte_size: number;
  created_at: string;
  /** Compatibility mirror emitted by the router; never used as provenance. */
  audio_path?: string;
}

export interface ApiTranscript {
  text: string;
  confidence: number;
  provider: string;
  segments: Record<string, unknown>[];
  evidence: string[];
  fallback_used: boolean;
}

export interface ApiTeacherResult {
  reply_text: string;
  demonstration_text: string;
  feedback: string[];
  repair: {
    original: string;
    minimal_correction: string;
    natural_expression: string;
    model_answer: string;
    issues: string[];
    confidence: number;
    evidence: string[];
  } | null;
  provider: string;
  confidence: number;
  fallback_used: boolean;
}

export interface ApiDemonstration {
  audio_path: string;
  audio_url?: string;
  provider: string;
  voice_role: "standard_tokyo" | "immersive_character";
  sample_rate: number;
  subtype: string;
  fallback_used: boolean;
}

export interface JapaneseTurnResponse {
  id: string;
  session_id: string;
  recording_id: string;
  exercise_id: string | null;
  sequence: number;
  original_audio_path: string;
  original_audio_sha256: string;
  transcript: ApiTranscript;
  teacher: ApiTeacherResult;
  demonstration: ApiDemonstration;
  scoring_source_kind: "original_uncolored";
  created_at: string;
}

export interface ApiMetricFeedback {
  metric: "content" | "mora" | "rhythm" | "pitch";
  value: number | null;
  confidence: number;
  summary: string;
  evidence: Record<string, unknown>;
  limitations: string[];
}

export interface ShadowingApiResponse {
  attempt_id: string;
  exercise: Record<string, unknown>;
  transcript: ApiTranscript;
  feedback: {
    content: ApiMetricFeedback;
    mora?: ApiMetricFeedback;
    rhythm: ApiMetricFeedback;
    pitch: ApiMetricFeedback;
    priorities: string[];
    scoring_source_path: string;
    scoring_source_kind: "original_uncolored";
    reference_audio_path: string;
    analyzed_at: string;
  };
  ab_playback: {
    recording_id: string;
    reference_audio_path: string;
    original_recording_path: string;
    reference_audio_url: string;
  };
  review_item_ids: string[];
}

export interface ShadowReferenceResponse {
  exercise: {
    id: string;
    learner_id: string;
    session_id: string;
    expected_text: string;
    reference_audio_path: string;
    [key: string]: unknown;
  };
  synthesis: ApiDemonstration & { audio_url: string };
}

export class JapaneseApiError extends Error {
  readonly status: number | null;
  readonly detail: string;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "JapaneseApiError";
    this.status = status;
    this.detail = message;
  }
}

export class JapaneseLearningApi {
  readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  private async json<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          Accept: "application/json",
          ...(init?.body && typeof init.body === "string" ? { "Content-Type": "application/json" } : {}),
          ...init?.headers,
        },
      });
    } catch {
      throw new JapaneseApiError(`无法连接日语学习 API：${this.baseUrl}`, null);
    }
    if (!response.ok) {
      let detail = `日语 API 请求失败（HTTP ${response.status}）`;
      try {
        const body = (await response.json()) as { detail?: string; message?: string };
        detail = body.detail ?? body.message ?? detail;
      } catch {
        // Keep the status-based message for non-JSON responses.
      }
      throw new JapaneseApiError(detail, response.status);
    }
    return (await response.json()) as T;
  }

  health() {
    return this.json<{ status: "ok"; scoring_policy: string; score_shape: string }>("/api/japanese/health");
  }

  curriculum() {
    return this.json<JapaneseCurriculumResponse>("/api/japanese/curriculum");
  }

  createLearner(input: { displayName: string; level: string; goals: string[]; interests: string[] }) {
    return this.json<JapaneseLearnerResponse>("/api/japanese/learners", {
      method: "POST",
      body: JSON.stringify({
        display_name: input.displayName,
        level: input.level,
        goals: input.goals,
        interests: input.interests,
      }),
    });
  }

  getLearner(learnerId: string) {
    return this.json<JapaneseLearnerResponse>(`/api/japanese/learners/${encodeURIComponent(learnerId)}`);
  }

  listSessions(learnerId: string) {
    return this.json<JapaneseSessionResponse[]>(`/api/japanese/learners/${encodeURIComponent(learnerId)}/sessions`);
  }

  listSessionExercises(sessionId: string) {
    return this.json<JapaneseExerciseResponse[]>(`/api/japanese/sessions/${encodeURIComponent(sessionId)}/exercises`);
  }

  createProjectLesson(learnerId: string, input: {
    sourceProjectId: string;
    lessonMode: ProjectLessonMode;
    scenario: string;
    lines: ProjectLessonLineInput[];
  }) {
    return this.json<ProjectLessonResponse>(
      `/api/japanese/learners/${encodeURIComponent(learnerId)}/project-lessons`,
      {
        method: "POST",
        body: JSON.stringify({
          source_project_id: input.sourceProjectId,
          lesson_mode: input.lessonMode,
          scenario: input.scenario,
          coach_mode: "strict",
          reference_voice_role: "standard_tokyo",
          lines: input.lines,
        }),
      },
    );
  }

  createSession(input: {
    learnerId: string;
    mode: ApiLearningMode;
    coachMode: ApiCoachMode;
    scenario: string;
    metadata?: Record<string, unknown>;
  }) {
    return this.json<JapaneseSessionResponse>("/api/japanese/sessions", {
      method: "POST",
      body: JSON.stringify({
        learner_id: input.learnerId,
        mode: input.mode,
        coach_mode: input.coachMode,
        scenario: input.scenario,
        metadata: input.metadata ?? {},
      }),
    });
  }

  completeSession(sessionId: string) {
    return this.json<JapaneseSessionResponse>(`/api/japanese/sessions/${encodeURIComponent(sessionId)}/complete`, {
      method: "POST",
    });
  }

  learningPath(learnerId: string) {
    return this.json<JapaneseLearningPathResponse>(`/api/japanese/learners/${encodeURIComponent(learnerId)}/learning-path`);
  }

  progress(learnerId: string) {
    return this.json<JapaneseProgressResponse>(`/api/japanese/learners/${encodeURIComponent(learnerId)}/progress`);
  }

  listTurns(sessionId: string) {
    return this.json<JapaneseTurnResponse[]>(`/api/japanese/sessions/${encodeURIComponent(sessionId)}/turns`);
  }

  uploadRecording(sessionId: string, recording: Blob, filename = "browser-recording.webm") {
    const query = new URLSearchParams({ session_id: sessionId, filename });
    return this.json<RecordingUploadResponse>(`/api/japanese/recordings?${query.toString()}`, {
      method: "POST",
      body: recording,
      headers: { "Content-Type": recording.type || "audio/webm" },
    });
  }

  processTurn(sessionId: string, input: {
    recordingId: string;
    transcriptHint?: string;
    expectedText?: string;
    voiceRole?: "standard_tokyo" | "immersive_character";
  }) {
    return this.json<JapaneseTurnResponse>(`/api/japanese/sessions/${encodeURIComponent(sessionId)}/turns`, {
      method: "POST",
      body: JSON.stringify({
        recording_id: input.recordingId,
        transcript_hint: input.transcriptHint || null,
        expected_text: input.expectedText || null,
        voice_role: input.voiceRole ?? "standard_tokyo",
      }),
    });
  }

  submitRolePlayTurn(sessionId: string, exerciseId: string, recordingId: string) {
    return this.json<JapaneseTurnResponse>(
      `/api/japanese/sessions/${encodeURIComponent(sessionId)}/role-play/exercises/${encodeURIComponent(exerciseId)}/turns`,
      {
        method: "POST",
        body: JSON.stringify({ recording_id: recordingId, voice_role: "standard_tokyo" }),
      },
    );
  }

  analyzeShadowing(sessionId: string, input: {
    referenceAudioPath: string;
    recordingId: string;
    expectedText: string;
    transcriptHint?: string;
  }) {
    return this.json<ShadowingApiResponse>(`/api/japanese/sessions/${encodeURIComponent(sessionId)}/shadowing`, {
      method: "POST",
      body: JSON.stringify({
        reference_audio_path: input.referenceAudioPath,
        recording_id: input.recordingId,
        expected_text: input.expectedText,
        transcript_hint: input.transcriptHint || null,
      }),
    });
  }

  createShadowingReference(sessionId: string, expectedText: string) {
    return this.json<ShadowReferenceResponse>(`/api/japanese/sessions/${encodeURIComponent(sessionId)}/shadowing/references`, {
      method: "POST",
      body: JSON.stringify({ expected_text: expectedText, voice_role: "standard_tokyo" }),
    });
  }

  submitShadowingAttempt(sessionId: string, exerciseId: string, input: {
    recordingId: string;
    transcriptHint?: string;
  }) {
    return this.json<ShadowingApiResponse>(
      `/api/japanese/sessions/${encodeURIComponent(sessionId)}/shadowing/exercises/${encodeURIComponent(exerciseId)}/attempts`,
      {
        method: "POST",
        body: JSON.stringify({
          recording_id: input.recordingId,
          transcript_hint: input.transcriptHint || null,
        }),
      },
    );
  }

  assetUrl(relativeOrAbsolute: string) {
    return new URL(relativeOrAbsolute, `${this.baseUrl}/`).toString();
  }
}

const storageKey = (baseUrl: string, kind: "learner" | "conversation" | "shadowing", scope?: string) =>
  `local-ai-voice-studio.jp.${kind}.${encodeURIComponent(baseUrl)}${scope ? `.${encodeURIComponent(scope)}` : ""}`;

export const readStoredJapaneseLearner = (baseUrl: string) =>
  localStorage.getItem(storageKey(baseUrl, "learner"));

export const ensureJapaneseLearner = async (api: JapaneseLearningApi): Promise<string> => {
  const learnerKey = storageKey(api.baseUrl, "learner");
  const stored = localStorage.getItem(learnerKey);
  if (stored) {
    try {
      await api.getLearner(stored);
      return stored;
    } catch (error) {
      if (!(error instanceof JapaneseApiError) || error.status !== 400) throw error;
      localStorage.removeItem(learnerKey);
    }
  }
  const learner = await api.createLearner({
    displayName: "本机学习者",
    level: "N4",
    goals: ["自然会话", "mora 节奏", "音高重音"],
    interests: ["旅行", "动漫", "游戏"],
  });
  localStorage.setItem(learnerKey, learner.id);
  return learner.id;
};

export const readStoredJapaneseSession = (baseUrl: string, mode: "conversation" | "shadowing", scope?: string) =>
  localStorage.getItem(storageKey(baseUrl, mode, scope));

export const clearStoredJapaneseSession = (baseUrl: string, mode: "conversation" | "shadowing", scope?: string) =>
  localStorage.removeItem(storageKey(baseUrl, mode, scope));

export const ensureJapaneseSession = async (
  api: JapaneseLearningApi,
  input: {
    mode: "conversation" | "shadowing";
    coachMode: ApiCoachMode;
    scenario: string;
    scenarioId?: string;
    metadata?: Record<string, unknown>;
  },
) => {
  const sessionScope = input.mode === "conversation" ? input.scenarioId : undefined;
  const existingSession = readStoredJapaneseSession(api.baseUrl, input.mode, sessionScope);
  if (existingSession) return existingSession;

  const learnerKey = storageKey(api.baseUrl, "learner");
  let learnerId = localStorage.getItem(learnerKey);
  if (!learnerId) {
    const learner = await api.createLearner({
      displayName: "本机学习者",
      level: "N4",
      goals: ["自然会话", "mora 节奏", "音高重音"],
      interests: ["旅行", "动漫", "游戏"],
    });
    learnerId = learner.id;
    localStorage.setItem(learnerKey, learnerId);
  }

  try {
    const session = await api.createSession({
      learnerId,
      mode: input.mode,
      coachMode: input.coachMode,
      scenario: input.scenario,
      metadata: {
        client: "react-frontend",
        upload: "browser-webm-opus",
        ...(input.scenarioId ? { curriculum_scenario_id: input.scenarioId } : {}),
        ...input.metadata,
      },
    });
    localStorage.setItem(storageKey(api.baseUrl, input.mode, sessionScope), session.id);
    return session.id;
  } catch (error) {
    if (!(error instanceof JapaneseApiError) || error.status !== 400) throw error;
    localStorage.removeItem(learnerKey);
    const learner = await api.createLearner({
      displayName: "本机学习者",
      level: "N4",
      goals: ["自然会话", "mora 节奏", "音高重音"],
      interests: ["旅行", "动漫", "游戏"],
    });
    localStorage.setItem(learnerKey, learner.id);
    const session = await api.createSession({
      learnerId: learner.id,
      mode: input.mode,
      coachMode: input.coachMode,
      scenario: input.scenario,
      metadata: {
        client: "react-frontend",
        upload: "browser-webm-opus",
        ...(input.scenarioId ? { curriculum_scenario_id: input.scenarioId } : {}),
        ...input.metadata,
      },
    });
    localStorage.setItem(storageKey(api.baseUrl, input.mode, sessionScope), session.id);
    return session.id;
  }
};

export const apiTurnToUiTurns = (turn: JapaneseTurnResponse, baseUrl = "http://127.0.0.1"): ConversationTurn[] => [
  {
    id: `${turn.id}-learner`,
    role: "learner",
    text: turn.transcript.text,
    feedback: `ASR: ${turn.transcript.provider}${turn.transcript.fallback_used ? "（fallback）" : ""}`,
    confidence: turn.transcript.confidence,
    createdAt: turn.created_at,
  },
  {
    id: `${turn.id}-teacher`,
    role: "teacher",
    text: turn.teacher.reply_text,
    translation: turn.teacher.demonstration_text,
    audioUrl: new URL(
      turn.demonstration.audio_url ?? `/api/japanese/turns/${encodeURIComponent(turn.id)}/demonstration`,
      `${baseUrl.replace(/\/$/, "")}/`,
    ).toString(),
    feedback: turn.teacher.feedback.join("；"),
    confidence: turn.teacher.confidence,
    createdAt: turn.created_at,
  },
];

const metricToUi = (metric: ApiMetricFeedback) => ({
  score: metric.value === null ? null : Math.round(metric.value * 100),
  evidence: metric.summary,
  confidence: metric.confidence,
  details: metric.evidence,
  limitations: metric.limitations,
});

const numberArray = (value: unknown) =>
  Array.isArray(value) && value.every((item) => typeof item === "number" && Number.isFinite(item))
    ? value as number[]
    : undefined;

const stringArray = (value: unknown) =>
  Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value as string[]
    : undefined;

export const apiShadowingToUi = (response: ShadowingApiResponse): ShadowFeedback => ({
  source: "api",
  content: metricToUi(response.feedback.content),
  rhythm: metricToUi(response.feedback.rhythm),
  pitch: metricToUi(response.feedback.pitch),
  priorities: response.feedback.priorities,
  scoringSourceKind: response.feedback.scoring_source_kind,
  referenceAudioUrl: response.ab_playback.reference_audio_url,
  normalizedTime: numberArray(response.feedback.pitch.evidence.normalized_time),
  referenceF0: numberArray(response.feedback.pitch.evidence.normalized_reference_f0_semitones),
  learnerF0: numberArray(response.feedback.pitch.evidence.normalized_recording_f0_semitones),
  recordingId: response.ab_playback.recording_id,
  expectedMoraSegmentsApprox:
    stringArray(response.feedback.rhythm.evidence.expected_mora_segments_approx)
    ?? stringArray(response.feedback.mora?.evidence.expected_segments_approx),
  actualMoraSegmentsApprox:
    stringArray(response.feedback.rhythm.evidence.actual_mora_segments_approx)
    ?? stringArray(response.feedback.mora?.evidence.actual_segments_approx),
});
