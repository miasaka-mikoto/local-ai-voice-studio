import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  connectGateway,
  GatewayError,
  normalizeLoopbackApiBase,
  persistRuntimeConfig,
  readRuntimeConfig,
  type StudioGateway,
} from "./lib/gateway";
import type {
  Character,
  ConnectionMode,
  CreateProjectInput,
  DialogueLinePatch,
  ImportedLine,
  JobAction,
  RuntimeConfig,
  StudioSnapshot,
} from "./types";

type Toast = { tone: "success" | "warning" | "danger" | "info"; message: string };

interface StudioContextValue {
  snapshot: StudioSnapshot | null;
  loading: boolean;
  operation: string | null;
  error: string | null;
  technicalError: string | null;
  connectionMode: ConnectionMode | null;
  connectionNotice: string | null;
  config: RuntimeConfig;
  toast: Toast | null;
  refresh(): Promise<void>;
  reconnect(next?: Partial<RuntimeConfig>): Promise<void>;
  createProject(input: CreateProjectInput): Promise<string | null>;
  updateLine(projectId: string, lineId: string, patch: DialogueLinePatch, revision: number): Promise<boolean>;
  importLines(projectId: string, lines: ImportedLine[]): Promise<boolean>;
  generateTakes(projectId: string, lineId: string, count: number): Promise<boolean>;
  selectTake(projectId: string, lineId: string, takeId: string, locked: boolean): Promise<boolean>;
  updateCharacter(characterId: string, patch: Partial<Character>): Promise<boolean>;
  actOnJob(jobId: string, action: JobAction): Promise<boolean>;
  addConversationTurn(text: string, coachMode: "flow" | "strict"): Promise<boolean>;
  resetMock(): Promise<boolean>;
  dismissToast(): void;
}

const StudioContext = createContext<StudioContextValue | null>(null);

const userMessage = (error: unknown) => {
  if (error instanceof GatewayError) return error.message;
  if (error instanceof Error) return error.message;
  return "操作未完成，请重试。";
};

export const StudioProvider = ({ children }: PropsWithChildren) => {
  const [snapshot, setSnapshot] = useState<StudioSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [operation, setOperation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [technicalError, setTechnicalError] = useState<string | null>(null);
  const [connectionMode, setConnectionMode] = useState<ConnectionMode | null>(null);
  const [connectionNotice, setConnectionNotice] = useState<string | null>(null);
  const [config, setConfig] = useState<RuntimeConfig>(() => readRuntimeConfig());
  const [toast, setToast] = useState<Toast | null>(null);
  const gatewayRef = useRef<StudioGateway | null>(null);

  const boot = useCallback(async (runtime: RuntimeConfig) => {
    setLoading(true);
    setError(null);
    setTechnicalError(null);
    try {
      const connection = await connectGateway(runtime);
      const nextSnapshot = await connection.gateway.getSnapshot();
      gatewayRef.current = connection.gateway;
      setSnapshot(nextSnapshot);
      setConnectionMode(connection.mode);
      setConnectionNotice(connection.notice);
    } catch (caught) {
      gatewayRef.current = null;
      setSnapshot(null);
      setConnectionMode(null);
      setConnectionNotice(null);
      setError(userMessage(caught));
      setTechnicalError(caught instanceof Error ? caught.stack ?? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void boot(config);
  }, [boot, config]);

  const refresh = useCallback(async () => {
    const gateway = gatewayRef.current;
    if (!gateway) {
      await boot(config);
      return;
    }
    setOperation("同步最新状态");
    setError(null);
    try {
      setSnapshot(await gateway.getSnapshot());
      setToast({ tone: "success", message: "状态已同步。" });
    } catch (caught) {
      setError(userMessage(caught));
      setTechnicalError(caught instanceof Error ? caught.stack ?? caught.message : String(caught));
    } finally {
      setOperation(null);
    }
  }, [boot, config]);

  const reconnect = useCallback(
    async (next?: Partial<RuntimeConfig>) => {
      try {
        const merged = {
          ...config,
          ...next,
          apiBaseUrl: normalizeLoopbackApiBase(next?.apiBaseUrl ?? config.apiBaseUrl),
        };
        persistRuntimeConfig(merged);
        setConfig(merged);
        if (
          merged.apiBaseUrl === config.apiBaseUrl &&
          merged.requestedMode === config.requestedMode &&
          merged.mockAllowed === config.mockAllowed
        ) {
          await boot(merged);
        }
      } catch (caught) {
        setError(userMessage(caught));
        setTechnicalError(caught instanceof Error ? caught.stack ?? caught.message : String(caught));
      }
    },
    [boot, config],
  );

  const mutate = useCallback(
    async (
      label: string,
      action: (gateway: StudioGateway) => Promise<StudioSnapshot>,
      successMessage: string,
    ): Promise<StudioSnapshot | null> => {
      const gateway = gatewayRef.current;
      if (!gateway) {
        setToast({ tone: "danger", message: "尚未连接数据服务，请先恢复连接。" });
        return null;
      }
      setOperation(label);
      try {
        const nextSnapshot = await action(gateway);
        setSnapshot(nextSnapshot);
        setToast({ tone: "success", message: successMessage });
        return nextSnapshot;
      } catch (caught) {
        setToast({ tone: "danger", message: userMessage(caught) });
        setTechnicalError(caught instanceof Error ? caught.stack ?? caught.message : String(caught));
        return null;
      } finally {
        setOperation(null);
      }
    },
    [],
  );

  const createProject = useCallback(
    async (input: CreateProjectInput) => {
      const before = new Set(snapshot?.projects.map((project) => project.id) ?? []);
      const next = await mutate("创建项目", (gateway) => gateway.createProject(input), `项目“${input.name}”已创建。`);
      return next?.projects.find((project) => !before.has(project.id))?.id ?? null;
    },
    [mutate, snapshot],
  );

  const updateLine = useCallback(
    async (projectId: string, lineId: string, patch: DialogueLinePatch, revision: number) =>
      Boolean(
        await mutate(
          "保存台词",
          (gateway) => gateway.updateLine(projectId, lineId, patch, revision),
          "台词已保存并建立新版本。",
        ),
      ),
    [mutate],
  );

  const importLines = useCallback(
    async (projectId: string, lines: ImportedLine[]) =>
      Boolean(
        await mutate(
          "导入台词",
          (gateway) => gateway.importLines(projectId, lines),
          `已导入 ${lines.length} 条有效台词。`,
        ),
      ),
    [mutate],
  );

  const generateTakes = useCallback(
    async (projectId: string, lineId: string, count: number) =>
      Boolean(
        await mutate(
          "创建候选 take",
          (gateway) => gateway.generateTakes(projectId, lineId, count),
          `已创建 ${count} 个候选 take；mock 模式未加载真实模型。`,
        ),
      ),
    [mutate],
  );

  const selectTake = useCallback(
    async (projectId: string, lineId: string, takeId: string, locked: boolean) =>
      Boolean(
        await mutate(
          "选择候选",
          (gateway) => gateway.selectTake(projectId, lineId, takeId, locked),
          locked ? "候选已选择并人工锁定。" : "候选已选择。",
        ),
      ),
    [mutate],
  );

  const updateCharacter = useCallback(
    async (characterId: string, patch: Partial<Character>) =>
      Boolean(
        await mutate(
          "保存角色映射",
          (gateway) => gateway.updateCharacter(characterId, patch),
          "角色与声音映射已保存。",
        ),
      ),
    [mutate],
  );

  const actOnJob = useCallback(
    async (jobId: string, action: JobAction) =>
      Boolean(
        await mutate(
          "更新任务",
          (gateway) => gateway.actOnJob(jobId, action),
          "任务状态已更新并持久化。",
        ),
      ),
    [mutate],
  );

  const addConversationTurn = useCallback(
    async (text: string, coachMode: "flow" | "strict") =>
      Boolean(
        await mutate(
          "保存会话轮次",
          (gateway) => gateway.addConversationTurn(text, coachMode),
          "本轮会话与反馈已保存。",
        ),
      ),
    [mutate],
  );

  const resetMock = useCallback(async () => {
    const gateway = gatewayRef.current;
    if (!gateway?.resetMock) return false;
    setOperation("重置 mock 数据");
    try {
      setSnapshot(await gateway.resetMock());
      setToast({ tone: "success", message: "mock 数据已恢复到可验证基线。" });
      return true;
    } finally {
      setOperation(null);
    }
  }, []);

  const value = useMemo<StudioContextValue>(
    () => ({
      snapshot,
      loading,
      operation,
      error,
      technicalError,
      connectionMode,
      connectionNotice,
      config,
      toast,
      refresh,
      reconnect,
      createProject,
      updateLine,
      importLines,
      generateTakes,
      selectTake,
      updateCharacter,
      actOnJob,
      addConversationTurn,
      resetMock,
      dismissToast: () => setToast(null),
    }),
    [
      snapshot,
      loading,
      operation,
      error,
      technicalError,
      connectionMode,
      connectionNotice,
      config,
      toast,
      refresh,
      reconnect,
      createProject,
      updateLine,
      importLines,
      generateTakes,
      selectTake,
      updateCharacter,
      actOnJob,
      addConversationTurn,
      resetMock,
    ],
  );

  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>;
};

export const useStudio = () => {
  const value = useContext(StudioContext);
  if (!value) throw new Error("useStudio 必须在 StudioProvider 内使用");
  return value;
};
