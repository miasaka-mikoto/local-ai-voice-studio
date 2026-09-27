import { describe, expect, it } from "vitest";
import {
  MAX_VRM_FILE_BYTES,
  formatVrmMetaSummary,
  inspectVrmBinary,
  summarizeVrmMeta,
  validateVrmFile,
  vrmEmotionForCompanionState,
  vrmEmotionFromLabel,
} from "./vrm";

describe("VRM local-file helpers", () => {
  const makeGlb = (document: Record<string, unknown>) => {
    const source = JSON.stringify(document);
    const padded = source.padEnd(Math.ceil(source.length / 4) * 4, " ");
    const bytes = new Uint8Array(20 + padded.length);
    const view = new DataView(bytes.buffer);
    view.setUint32(0, 0x46546c67, true);
    view.setUint32(4, 2, true);
    view.setUint32(8, bytes.length, true);
    view.setUint32(12, padded.length, true);
    view.setUint32(16, 0x4e4f534a, true);
    bytes.set(new TextEncoder().encode(padded), 20);
    return new Blob([bytes], { type: "model/vrm" });
  };

  it("accepts browser MIME variants but enforces extension, size and type", () => {
    expect(validateVrmFile({ name: "avatar.vrm", size: 1024, type: "model/vrm" }).ok).toBe(true);
    expect(validateVrmFile({ name: "avatar.vrm", size: 1024, type: "" }).ok).toBe(true);
    expect(validateVrmFile({ name: "avatar.VRM", size: 1024, type: "application/octet-stream" }).ok).toBe(true);
    expect(validateVrmFile({ name: "avatar.vrm", size: 1024, type: "model/gltf-binary" }).ok).toBe(true);
    expect(validateVrmFile({ name: "avatar.glb", size: 1024, type: "model/vrm" }).ok).toBe(false);
    expect(validateVrmFile({ name: "avatar.vrm", size: 1024, type: "model/gltf+json" }).ok).toBe(false);
    expect(validateVrmFile({ name: "avatar.vrm", size: MAX_VRM_FILE_BYTES + 1, type: "model/vrm" }).ok).toBe(false);
    expect(validateVrmFile({ name: "avatar.vrm", size: 0, type: "model/vrm" }).ok).toBe(false);
  });

  it("normalizes VRM 1.0 license metadata without fetching license URLs", () => {
    const summary = summarizeVrmMeta({
      metaVersion: "1",
      name: "Test Avatar",
      authors: ["A", "B"],
      licenseUrl: "https://example.invalid/license",
      otherLicenseUrl: "https://example.invalid/extra",
      thirdPartyLicenses: "Texture author credit required",
      avatarPermission: "onlySeparatelyLicensedPerson",
      commercialUsage: "personalNonProfit",
      allowRedistribution: false,
      modification: "prohibited",
      allowPoliticalOrReligiousUsage: false,
      creditNotation: "required",
    });
    expect(summary).toEqual({
      modelName: "Test Avatar",
      authors: ["A", "B"],
      performance: "仅另行授权者可扮演",
      commercial: "仅个人非商用",
      redistribution: "禁止再分发",
      modification: "禁止修改",
      license: "外部许可证（需打开原文核验）",
      licenseUrl: "https://example.invalid/license",
      otherLicenseUrl: "https://example.invalid/extra",
      thirdPartyLicenses: "Texture author credit required",
      restrictions: ["禁止政治或宗教用途"],
      credit: "必须署名",
    });
    expect(formatVrmMetaSummary(summary)).toContain("Test Avatar · A, B");
  });

  it("accepts self-contained GLB and rejects renamed or externally-referenced files", async () => {
    await expect(inspectVrmBinary(makeGlb({ asset: { version: "2.0" }, images: [{ uri: "data:image/png;base64,AA==" }] }))).resolves.toEqual({ ok: true });
    await expect(inspectVrmBinary(makeGlb({ asset: { version: "2.0" }, images: [{ uri: "https://example.invalid/avatar.png" }] }))).resolves.toEqual({
      ok: false,
      reason: "VRM 引用了外部资源；请使用纹理与数据全部内嵌的自包含模型。",
    });
    await expect(inspectVrmBinary(new Blob(["{}"], { type: "model/vrm" }))).resolves.toMatchObject({ ok: false });
  });

  it("supports legacy VRM 0.x metadata and conservative defaults", () => {
    const summary = summarizeVrmMeta({
      metaVersion: "0",
      title: "Legacy",
      author: "Author",
      commercialUssageName: "Disallow",
      licenseName: "Redistribution_Prohibited",
    });
    expect(summary.modelName).toBe("Legacy");
    expect(summary.authors).toEqual(["Author"]);
    expect(summary.commercial).toBe("禁止商用");
    expect(summary.redistribution).toBe("禁止再分发");
  });

  it("maps conversation state to standard VRM expression presets", () => {
    expect(vrmEmotionForCompanionState("idle")).toBe("relaxed");
    expect(vrmEmotionForCompanionState("speaking")).toBe("happy");
    expect(vrmEmotionForCompanionState("error")).toBe("sad");
    expect(vrmEmotionForCompanionState("unexpected")).toBe("relaxed");
    expect(vrmEmotionFromLabel("愤怒")).toBe("angry");
    expect(vrmEmotionFromLabel("びっくり")).toBe("surprised");
    expect(vrmEmotionFromLabel("专注")).toBe("neutral");
    expect(vrmEmotionFromLabel("unknown label")).toBeNull();
  });
});
