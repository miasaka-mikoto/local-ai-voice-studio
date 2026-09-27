"""In-memory engine registry; lifecycle scheduling remains backend-owned."""

from __future__ import annotations

from pathlib import Path
import threading

from .base import EngineAdapterProtocol, ManifestOnlyEngineAdapter
from .deployment import DeploymentImportResult, import_deployment_manifest
from .models import EngineCapability, EngineKind, LicenseRisk, RuntimeWeight


class EngineRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, EngineAdapterProtocol] = {}
        self._lock = threading.RLock()

    def register(self, adapter: EngineAdapterProtocol, *, replace: bool = False) -> None:
        capability = adapter.capability
        with self._lock:
            if capability.engine_id in self._adapters and not replace:
                raise ValueError(f"engine already registered: {capability.engine_id}")
            self._adapters[capability.engine_id] = adapter

    def unregister(self, engine_id: str) -> EngineAdapterProtocol:
        with self._lock:
            return self._adapters.pop(engine_id)

    def get(self, engine_id: str) -> EngineAdapterProtocol:
        with self._lock:
            try:
                return self._adapters[engine_id]
            except KeyError as exc:
                raise KeyError(f"unknown engine: {engine_id}") from exc

    def capabilities(
        self,
        *,
        kind: EngineKind | None = None,
        language: str | None = None,
        include_noncommercial: bool = True,
        include_unknown_languages: bool = False,
    ) -> tuple[EngineCapability, ...]:
        with self._lock:
            values = [adapter.capability for adapter in self._adapters.values()]
        if kind is not None:
            values = [item for item in values if kind in item.kinds]
        if language is not None:
            values = [
                item
                for item in values
                if language in item.languages or (include_unknown_languages and not item.languages)
            ]
        if not include_noncommercial:
            values = [item for item in values if item.license_risk != LicenseRisk.NONCOMMERCIAL]
        return tuple(sorted(values, key=lambda item: item.engine_id))

    def import_manifest(
        self, path: str | Path, *, replace: bool = False
    ) -> DeploymentImportResult:
        result = import_deployment_manifest(path)
        with self._lock:
            conflicts = [
                item.engine_id for item in result.capabilities if item.engine_id in self._adapters
            ]
            if conflicts and not replace:
                raise ValueError(
                    "manifest import would replace registered engines: " + ", ".join(sorted(conflicts))
                )
            for capability in result.capabilities:
                self._adapters[capability.engine_id] = ManifestOnlyEngineAdapter(capability)
        return result

    def snapshot(self) -> list[dict[str, object]]:
        return [item.to_dict() for item in self.capabilities()]

    def backend_catalog(self) -> list[dict[str, object]]:
        """Return the transitional shape consumed by the current MVP backend.

        This keeps the safe registry as the fact source while the backend moves
        from its original deployment.json-specific EngineCatalog.
        """

        result: list[dict[str, object]] = []
        with self._lock:
            adapters = tuple(
                sorted(self._adapters.values(), key=lambda value: value.capability.engine_id)
            )
        for adapter in adapters:
            item = adapter.capability
            try:
                health_available = adapter.health().available
            except Exception:
                health_available = False
            artifact_path = next(
                (
                    item.local_path_roles[key]
                    for key in ("model_path", "base_model_path", "weights_path", "download_target")
                    if key in item.local_path_roles
                ),
                None,
            )
            result.append(
                {
                    "id": item.engine_id,
                    "name": item.display_name,
                    "role": item.metadata.get("role", ""),
                    "kinds": [str(value) for value in item.kinds],
                    "languages": list(item.languages),
                    "cloning": item.supports_voice_cloning,
                    "emotion_control": item.supports_emotion_control,
                    "training": item.supports_training,
                    "sample_rate_hz": item.output_sample_rates[0] if item.output_sample_rates else None,
                    "vram_mb": item.minimum_vram_mb,
                    "license": item.license_name,
                    "license_note": item.metadata.get("license_note"),
                    "license_risk": str(item.license_risk),
                    "path": artifact_path,
                    "status": item.status,
                    "available_on_disk": item.available_on_disk,
                    "heavy_gpu": item.runtime_weight == RuntimeWeight.HEAVY,
                    "executable_in_mvp": (
                        not isinstance(adapter, ManifestOnlyEngineAdapter) and health_available
                    ),
                }
            )
        return result

    def unload_all(self) -> None:
        """Best-effort unload, intended for the backend's single-GPU scheduler."""

        with self._lock:
            adapters = tuple(self._adapters.values())
        errors: list[str] = []
        for adapter in adapters:
            try:
                adapter.unload()
            except Exception as exc:  # adapters are isolated; aggregate failures
                errors.append(f"{adapter.capability.engine_id}: {exc}")
        if errors:
            raise RuntimeError("one or more engines failed to unload: " + "; ".join(errors))
