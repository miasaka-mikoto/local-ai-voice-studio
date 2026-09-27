"""Optional lip-sync/viseme plugin protocol; no tool is installed or invoked."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import threading
from typing import Any, Mapping, Protocol, runtime_checkable

from .base import AdapterUnavailable
from .game_manifest import atomic_text_write


@dataclass(frozen=True, slots=True)
class VisemeCue:
    start_seconds: float
    end_seconds: float
    viseme: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.start_seconds)
            or not math.isfinite(self.end_seconds)
            or self.start_seconds < 0
            or self.end_seconds < self.start_seconds
        ):
            raise ValueError("invalid viseme cue time range")
        if not self.viseme.strip():
            raise ValueError("viseme name must not be empty")
        if self.confidence is not None and (
            not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("viseme confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, object]:
        return {
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "viseme": self.viseme,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class VisemeResult:
    plugin_id: str
    audio_path: str
    cues: tuple[VisemeCue, ...]
    output_path: str | None = None
    audio_sha256: str = ""
    plugin_version: str = ""
    viseme_set: str = "unspecified"
    time_base: str = "seconds"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.audio_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", self.audio_sha256):
            raise ValueError("audio_sha256 must be a 64-character hexadecimal digest")
        if self.time_base != "seconds":
            raise ValueError("viseme time_base must be seconds")
        previous_end = 0.0
        for index, cue in enumerate(self.cues):
            if index and cue.start_seconds < previous_end:
                raise ValueError("viseme cues must be ordered and non-overlapping")
            previous_end = cue.end_seconds

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "viseme_set": self.viseme_set,
            "time_base": self.time_base,
            "audio_path": self.audio_path,
            "audio_sha256": self.audio_sha256,
            "cues": [cue.to_dict() for cue in self.cues],
            "metadata": dict(self.metadata),
        }

    def write_json(
        self, path: str | Path, cancel_event: threading.Event | None = None
    ) -> Path:
        destination = Path(path)
        atomic_text_write(
            destination,
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            cancel_event,
        )
        return destination


@runtime_checkable
class VisemePlugin(Protocol):
    plugin_id: str

    def available(self) -> bool: ...

    def generate(
        self,
        audio_path: str | Path,
        transcript: str,
        *,
        locale: str = "und",
        output_path: str | Path | None = None,
        cancel_event: threading.Event | None = None,
    ) -> VisemeResult: ...


class DisabledVisemePlugin:
    """Explicit placeholder used until Rhubarb or another tool is configured."""

    plugin_id = "disabled"

    def available(self) -> bool:
        return False

    def generate(
        self,
        audio_path: str | Path,
        transcript: str,
        *,
        locale: str = "und",
        output_path: str | Path | None = None,
        cancel_event: threading.Event | None = None,
    ) -> VisemeResult:
        del audio_path, transcript, locale, output_path, cancel_event
        raise AdapterUnavailable("viseme generation is optional and no plugin is configured")


class VisemeRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, VisemePlugin] = {"disabled": DisabledVisemePlugin()}

    def register(self, plugin: VisemePlugin, *, replace: bool = False) -> None:
        if plugin.plugin_id in self._plugins and not replace:
            raise ValueError(f"viseme plugin already registered: {plugin.plugin_id}")
        self._plugins[plugin.plugin_id] = plugin

    def get(self, plugin_id: str) -> VisemePlugin:
        try:
            return self._plugins[plugin_id]
        except KeyError as exc:
            raise KeyError(f"unknown viseme plugin: {plugin_id}") from exc

    def available_plugins(self) -> tuple[str, ...]:
        return tuple(sorted(key for key, plugin in self._plugins.items() if plugin.available()))
