import type { DialogueLine } from "../types";

type DeliveryReadinessLine = Pick<DialogueLine, "voiceProfileId" | "selectedTakeId" | "stale">;

export interface DeliveryReadiness {
  score: number;
  ready: number;
  total: number;
  blockers: {
    unmapped: number;
    unselected: number;
    stale: number;
  };
}

/**
 * A line is deliverable only after every delivery gate has passed. Counting
 * ready lines avoids deducting the same line more than once when its blockers
 * overlap (for example, a newly imported line is both unmapped and unselected).
 */
export const calculateDeliveryReadiness = (lines: readonly DeliveryReadinessLine[]): DeliveryReadiness => {
  const blockers = {
    unmapped: lines.filter((line) => !line.voiceProfileId).length,
    unselected: lines.filter((line) => !line.selectedTakeId).length,
    stale: lines.filter((line) => line.stale).length,
  };
  const ready = lines.filter((line) => line.voiceProfileId && line.selectedTakeId && !line.stale).length;
  const rawScore = lines.length ? Math.round((ready / lines.length) * 100) : 0;

  return {
    score: Math.min(100, Math.max(0, rawScore)),
    ready,
    total: lines.length,
    blockers,
  };
};
