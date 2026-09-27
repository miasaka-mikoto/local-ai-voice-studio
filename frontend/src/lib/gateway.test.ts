import { beforeEach, describe, expect, it } from "vitest";
import { connectGateway, GatewayError, normalizeLoopbackApiBase } from "./gateway";

const config = {
  apiBaseUrl: "http://127.0.0.1:8766",
  requestedMode: "mock" as const,
  mockAllowed: true,
};

describe("MockGateway persistence and invariants", () => {
  beforeEach(() => localStorage.clear());

  it("persists project creation across gateway reconnection", async () => {
    const first = await connectGateway(config);
    const created = await first.gateway.createProject({ name: "持久化测试", kind: "game_voice", locale: "ja-JP" });
    expect(created.projects.some((project) => project.name === "持久化测试")).toBe(true);

    const second = await connectGateway(config);
    const restored = await second.gateway.getSnapshot();
    expect(restored.projects.some((project) => project.name === "持久化测试")).toBe(true);
  });

  it("generates deterministic mock takes and preserves a locked selection", async () => {
    const connection = await connectGateway(config);
    let snapshot = await connection.gateway.generateTakes("project-anime-01", "line-a-003", 3);
    const takes = snapshot.takes.filter((take) => take.lineId === "line-a-003");
    expect(takes).toHaveLength(3);
    expect(takes.every((take) => take.sampleRate === 48000 && take.subtype === "PCM_24")).toBe(true);

    snapshot = await connection.gateway.selectTake("project-anime-01", "line-a-003", takes[1].id, true);
    const selectedLine = snapshot.lines.find((line) => line.id === "line-a-003");
    expect(selectedLine).toMatchObject({ selectedTakeId: takes[1].id, selectionLocked: true });

    snapshot = await connection.gateway.generateTakes("project-anime-01", "line-a-003", 2);
    expect(snapshot.lines.find((line) => line.id === "line-a-003")?.selectedTakeId).toBe(takes[1].id);
  });

  it("enforces optimistic revisions and exposes a recoverable conflict", async () => {
    const connection = await connectGateway(config);
    await connection.gateway.updateLine("project-anime-01", "line-a-003", { text: "第一次保存" }, 1);
    await expect(connection.gateway.updateLine("project-anime-01", "line-a-003", { text: "过期编辑" }, 1)).rejects.toMatchObject({
      code: "revision_conflict",
      status: 409,
      recoverable: true,
    });
  });

  it("persists allowed task transitions", async () => {
    const connection = await connectGateway(config);
    const paused = await connection.gateway.actOnJob("job-001", "pause");
    expect(paused.jobs.find((job) => job.id === "job-001")).toMatchObject({
      status: "paused",
      allowedActions: ["resume", "cancel"],
    });
    const resumed = await connection.gateway.actOnJob("job-001", "resume");
    expect(resumed.jobs.find((job) => job.id === "job-001")?.status).toBe("running");
  });

  it("accepts loopback API bases and rejects remote or credential-bearing URLs", () => {
    expect(normalizeLoopbackApiBase("http://127.0.0.1:8766/")).toBe("http://127.0.0.1:8766");
    expect(normalizeLoopbackApiBase("http://localhost:8766")).toBe("http://localhost:8766");
    expect(() => normalizeLoopbackApiBase("https://example.com/api")).toThrow(GatewayError);
    expect(() => normalizeLoopbackApiBase("http://user:secret@127.0.0.1:8766")).toThrow(GatewayError);
  });
});
