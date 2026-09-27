"""Canonical game dialogue rows plus CSV/JSON/JSONL interchange."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field, replace
import io
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Iterable, Mapping

from .base import AdapterCancelled
from .models import _freeze_json, _thaw_json
from .naming import stable_asset_name


_CANONICAL_FIELDS = (
    "line_id",
    "character_id",
    "text",
    "scene_id",
    "emotion",
    "emotion_intensity",
    "context",
    "listener",
    "variation",
    "locale",
    "asset_name",
    "duration_limit",
    "seed",
    "take_index",
    "engine_id",
    "voice_profile",
    "model_revision",
    "input_hash",
    "metadata",
)
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_WRITE_LOCK_SHARD_COUNT = 64
_WRITE_LOCK_SHARDS = tuple(threading.Lock() for _ in range(_WRITE_LOCK_SHARD_COUNT))


class ManifestWriteError(RuntimeError):
    """A recoverable manifest commit failure, usually a Windows file lock."""


def _cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AdapterCancelled("game manifest operation cancelled")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _json_loads(value: str) -> Any:
    return json.loads(value, parse_constant=_reject_json_constant)


def _float(value: object, default: float | None) -> float | None:
    if value in (None, ""):
        return default
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("numeric fields must be finite")
    return number


def _int(value: object, default: int) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise ValueError("integer fields must not be booleans")
    return int(value)


def _required_identifier(value: object, field_name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{field_name} must be a non-empty string or integer")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("text must be a non-empty string")
    return value.strip()


def _optional_text(value: object, field_name: str) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{field_name} must be scalar text")
    return str(value).strip()


def _locale(value: object) -> str:
    normalized = str(value or "und").strip()
    aliases = {
        "chinese": "zh-CN",
        "japanese": "ja-JP",
        "english": "en-US",
        "中文": "zh-CN",
        "日语": "ja-JP",
    }
    return aliases.get(normalized.lower(), aliases.get(normalized, normalized or "und"))


@dataclass(frozen=True, slots=True)
class GameLine:
    line_id: str
    character_id: str
    text: str
    scene_id: str = ""
    emotion: str = "neutral"
    emotion_intensity: float = 0.5
    context: str = ""
    listener: str = ""
    variation: int = 0
    locale: str = "und"
    asset_name: str = ""
    duration_limit: float | None = None
    seed: int = 0
    take_index: int = 0
    engine_id: str = ""
    voice_profile: str = ""
    model_revision: str = ""
    input_hash: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.line_id.strip() or not self.character_id.strip():
            raise ValueError("line_id and character_id are required")
        if not self.text.strip():
            raise ValueError("text must not be empty")
        if not math.isfinite(self.emotion_intensity) or not 0.0 <= self.emotion_intensity <= 1.0:
            raise ValueError("emotion_intensity must be between 0 and 1")
        if self.variation < 0 or self.take_index < 0:
            raise ValueError("variation and take_index must be non-negative")
        if self.duration_limit is not None and (
            not math.isfinite(self.duration_limit) or self.duration_limit <= 0
        ):
            raise ValueError("duration_limit must be positive")
        if self.asset_name and (
            Path(self.asset_name).name != self.asset_name or "/" in self.asset_name or "\\" in self.asset_name
        ):
            raise ValueError("asset_name must be a filename, not a path")
        if self.asset_name:
            if any(ord(char) < 32 or char in '<>:"|?*' for char in self.asset_name):
                raise ValueError("asset_name contains characters forbidden by Windows")
            if self.asset_name.endswith((" ", ".")) or Path(self.asset_name).stem.lower() in _WINDOWS_RESERVED:
                raise ValueError("asset_name is reserved or has an invalid Windows suffix")
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))

    def ensure_asset_name(self) -> "GameLine":
        if self.asset_name:
            return self
        return replace(
            self,
            asset_name=stable_asset_name(
                line_id=self.line_id,
                character_id=self.character_id,
                locale=self.locale,
                emotion=self.emotion,
                emotion_intensity=self.emotion_intensity,
                variation=self.variation,
                seed=self.seed,
                take_index=self.take_index,
                text=self.text,
                engine_id=self.engine_id,
                voice_profile=self.voice_profile,
                model_revision=self.model_revision,
                input_hash=self.input_hash,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        value = self.ensure_asset_name()
        return {
            "line_id": value.line_id,
            "character_id": value.character_id,
            "text": value.text,
            "scene_id": value.scene_id,
            "emotion": value.emotion,
            "emotion_intensity": value.emotion_intensity,
            "context": value.context,
            "listener": value.listener,
            "variation": value.variation,
            "locale": value.locale,
            "asset_name": value.asset_name,
            "duration_limit": value.duration_limit,
            "seed": value.seed,
            "take_index": value.take_index,
            "engine_id": value.engine_id,
            "voice_profile": value.voice_profile,
            "model_revision": value.model_revision,
            "input_hash": value.input_hash,
            "metadata": _thaw_json(value.metadata),
        }

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        default_scene_id: str = "",
        default_locale: str = "und",
        inherited_metadata: Mapping[str, Any] | None = None,
    ) -> "GameLine":
        line_id = value.get("line_id", value.get("dialogue_id", value.get("id", "")))
        character_id = value.get("character_id", value.get("speaker_id", value.get("speaker", "")))
        known = set(_CANONICAL_FIELDS) | {
            "id",
            "dialogue_id",
            "speaker_id",
            "speaker",
            "language",
            "stage_direction",
            "subtext",
            "target_duration_seconds",
            "candidate_index",
            "engine",
            "listener_target",
            "listener_targets",
        }
        metadata: dict[str, Any] = dict(inherited_metadata or {})
        raw_metadata = value.get("metadata")
        if isinstance(raw_metadata, str) and raw_metadata.strip():
            try:
                decoded = _json_loads(raw_metadata)
                if isinstance(decoded, dict):
                    metadata.update(decoded)
                else:
                    metadata["source_metadata_value"] = decoded
            except json.JSONDecodeError:
                metadata["source_metadata_text"] = raw_metadata
        elif isinstance(raw_metadata, Mapping):
            metadata.update(raw_metadata)
        elif raw_metadata is not None:
            metadata["source_metadata_value"] = raw_metadata
        metadata.update({key: item for key, item in value.items() if key not in known})
        context_parts = [
            _optional_text(value.get("context", ""), "context"),
            _optional_text(value.get("stage_direction", ""), "stage_direction"),
        ]
        subtext = _optional_text(value.get("subtext", ""), "subtext")
        if subtext:
            metadata.setdefault("subtext", subtext)
        raw_listener = value.get(
            "listener",
            value.get("listener_target", value.get("listener_targets", "")),
        )
        if isinstance(raw_listener, list):
            listener = ",".join(_required_identifier(item, "listener_targets item") for item in raw_listener)
        else:
            listener = _optional_text(raw_listener, "listener")
        line = cls(
            line_id=_required_identifier(line_id, "line_id"),
            character_id=_required_identifier(character_id, "character_id"),
            text=_required_text(value.get("text")),
            scene_id=_optional_text(value.get("scene_id", default_scene_id) or default_scene_id, "scene_id"),
            emotion=_optional_text(value.get("emotion", "neutral") or "neutral", "emotion") or "neutral",
            emotion_intensity=float(_float(value.get("emotion_intensity"), 0.5)),
            context=" | ".join(part for part in context_parts if part),
            listener=listener,
            variation=_int(value.get("variation", value.get("candidate_index")), 0),
            locale=_locale(value.get("locale", value.get("language", default_locale))),
            asset_name=_optional_text(value.get("asset_name", ""), "asset_name"),
            duration_limit=_float(value.get("duration_limit", value.get("target_duration_seconds")), None),
            seed=_int(value.get("seed"), 0),
            take_index=_int(value.get("take_index"), 0),
            engine_id=_optional_text(value.get("engine_id", value.get("engine", "")), "engine_id"),
            voice_profile=_optional_text(value.get("voice_profile", ""), "voice_profile"),
            model_revision=_optional_text(value.get("model_revision", ""), "model_revision"),
            input_hash=_optional_text(value.get("input_hash", ""), "input_hash"),
            metadata=metadata,
        )
        return line.ensure_asset_name()


def _mapping_rows(
    values: object,
    *,
    label: str,
    default_scene_id: str = "",
    default_locale: str = "und",
    inherited_metadata: Mapping[str, Any] | None = None,
    cancel_event: threading.Event | None = None,
) -> list[GameLine]:
    if not isinstance(values, list):
        raise ValueError(f"{label} must be an array")
    result: list[GameLine] = []
    for index, item in enumerate(values):
        _cancelled(cancel_event)
        if not isinstance(item, Mapping):
            raise ValueError(f"{label}[{index}] must be an object")
        result.append(
            GameLine.from_mapping(
                item,
                default_scene_id=default_scene_id,
                default_locale=default_locale,
                inherited_metadata=inherited_metadata,
            )
        )
    return result


def _rows_from_json(
    value: object, cancel_event: threading.Event | None = None
) -> list[GameLine]:
    if isinstance(value, list):
        return _mapping_rows(value, label="root", cancel_event=cancel_event)
    if not isinstance(value, Mapping):
        raise ValueError("JSON root must be an array or object")
    default_locale = _locale(value.get("target_language", value.get("language", "und")))
    if "lines" in value:
        return _mapping_rows(
            value["lines"], label="lines", default_locale=default_locale, cancel_event=cancel_event
        )
    if "dialogues" in value:
        return _mapping_rows(
            value["dialogues"],
            label="dialogues",
            default_locale=default_locale,
            cancel_event=cancel_event,
        )
    scenes = value.get("scenes")
    if "scenes" in value:
        if not isinstance(scenes, list):
            raise ValueError("scenes must be an array")
        result: list[GameLine] = []
        for scene_index, scene in enumerate(scenes):
            _cancelled(cancel_event)
            if not isinstance(scene, Mapping):
                raise ValueError(f"scenes[{scene_index}] must be an object")
            scene_id = _optional_text(
                scene.get("scene_id", scene.get("id", "")), "scene_id"
            )
            dialogues = scene.get("dialogues", scene.get("lines", []))
            if not isinstance(dialogues, list):
                raise ValueError(f"scenes[{scene_index}].dialogues must be an array")
            scene_metadata = {
                f"scene_{key}": scene[key]
                for key in ("title", "synopsis", "location", "stakes", "previous_scene_summary")
                if key in scene
            }
            result.extend(
                _mapping_rows(
                    dialogues,
                    label=f"scenes[{scene_index}].dialogues",
                    default_scene_id=scene_id,
                    default_locale=default_locale,
                    inherited_metadata=scene_metadata,
                    cancel_event=cancel_event,
                )
            )
        return result
    if any(key in value for key in ("line_id", "dialogue_id", "id")):
        return [GameLine.from_mapping(value)]
    raise ValueError("JSON object contains no supported dialogue collection")


def import_lines(
    path: str | Path, cancel_event: threading.Event | None = None
) -> list[GameLine]:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            result = []
            for index, row in enumerate(csv.DictReader(handle), start=2):
                _cancelled(cancel_event)
                try:
                    result.append(GameLine.from_mapping(row))
                except ValueError as exc:
                    raise ValueError(f"invalid CSV record at line {index}: {exc}") from exc
            return result
    if suffix == ".jsonl":
        result: list[GameLine] = []
        with source.open("r", encoding="utf-8-sig") as handle:
            for number, raw in enumerate(handle, start=1):
                _cancelled(cancel_event)
                if not raw.strip():
                    continue
                try:
                    value = _json_loads(raw)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise ValueError(f"invalid JSONL record at line {number}: {exc}") from exc
                if not isinstance(value, Mapping):
                    raise ValueError(f"JSONL record at line {number} must be an object")
                try:
                    result.append(GameLine.from_mapping(value))
                except ValueError as exc:
                    raise ValueError(f"invalid JSONL record at line {number}: {exc}") from exc
        return result
    if suffix == ".json":
        _cancelled(cancel_event)
        return _rows_from_json(
            _json_loads(source.read_text(encoding="utf-8-sig")), cancel_event=cancel_event
        )
    raise ValueError(f"unsupported game dialogue format: {suffix or '<none>'}")


def _target_lock(path: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(path))
    return _WRITE_LOCK_SHARDS[hash(key) % _WRITE_LOCK_SHARD_COUNT]


def atomic_text_write(
    path: Path, text: str, cancel_event: threading.Event | None = None
) -> None:
    _cancelled(cancel_event)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _target_lock(path):
        _cancelled(cancel_event)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(text, encoding="utf-8", newline="")
            _cancelled(cancel_event)
            for attempt, delay in enumerate((0.0, 0.05, 0.1, 0.2, 0.4)):
                _cancelled(cancel_event)
                if delay:
                    time.sleep(delay)
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError as exc:
                    if attempt == 4:
                        raise ManifestWriteError(
                            f"cannot replace {path}; the file may be open in another Windows application"
                        ) from exc
        finally:
            if temporary.exists():
                temporary.unlink()


def export_lines(
    lines: Iterable[GameLine],
    path: str | Path,
    cancel_event: threading.Event | None = None,
) -> Path:
    destination = Path(path)
    rows = []
    for line in lines:
        _cancelled(cancel_event)
        rows.append(line.to_dict())
    suffix = destination.suffix.lower()
    if suffix == ".json":
        atomic_text_write(
            destination,
            json.dumps(
                {"schema_version": "1.0", "lines": rows},
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            cancel_event,
        )
        return destination
    if suffix == ".jsonl":
        atomic_text_write(
            destination,
            "".join(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
                for row in rows
            ),
            cancel_event,
        )
        return destination
    if suffix == ".csv":
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=_CANONICAL_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            row = dict(row)
            _cancelled(cancel_event)
            row["metadata"] = json.dumps(
                row["metadata"], ensure_ascii=False, sort_keys=True, allow_nan=False
            )
            writer.writerow(row)
        atomic_text_write(destination, buffer.getvalue(), cancel_event)
        return destination
    raise ValueError(f"unsupported game dialogue format: {suffix or '<none>'}")
