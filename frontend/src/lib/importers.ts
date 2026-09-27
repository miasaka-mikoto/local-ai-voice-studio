import type { DialogueLine, ImportPreview, ImportedLine, Project } from "../types";

const textDecoder = new TextDecoder("utf-8");

const parseClock = (value: string): number | null => {
  const normalized = value.trim().replace(".", ",");
  const match = normalized.match(/^(\d{1,2}):(\d{2}):(\d{2})[,.:](\d{2,3})$/);
  if (!match) return null;
  const [, hours, minutes, seconds, fraction] = match;
  const millis = fraction.length === 2 ? Number(fraction) * 10 : Number(fraction);
  return ((Number(hours) * 60 + Number(minutes)) * 60 + Number(seconds)) * 1000 + millis;
};

const parseAssClock = (value: string): number | null => {
  const match = value.trim().match(/^(\d+):(\d{2}):(\d{2})[.](\d{2})$/);
  if (!match) return null;
  const [, hours, minutes, seconds, centiseconds] = match;
  return ((Number(hours) * 60 + Number(minutes)) * 60 + Number(seconds)) * 1000 + Number(centiseconds) * 10;
};

const stripTags = (value: string) =>
  value
    .replace(/<[^>]+>/g, "")
    .replace(/\{\\[^}]+}/g, "")
    .replace(/\\N/g, "\n")
    .trim();

const emptyLine = (index: number, text: string): ImportedLine => ({
  lineId: `LINE_${String(index + 1).padStart(4, "0")}`,
  sceneId: "SCENE_001",
  startMs: null,
  endMs: null,
  speaker: "",
  listener: "",
  text: text.trim(),
  emotion: "中性",
  locale: "zh-CN",
  durationLimitMs: null,
  assetName: "",
});

export const parseSrt = (input: string): ImportPreview => {
  const blocks = input.replace(/\r\n/g, "\n").trim().split(/\n{2,}/);
  const warnings: string[] = [];
  const lines = blocks.flatMap((block, blockIndex) => {
    const rows = block.split("\n").map((row) => row.trimEnd());
    const timeIndex = rows.findIndex((row) => row.includes("-->"));
    if (timeIndex < 0) {
      warnings.push(`第 ${blockIndex + 1} 个字幕块缺少时间轴，已跳过。`);
      return [];
    }
    const [startRaw, endRaw] = rows[timeIndex].split("-->");
    const startMs = parseClock(startRaw ?? "");
    const endMs = parseClock((endRaw ?? "").trim().split(/\s+/)[0]);
    const text = stripTags(rows.slice(timeIndex + 1).join("\n"));
    if (!text) {
      warnings.push(`第 ${blockIndex + 1} 个字幕块没有文本，已跳过。`);
      return [];
    }
    if (startMs === null || endMs === null || endMs <= startMs) {
      warnings.push(`第 ${blockIndex + 1} 个字幕块时间无效，请导入后人工校正。`);
    }
    return [
      {
        ...emptyLine(blockIndex, text),
        lineId: rows[0] && /^\d+$/.test(rows[0]) ? `SRT_${rows[0]}` : `SRT_${blockIndex + 1}`,
        startMs,
        endMs,
        durationLimitMs: startMs !== null && endMs !== null && endMs > startMs ? endMs - startMs : null,
      },
    ];
  });
  return { format: "srt", lines, warnings };
};

export const parseAss = (input: string): ImportPreview => {
  const rows = input.replace(/\r\n/g, "\n").split("\n");
  const warnings: string[] = [];
  let fields = ["Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR", "MarginV", "Effect", "Text"];
  const lines: ImportedLine[] = [];
  let inEvents = false;

  rows.forEach((raw) => {
    const row = raw.trim();
    if (/^\[Events\]$/i.test(row)) {
      inEvents = true;
      return;
    }
    if (row.startsWith("[") && !/^\[Events\]$/i.test(row)) {
      inEvents = false;
      return;
    }
    if (!inEvents) return;
    if (/^Format:/i.test(row)) {
      fields = row.slice(row.indexOf(":") + 1).split(",").map((field) => field.trim());
      return;
    }
    if (!/^Dialogue:/i.test(row)) return;
    const body = row.slice(row.indexOf(":") + 1).trimStart();
    const parts = body.split(",");
    if (parts.length < fields.length) {
      warnings.push(`ASS 第 ${lines.length + 1} 条 Dialogue 字段不足，已跳过。`);
      return;
    }
    const fixed = parts.slice(0, fields.length - 1);
    fixed.push(parts.slice(fields.length - 1).join(","));
    const record = Object.fromEntries(fields.map((field, index) => [field.toLowerCase(), fixed[index] ?? ""]));
    const startMs = parseAssClock(record.start ?? "");
    const endMs = parseAssClock(record.end ?? "");
    const text = stripTags(record.text ?? "");
    if (!text) return;
    lines.push({
      ...emptyLine(lines.length, text),
      lineId: `ASS_${String(lines.length + 1).padStart(4, "0")}`,
      startMs,
      endMs,
      speaker: record.name ?? "",
      durationLimitMs: startMs !== null && endMs !== null && endMs > startMs ? endMs - startMs : null,
    });
  });

  if (!lines.length) warnings.push("没有在 [Events] 中找到可导入的 Dialogue 行。");
  return { format: "ass", lines, warnings };
};

export const parseCsvRows = (input: string): string[][] => {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < input.length; index += 1) {
    const char = input[index];
    const next = input[index + 1];
    if (char === '"' && quoted && next === '"') {
      cell += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || (char === "\r" && next !== "\n")) && !quoted) {
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row);
      row = [];
      cell = "";
    } else if (char === "\r" && next === "\n" && !quoted) {
      continue;
    } else {
      cell += char;
    }
  }
  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  return rows;
};

const pick = (record: Record<string, unknown>, keys: string[], fallback = "") => {
  for (const key of keys) {
    const value = record[key];
    if (value !== undefined && value !== null && String(value).trim() !== "") return String(value).trim();
  }
  return fallback;
};

const numberOrNull = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

const recordToLine = (record: Record<string, unknown>, index: number): ImportedLine => {
  const normalized = Object.fromEntries(
    Object.entries(record).map(([key, value]) => [key.trim().toLowerCase(), value]),
  );
  const text = pick(normalized, ["text", "line", "dialogue", "content", "台词", "正文"]);
  const startMs = numberOrNull(normalized.start_ms ?? normalized.startms);
  const endMs = numberOrNull(normalized.end_ms ?? normalized.endms);
  const durationLimitMs = numberOrNull(
    normalized.duration_limit_ms ?? normalized.durationlimitms ?? normalized.duration_limit,
  );
  return {
    lineId: pick(normalized, ["line_id", "lineid", "id"], `LINE_${String(index + 1).padStart(4, "0")}`),
    sceneId: pick(normalized, ["scene_id", "sceneid", "scene"], "SCENE_001"),
    startMs,
    endMs,
    speaker: pick(normalized, ["character_id", "characterid", "speaker", "speaker_id", "角色"]),
    listener: pick(normalized, ["listener", "listener_id", "听者"]),
    text,
    emotion: pick(normalized, ["emotion", "情绪"], "中性"),
    locale: pick(normalized, ["locale", "language", "lang"], "zh-CN"),
    durationLimitMs:
      durationLimitMs ?? (startMs !== null && endMs !== null && endMs > startMs ? endMs - startMs : null),
    assetName: pick(normalized, ["asset_name", "assetname", "filename", "file"]),
  };
};

export const parseCsv = (input: string): ImportPreview => {
  const rows = parseCsvRows(input.replace(/^\uFEFF/, ""));
  if (!rows.length) return { format: "csv", lines: [], warnings: ["CSV 为空。"] };
  const headers = rows[0].map((header) => header.trim());
  const warnings: string[] = [];
  const lines = rows.slice(1).flatMap((row, index) => {
    const record = Object.fromEntries(headers.map((header, cellIndex) => [header, row[cellIndex] ?? ""]));
    const line = recordToLine(record, index);
    if (!line.text) {
      warnings.push(`CSV 第 ${index + 2} 行缺少 text/line/dialogue 字段，已跳过。`);
      return [];
    }
    return [line];
  });
  return { format: "csv", lines, warnings };
};

export const parseJson = (input: string): ImportPreview => {
  const parsed = JSON.parse(input) as unknown;
  const records = Array.isArray(parsed)
    ? parsed
    : typeof parsed === "object" && parsed !== null && Array.isArray((parsed as { lines?: unknown }).lines)
      ? (parsed as { lines: unknown[] }).lines
      : [parsed];
  const warnings: string[] = [];
  const lines = records.flatMap((value, index) => {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      warnings.push(`JSON 第 ${index + 1} 项不是对象，已跳过。`);
      return [];
    }
    const line = recordToLine(value as Record<string, unknown>, index);
    if (!line.text) {
      warnings.push(`JSON 第 ${index + 1} 项缺少台词文本，已跳过。`);
      return [];
    }
    return [line];
  });
  return { format: "json", lines, warnings };
};

export const parseJsonl = (input: string): ImportPreview => {
  const warnings: string[] = [];
  const lines = input.replace(/\r\n/g, "\n").split("\n").flatMap((row, index) => {
    if (!row.trim()) return [];
    try {
      const value = JSON.parse(row) as unknown;
      if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("必须是对象");
      const line = recordToLine(value as Record<string, unknown>, index);
      if (!line.text) throw new Error("缺少台词文本");
      return [line];
    } catch (error) {
      warnings.push(`JSONL 第 ${index + 1} 行无效：${error instanceof Error ? error.message : "未知错误"}`);
      return [];
    }
  });
  return { format: "jsonl", lines, warnings };
};

export const parsePlainText = (input: string): ImportPreview => ({
  format: "text",
  lines: input.replace(/\r\n/g, "\n").split("\n").filter((row) => row.trim()).map((text, index) => emptyLine(index, text)),
  warnings: [],
});

export const parseDialogueText = (name: string, input: string): ImportPreview => {
  const extension = name.toLowerCase().split(".").pop();
  if (extension === "srt") return parseSrt(input);
  if (extension === "ass" || extension === "ssa") return parseAss(input);
  if (extension === "csv") return parseCsv(input);
  if (extension === "json") return parseJson(input);
  if (extension === "jsonl" || extension === "ndjson") return parseJsonl(input);
  return parsePlainText(input);
};

export const parseDialogueFile = async (file: File): Promise<ImportPreview> => {
  const buffer = await file.arrayBuffer();
  return parseDialogueText(file.name, textDecoder.decode(buffer));
};

const csvCell = (value: unknown) => {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

export const exportProjectLines = (
  project: Project,
  lines: DialogueLine[],
  format: "json" | "jsonl" | "csv",
) => {
  const records = lines.map((line) => ({
    line_id: line.lineId,
    scene_id: line.sceneId,
    character_id: line.speakerId,
    listener: line.listener,
    text: line.text,
    emotion: line.emotion,
    emotion_intensity: line.emotionIntensity,
    locale: line.locale,
    start_ms: line.startMs,
    end_ms: line.endMs,
    duration_limit_ms: line.durationBudgetMs,
    voice_profile_id: line.voiceProfileId,
    engine: line.engineId,
    seed: line.seed,
    selected_take_id: line.selectedTakeId,
    locked: line.selectionLocked,
  }));
  let content: string;
  let mime: string;
  if (format === "json") {
    content = JSON.stringify({ project, lines: records }, null, 2);
    mime = "application/json";
  } else if (format === "jsonl") {
    content = records.map((record) => JSON.stringify(record)).join("\n");
    mime = "application/x-ndjson";
  } else {
    const headers = Object.keys(records[0] ?? { line_id: "", text: "" });
    content = [headers.join(","), ...records.map((record) => headers.map((key) => csvCell(record[key as keyof typeof record])).join(","))].join("\r\n");
    mime = "text/csv";
  }
  return { content, mime, fileName: `${project.name.replace(/[\\/:*?"<>|]/g, "_")}.${format}` };
};

export const downloadTextFile = (content: string, mime: string, fileName: string) => {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};
