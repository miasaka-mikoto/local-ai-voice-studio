import { describe, expect, it } from "vitest";
import { japaneseScenarios } from "./JapanesePage";
import { japaneseStages } from "../data/japaneseCurriculum";

describe("Japanese companion scenes", () => {
  it("covers the N5-N1 daily-life path with project-local visuals", () => {
    expect(japaneseScenarios).toHaveLength(38);
    expect(japaneseStages.map((stage) => stage.id)).toEqual([
      "foundation",
      "daily_independence",
      "social_work",
      "advanced_life",
    ]);
    expect(new Set(japaneseScenarios.map((scene) => scene.level))).toEqual(new Set(["N5", "N4", "N3", "N2", "N1"]));
    expect(new Set(japaneseScenarios.map((scene) => scene.domain)).size).toBeGreaterThanOrEqual(10);
    expect(new Set(japaneseScenarios.map((scene) => scene.id)).size).toBe(38);
    expect(japaneseScenarios.every((scene) => scene.image.startsWith("/assets/scenes/") && scene.image.endsWith(".webp"))).toBe(true);
    expect(new Set(japaneseScenarios.map((scene) => scene.image))).toEqual(new Set([
      "/assets/scenes/station.webp",
      "/assets/scenes/cafe.webp",
      "/assets/scenes/workplace.webp",
      "/assets/scenes/gaming.webp",
    ]));
    expect(japaneseScenarios.every((scene) => scene.greeting && scene.suggestions.length === 2 && scene.goal)).toBe(true);
    expect(japaneseScenarios.find((scene) => scene.id === "station-ticket")).toMatchObject({ title: "车站买票", level: "N5", domain: "transport" });
    expect(japaneseScenarios.find((scene) => scene.id === "emergency-disaster")).toMatchObject({ level: "N2", domain: "safety" });
  });
});
