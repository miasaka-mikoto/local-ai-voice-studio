import { describe, expect, it } from "vitest";
import { exportProjectLines, parseCsv, parseJsonl, parseSrt } from "./importers";
import { createSeedSnapshot } from "../data/seed";

describe("dialogue importers", () => {
  it("parses SRT timestamps, multiline text and duration budgets", () => {
    const result = parseSrt(`1\n00:00:01,250 --> 00:00:03,500\nこんばんは。\n雨ですね。\n\n2\n00:00:04,000 --> 00:00:05,100\nそうですね。`);
    expect(result.lines).toHaveLength(2);
    expect(result.lines[0]).toMatchObject({
      lineId: "SRT_1",
      startMs: 1250,
      endMs: 3500,
      durationLimitMs: 2250,
      text: "こんばんは。\n雨ですね。",
    });
    expect(result.warnings).toEqual([]);
  });

  it("parses quoted CSV and game voice fields", () => {
    const result = parseCsv(`line_id,scene_id,character_id,text,emotion,listener,duration_limit_ms,asset_name\nB001,forest,KIRI,"敌人，出现了！",紧张,player,1800,kiri_b001`);
    expect(result.lines).toEqual([
      expect.objectContaining({
        lineId: "B001",
        sceneId: "forest",
        speaker: "KIRI",
        text: "敌人，出现了！",
        emotion: "紧张",
        listener: "player",
        durationLimitMs: 1800,
        assetName: "kiri_b001",
      }),
    ]);
  });

  it("keeps valid JSONL rows and reports exact invalid rows", () => {
    const result = parseJsonl(`{"line_id":"A1","text":"第一句"}\nnot-json\n{"line_id":"A3","text":"第三句"}`);
    expect(result.lines.map((line) => line.lineId)).toEqual(["A1", "A3"]);
    expect(result.warnings).toHaveLength(1);
    expect(result.warnings[0]).toContain("第 2 行");
  });

  it("exports stable generation and manual selection fields", () => {
    const snapshot = createSeedSnapshot();
    const project = snapshot.projects[0];
    const result = exportProjectLines(project, snapshot.lines.filter((line) => line.projectId === project.id), "json");
    const parsed = JSON.parse(result.content) as { lines: Record<string, unknown>[] };
    expect(parsed.lines[0]).toMatchObject({
      line_id: "A001",
      engine: "qwen3_tts_1_7b_base",
      seed: 4201,
      selected_take_id: "take-a-001-2",
      locked: true,
    });
  });
});
