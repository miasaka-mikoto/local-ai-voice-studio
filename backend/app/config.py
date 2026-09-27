from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    backend_root: Path
    data_root: Path
    database_path: Path
    host: str = "127.0.0.1"
    port: int = 8766
    worker_enabled: bool = True
    worker_poll_seconds: float = 0.2
    max_import_bytes: int = 8 * 1024 * 1024
    max_scene_artwork_bytes: int = 16 * 1024 * 1024

    @classmethod
    def load(
        cls,
        *,
        data_root: Path | None = None,
        database_path: Path | None = None,
        worker_enabled: bool | None = None,
    ) -> "Settings":
        backend_root = Path(__file__).resolve().parents[1]
        configured_root = data_root or Path(
            os.getenv("VOICE_STUDIO_DATA_ROOT", str(backend_root / "data"))
        )
        configured_db = database_path or Path(
            os.getenv("VOICE_STUDIO_DATABASE", str(configured_root / "voice_studio.sqlite3"))
        )
        host = os.getenv("VOICE_STUDIO_HOST", "127.0.0.1").strip()
        if host not in LOOPBACK_HOSTS:
            raise ValueError("VOICE_STUDIO_HOST 只允许本机回环地址 127.0.0.1/localhost/::1")
        port = int(os.getenv("VOICE_STUDIO_PORT", "8766"))
        if not (1 <= port <= 65535):
            raise ValueError("VOICE_STUDIO_PORT 必须在 1..65535 范围内")
        return cls(
            backend_root=backend_root,
            data_root=configured_root.resolve(),
            database_path=configured_db.resolve(),
            host=host,
            port=port,
            worker_enabled=(
                _env_bool("VOICE_STUDIO_WORKER_ENABLED", True)
                if worker_enabled is None
                else worker_enabled
            ),
            worker_poll_seconds=float(os.getenv("VOICE_STUDIO_WORKER_POLL_SECONDS", "0.2")),
            max_import_bytes=int(os.getenv("VOICE_STUDIO_MAX_IMPORT_BYTES", str(8 * 1024 * 1024))),
            max_scene_artwork_bytes=int(
                os.getenv("VOICE_STUDIO_MAX_SCENE_ARTWORK_BYTES", str(16 * 1024 * 1024))
            ),
        )

    def ensure_directories(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        (self.data_root / "projects").mkdir(parents=True, exist_ok=True)
