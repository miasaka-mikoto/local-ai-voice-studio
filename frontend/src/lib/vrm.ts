/**
 * Pure, UI-facing VRM helpers.
 *
 * The actual Three.js/VRM runtime is intentionally not imported here. Keeping
 * validation and metadata formatting pure lets the UI reject unsafe files
 * before a renderer (and its comparatively large code split) is loaded.
 */

export const MAX_VRM_FILE_BYTES = 200 * 1024 * 1024;

/** Browser implementations commonly report VRM as either model/vrm or octet-stream. */
export const ACCEPTED_VRM_MIME_TYPES = [
  "",
  "model/vrm",
  "application/vrm",
  "application/x-vrm",
  "model/gltf-binary",
  "application/octet-stream",
] as const;

export type VrmValidationResult =
  | { ok: true; normalizedName: string }
  | { ok: false; reason: string };

export interface VrmFileLike {
  name: string;
  size: number;
  type?: string;
}

export type VrmBinaryInspection = { ok: true } | { ok: false; reason: string };

const GLB_MAGIC = 0x46546c67;
const GLB_JSON_CHUNK = 0x4e4f534a;
const MAX_GLTF_JSON_BYTES = 16 * 1024 * 1024;

const containsExternalUri = (value: unknown): boolean => {
  if (Array.isArray(value)) return value.some(containsExternalUri);
  if (!value || typeof value !== "object") return false;
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    if (key === "uri" && typeof child === "string" && !child.trim().toLowerCase().startsWith("data:")) return true;
    if (containsExternalUri(child)) return true;
  }
  return false;
};

/**
 * Require a self-contained GLB before invoking GLTFLoader. This prevents a
 * renamed JSON glTF from causing the loader to request remote/relative assets.
 */
export const inspectVrmBinary = async (file: Blob): Promise<VrmBinaryInspection> => {
  if (file.size < 20) return { ok: false, reason: "VRM 文件不是完整的二进制 GLB。" };
  const header = new DataView(await file.slice(0, 20).arrayBuffer());
  if (header.getUint32(0, true) !== GLB_MAGIC || header.getUint32(4, true) !== 2) {
    return { ok: false, reason: "VRM 必须是 GLB 2.0 二进制文件。" };
  }
  const declaredLength = header.getUint32(8, true);
  const jsonLength = header.getUint32(12, true);
  const chunkType = header.getUint32(16, true);
  if (declaredLength !== file.size || chunkType !== GLB_JSON_CHUNK || jsonLength <= 0 || 20 + jsonLength > file.size) {
    return { ok: false, reason: "VRM 的 GLB 结构或长度无效。" };
  }
  if (jsonLength > MAX_GLTF_JSON_BYTES) {
    return { ok: false, reason: "VRM 的描述区过大，已拒绝加载。" };
  }
  try {
    const jsonBytes = new Uint8Array(await file.slice(20, 20 + jsonLength).arrayBuffer());
    const document = JSON.parse(new TextDecoder().decode(jsonBytes));
    if (containsExternalUri(document)) {
      return { ok: false, reason: "VRM 引用了外部资源；请使用纹理与数据全部内嵌的自包含模型。" };
    }
  } catch {
    return { ok: false, reason: "VRM 的 GLB 描述区无法解析。" };
  }
  return { ok: true };
};

/**
 * Validate a local file without reading it or sending it anywhere.
 * An empty MIME is accepted because Windows browsers often omit it for .vrm.
 */
export const validateVrmFile = (file: VrmFileLike): VrmValidationResult => {
  const normalizedName = file.name.trim();
  if (!normalizedName.toLowerCase().endsWith(".vrm")) {
    return { ok: false, reason: "请选择 .vrm 文件。" };
  }
  if (!Number.isFinite(file.size) || file.size <= 0) {
    return { ok: false, reason: "VRM 文件为空或大小无效。" };
  }
  if (file.size > MAX_VRM_FILE_BYTES) {
    return { ok: false, reason: `VRM 文件不能超过 ${Math.round(MAX_VRM_FILE_BYTES / 1024 / 1024)} MB。` };
  }

  const mime = (file.type ?? "").split(";", 1)[0].trim().toLowerCase();
  if (!(ACCEPTED_VRM_MIME_TYPES as readonly string[]).includes(mime)) {
    return { ok: false, reason: "VRM 文件类型与 .vrm 扩展名不匹配。" };
  }
  return { ok: true, normalizedName };
};

export type VrmEmotion = "neutral" | "happy" | "sad" | "angry" | "relaxed" | "surprised";

/** Map conversation phases to the standard VRM expression presets. */
export const vrmEmotionForCompanionState = (state: string): VrmEmotion => {
  switch (state) {
    case "speaking":
      return "happy";
    case "listening":
      return "surprised";
    case "thinking":
      return "neutral";
    case "error":
      return "sad";
    case "idle":
    default:
      return "relaxed";
  }
};

/** Resolve common UI emotion labels before falling back to the phase mapping. */
export const vrmEmotionFromLabel = (label: string): VrmEmotion | null => {
  const value = label.trim().toLowerCase();
  if (!value) return null;
  if (/angry|anger|怒|生气|愤怒|恼火|苛立|いらだ/.test(value)) return "angry";
  if (/surpris|惊|驚|意外|びっくり/.test(value)) return "surprised";
  if (/sad|悲|难过|低落|失落|寂し/.test(value)) return "sad";
  if (/happy|joy|开心|高兴|愉快|喜|嬉し|楽しい/.test(value)) return "happy";
  if (/relax|放松|轻松|平静|穏やか|落ち着/.test(value)) return "relaxed";
  if (/neutral|中性|专注|认真|通常|普通/.test(value)) return "neutral";
  return null;
};

export interface VrmMetaSummary {
  modelName: string;
  authors: string[];
  performance: string;
  commercial: string;
  redistribution: string;
  modification: string;
  license: string;
  licenseUrl?: string;
  otherLicenseUrl?: string;
  thirdPartyLicenses?: string;
  restrictions: string[];
  credit: string;
}

const textOr = (value: unknown, fallback: string, maxLength = 240): string => {
  if (typeof value !== "string") return fallback;
  const text = value.trim();
  if (!text) return fallback;
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
};

const listOr = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    .slice(0, 8)
    .map((item) => textOr(item, "未署名", 120));
};

/**
 * Normalize VRM 0.x and VRM 1.0 metadata into a short, safe summary.
 * Unknown fields are intentionally ignored and URLs are displayed as-is only
 * as metadata; the renderer never fetches them.
 */
export const summarizeVrmMeta = (meta: unknown): VrmMetaSummary => {
  const value = (meta && typeof meta === "object" ? meta : {}) as Record<string, unknown>;
  const isVrm1 = value.metaVersion === "1" || "name" in value || "authors" in value;
  const modelName = isVrm1 ? textOr(value.name, "未命名 VRM") : textOr(value.title, "未命名 VRM");
  const authors = isVrm1 ? listOr(value.authors) : [textOr(value.author, "未署名")];

  const performance = isVrm1
    ? value.avatarPermission === "everyone"
      ? "任何人可扮演"
      : value.avatarPermission === "onlySeparatelyLicensedPerson"
        ? "仅另行授权者可扮演"
        : value.avatarPermission === "onlyAuthor"
          ? "仅作者可扮演"
          : "未声明"
    : value.allowedUserName === "Everyone"
      ? "任何人可扮演"
      : value.allowedUserName === "ExplicitlyLicensedPerson"
        ? "仅明确授权者可扮演"
        : value.allowedUserName === "OnlyAuthor"
          ? "仅作者可扮演"
          : "未声明";

  let commercial = "未声明";
  if (isVrm1) {
    const usage = value.commercialUsage;
    commercial = usage === "corporation" ? "允许企业商用" : usage === "personalProfit" ? "允许个人商用" : usage === "personalNonProfit" ? "仅个人非商用" : "未声明";
  } else if (value.commercialUssageName === "Allow") {
    commercial = "允许商用";
  } else if (value.commercialUssageName === "Disallow") {
    commercial = "禁止商用";
  }

  let redistribution = "未声明";
  if (isVrm1) {
    redistribution = value.allowRedistribution === true ? "允许再分发" : value.allowRedistribution === false ? "禁止再分发" : "未声明";
  } else if (value.licenseName === "Redistribution_Prohibited") {
    redistribution = "禁止再分发";
  } else if (typeof value.licenseName === "string") {
    redistribution = "按许可证条件";
  }

  const modification = isVrm1
    ? value.modification === "allowModificationRedistribution"
      ? "允许修改并再分发"
      : value.modification === "allowModification"
        ? "允许修改"
        : value.modification === "prohibited"
          ? "禁止修改"
          : "未声明"
    : "按许可证条件";

  const licenseUrl = isVrm1 ? textOr(value.licenseUrl, "", 600) : textOr(value.otherLicenseUrl, "", 600);
  const otherLicenseUrl = isVrm1
    ? textOr(value.otherLicenseUrl, "", 600)
    : textOr(value.otherPermissionUrl, "", 600);
  const thirdPartyLicenses = isVrm1 ? textOr(value.thirdPartyLicenses, "", 600) : "";
  const license = isVrm1
    ? licenseUrl || otherLicenseUrl
      ? "外部许可证（需打开原文核验）"
      : "未声明"
    : textOr(value.licenseName, "未声明");
  const credit = isVrm1
    ? value.creditNotation === "required"
      ? "必须署名"
      : value.creditNotation === "unnecessary"
        ? "可不署名"
        : "未声明"
    : "请遵循许可证";

  const restrictions: string[] = [];
  if (isVrm1) {
    if (value.allowExcessivelyViolentUsage === false) restrictions.push("禁止过度暴力内容");
    if (value.allowExcessivelySexualUsage === false) restrictions.push("禁止过度色情内容");
    if (value.allowPoliticalOrReligiousUsage === false) restrictions.push("禁止政治或宗教用途");
    if (value.allowAntisocialOrHateUsage === false) restrictions.push("禁止反社会或仇恨用途");
  } else {
    if (value.violentUssageName === "Disallow") restrictions.push("禁止暴力内容");
    if (value.sexualUssageName === "Disallow") restrictions.push("禁止色情内容");
  }

  return {
    modelName,
    authors: authors.length > 0 ? authors : ["未署名"],
    performance,
    commercial,
    redistribution,
    modification,
    license,
    ...(licenseUrl ? { licenseUrl } : {}),
    ...(otherLicenseUrl ? { otherLicenseUrl } : {}),
    ...(thirdPartyLicenses ? { thirdPartyLicenses } : {}),
    restrictions,
    credit,
  };
};

/** Short, deterministic text useful in compact cards and aria labels. */
export const formatVrmMetaSummary = (summary: VrmMetaSummary): string =>
  `${summary.modelName} · ${summary.authors.join(", ")} · ${summary.commercial} · ${summary.redistribution}`;
