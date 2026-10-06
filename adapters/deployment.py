"""Safe, allow-list based import of local deployment capability manifests."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from .models import EngineCapability, EngineKind, LicenseRisk, RuntimeWeight


MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_ENGINES = 256
_ENGINE_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_PATH_KEYS = (
    "model_path",
    "base_model_path",
    "weights_path",
    "indices_path",
    "auxiliary_path",
    "download_target",
    "environment",
    "audio_tokenizer",
)
_ARTIFACT_PATH_KEYS = {"model_path", "base_model_path", "weights_path", "download_target"}
_SAFE_METADATA_KEYS = (
    "role",
    "license_note",
    "hardware_note",
    "default_version",
    "alternate_version",
    "python",
    "torch",
)
_SECRET_MARKER = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|password|secret|authorization)\s*[:=]"
)


@dataclass(frozen=True, slots=True)
class DeploymentImportResult:
    source_path: str
    schema_version: str
    capabilities: tuple[EngineCapability, ...]
    hardware: Mapping[str, Any]
    policy: Mapping[str, Any]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "schema_version": self.schema_version,
            "capabilities": [item.to_dict() for item in self.capabilities],
            "hardware": dict(self.hardware),
            "policy": dict(self.policy),
            "warnings": list(self.warnings),
        }


def _read_manifest(path: Path) -> dict[str, Any]:
    if str(path).startswith(("\\\\", "//")):
        raise ValueError("UNC/network deployment manifests are not allowed")
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size <= 0 or size > MAX_MANIFEST_BYTES:
        raise ValueError(f"manifest size {size} is outside the allowed range")
    try:
        def reject_constant(constant: str) -> None:
            raise ValueError(f"non-finite JSON number is not allowed: {constant}")

        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key is not allowed: {key}")
                result[key] = value
            return result

        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid UTF-8 JSON manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("deployment manifest root must be an object")
    return value


def _local_endpoint(value: object) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    if not isinstance(value, str) or len(value) > 2048:
        return None, "ignored endpoint with invalid type or length"
    endpoint = value.strip()
    try:
        parsed = urlsplit(endpoint)
        parsed.port  # Validate malformed or out-of-range ports without connecting.
    except ValueError:
        return None, "ignored malformed endpoint"
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        return None, "ignored endpoint with unsupported scheme"
    if (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        return None, "ignored non-loopback endpoint for local-only policy"
    if parsed.username or parsed.password:
        return None, "ignored endpoint containing credentials"
    if parsed.query or parsed.fragment:
        return None, "ignored endpoint containing query parameters or fragment"
    return endpoint, None


def _public_source_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    return value.strip()


def classify_license(license_name: str, license_note: str = "") -> LicenseRisk:
    name = re.sub(r"\s+", " ", license_name.strip().lower())
    note = re.sub(r"\s+", " ", license_note.strip().lower())
    text = f"{name} {note}".strip()
    if any(term in text for term in ("non-commercial", "noncommercial", "cc by-nc", "research only")):
        return LicenseRisk.NONCOMMERCIAL
    if "agpl" in text or "gpl" in text:
        return LicenseRisk.COPYLEFT_REVIEW
    if any(term in text for term in ("model license", "creator use", "revenue", "separate commercial")):
        return LicenseRisk.CUSTOM_REVIEW
    exact_permissive = {
        "apache-2.0", "apache 2.0", "apache license 2.0", "mit", "mit license",
        "bsd-2-clause", "bsd-3-clause", "cc0", "cc0-1.0",
    }
    if not note and name in exact_permissive:
        return LicenseRisk.PERMISSIVE
    if not text.strip() or text.strip() == "unknown":
        return LicenseRisk.UNKNOWN
    return LicenseRisk.CUSTOM_REVIEW


def _infer_kinds(engine_id: str, role: str) -> tuple[EngineKind, ...]:
    text = f"{engine_id} {role}".lower()
    kinds: list[EngineKind] = []
    if any(term in text for term in ("tts", "voice_design", "voice design", "synthesis")):
        kinds.append(EngineKind.TTS)
    if any(term in text for term in ("voice_color", "voice color", "voice conversion", "seed_vc", "rvc")):
        kinds.append(EngineKind.VOICE_CONVERSION)
    if any(term in text for term in ("train", "lora", "fine-tun", "finetun")):
        kinds.append(EngineKind.TRAINING)
    if any(term in text for term in ("director", "direction")):
        kinds.append(EngineKind.DIRECTOR)
    if "asr" in text or "whisper" in text:
        kinds.append(EngineKind.ASR)
    if any(term in text for term in ("qa", "quality", "pasqa")):
        kinds.append(EngineKind.QUALITY)
    if not kinds:
        kinds.append(EngineKind.TTS)
    return tuple(dict.fromkeys(kinds))


def _infer_languages(role: str, engine: Mapping[str, Any]) -> tuple[str, ...]:
    declared: list[str] = []
    language = engine.get("language")
    languages = engine.get("languages")
    if isinstance(language, str):
        declared.append(language)
    if isinstance(languages, list) and all(isinstance(item, str) for item in languages):
        declared.extend(languages)
    elif isinstance(languages, str):
        declared.append(languages)
    text = f"{role} {' '.join(declared)}".lower()
    languages: list[str] = []
    if any(term in text for term in ("japanese", "jp", "日本", "日语")):
        languages.append("ja")
    if any(term in text for term in ("chinese", "zh", "中文", "汉语")):
        languages.append("zh")
    if "english" in text or " en" in f" {text}":
        languages.append("en")
    if "cross_lingual" in text or "multilingual" in text:
        languages.extend(("zh", "ja", "en"))
    return tuple(dict.fromkeys(languages))


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve(strict=False)
    candidate = os.path.normcase(str(resolved))
    for root in roots:
        normalized_root = os.path.normcase(str(root.resolve(strict=False)))
        try:
            if os.path.commonpath((candidate, normalized_root)) == normalized_root:
                return True
        except ValueError:
            continue
    return False


def _allowed_roots(source: Path, supplied: Iterable[str | Path] | None) -> tuple[Path, ...]:
    raw_roots = list(supplied or ())
    if not raw_roots:
        raw_roots = [source.parent.parent if source.parent.name.lower() == "deployment" else source.parent]
    roots: list[Path] = []
    for raw in raw_roots:
        text = str(raw)
        windows = PureWindowsPath(text)
        if text.startswith(("\\\\", "//", "\\\\?\\")) or not Path(text).is_absolute():
            raise ValueError("allowed_roots must contain absolute local paths")
        roots.append(Path(text).resolve(strict=False))
    return tuple(roots)


def _safe_environment_root(
    manifest: Mapping[str, Any], source: Path, roots: tuple[Path, ...]
) -> tuple[Path, str | None]:
    raw = manifest.get("environment_root")
    if not isinstance(raw, str) or not raw.strip():
        return roots[0], None
    value = raw.strip()
    windows = PureWindowsPath(value)
    if (
        _SECRET_MARKER.search(value)
        or
        value.startswith(("\\\\", "//", "\\\\?\\"))
        or ".." in windows.parts
        or (windows.drive and not windows.root)
        or (windows.root and not windows.drive and not Path(value).is_absolute())
        or (windows.is_absolute() and os.name != "nt")
    ):
        return roots[0], "ignored unsafe environment_root"
    candidate = Path(value) if Path(value).is_absolute() else source.parent / value
    if not _is_within(candidate, roots):
        return roots[0], "ignored environment_root outside allowed roots"
    return candidate.resolve(strict=False), None


def _resolve_local_path(
    raw: object, base: Path, roots: tuple[Path, ...]
) -> tuple[str | None, str | None]:
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    value = raw.strip()
    windows = PureWindowsPath(value)
    if (
        "\x00" in value
        or _SECRET_MARKER.search(value)
        or value.startswith(("\\\\", "//", "\\\\?\\"))
        or ".." in windows.parts
        or (windows.drive and not windows.root)
        or (windows.root and not windows.drive and not Path(value).is_absolute())
        or (windows.is_absolute() and os.name != "nt")
    ):
        return None, "ignored unsafe, network path, or ambiguous declared path"
    candidate = Path(value) if Path(value).is_absolute() else base / value
    if not _is_within(candidate, roots):
        return None, "ignored declared path outside allowed roots"
    return str(candidate.resolve(strict=False)), None


def _minimum_vram(engine: Mapping[str, Any]) -> int | None:
    for key in ("minimum_vram_mb", "vram_mb", "estimated_vram_mb"):
        value = engine.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    raw_note = engine.get("hardware_note", "")
    note = raw_note.lower() if isinstance(raw_note, str) else ""
    match = re.search(r"(?:near_|about_|minimum_)?(\d{1,3})\s*gb", note)
    return int(match.group(1)) * 1024 if match else None


def _bounded_text(
    value: object,
    *,
    default: str = "",
    maximum: int = 1024,
) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        return default
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or _SECRET_MARKER.search(normalized):
        return default
    return normalized


def _safe_metadata(engine: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in _SAFE_METADATA_KEYS:
        if key not in engine:
            continue
        value = engine[key]
        if isinstance(value, str) and len(value) <= 2048 and not _SECRET_MARKER.search(value):
            result[key] = value
        elif isinstance(value, bool) or value is None:
            result[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            result[key] = value
    return result


def _capability_from_engine(
    engine: Mapping[str, Any],
    roots: tuple[Path, ...],
    environment_root: Path,
    warnings: list[str],
) -> EngineCapability:
    raw_id = engine.get("id")
    if not isinstance(raw_id, str) or not _ENGINE_ID.fullmatch(raw_id):
        raise ValueError("invalid engine id in deployment manifest")
    for field_name in (
        "role", "license", "license_note", "model", "model_repo",
        "model_revision", "checked_revision", "status",
    ):
        if field_name in engine and engine[field_name] is not None and not isinstance(engine[field_name], str):
            warnings.append(f"{raw_id}: ignored {field_name} with invalid type")
    role = _bounded_text(engine.get("role"), maximum=512)
    license_name = _bounded_text(engine.get("license"), default="unknown", maximum=1024)
    license_note = _bounded_text(engine.get("license_note"), maximum=2048)
    endpoint, endpoint_warning = _local_endpoint(engine.get("url"))
    if endpoint_warning:
        warnings.append(f"{raw_id}: {endpoint_warning}")
    path_roles: dict[str, str] = {}
    for key in _PATH_KEYS:
        value, path_warning = _resolve_local_path(engine.get(key), environment_root, roots)
        if path_warning:
            warnings.append(f"{raw_id}: {key}: {path_warning}")
        if value is not None:
            path_roles[key] = value
    paths = tuple(path_roles.values())
    available = False
    for key, value in path_roles.items():
        if key not in _ARTIFACT_PATH_KEYS:
            continue
        try:
            if Path(value).exists():
                available = True
                break
        except OSError:
            warnings.append(f"{raw_id}: could not inspect declared local path")
    source_url = _public_source_url(engine.get("source"))
    model_id = _bounded_text(engine.get("model") or engine.get("model_repo"), maximum=512)
    model_revision = _bounded_text(
        engine.get("model_revision") or engine.get("checked_revision"), maximum=256
    )
    status = _bounded_text(engine.get("status"), default="unknown", maximum=160)
    lower = f"{raw_id} {role}".lower()
    rates: tuple[int, ...] = (48_000,) if "48k" in lower or "48khz" in lower else ()
    metadata = _safe_metadata(engine)
    return EngineCapability(
        engine_id=raw_id,
        display_name=model_id or raw_id,
        kinds=_infer_kinds(raw_id, role),
        languages=_infer_languages(role, engine),
        supports_voice_cloning=any(term in lower for term in ("clone", "reference", "rvc", "seed_vc")),
        supports_emotion_control=any(term in lower for term in ("emotion", "acting", "director")),
        supports_training=any(term in lower for term in ("train", "lora", "rvc", "gpt_sovits")),
        output_sample_rates=rates,
        minimum_vram_mb=_minimum_vram(engine),
        runtime_weight=RuntimeWeight.HEAVY,
        license_name=license_name,
        license_risk=classify_license(license_name, license_note),
        source_url=source_url,
        model_id=model_id or None,
        model_revision=model_revision or None,
        local_paths=paths,
        local_path_roles=path_roles,
        endpoint=endpoint,
        status=status,
        available_on_disk=available,
        metadata=metadata,
    )


def import_deployment_manifest(
    path: str | Path,
    *,
    allowed_roots: Iterable[str | Path] | None = None,
) -> DeploymentImportResult:
    """Import capabilities without importing engine Python or honoring commands.

    Only allow-listed descriptive keys are copied.  Install commands, arbitrary
    environment data, API keys, and remote endpoints are deliberately ignored.
    """

    source = Path(path)
    manifest = _read_manifest(source)
    source = source.resolve()
    schema_version = manifest.get("schema_version")
    if schema_version != "1.0":
        raise ValueError("unsupported deployment schema_version")
    roots = _allowed_roots(source, allowed_roots)
    environment_root, environment_warning = _safe_environment_root(manifest, source, roots)
    engines = manifest.get("engines")
    if not isinstance(engines, list):
        raise ValueError("deployment manifest must contain an engines array")
    if len(engines) > MAX_ENGINES:
        raise ValueError(f"deployment manifest contains more than {MAX_ENGINES} engines")
    warnings: list[str] = []
    if environment_warning:
        warnings.append(environment_warning)
    capabilities: list[EngineCapability] = []
    seen: set[str] = set()
    for index, raw in enumerate(engines):
        if not isinstance(raw, dict):
            raise ValueError(f"engine entry {index} must be an object")
        capability = _capability_from_engine(
            raw, roots, environment_root, warnings
        )
        if capability.engine_id in seen:
            raise ValueError(f"duplicate engine id: {capability.engine_id}")
        seen.add(capability.engine_id)
        capabilities.append(capability)
    raw_hardware = manifest.get("hardware", {})
    hardware: dict[str, Any] = {}
    if isinstance(raw_hardware, dict):
        gpu = _bounded_text(raw_hardware.get("gpu"), maximum=256)
        if gpu:
            hardware["gpu"] = gpu
        system_ram = raw_hardware.get("system_ram_gb")
        if (
            isinstance(system_ram, (int, float))
            and not isinstance(system_ram, bool)
            and math.isfinite(system_ram)
            and system_ram > 0
        ):
            hardware["system_ram_gb"] = system_ram
        hardware_policy = _bounded_text(raw_hardware.get("policy"), maximum=128)
        if hardware_policy:
            hardware["policy"] = hardware_policy
    raw_policy = manifest.get("policy", {})
    policy: dict[str, Any] = {}
    if isinstance(raw_policy, dict):
        for key in (
            "one_engine_at_a_time",
            "require_two_resource_checks",
            "forbid_unlicensed_reference_audio",
        ):
            if isinstance(raw_policy.get(key), bool):
                policy[key] = raw_policy[key]
        interval = raw_policy.get("minimum_check_interval_seconds")
        if isinstance(interval, int) and not isinstance(interval, bool) and interval >= 0:
            policy["minimum_check_interval_seconds"] = interval
        if raw_policy.get("require_runtime_lock"):
            policy["require_runtime_lock"] = True
    if hardware.get("policy") == "one_engine_at_a_time":
        policy["one_engine_at_a_time"] = True
    reference_policy = _bounded_text(manifest.get("reference_audio_policy"), maximum=128)
    if reference_policy:
        policy["reference_audio_policy"] = reference_policy
    return DeploymentImportResult(
        source_path=str(source),
        schema_version=schema_version,
        capabilities=tuple(capabilities),
        hardware=hardware,
        policy=policy,
        warnings=tuple(warnings),
    )
