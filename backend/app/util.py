from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_load(value: str | None, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    return sha256_text(canonical_json(value))


def safe_filename(value: str, fallback: str = "asset") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value).strip(" .")
    cleaned = re.sub(r"\s+", "_", cleaned)
    if not cleaned:
        cleaned = fallback
    if cleaned.upper().split(".", 1)[0] in WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:120]


def relative_posix(path: Path, root: Path) -> str:
    resolved = path.resolve()
    base = root.resolve()
    try:
        relative = resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"路径不在数据根目录内：{resolved}") from exc
    return PurePosixPath(relative).as_posix()


def resolve_relative(relative: str, root: Path) -> Path:
    candidate = (root / Path(PurePosixPath(relative))).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("资源路径越过数据根目录") from exc
    return candidate
