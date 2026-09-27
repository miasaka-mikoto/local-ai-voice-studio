import { createSeedSnapshot } from "../data/seed";
import type {
  Character,
  ConnectionMode,
  ConversationTurn,
  CreateProjectInput,
  DialogueLinePatch,
  HealthResult,
  ImportedLine,
  JobAction,
  RuntimeConfig,
  StudioSnapshot,
} from "../types";

const SNAPSHOT_KEY = "local-ai-voice-studio.mock.v2";
const API_BASE_KEY = "local-ai-voice-studio.api-base";
const DATA_MODE_KEY = "local-ai-voice-studio.data-mode";
const DEFAULT_API_BASE = "http://127.0.0.1:8766";

const uuid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

const clone = <T,>(value: T): T => structuredClone(value);

const nowIso = () => new Date().toISOString();

const delay = (milliseconds = 180) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

const actionsForStatus = (status: string): JobAction[] => {
  if (status === "queued") return ["cancel"];
  if (status === "running") return ["pause", "cancel"];
  if (status === "paused") return ["resume", "cancel"];
  if (status === "failed") return ["retry"];
  if (status === "stale") return ["recompute"];
  return [];
};

export class GatewayError extends Error {
  readonly code: string;
  readonly recoverable: boolean;
  readonly status: number | null;

  constructor(message: string, options?: { code?: string; recoverable?: boolean; status?: number | null }) {
    super(message);
    this.name = "GatewayError";
    this.code = options?.code ?? "gateway_error";
    this.recoverable = options?.recoverable ?? true;
    this.status = options?.status ?? null;
  }
}

export const normalizeLoopbackApiBase = (value: string) => {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    throw new GatewayError("API 基址必须是有效的本机 HTTP URL。", { code: "invalid_api_base" });
  }
  const loopbackHosts = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);
  if (!['http:', 'https:'].includes(url.protocol) || !loopbackHosts.has(url.hostname)) {
    throw new GatewayError("API 基址只允许 127.0.0.1、localhost 或 ::1。", { code: "non_loopback_api_base" });
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new GatewayError("API 基址不能包含凭据、查询参数或片段。", { code: "invalid_api_base" });
  }
  return url.toString().replace(/\/$/, "");
};

export interface StudioGateway {
  readonly mode: ConnectionMode;
  readonly apiBaseUrl: string;
  health(): Promise<HealthResult>;
  getSnapshot(): Promise<StudioSnapshot>;
  createProject(input: CreateProjectInput): Promise<StudioSnapshot>;
  updateLine(projectId: string, lineId: string, patch: DialogueLinePatch, revision: number): Promise<StudioSnapshot>;
  importLines(projectId: string, lines: ImportedLine[]): Promise<StudioSnapshot>;
  generateTakes(projectId: string, lineId: string, count: number): Promise<StudioSnapshot>;
  selectTake(projectId: string, lineId: string, takeId: string, locked: boolean): Promise<StudioSnapshot>;
  updateCharacter(characterId: string, patch: Partial<Character>): Promise<StudioSnapshot>;
  actOnJob(jobId: string, action: JobAction): Promise<StudioSnapshot>;
  addConversationTurn(text: string, coachMode: "flow" | "strict"): Promise<StudioSnapshot>;
  resetMock?(): Promise<StudioSnapshot>;
}

export const readRuntimeConfig = (): RuntimeConfig => {
  const envBase = import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_API_BASE;
  const envMode = import.meta.env.VITE_DATA_MODE ?? "auto";
  const storedBase = typeof localStorage !== "undefined" ? localStorage.getItem(API_BASE_KEY) : null;
  const storedMode = typeof localStorage !== "undefined" ? localStorage.getItem(DATA_MODE_KEY) : null;
  const requestedMode = storedMode === "api" || storedMode === "mock" || storedMode === "auto" ? storedMode : envMode;
  let apiBaseUrl = DEFAULT_API_BASE;
  try {
    apiBaseUrl = normalizeLoopbackApiBase(storedBase || envBase);
  } catch {
    // Ignore stale/unsafe browser configuration and recover to the local default.
  }
  return {
    apiBaseUrl,
    requestedMode,
    mockAllowed: import.meta.env.VITE_ENABLE_MOCK !== "false",
  };
};

export const persistRuntimeConfig = (config: Pick<RuntimeConfig, "apiBaseUrl" | "requestedMode">) => {
  localStorage.setItem(API_BASE_KEY, normalizeLoopbackApiBase(config.apiBaseUrl));
  localStorage.setItem(DATA_MODE_KEY, config.requestedMode);
};

class RestGateway implements StudioGateway {
  readonly mode = "api" as const;
  readonly apiBaseUrl: string;

  constructor(apiBaseUrl: string) {
    this.apiBaseUrl = apiBaseUrl.replace(/\/$/, "");
  }

  private async request<T>(path: string, init?: RequestInit, timeoutMs = 5000): Promise<T> {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${this.apiBaseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          ...(init?.body ? { "Content-Type": "application/json" } : {}),
          ...init?.headers,
        },
      });
      if (!response.ok) {
        let message = `请求失败（HTTP ${response.status}）`;
        let code = "http_error";
        try {
          const body = (await response.json()) as { message?: string; detail?: string; code?: string };
          message = body.message ?? body.detail ?? message;
          code = body.code ?? code;
        } catch {
          // Non-JSON responses are represented by the status message above.
        }
        throw new GatewayError(message, {
          code,
          status: response.status,
          recoverable: response.status >= 500 || response.status === 408 || response.status === 409,
        });
      }
      if (response.status === 204) return undefined as T;
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof GatewayError) throw error;
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new GatewayError(`连接 ${this.apiBaseUrl} 超时。`, { code: "timeout" });
      }
      throw new GatewayError(`无法连接 Voice Studio API：${this.apiBaseUrl}`, { code: "unreachable" });
    } finally {
      window.clearTimeout(timeout);
    }
  }

  health() {
    return this.request<HealthResult>("/api/v1/health", undefined, 1800);
  }

  getSnapshot() {
    return this.request<StudioSnapshot>("/api/v1/bootstrap");
  }

  createProject(input: CreateProjectInput) {
    return this.request<StudioSnapshot>("/api/v1/projects", { method: "POST", body: JSON.stringify(input) });
  }

  updateLine(projectId: string, lineId: string, patch: DialogueLinePatch, revision: number) {
    return this.request<StudioSnapshot>(`/api/v1/projects/${projectId}/lines/${lineId}`, {
      method: "PATCH",
      body: JSON.stringify({ patch, revision }),
    });
  }

  importLines(projectId: string, lines: ImportedLine[]) {
    return this.request<StudioSnapshot>(`/api/v1/projects/${projectId}/imports`, {
      method: "POST",
      body: JSON.stringify({ lines }),
    });
  }

  generateTakes(projectId: string, lineId: string, count: number) {
    return this.request<StudioSnapshot>(`/api/v1/projects/${projectId}/lines/${lineId}/takes`, {
      method: "POST",
      body: JSON.stringify({ count }),
    });
  }

  selectTake(projectId: string, lineId: string, takeId: string, locked: boolean) {
    return this.request<StudioSnapshot>(`/api/v1/projects/${projectId}/lines/${lineId}/takes/${takeId}/select`, {
      method: "POST",
      body: JSON.stringify({ locked }),
    });
  }

  updateCharacter(characterId: string, patch: Partial<Character>) {
    return this.request<StudioSnapshot>(`/api/v1/characters/${characterId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  }

  actOnJob(jobId: string, action: JobAction) {
    return this.request<StudioSnapshot>(`/api/v1/tasks/${jobId}/${action}`, { method: "POST" });
  }

  addConversationTurn(text: string, coachMode: "flow" | "strict") {
    return this.request<StudioSnapshot>("/api/v1/japanese/sessions/default/turns", {
      method: "POST",
      body: JSON.stringify({ text, coachMode }),
    });
  }
}

class MockGateway implements StudioGateway {
  readonly mode = "mock" as const;
  readonly apiBaseUrl: string;

  constructor(apiBaseUrl: string) {
    this.apiBaseUrl = apiBaseUrl;
  }

  private read(): StudioSnapshot {
    const stored = localStorage.getItem(SNAPSHOT_KEY);
    if (!stored) {
      const seeded = createSeedSnapshot();
      this.write(seeded);
      return seeded;
    }
    try {
      return JSON.parse(stored) as StudioSnapshot;
    } catch {
      const seeded = createSeedSnapshot();
      this.write(seeded);
      return seeded;
    }
  }

  private write(snapshot: StudioSnapshot) {
    localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snapshot));
  }

  private async mutate(change: (snapshot: StudioSnapshot) => void): Promise<StudioSnapshot> {
    await delay();
    const snapshot = this.read();
    change(snapshot);
    snapshot.system.lastUpdatedAt = nowIso();
    this.write(snapshot);
    return clone(snapshot);
  }

  async health(): Promise<HealthResult> {
    await delay(40);
    return { ok: true, version: "mock-0.1", message: "浏览器本地持久化 mock" };
  }

  async getSnapshot(): Promise<StudioSnapshot> {
    await delay(90);
    return clone(this.read());
  }

  createProject(input: CreateProjectInput) {
    return this.mutate((snapshot) => {
      const now = nowIso();
      snapshot.projects.unshift({
        id: `project-${uuid()}`,
        name: input.name.trim(),
        kind: input.kind,
        status: "draft",
        description: input.description?.trim() ?? "",
        locale: input.locale ?? (input.kind === "japanese_learning" ? "ja-JP" : "zh-CN"),
        progress: 0,
        lineCount: 0,
        selectedTakeCount: 0,
        characterCount: 0,
        createdAt: now,
        updatedAt: now,
      });
    });
  }

  updateLine(projectId: string, lineId: string, patch: DialogueLinePatch, revision: number) {
    return this.mutate((snapshot) => {
      const line = snapshot.lines.find((candidate) => candidate.projectId === projectId && candidate.id === lineId);
      if (!line) throw new GatewayError("台词不存在或已被删除。", { code: "line_not_found", status: 404 });
      if (line.revision !== revision) {
        throw new GatewayError("台词已在其他位置更新，请复制当前内容后重新载入。", {
          code: "revision_conflict",
          status: 409,
        });
      }
      const generationFields = [
        "text",
        "emotion",
        "emotionIntensity",
        "pace",
        "pitch",
        "volume",
        "durationBudgetMs",
        "voiceProfileId",
        "engineId",
        "seed",
      ];
      const invalidates = Object.keys(patch).some((key) => generationFields.includes(key));
      Object.assign(line, patch, { revision: line.revision + 1, stale: invalidates || line.stale });
      if (invalidates) {
        snapshot.takes.forEach((take) => {
          if (take.lineId === line.id && !take.selected) take.status = "stale";
        });
      }
      const project = snapshot.projects.find((candidate) => candidate.id === projectId);
      if (project) project.updatedAt = nowIso();
    });
  }

  importLines(projectId: string, imported: ImportedLine[]) {
    return this.mutate((snapshot) => {
      const project = snapshot.projects.find((candidate) => candidate.id === projectId);
      if (!project) throw new GatewayError("目标项目不存在。", { code: "project_not_found", status: 404 });
      const baseIndex = snapshot.lines.filter((line) => line.projectId === projectId).length;
      imported.forEach((item, offset) => {
        const character = snapshot.characters.find(
          (candidate) =>
            candidate.projectId === projectId &&
            (candidate.characterId.toLowerCase() === item.speaker.toLowerCase() ||
              candidate.name.toLowerCase() === item.speaker.toLowerCase()),
        );
        snapshot.lines.push({
          id: `line-${uuid()}`,
          projectId,
          lineId: item.lineId,
          sceneId: item.sceneId,
          index: baseIndex + offset + 1,
          startMs: item.startMs,
          endMs: item.endMs,
          sourceText: item.text,
          text: item.text,
          locale: item.locale,
          speakerId: character?.id ?? null,
          listener: item.listener,
          intent: "",
          subtext: "",
          emotion: item.emotion,
          emotionIntensity: 50,
          pace: 1,
          pitch: 0,
          volume: 0,
          breath: "",
          pause: "",
          pronunciation: "",
          durationBudgetMs: item.durationLimitMs,
          voiceProfileId: character?.voiceProfileId ?? null,
          engineId: "voxcpm2",
          seed: 42 + baseIndex + offset,
          selectedTakeId: null,
          selectionLocked: false,
          revision: 1,
          stale: false,
        });
      });
      const now = nowIso();
      project.lineCount = snapshot.lines.filter((line) => line.projectId === projectId).length;
      project.updatedAt = now;
      snapshot.jobs.unshift({
        id: `job-${uuid()}`,
        projectId,
        kind: "import",
        label: `导入 ${imported.length} 条台词`,
        status: "completed",
        progress: 100,
        stage: "已保存并建立版本 1",
        engineId: null,
        attempt: 1,
        error: null,
        recoverable: false,
        allowedActions: [],
        createdAt: now,
        updatedAt: now,
      });
    });
  }

  generateTakes(projectId: string, lineId: string, count: number) {
    return this.mutate((snapshot) => {
      const line = snapshot.lines.find((candidate) => candidate.projectId === projectId && candidate.id === lineId);
      if (!line) throw new GatewayError("待生成台词不存在。", { code: "line_not_found", status: 404 });
      if (!line.voiceProfileId) {
        throw new GatewayError("请先为台词映射已授权的声音。", { code: "voice_required", status: 422 });
      }
      const profile = snapshot.voices.find((voice) => voice.id === line.voiceProfileId);
      if (!profile || profile.authorizationStatus !== "verified") {
        throw new GatewayError("声音授权尚未验证，生成已安全阻止。", { code: "authorization_required", status: 422 });
      }
      const now = nowIso();
      const existingCount = snapshot.takes.filter((take) => take.lineId === line.id).length;
      Array.from({ length: Math.max(1, Math.min(6, count)) }, (_, offset) => offset).forEach((offset) => {
        const takeIndex = existingCount + offset + 1;
        const selected = false;
        const id = `take-${uuid()}`;
        snapshot.takes.push({
          id,
          projectId,
          lineId: line.id,
          index: takeIndex,
          engineId: line.engineId,
          modelVersion: "mock-deterministic-1",
          seed: line.seed + offset,
          durationMs: Math.max(650, (line.durationBudgetMs ?? line.text.length * 190) + (offset - 1) * 73),
          sampleRate: 48000,
          subtype: "PCM_24",
          loudnessLufs: -18 + offset * 0.3,
          status: "ready",
          emotion: line.emotion,
          qualityScore: 78 + ((line.seed + offset * 7) % 18),
          selected,
          inputHash: `mock-${line.id}-${line.revision}-${line.seed + offset}`,
          createdAt: now,
        });
      });
      line.stale = false;
      const project = snapshot.projects.find((candidate) => candidate.id === projectId);
      if (project) {
        project.updatedAt = now;
        project.selectedTakeCount = snapshot.lines.filter(
          (candidate) => candidate.projectId === projectId && candidate.selectedTakeId,
        ).length;
      }
      snapshot.jobs.unshift({
        id: `job-${uuid()}`,
        projectId,
        kind: "generate_takes",
        label: `生成 ${line.lineId} 的 ${count} 个 mock take`,
        status: "completed",
        progress: 100,
        stage: "mock 引擎完成；未加载 GPU 模型",
        engineId: "mock",
        attempt: 1,
        error: null,
        recoverable: false,
        allowedActions: [],
        createdAt: now,
        updatedAt: now,
      });
    });
  }

  selectTake(projectId: string, lineId: string, takeId: string, locked: boolean) {
    return this.mutate((snapshot) => {
      const line = snapshot.lines.find((candidate) => candidate.projectId === projectId && candidate.id === lineId);
      const take = snapshot.takes.find((candidate) => candidate.id === takeId && candidate.lineId === lineId);
      if (!line || !take) throw new GatewayError("候选 take 不存在。", { code: "take_not_found", status: 404 });
      snapshot.takes.forEach((candidate) => {
        if (candidate.lineId === lineId) candidate.selected = candidate.id === takeId;
      });
      line.selectedTakeId = takeId;
      line.selectionLocked = locked;
      line.revision += 1;
      const project = snapshot.projects.find((candidate) => candidate.id === projectId);
      if (project) {
        project.selectedTakeCount = snapshot.lines.filter(
          (candidate) => candidate.projectId === projectId && candidate.selectedTakeId,
        ).length;
        project.updatedAt = nowIso();
      }
    });
  }

  updateCharacter(characterId: string, patch: Partial<Character>) {
    return this.mutate((snapshot) => {
      const character = snapshot.characters.find((candidate) => candidate.id === characterId);
      if (!character) throw new GatewayError("角色不存在。", { code: "character_not_found", status: 404 });
      Object.assign(character, patch);
      if (patch.voiceProfileId !== undefined) {
        snapshot.lines.forEach((line) => {
          if (line.speakerId === characterId && !line.voiceProfileId) line.voiceProfileId = patch.voiceProfileId ?? null;
        });
      }
    });
  }

  actOnJob(jobId: string, action: JobAction) {
    return this.mutate((snapshot) => {
      const job = snapshot.jobs.find((candidate) => candidate.id === jobId);
      if (!job) throw new GatewayError("任务不存在。", { code: "job_not_found", status: 404 });
      if (!job.allowedActions.includes(action)) {
        throw new GatewayError(`任务当前状态不允许“${action}”。`, { code: "action_not_allowed", status: 409 });
      }
      if (action === "pause") {
        job.status = "paused";
        job.stage = "已保存检查点";
      } else if (action === "resume") {
        job.status = "running";
        job.stage = "从检查点恢复（mock）";
      } else if (action === "cancel") {
        job.status = "cancelled";
        job.stage = "已安全取消";
      } else {
        job.status = "queued";
        job.progress = 0;
        job.stage = action === "retry" ? "等待重试" : "等待重新计算";
        job.attempt += 1;
        job.error = null;
      }
      job.allowedActions = actionsForStatus(job.status);
      job.updatedAt = nowIso();
    });
  }

  addConversationTurn(text: string, coachMode: "flow" | "strict") {
    return this.mutate((snapshot) => {
      const now = nowIso();
      snapshot.conversations.push({
        id: `turn-${uuid()}`,
        role: "learner",
        text: text.trim(),
        createdAt: now,
      });
      const feedback = coachMode === "strict"
        ? "重点 1：目的地后使用「まで」更自然。请立即重说一次。"
        : "表达可以理解。下一轮只留意目的地后的助词「まで」。";
      snapshot.conversations.push({
        id: `turn-${uuid()}`,
        role: "teacher",
        text: "いいですね。では、切符売り場で『新宿まで一枚お願いします』と言ってみましょう。",
        translation: "很好。请在售票处试着说：请给我一张到新宿的票。",
        feedback,
        confidence: 0.82,
        createdAt: now,
      });
    });
  }

  async resetMock() {
    localStorage.removeItem(SNAPSHOT_KEY);
    return this.getSnapshot();
  }
}

export interface GatewayConnection {
  gateway: StudioGateway;
  mode: ConnectionMode;
  notice: string | null;
}

export const connectGateway = async (config: RuntimeConfig): Promise<GatewayConnection> => {
  const apiBaseUrl = normalizeLoopbackApiBase(config.apiBaseUrl);
  if (config.requestedMode === "mock") {
    if (!config.mockAllowed) throw new GatewayError("当前构建已禁用 mock。", { code: "mock_disabled" });
    const gateway = new MockGateway(apiBaseUrl);
    await gateway.health();
    return { gateway, mode: "mock", notice: "当前处于浏览器本地 mock，不会加载任何真实模型。" };
  }

  const api = new RestGateway(apiBaseUrl);
  try {
    await api.health();
    return { gateway: api, mode: "api", notice: null };
  } catch (error) {
    if (config.requestedMode === "api" || !config.mockAllowed) throw error;
    const mock = new MockGateway(apiBaseUrl);
    await mock.health();
    return {
      gateway: mock,
      mode: "mock",
      notice: `API ${apiBaseUrl} 不可达，已明确进入本地 mock；真实数据没有被修改。`,
    };
  }
};
