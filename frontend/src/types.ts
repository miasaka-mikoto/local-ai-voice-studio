export type ProjectKind =
  | "video_dubbing"
  | "game_voice"
  | "voice_dataset"
  | "japanese_learning";

export type ProjectStatus = "draft" | "active" | "blocked" | "completed";

export type JobStatus =
  | "queued"
  | "running"
  | "paused"
  | "failed"
  | "completed"
  | "stale"
  | "cancelled";

export type JobAction = "pause" | "resume" | "retry" | "cancel" | "recompute";

export type ConnectionMode = "api" | "mock";

export interface Project {
  id: string;
  name: string;
  kind: ProjectKind;
  status: ProjectStatus;
  description: string;
  locale: string;
  progress: number;
  lineCount: number;
  selectedTakeCount: number;
  characterCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface CreateProjectInput {
  name: string;
  kind: ProjectKind;
  description?: string;
  locale?: string;
}

export interface DialogueLine {
  id: string;
  projectId: string;
  lineId: string;
  sceneId: string;
  index: number;
  startMs: number | null;
  endMs: number | null;
  sourceText: string;
  text: string;
  locale: string;
  speakerId: string | null;
  listener: string;
  intent: string;
  subtext: string;
  emotion: string;
  emotionIntensity: number;
  pace: number;
  pitch: number;
  volume: number;
  breath: string;
  pause: string;
  pronunciation: string;
  durationBudgetMs: number | null;
  voiceProfileId: string | null;
  engineId: string;
  seed: number;
  selectedTakeId: string | null;
  selectionLocked: boolean;
  revision: number;
  stale: boolean;
}

export type DialogueLinePatch = Partial<
  Omit<DialogueLine, "id" | "projectId" | "lineId" | "index" | "revision">
>;

export interface Character {
  id: string;
  projectId: string;
  characterId: string;
  name: string;
  color: string;
  identity: string;
  ageImpression: string;
  timbre: string;
  speechHabits: string;
  politeness: string;
  voiceProfileId: string | null;
  authorizationStatus: "verified" | "pending" | "restricted" | "unknown";
}

export interface VoiceProfile {
  id: string;
  name: string;
  engineId: string;
  locale: string;
  description: string;
  sampleUrl?: string;
  authorizationStatus: "verified" | "pending" | "restricted";
  licenseNote: string;
}

export interface Take {
  id: string;
  projectId: string;
  lineId: string;
  index: number;
  engineId: string;
  modelVersion: string;
  seed: number;
  durationMs: number;
  sampleRate: number;
  subtype: string;
  loudnessLufs: number | null;
  status: "queued" | "generating" | "ready" | "failed" | "stale";
  audioUrl?: string;
  emotion: string;
  qualityScore: number | null;
  selected: boolean;
  inputHash: string;
  createdAt: string;
}

export interface Job {
  id: string;
  projectId: string | null;
  kind: string;
  label: string;
  status: JobStatus;
  progress: number;
  stage: string;
  engineId: string | null;
  attempt: number;
  error: string | null;
  recoverable: boolean;
  allowedActions: JobAction[];
  createdAt: string;
  updatedAt: string;
}

export interface EngineStatus {
  id: string;
  name: string;
  role: string;
  deploymentStatus: string;
  runtimeStatus: "running" | "stopped" | "unreachable" | "unknown";
  license: string;
  licenseRisk: "low" | "review" | "restricted";
  languages: string[];
  capabilities: string[];
  sampleRate: number | null;
  vramGb: number | null;
  url?: string;
}

export interface SystemStatus {
  apiVersion: string;
  hostname: string;
  platform: string;
  gpuName: string;
  gpuUsedMb: number;
  gpuTotalMb: number;
  ramAvailableGb: number;
  ramTotalGb: number;
  diskFreeGb: number;
  gpuScheduler: "idle" | "busy" | "blocked";
  activeEngineId: string | null;
  ffmpegReady: boolean;
  databaseReady: boolean;
  lastUpdatedAt: string;
}

export interface ImportedLine {
  lineId: string;
  sceneId: string;
  startMs: number | null;
  endMs: number | null;
  speaker: string;
  listener: string;
  text: string;
  emotion: string;
  locale: string;
  durationLimitMs: number | null;
  assetName: string;
}

export interface ImportPreview {
  format: "srt" | "ass" | "csv" | "json" | "jsonl" | "text";
  lines: ImportedLine[];
  warnings: string[];
}

export interface ConversationTurn {
  id: string;
  role: "learner" | "teacher";
  text: string;
  translation?: string;
  feedback?: string;
  confidence?: number;
  audioUrl?: string;
  createdAt: string;
}

export interface ShadowFeedback {
  source?: "api" | "mock";
  content: { score: number | null; evidence: string; confidence: number; details?: Record<string, unknown>; limitations?: string[] };
  rhythm: { score: number | null; evidence: string; confidence: number; details?: Record<string, unknown>; limitations?: string[] };
  pitch: { score: number | null; evidence: string; confidence: number; details?: Record<string, unknown>; limitations?: string[] };
  mora?: { score: number | null; evidence: string; confidence: number; details?: Record<string, unknown>; limitations?: string[] };
  referenceF0?: number[];
  learnerF0?: number[];
  normalizedTime?: number[];
  expectedMoraSegmentsApprox?: string[];
  actualMoraSegmentsApprox?: string[];
  priorities?: string[];
  scoringSourceKind?: "original_uncolored";
  recordingId?: string;
  referenceAudioUrl?: string;
}

export interface StudioSnapshot {
  projects: Project[];
  lines: DialogueLine[];
  characters: Character[];
  voices: VoiceProfile[];
  takes: Take[];
  jobs: Job[];
  engines: EngineStatus[];
  system: SystemStatus;
  conversations: ConversationTurn[];
}

export interface HealthResult {
  ok: boolean;
  version: string;
  message: string;
}

export interface RuntimeConfig {
  apiBaseUrl: string;
  requestedMode: "auto" | "api" | "mock";
  mockAllowed: boolean;
}
