from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .errors import DomainError
from .repository import Repository
from .util import canonical_json, new_id, resolve_relative, safe_filename, stable_hash, utc_now


GAME_FIELDS = [
    "character_id", "line_id", "scene_id", "text", "emotion", "context", "listener",
    "variation", "locale", "asset_name", "duration_limit_ms", "selected_take_id", "audio_path",
]


def _srt_time(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _atomic_text(path: Path, content: str) -> None:
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(content, encoding="utf-8", newline="")
    os.replace(partial, path)


class ProjectExporter:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def _export_rows(self, project_id: str, destination: Path) -> tuple[list[dict[str, Any]], list[str]]:
        lines = self.repository.list_lines(project_id)
        audio_dir = destination / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        used_names: set[str] = set()
        for line in lines:
            audio_relative = ""
            take = None
            if line.get("selected_take_id"):
                take = self.repository.get_take(line["selected_take_id"])
                base = safe_filename(
                    line.get("asset_name") or line.get("external_line_id") or f"line_{line['ordinal']:04d}"
                )
                candidate = f"{base}.wav"
                if candidate.lower() in used_names:
                    candidate = f"{base}_{line['id'][:8]}.wav"
                used_names.add(candidate.lower())
                source = resolve_relative(take["asset_path"], self.repository.settings.data_root)
                target = audio_dir / candidate
                shutil.copy2(source, target)
                audio_relative = f"audio/{candidate}"
                if take["is_stale"]:
                    warnings.append(f"台词 {line['id']} 的人工选择 take 已过期，但按人工锁定原样导出")
            else:
                warnings.append(f"台词 {line['id']} 尚未选择 take")
            rows.append(
                {
                    "character_id": line.get("character_id") or line.get("speaker", ""),
                    "line_id": line.get("external_line_id") or line["id"],
                    "scene_id": line.get("scene_id") or line.get("scene_label", ""),
                    "text": line["text"],
                    "emotion": line["emotion"],
                    "context": line["context"],
                    "listener": line["listener"],
                    "variation": line["variation"],
                    "locale": line["locale"],
                    "asset_name": line.get("asset_name") or Path(audio_relative).stem,
                    "duration_limit_ms": line.get("duration_limit_ms"),
                    "selected_take_id": line.get("selected_take_id"),
                    "audio_path": audio_relative,
                    "start_ms": line.get("start_ms"),
                    "end_ms": line.get("end_ms"),
                    "revision": line["revision"],
                    "content_hash": line["content_hash"],
                }
            )
        return rows, warnings

    def export(self, project_id: str, export_format: str, task_id: str) -> dict[str, Any]:
        normalized = export_format.strip().lower().lstrip(".")
        if normalized not in {"project_json", "json", "jsonl", "csv", "srt"}:
            raise DomainError(
                "unsupported_export_format", f"不支持导出格式：{export_format}",
                details={"supported": ["project_json", "json", "jsonl", "csv", "srt"]},
            )
        project = self.repository.get_project(project_id)
        export_id = new_id()
        destination = self.repository.settings.data_root / "projects" / project_id / "exports" / export_id
        destination.mkdir(parents=True, exist_ok=False)
        rows, warnings = self._export_rows(project_id, destination)
        if normalized == "project_json":
            payload = {
                "schema_version": "1.0",
                "exported_at": utc_now(),
                "project": project,
                "scenes": self.repository.list_scenes(project_id),
                "characters": self.repository.list_characters(project_id),
                "voices": self.repository.list_voices(project_id),
                "lines": rows,
            }
            output = destination / "project.json"
            _atomic_text(output, json.dumps(payload, ensure_ascii=False, indent=2))
        elif normalized == "json":
            output = destination / "lines.json"
            _atomic_text(output, json.dumps(rows, ensure_ascii=False, indent=2))
        elif normalized == "jsonl":
            output = destination / "lines.jsonl"
            _atomic_text(output, "\n".join(canonical_json(row) for row in rows) + ("\n" if rows else ""))
        elif normalized == "csv":
            output = destination / "lines.csv"
            partial = output.with_suffix(".csv.part")
            with partial.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=GAME_FIELDS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            os.replace(partial, output)
        else:
            output = destination / "dialogue.srt"
            blocks = []
            for index, row in enumerate(rows, 1):
                start = row.get("start_ms")
                end = row.get("end_ms")
                if start is None or end is None:
                    warnings.append(f"台词 {row['line_id']} 没有时间码，未写入 SRT")
                    continue
                blocks.append(f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n{row['text']}")
            _atomic_text(output, "\n\n".join(blocks) + ("\n" if blocks else ""))
        manifest = {
            "schema_version": "1.0",
            "project_id": project_id,
            "format": normalized,
            "output": output.name,
            "audio_master": {"sample_rate_hz": 48000, "bit_depth": 24, "channels": 1},
            "line_count": len(rows),
            "warnings": warnings,
            "created_at": utc_now(),
        }
        manifest_path = destination / "manifest.json"
        _atomic_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
        input_hash = stable_hash(
            [{"id": row["line_id"], "revision": row["revision"], "take": row["selected_take_id"]} for row in rows]
        )
        record = self.repository.record_export(
            project_id=project_id, export_format=normalized, path=destination,
            input_hash=input_hash, warnings=warnings, task_id=task_id,
        )
        record.update({"output_path": str(output), "manifest_path": str(manifest_path), "line_count": len(rows)})
        return record
