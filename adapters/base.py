"""Runtime adapter protocol and safe manifest-only placeholder."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import threading
from typing import Protocol, runtime_checkable

from .models import EngineCapability, EngineHealth, SynthesisRequest, SynthesisResult


class AdapterError(RuntimeError):
    """Base class for user-actionable adapter failures."""


class AdapterUnavailable(AdapterError):
    """Raised when an engine is registered but no runtime bridge is configured."""


class AdapterCancelled(AdapterError):
    """Raised when a cooperative cancellation event is observed."""


@runtime_checkable
class EngineAdapterProtocol(Protocol):
    @property
    def capability(self) -> EngineCapability: ...

    def health(self) -> EngineHealth: ...

    def synthesize(
        self,
        request: SynthesisRequest,
        output_dir: str | Path,
        cancel_event: threading.Event | None = None,
    ) -> SynthesisResult: ...

    def unload(self) -> None: ...


class EngineAdapter(ABC):
    @property
    @abstractmethod
    def capability(self) -> EngineCapability:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> EngineHealth:
        raise NotImplementedError

    @abstractmethod
    def synthesize(
        self,
        request: SynthesisRequest,
        output_dir: str | Path,
        cancel_event: threading.Event | None = None,
    ) -> SynthesisResult:
        raise NotImplementedError

    @abstractmethod
    def unload(self) -> None:
        raise NotImplementedError


class ManifestOnlyEngineAdapter(EngineAdapter):
    """Exposes audited capabilities without importing or starting model code."""

    def __init__(self, capability: EngineCapability) -> None:
        self._capability = capability

    @property
    def capability(self) -> EngineCapability:
        return self._capability

    def health(self) -> EngineHealth:
        return EngineHealth(
            engine_id=self._capability.engine_id,
            available=self._capability.available_on_disk,
            loaded=False,
            detail="manifest only; runtime bridge is not configured",
        )

    def synthesize(
        self,
        request: SynthesisRequest,
        output_dir: str | Path,
        cancel_event: threading.Event | None = None,
    ) -> SynthesisResult:
        del request, output_dir, cancel_event
        raise AdapterUnavailable(
            f"engine {self._capability.engine_id!r} is registered for capability "
            "inspection only; configure an isolated runtime bridge before use"
        )

    def unload(self) -> None:
        return None
