import { describe, expect, it } from "vitest";
import { calculateDeliveryReadiness } from "./deliveryReadiness";

describe("calculateDeliveryReadiness", () => {
  it("regresses overlapping blockers without producing a negative score", () => {
    const readiness = calculateDeliveryReadiness([
      { voiceProfileId: null, selectedTakeId: null, stale: false },
      { voiceProfileId: null, selectedTakeId: null, stale: false },
    ]);

    expect(readiness).toEqual({
      score: 0,
      ready: 0,
      total: 2,
      blockers: { unmapped: 2, unselected: 2, stale: 0 },
    });
  });

  it("counts a line once even when it has several delivery blockers", () => {
    const readiness = calculateDeliveryReadiness([
      { voiceProfileId: "voice-1", selectedTakeId: "take-1", stale: false },
      { voiceProfileId: null, selectedTakeId: null, stale: true },
      { voiceProfileId: "voice-2", selectedTakeId: null, stale: false },
      { voiceProfileId: "voice-3", selectedTakeId: "take-3", stale: true },
    ]);

    expect(readiness.score).toBe(25);
    expect(readiness.ready).toBe(1);
    expect(readiness.blockers).toEqual({ unmapped: 1, unselected: 2, stale: 2 });
  });

  it("reports zero for an empty project", () => {
    expect(calculateDeliveryReadiness([]).score).toBe(0);
  });

  it("reports 100 only when every line passes every delivery gate", () => {
    const readiness = calculateDeliveryReadiness([
      { voiceProfileId: "voice-1", selectedTakeId: "take-1", stale: false },
      { voiceProfileId: "voice-2", selectedTakeId: "take-2", stale: false },
    ]);

    expect(readiness.score).toBe(100);
    expect(readiness.ready).toBe(readiness.total);
  });
});
