"""Non-invasive game-engine manifest exporters.

These exporters create import tables/manifests only.  They never modify a game
project, invoke an editor, or synthesize proprietary project files.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import csv
import io
import json
from pathlib import Path, PurePosixPath
import threading
from typing import Iterable

from .base import AdapterCancelled
from .game_manifest import GameLine, atomic_text_write
from .naming import slug_component


def _normalize_audio_root(root: str) -> PurePosixPath:
    normalized = str(root).strip().replace("\\", "/")
    base = PurePosixPath(normalized)
    if not normalized or base.is_absolute() or ".." in base.parts or any(":" in part for part in base.parts):
        raise ValueError("audio_root must be a non-empty relative game asset path")
    return base


def _audio_path(root: PurePosixPath, line: GameLine) -> str:
    return str(root / line.ensure_asset_name().asset_name)


def _prepared_lines(
    lines: Iterable[GameLine], cancel_event: threading.Event | None
) -> tuple[GameLine, ...]:
    result: list[GameLine] = []
    seen: set[str] = set()
    for raw_line in lines:
        if cancel_event is not None and cancel_event.is_set():
            raise AdapterCancelled("game export cancelled")
        line = raw_line.ensure_asset_name()
        identity = line.asset_name.casefold()
        if identity in seen:
            raise ValueError(f"duplicate case-insensitive asset_name: {line.asset_name}")
        seen.add(identity)
        result.append(line)
    return tuple(result)


def _write_csv(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: list[dict[str, object]],
    cancel_event: threading.Event | None,
) -> Path:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_text_write(path, buffer.getvalue(), cancel_event)
    return path


class GameManifestExporter(ABC):
    target: str

    @abstractmethod
    def export(
        self,
        lines: Iterable[GameLine],
        destination: Path,
        *,
        audio_root: str,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        raise NotImplementedError


class GenericExporter(GameManifestExporter):
    target = "generic"

    def export(
        self,
        lines: Iterable[GameLine],
        destination: Path,
        *,
        audio_root: str,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        root = _normalize_audio_root(audio_root)
        records = []
        for line in _prepared_lines(lines, cancel_event):
            record = line.to_dict()
            record["asset_id"] = Path(line.asset_name).stem
            record["audio_file"] = _audio_path(root, line)
            records.append(record)
        payload = {"schema_version": "1.0", "target": self.target, "assets": records}
        atomic_text_write(
            destination,
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            cancel_event,
        )
        return destination


class WwiseExporter(GameManifestExporter):
    target = "wwise"
    fields = (
        "AudioFile", "ObjectPath", "SoundName", "Language", "LineId", "CharacterId",
        "SceneId", "Emotion", "EmotionIntensity", "Variation", "Seed", "TakeIndex",
        "EngineId", "VoiceProfile", "ModelRevision", "InputHash", "DurationLimit",
        "Listener", "Context", "Subtitle", "Metadata",
    )

    def export(
        self,
        lines: Iterable[GameLine],
        destination: Path,
        *,
        audio_root: str,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        root = _normalize_audio_root(audio_root)
        rows: list[dict[str, object]] = []
        for line in _prepared_lines(lines, cancel_event):
            asset_id = Path(line.asset_name).stem
            object_path = "\\Actor-Mixer Hierarchy\\Default Work Unit\\Voice\\{}\\{}\\{}".format(
                slug_component(line.character_id),
                slug_component(line.scene_id or "unscoped"),
                asset_id,
            )
            rows.append(
                {
                    "AudioFile": _audio_path(root, line).replace("/", "\\"),
                    "ObjectPath": object_path,
                    "SoundName": asset_id,
                    "Language": line.locale,
                    "LineId": line.line_id,
                    "CharacterId": line.character_id,
                    "SceneId": line.scene_id,
                    "Emotion": line.emotion,
                    "EmotionIntensity": line.emotion_intensity,
                    "Variation": line.variation,
                    "Seed": line.seed,
                    "TakeIndex": line.take_index,
                    "EngineId": line.engine_id,
                    "VoiceProfile": line.voice_profile,
                    "ModelRevision": line.model_revision,
                    "InputHash": line.input_hash,
                    "DurationLimit": line.duration_limit,
                    "Listener": line.listener,
                    "Context": line.context,
                    "Subtitle": line.text,
                    "Metadata": json.dumps(line.to_dict()["metadata"], ensure_ascii=False, sort_keys=True, allow_nan=False),
                }
            )
        return _write_csv(destination, self.fields, rows, cancel_event)


class FmodExporter(GameManifestExporter):
    target = "fmod"
    fields = (
        "event_path", "asset_id", "audio_file", "locale", "line_id", "character_id",
        "scene_id", "emotion", "emotion_intensity", "variation", "seed", "take_index",
        "engine_id", "voice_profile", "model_revision", "input_hash", "duration_limit",
        "listener", "context", "subtitle", "metadata",
    )

    def export(
        self,
        lines: Iterable[GameLine],
        destination: Path,
        *,
        audio_root: str,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        root = _normalize_audio_root(audio_root)
        rows: list[dict[str, object]] = []
        for line in _prepared_lines(lines, cancel_event):
            asset_id = Path(line.asset_name).stem
            rows.append(
                {
                    "event_path": "event:/voice/{}/{}/{}".format(
                        slug_component(line.locale),
                        slug_component(line.character_id),
                        asset_id,
                    ),
                    "asset_id": asset_id,
                    "audio_file": _audio_path(root, line),
                    "locale": line.locale,
                    "line_id": line.line_id,
                    "character_id": line.character_id,
                    "scene_id": line.scene_id,
                    "emotion": line.emotion,
                    "emotion_intensity": line.emotion_intensity,
                    "variation": line.variation,
                    "seed": line.seed,
                    "take_index": line.take_index,
                    "engine_id": line.engine_id,
                    "voice_profile": line.voice_profile,
                    "model_revision": line.model_revision,
                    "input_hash": line.input_hash,
                    "duration_limit": line.duration_limit,
                    "listener": line.listener,
                    "context": line.context,
                    "subtitle": line.text,
                    "metadata": json.dumps(line.to_dict()["metadata"], ensure_ascii=False, sort_keys=True, allow_nan=False),
                }
            )
        return _write_csv(destination, self.fields, rows, cancel_event)


class UnityExporter(GameManifestExporter):
    target = "unity"

    def export(
        self,
        lines: Iterable[GameLine],
        destination: Path,
        *,
        audio_root: str,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        root = _normalize_audio_root(audio_root)
        assets = []
        for line in _prepared_lines(lines, cancel_event):
            relative = _audio_path(root, line)
            record = line.to_dict()
            record.update(
                {
                    "assetId": Path(line.asset_name).stem,
                    "address": f"voice/{slug_component(line.locale)}/{Path(line.asset_name).stem}",
                    "assetPath": str(PurePosixPath("Assets") / relative),
                }
            )
            assets.append(record)
        payload = {"schemaVersion": "1.0", "kind": "LocalVoiceStudioUnityManifest", "assets": assets}
        atomic_text_write(
            destination,
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            cancel_event,
        )
        return destination


class GodotExporter(GameManifestExporter):
    target = "godot"

    def export(
        self,
        lines: Iterable[GameLine],
        destination: Path,
        *,
        audio_root: str,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        root = _normalize_audio_root(audio_root)
        assets: dict[str, dict[str, object]] = {}
        for line in _prepared_lines(lines, cancel_event):
            asset_id = Path(line.asset_name).stem
            record = line.to_dict()
            record.update({"resource": "res://" + _audio_path(root, line), "bus": "Voice"})
            assets[asset_id] = record
        payload = {"schema_version": "1.0", "kind": "local_voice_studio_godot", "assets": assets}
        atomic_text_write(
            destination,
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            cancel_event,
        )
        return destination


class UnrealExporter(GameManifestExporter):
    target = "unreal"
    fields = (
        "Name", "AudioFile", "DialogueContext", "Speaker", "Listener", "Subtitle", "Locale",
        "LineId", "Emotion", "EmotionIntensity", "Variation", "Seed", "TakeIndex", "EngineId",
        "VoiceProfile", "ModelRevision", "InputHash", "DurationLimit", "Context", "Metadata",
    )

    def export(
        self,
        lines: Iterable[GameLine],
        destination: Path,
        *,
        audio_root: str,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        root = _normalize_audio_root(audio_root)
        rows: list[dict[str, object]] = []
        for line in _prepared_lines(lines, cancel_event):
            rows.append(
                {
                    "Name": Path(line.asset_name).stem,
                    "AudioFile": _audio_path(root, line),
                    "DialogueContext": line.scene_id,
                    "Speaker": line.character_id,
                    "Listener": line.listener,
                    "Subtitle": line.text,
                    "Locale": line.locale,
                    "LineId": line.line_id,
                    "Emotion": line.emotion,
                    "EmotionIntensity": line.emotion_intensity,
                    "Variation": line.variation,
                    "Seed": line.seed,
                    "TakeIndex": line.take_index,
                    "EngineId": line.engine_id,
                    "VoiceProfile": line.voice_profile,
                    "ModelRevision": line.model_revision,
                    "InputHash": line.input_hash,
                    "DurationLimit": line.duration_limit,
                    "Context": line.context,
                    "Metadata": json.dumps(line.to_dict()["metadata"], ensure_ascii=False, sort_keys=True, allow_nan=False),
                }
            )
        return _write_csv(destination, self.fields, rows, cancel_event)


class ExporterRegistry:
    def __init__(self) -> None:
        exporters = (GenericExporter(), WwiseExporter(), FmodExporter(), UnityExporter(), GodotExporter(), UnrealExporter())
        self._exporters = {exporter.target: exporter for exporter in exporters}

    @property
    def targets(self) -> tuple[str, ...]:
        return tuple(sorted(self._exporters))

    def get(self, target: str) -> GameManifestExporter:
        try:
            return self._exporters[target.lower()]
        except KeyError as exc:
            raise ValueError(f"unknown export target {target!r}; expected one of {self.targets}") from exc

    def register(self, exporter: GameManifestExporter, *, replace: bool = False) -> None:
        if exporter.target in self._exporters and not replace:
            raise ValueError(f"export target already registered: {exporter.target}")
        self._exporters[exporter.target] = exporter


def export_game_manifest(
    target: str,
    lines: Iterable[GameLine],
    destination: str | Path,
    *,
    audio_root: str = "Audio/Voice",
    registry: ExporterRegistry | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    active_registry = registry or ExporterRegistry()
    return active_registry.get(target).export(
        lines,
        Path(destination),
        audio_root=audio_root,
        cancel_event=cancel_event,
    )
