from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from .engines import EngineCatalog
from .repository import Repository
from .util import utc_now


PROJECT_KIND_TO_UI = {
    "video": "video_dubbing",
    "game": "game_voice",
    "character": "voice_dataset",
    "japanese": "japanese_learning",
}

LICENSE_RISK_TO_UI = {
    "permissive": "low",
    "copyleft_review": "review",
    "custom_review": "review",
    "unknown": "review",
    "noncommercial": "restricted",
}


def _actions(status: str) -> list[str]:
    return {
        "queued": ["cancel"],
        "running": ["pause", "cancel"],
        "paused": ["resume", "cancel"],
        "failed": ["retry"],
        "stale": ["recompute", "cancel"],
    }.get(status, [])


def _memory() -> tuple[float, float]:
    if os.name != "nt":
        return 0.0, 0.0

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0.0, 0.0
    return round(status.ullAvailPhys / (1024 ** 3), 2), round(status.ullTotalPhys / (1024 ** 3), 2)


def _gpu() -> tuple[str, int, int]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        first = result.stdout.strip().splitlines()[0]
        name, used, total = [part.strip() for part in first.split(",", 2)]
        return name, int(used), int(total)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return "NVIDIA GPU（状态未读取）", 0, 0


class SnapshotBuilder:
    def __init__(self, repository: Repository, voice_root: Path) -> None:
        self.repository = repository
        self.catalog = EngineCatalog(voice_root)
        self.conversations: list[dict[str, Any]] = []

    def add_preview_conversation(self, text: str, coach_mode: str) -> None:
        from .util import new_id

        now = utc_now()
        self.conversations.append({"id": new_id(), "role": "learner", "text": text, "createdAt": now})
        feedback = "请保持自然节奏。" if coach_mode == "flow" else "优先检查助词与长短音，并立即重说。"
        self.conversations.append(
            {"id": new_id(), "role": "teacher", "text": f"收到：{text}", "feedback": feedback,
             "confidence": 0.5, "createdAt": now}
        )
        self.conversations = self.conversations[-100:]

    def build(self) -> dict[str, Any]:
        projects_raw = self.repository.list_projects()
        all_lines: list[dict[str, Any]] = []
        all_characters: list[dict[str, Any]] = []
        all_takes: list[dict[str, Any]] = []
        projects: list[dict[str, Any]] = []
        for project in projects_raw:
            lines = self.repository.list_lines(project["id"])
            characters = self.repository.list_characters(project["id"])
            selected = sum(1 for line in lines if line.get("selected_take_id"))
            completed_ratio = selected / len(lines) if lines else 0.0
            projects.append(
                {
                    "id": project["id"], "name": project["name"],
                    "kind": PROJECT_KIND_TO_UI[project["project_type"]], "status": "active",
                    "description": project["description"], "locale": project["default_locale"],
                    "progress": round(completed_ratio * 100), "lineCount": len(lines), "selectedTakeCount": selected,
                    "characterCount": len(characters), "createdAt": project["created_at"],
                    "updatedAt": project["updated_at"],
                }
            )
            for line in lines:
                takes = self.repository.list_takes(line["id"])
                stale = any(take["is_stale"] for take in takes)
                all_lines.append(
                    {
                        "id": line["id"], "projectId": project["id"],
                        "lineId": line.get("external_line_id") or line["id"],
                        "sceneId": line.get("scene_id") or line.get("scene_label", ""),
                        "index": line["ordinal"], "startMs": line.get("start_ms"), "endMs": line.get("end_ms"),
                        "sourceText": line["source_text"], "text": line["text"], "locale": line["locale"],
                        "speakerId": line.get("character_id"), "listener": line["listener"], "intent": line["intent"],
                        "subtext": line["subtext"], "emotion": line["emotion"],
                        "emotionIntensity": line["emotion_intensity"], "pace": line["pace"], "pitch": line["pitch"],
                        "volume": line["volume"], "breath": line["breath"], "pause": line["pause"],
                        "pronunciation": json.dumps(line["pronunciation"], ensure_ascii=False),
                        "durationBudgetMs": line.get("duration_budget_ms"), "voiceProfileId": line.get("voice_id"),
                        "engineId": line["engine_id"], "seed": line["seed"],
                        "selectedTakeId": line.get("selected_take_id"),
                        "selectionLocked": line["selection_locked"], "revision": line["revision"], "stale": stale,
                    }
                )
                for take in takes:
                    all_takes.append(
                        {
                            "id": take["id"], "projectId": project["id"], "lineId": line["id"],
                            "index": take["variant_no"], "engineId": take["engine_id"],
                            "modelVersion": take["model_version"], "seed": take["seed"],
                            "durationMs": take["duration_ms"], "sampleRate": take["sample_rate_hz"],
                            "subtype": "PCM_24", "loudnessLufs": None,
                            "status": "stale" if take["is_stale"] else "ready",
                            "audioUrl": f"http://127.0.0.1:{self.repository.settings.port}/api/v1/takes/{take['id']}/audio",
                            "emotion": line["emotion"], "qualityScore": None,
                            "selected": line.get("selected_take_id") == take["id"],
                            "inputHash": take["input_hash"], "createdAt": take["created_at"],
                        }
                    )
            for character in characters:
                profile = character["profile"]
                authorization = character["authorization_status"]
                all_characters.append(
                    {
                        "id": character["id"], "projectId": project["id"],
                        "characterId": character.get("external_id") or character["id"], "name": character["name"],
                        "color": profile.get("color", "#7c9cff"), "identity": profile.get("identity", ""),
                        "ageImpression": profile.get("age_impression", ""), "timbre": profile.get("timbre", ""),
                        "speechHabits": profile.get("speech_habits", ""), "politeness": profile.get("politeness", ""),
                        "voiceProfileId": character.get("default_voice_id"),
                        "authorizationStatus": authorization if authorization in {"verified", "pending", "restricted"} else "unknown",
                    }
                )
        voices = []
        for voice in self.repository.list_voices():
            profile = voice["voice_profile"]
            authorization = voice["authorization_status"]
            voices.append(
                {"id": voice["id"], "name": voice["name"], "engineId": voice["engine_id"],
                 "locale": voice["locale"], "description": profile.get("description", ""),
                 "authorizationStatus": authorization if authorization in {"verified", "pending", "restricted"} else "pending",
                 "licenseNote": voice["authorization"].get("license_note", "")}
            )
        jobs = []
        for task in self.repository.list_tasks():
            error = task["error"]
            jobs.append(
                {"id": task["id"], "projectId": task["project_id"], "kind": task["task_type"],
                 "label": task["task_type"], "status": task["status"], "progress": task["progress"],
                 "stage": task["phase"], "engineId": task["payload"].get("engine_id"),
                 "attempt": task["attempt"], "error": error.get("message") if error else None,
                 "recoverable": task["status"] in {"failed", "stale", "paused"},
                 "allowedActions": _actions(task["status"]), "createdAt": task["created_at"],
                 "updatedAt": task["updated_at"]}
            )
        engines = []
        for engine in self.catalog.list():
            license_value = str(engine.get("license", "unknown"))
            risk = LICENSE_RISK_TO_UI.get(str(engine.get("license_risk", "unknown")), "review")
            capabilities = list(engine.get("kinds", []))
            capabilities.extend(name for name, enabled in {
                "cloning": engine.get("cloning"), "emotion": engine.get("emotion_control"),
                "training": engine.get("training")}.items() if enabled)
            capabilities = list(dict.fromkeys(capabilities))
            vram_mb = engine.get("vram_mb")
            engines.append(
                {"id": engine["id"], "name": engine.get("name") or engine["id"],
                 "role": engine.get("role", "流程测试"), "deploymentStatus": engine.get("status", "unknown"),
                 "runtimeStatus": "stopped" if engine["id"] != "mock" else "running",
                 "license": license_value, "licenseRisk": risk, "languages": engine.get("languages", []),
                 "capabilities": capabilities, "sampleRate": engine.get("sample_rate_hz"),
                 "vramGb": round(vram_mb / 1024, 1) if isinstance(vram_mb, (int, float)) else None}
            )
        gpu_name, gpu_used, gpu_total = _gpu()
        ram_available, ram_total = _memory()
        disk = shutil.disk_usage(self.repository.settings.data_root)
        lease = self.repository.gpu_lease()
        return {
            "projects": projects, "lines": all_lines, "characters": all_characters,
            "voices": voices, "takes": all_takes, "jobs": jobs, "engines": engines,
            "system": {
                "apiVersion": "0.1.0", "hostname": socket.gethostname(), "platform": platform.platform(),
                "gpuName": gpu_name, "gpuUsedMb": gpu_used, "gpuTotalMb": gpu_total,
                "ramAvailableGb": ram_available, "ramTotalGb": ram_total,
                "diskFreeGb": round(disk.free / (1024 ** 3), 2),
                "gpuScheduler": "busy" if lease else "idle", "activeEngineId": None,
                "ffmpegReady": (self.catalog.voice_root / "tools" / "ffmpeg" / "ffmpeg.exe").is_file(),
                "databaseReady": True, "lastUpdatedAt": utc_now(),
            },
            "conversations": list(self.conversations),
        }
