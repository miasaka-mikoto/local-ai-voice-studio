from __future__ import annotations

import csv
import html
import io
import json
import re
from dataclasses import dataclass
from typing import Any

from .errors import DomainError


SRT_TIME_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
ASS_OVERRIDE_RE = re.compile(r"\{[^}]*\}")


@dataclass(slots=True)
class ImportResult:
    lines: list[dict[str, Any]]
    warnings: list[str]


def decode_bytes(data: bytes, requested_encoding: str | None = None) -> str:
    encodings = [requested_encoding] if requested_encoding else []
    encodings.extend(["utf-8-sig", "utf-16", "cp932", "gb18030"])
    failures: list[str] = []
    for encoding in dict.fromkeys(item for item in encodings if item):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            failures.append(f"{encoding}: {exc}")
    raise DomainError(
        "unsupported_encoding",
        "无法解码导入文件，请显式指定 encoding",
        details={"attempts": failures},
    )


def parse_timestamp(value: str) -> int:
    normalized = value.strip().replace(",", ".")
    parts = normalized.split(":")
    if len(parts) != 3:
        raise ValueError(f"无效时间戳：{value}")
    hours, minutes = int(parts[0]), int(parts[1])
    seconds = float(parts[2])
    return int(round((hours * 3600 + minutes * 60 + seconds) * 1000))


def _clean_subtitle(value: str) -> str:
    value = value.replace("\\N", "\n").replace("\\n", "\n")
    return html.unescape(HTML_TAG_RE.sub("", value)).strip()


def parse_srt(content: str) -> ImportResult:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ImportResult([], ["SRT 内容为空"])
    blocks = re.split(r"\n\s*\n", normalized)
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for block_number, block in enumerate(blocks, 1):
        rows = [row.rstrip() for row in block.split("\n") if row.strip()]
        if not rows:
            continue
        time_index = next((i for i, row in enumerate(rows) if "-->" in row), -1)
        if time_index < 0:
            warnings.append(f"第 {block_number} 个字幕块缺少时间戳，已跳过")
            continue
        match = SRT_TIME_RE.search(rows[time_index])
        if match is None:
            raise DomainError(
                "invalid_srt_timestamp",
                f"第 {block_number} 个字幕块时间戳无效",
                details={"value": rows[time_index]},
            )
        text = _clean_subtitle("\n".join(rows[time_index + 1 :]))
        if not text:
            warnings.append(f"第 {block_number} 个字幕块台词为空，已跳过")
            continue
        external_id = rows[0].strip() if time_index > 0 else str(block_number)
        start_ms = parse_timestamp(match.group("start"))
        end_ms = parse_timestamp(match.group("end"))
        records.append(
            {
                "external_line_id": external_id,
                "ordinal": len(records),
                "source_text": text,
                "text": text,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_limit_ms": max(0, end_ms - start_ms),
                "duration_budget_ms": max(0, end_ms - start_ms),
                "source_payload": {"srt_block": block_number},
            }
        )
    return ImportResult(records, warnings)


def parse_ass(content: str) -> ImportResult:
    in_events = False
    fields: list[str] = []
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for line_number, raw in enumerate(content.replace("\r\n", "\n").split("\n"), 1):
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_events = line.lower() == "[events]"
            continue
        if not in_events or not line:
            continue
        if line.lower().startswith("format:"):
            fields = [part.strip().lower() for part in line.split(":", 1)[1].split(",")]
            continue
        if not line.lower().startswith("dialogue:"):
            continue
        if not fields:
            raise DomainError("invalid_ass", "ASS [Events] 缺少 Format 行")
        values = line.split(":", 1)[1].lstrip().split(",", len(fields) - 1)
        if len(values) != len(fields):
            warnings.append(f"ASS 第 {line_number} 行字段数不匹配，已跳过")
            continue
        row = dict(zip(fields, values, strict=True))
        text = _clean_subtitle(ASS_OVERRIDE_RE.sub("", row.get("text", "")))
        if not text:
            continue
        start_ms = parse_timestamp(row.get("start", "0:00:00.00"))
        end_ms = parse_timestamp(row.get("end", "0:00:00.00"))
        speaker = row.get("name", "").strip()
        records.append(
            {
                "external_line_id": str(line_number),
                "ordinal": len(records),
                "source_text": text,
                "text": text,
                "speaker": speaker,
                "character_external_id": speaker or None,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_limit_ms": max(0, end_ms - start_ms),
                "duration_budget_ms": max(0, end_ms - start_ms),
                "source_payload": row,
            }
        )
    return ImportResult(records, warnings)


def _first(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return default


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(float(value))


def _float(value: Any, default: float) -> float:
    if value in (None, ""):
        return default
    return float(value)


def _json_object(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(str(value))
    except json.JSONDecodeError:
        return {"instruction": str(value)}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


def normalize_record(row: dict[str, Any], ordinal: int) -> dict[str, Any]:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    text = str(_first(lowered, "text", "dialogue", "line", "content", "source_text", default="")).strip()
    if not text:
        raise DomainError(
            "missing_line_text",
            f"第 {ordinal + 1} 行没有台词文本",
            details={"row": ordinal + 1},
        )
    source_text = str(_first(lowered, "source_text", "original_text", default=text)).strip()
    external_line_id = _first(lowered, "line_id", "external_line_id", "id")
    speaker = str(_first(lowered, "speaker", "character", "character_name", default="")).strip()
    character_external_id = _first(lowered, "character_id", "speaker_id", default=speaker or None)
    scene_external_id = _first(lowered, "scene_id", "external_scene_id")
    scene_label = str(_first(lowered, "scene", "scene_name", default=scene_external_id or "")).strip()
    start_ms = _optional_int(_first(lowered, "start_ms", "start"))
    end_ms = _optional_int(_first(lowered, "end_ms", "end"))
    duration_limit_ms = _optional_int(
        _first(lowered, "duration_limit_ms", "duration_limit", "duration_budget_ms", "duration_budget")
    )
    if duration_limit_ms is None and start_ms is not None and end_ms is not None:
        duration_limit_ms = max(0, end_ms - start_ms)
    pronunciation = _json_object(_first(lowered, "pronunciation", "pronunciation_json"))
    return {
        "external_line_id": None if external_line_id in (None, "") else str(external_line_id),
        "ordinal": _optional_int(_first(lowered, "ordinal", "order", "index")) or ordinal,
        "scene_external_id": None if scene_external_id in (None, "") else str(scene_external_id),
        "scene_label": scene_label,
        "character_external_id": None if character_external_id in (None, "") else str(character_external_id),
        "source_text": source_text,
        "text": text,
        "speaker": speaker,
        "listener": str(_first(lowered, "listener", default="")),
        "intent": str(_first(lowered, "intent", default="")),
        "subtext": str(_first(lowered, "subtext", default="")),
        "emotion": str(_first(lowered, "emotion", default="neutral")),
        "emotion_intensity": min(1.0, max(0.0, _float(_first(lowered, "emotion_intensity"), 0.5))),
        "pace": max(0.1, _float(_first(lowered, "pace"), 1.0)),
        "pitch": _float(_first(lowered, "pitch"), 0.0),
        "volume": max(0.0, _float(_first(lowered, "volume"), 1.0)),
        "breath": str(_first(lowered, "breath", default="")),
        "pause": str(_first(lowered, "pause", default="")),
        "pronunciation": pronunciation,
        "duration_budget_ms": _optional_int(_first(lowered, "duration_budget_ms", "duration_budget")) or duration_limit_ms,
        "engine_id": str(_first(lowered, "engine", "engine_id", default="mock")),
        "seed": _optional_int(_first(lowered, "seed")) or 42,
        "context": str(_first(lowered, "context", default="")),
        "variation": str(_first(lowered, "variation", default="")),
        "locale": str(_first(lowered, "locale", default="ja-JP")),
        "asset_name": str(_first(lowered, "asset_name", default="")),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_limit_ms": duration_limit_ms,
        "source_payload": row,
    }


def parse_csv_content(content: str) -> ImportResult:
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise DomainError("invalid_csv", "CSV 缺少表头")
    lines = [normalize_record(dict(row), index) for index, row in enumerate(reader)]
    return ImportResult(lines, [])


def parse_json_content(content: str) -> ImportResult:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise DomainError(
            "invalid_json", f"JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列"
        ) from exc
    if isinstance(payload, dict):
        for key in ("lines", "dialogues", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise DomainError("invalid_json_shape", "JSON 必须是数组或包含 lines/dialogues/items 数组")
    if not all(isinstance(item, dict) for item in payload):
        raise DomainError("invalid_json_shape", "JSON 台词数组的每个元素必须是对象")
    return ImportResult([normalize_record(item, index) for index, item in enumerate(payload)], [])


def parse_jsonl_content(content: str) -> ImportResult:
    records: list[dict[str, Any]] = []
    for line_number, raw in enumerate(content.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DomainError(
                "invalid_jsonl", f"JSONL 第 {line_number} 行解析失败：{exc.msg}", details={"row": line_number}
            ) from exc
        if not isinstance(value, dict):
            raise DomainError("invalid_jsonl", f"JSONL 第 {line_number} 行必须是对象")
        records.append(normalize_record(value, len(records)))
    return ImportResult(records, [])


def parse_import(source_format: str, content: str) -> ImportResult:
    normalized = source_format.strip().lower().lstrip(".")
    if normalized == "srt":
        return parse_srt(content)
    if normalized in {"ass", "ssa"}:
        return parse_ass(content)
    if normalized == "csv":
        return parse_csv_content(content)
    if normalized == "json":
        return parse_json_content(content)
    if normalized == "jsonl":
        return parse_jsonl_content(content)
    raise DomainError(
        "unsupported_import_format",
        f"不支持导入格式：{source_format}",
        details={"supported": ["srt", "ass", "csv", "json", "jsonl"]},
    )
