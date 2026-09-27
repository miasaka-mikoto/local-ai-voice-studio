from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Settings
from .database import Database
from .errors import DomainError
from .scene_artworks import extension_for_mime, inspect_image, validate_local_source
from .util import (
    canonical_json,
    json_load,
    new_id,
    relative_posix,
    resolve_relative,
    safe_filename,
    sha256_file,
    stable_hash,
    utc_now,
)


TASK_STATES = {"queued", "running", "paused", "failed", "completed", "stale", "cancelled"}
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "paused", "cancelled"},
    "running": {"completed", "failed", "paused", "cancelled", "stale"},
    "paused": {"queued", "cancelled"},
    "failed": {"queued", "cancelled"},
    "stale": {"queued", "failed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


LINE_HASH_FIELDS = (
    "text", "speaker", "listener", "scene_label", "intent", "subtext", "emotion",
    "emotion_intensity", "pace", "pitch", "volume", "breath", "pause",
    "pronunciation", "duration_budget_ms", "voice_id", "engine_id", "locale",
)


LINE_MUTABLE_FIELDS = {
    "scene_id", "external_line_id", "ordinal", "character_id", "voice_id", "source_text",
    "text", "speaker", "listener", "scene_label", "intent", "subtext", "emotion",
    "emotion_intensity", "pace", "pitch", "volume", "breath", "pause", "pronunciation",
    "duration_budget_ms", "engine_id", "seed", "context", "variation", "locale",
    "asset_name", "start_ms", "end_ms", "duration_limit_ms",
}


def _iso_after(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _decode_project(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    value["settings"] = json_load(value.pop("settings_json"), {})
    return value


def _decode_scene(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    value["context"] = json_load(value.pop("context_json"), {})
    return value


def _decode_scene_artwork(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    value["selected"] = bool(value["selected"])
    value["image_url"] = (
        f"/api/v1/projects/{value['project_id']}/scenes/{value['scene_id']}"
        f"/artworks/{value['id']}/content"
    )
    return value


def _decode_character(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    value["profile"] = json_load(value.pop("profile_json"), {})
    return value


def _decode_voice(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    value["voice_profile"] = json_load(value.pop("voice_profile_json"), {})
    value["authorization"] = json_load(value.pop("authorization_json"), {})
    return value


def _decode_line(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    value["pronunciation"] = json_load(value.pop("pronunciation_json"), {})
    value["source_payload"] = json_load(value.pop("source_payload_json"), {})
    value["selection_locked"] = bool(value["selection_locked"])
    return value


def _decode_take(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    value["parameters"] = json_load(value.pop("parameters_json"), {})
    value["qc"] = json_load(value.pop("qc_json"), {})
    value["is_stale"] = bool(value["is_stale"])
    return value


def _decode_task(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    for source, target, default in (
        ("payload_json", "payload", {}),
        ("result_json", "result", {}),
        ("error_json", "error", {}),
        ("depends_on_json", "depends_on", []),
    ):
        value[target] = json_load(value.pop(source), default)
    value["cancel_requested"] = bool(value["cancel_requested"])
    value["pause_requested"] = bool(value["pause_requested"])
    return value


class Repository:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.db = database
        self.settings = settings

    def _require_project(self, connection: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise DomainError("project_not_found", "项目不存在", status_code=404, details={"id": project_id})
        return row

    def create_project(
        self,
        name: str,
        project_type: str,
        *,
        description: str = "",
        default_locale: str = "ja-JP",
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if project_type not in {"video", "game", "character", "japanese"}:
            raise DomainError("invalid_project_type", f"不支持项目类型：{project_type}")
        project_id = new_id()
        now = utc_now()
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO projects(id,name,project_type,description,default_locale,settings_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (project_id, name.strip(), project_type, description, default_locale, canonical_json(settings or {}), now, now),
            )
        project_dir = self.settings.data_root / "projects" / project_id
        for child in ("imports", "takes", "exports", "assets"):
            (project_dir / child).mkdir(parents=True, exist_ok=True)
        return self.get_project(project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [_decode_project(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = self._require_project(connection, project_id)
        return _decode_project(row)

    def update_project(
        self, project_id: str, changes: dict[str, Any], expected_revision: int | None = None
    ) -> dict[str, Any]:
        allowed = {"name", "description", "default_locale", "settings"}
        unknown = set(changes) - allowed
        if unknown:
            raise DomainError("invalid_fields", "包含不可修改的项目字段", details={"fields": sorted(unknown)})
        with self.db.transaction(immediate=True) as connection:
            current = self._require_project(connection, project_id)
            if expected_revision is not None and current["revision"] != expected_revision:
                raise DomainError(
                    "revision_conflict", "项目已被其他操作修改", status_code=409,
                    details={"expected": expected_revision, "actual": current["revision"]},
                )
            assignments: list[str] = []
            values: list[Any] = []
            for key, value in changes.items():
                column = "settings_json" if key == "settings" else key
                assignments.append(f"{column}=?")
                values.append(canonical_json(value) if key == "settings" else value)
            if assignments:
                assignments.extend(["revision=revision+1", "updated_at=?"])
                values.extend([utc_now(), project_id])
                connection.execute(f"UPDATE projects SET {','.join(assignments)} WHERE id=?", values)
        return self.get_project(project_id)

    def create_scene(
        self, project_id: str, name: str, *, external_id: str | None = None,
        ordinal: int = 0, start_ms: int | None = None, end_ms: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scene_id, now = new_id(), utc_now()
        with self.db.transaction(immediate=True) as connection:
            self._require_project(connection, project_id)
            connection.execute(
                """INSERT INTO scenes(id,project_id,external_id,name,ordinal,start_ms,end_ms,context_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (scene_id, project_id, external_id, name, ordinal, start_ms, end_ms, canonical_json(context or {}), now, now),
            )
            row = connection.execute("SELECT * FROM scenes WHERE id=?", (scene_id,)).fetchone()
        return _decode_scene(row)

    def list_scenes(self, project_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            self._require_project(connection, project_id)
            rows = connection.execute(
                "SELECT * FROM scenes WHERE project_id=? ORDER BY ordinal,id", (project_id,)
            ).fetchall()
        return [_decode_scene(row) for row in rows]

    def _require_scene(
        self, connection: sqlite3.Connection, project_id: str, scene_id: str
    ) -> sqlite3.Row:
        self._require_project(connection, project_id)
        row = connection.execute(
            "SELECT * FROM scenes WHERE id=? AND project_id=?", (scene_id, project_id)
        ).fetchone()
        if row is None:
            raise DomainError("scene_not_found", "场景不存在或不属于该项目", status_code=404)
        return row

    def create_scene_artwork(
        self,
        project_id: str,
        scene_id: str,
        content: bytes,
        *,
        filename: str,
        mime_type: str,
        source_kind: str,
        prompt: str = "",
        source: str = "",
        license: str = "",
        select: bool = False,
    ) -> dict[str, Any]:
        if source_kind not in {"user_upload", "local_generated"}:
            raise DomainError("invalid_scene_artwork_source_kind", "未知的场景插画来源类型")
        if len(filename) > 240 or len(prompt) > 20_000 or len(source) > 500 or len(license) > 500:
            raise DomainError("invalid_scene_artwork_metadata", "场景插画元数据超过长度上限")
        source = validate_local_source(source)
        image = inspect_image(content, mime_type, self.settings.max_scene_artwork_bytes)
        artwork_id = new_id()
        extension = extension_for_mime(image.mime_type)
        original_filename = safe_filename(filename, fallback=f"scene-artwork{extension}")
        relative = f"projects/{project_id}/scene-artworks/{artwork_id}{extension}"
        try:
            destination = resolve_relative(relative, self.settings.data_root)
        except ValueError as exc:
            raise DomainError("invalid_scene_artwork_path", "场景插画存储路径无效") from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        committed = False
        try:
            with self.db.transaction(immediate=True) as connection:
                self._require_scene(connection, project_id, scene_id)
                current_selection = connection.execute(
                    "SELECT id FROM scene_artworks WHERE scene_id=? AND selected=1", (scene_id,)
                ).fetchone()
                should_select = select or current_selection is None
                if should_select:
                    connection.execute("UPDATE scene_artworks SET selected=0 WHERE scene_id=?", (scene_id,))
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{artwork_id}-", suffix=".tmp", dir=destination.parent
                )
                temporary_path = Path(temporary_name)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, destination)
                temporary_path = None
                connection.execute(
                    """
                    INSERT INTO scene_artworks(
                        id,project_id,scene_id,source_kind,original_filename,relative_path,
                        sha256,byte_size,width,height,mime_type,prompt,source,license,selected,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        artwork_id,
                        project_id,
                        scene_id,
                        source_kind,
                        original_filename,
                        relative_posix(destination, self.settings.data_root),
                        sha256_file(destination),
                        len(content),
                        image.width,
                        image.height,
                        image.mime_type,
                        prompt.strip(),
                        source,
                        license.strip(),
                        int(should_select),
                        utc_now(),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM scene_artworks WHERE id=?", (artwork_id,)
                ).fetchone()
            committed = True
            return _decode_scene_artwork(row)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            if not committed:
                destination.unlink(missing_ok=True)

    def list_scene_artworks(self, project_id: str, scene_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            self._require_scene(connection, project_id, scene_id)
            rows = connection.execute(
                """
                SELECT * FROM scene_artworks
                WHERE project_id=? AND scene_id=?
                ORDER BY selected DESC, created_at, id
                """,
                (project_id, scene_id),
            ).fetchall()
        return [_decode_scene_artwork(row) for row in rows]

    def select_scene_artwork(
        self, project_id: str, scene_id: str, artwork_id: str
    ) -> dict[str, Any]:
        with self.db.transaction(immediate=True) as connection:
            self._require_scene(connection, project_id, scene_id)
            row = connection.execute(
                """
                SELECT * FROM scene_artworks
                WHERE id=? AND project_id=? AND scene_id=?
                """,
                (artwork_id, project_id, scene_id),
            ).fetchone()
            if row is None:
                raise DomainError("scene_artwork_not_found", "场景插画不存在", status_code=404)
            connection.execute("UPDATE scene_artworks SET selected=0 WHERE scene_id=?", (scene_id,))
            connection.execute("UPDATE scene_artworks SET selected=1 WHERE id=?", (artwork_id,))
            row = connection.execute("SELECT * FROM scene_artworks WHERE id=?", (artwork_id,)).fetchone()
        return _decode_scene_artwork(row)

    def scene_artwork_content_path(
        self, project_id: str, scene_id: str, artwork_id: str
    ) -> tuple[dict[str, Any], Path]:
        with self.db.connection() as connection:
            self._require_scene(connection, project_id, scene_id)
            row = connection.execute(
                """
                SELECT * FROM scene_artworks
                WHERE id=? AND project_id=? AND scene_id=?
                """,
                (artwork_id, project_id, scene_id),
            ).fetchone()
        if row is None:
            raise DomainError("scene_artwork_not_found", "场景插画不存在", status_code=404)
        artwork = _decode_scene_artwork(row)
        try:
            path = resolve_relative(artwork["relative_path"], self.settings.data_root)
        except ValueError as exc:
            raise DomainError(
                "scene_artwork_integrity_mismatch", "场景插画完整性校验失败", status_code=409
            ) from exc
        if not path.is_file() or path.stat().st_size != artwork["byte_size"]:
            raise DomainError(
                "scene_artwork_integrity_mismatch", "场景插画完整性校验失败", status_code=409
            )
        content = path.read_bytes()
        try:
            image = inspect_image(content, artwork["mime_type"], self.settings.max_scene_artwork_bytes)
        except DomainError as exc:
            raise DomainError(
                "scene_artwork_integrity_mismatch", "场景插画完整性校验失败", status_code=409
            ) from exc
        if (
            sha256_file(path) != artwork["sha256"]
            or image.width != artwork["width"]
            or image.height != artwork["height"]
        ):
            raise DomainError(
                "scene_artwork_integrity_mismatch", "场景插画完整性校验失败", status_code=409
            )
        return artwork, path

    def create_character(
        self, project_id: str, name: str, *, external_id: str | None = None,
        default_voice_id: str | None = None, profile: dict[str, Any] | None = None,
        authorization_status: str = "unverified",
    ) -> dict[str, Any]:
        character_id, now = new_id(), utc_now()
        with self.db.transaction(immediate=True) as connection:
            self._require_project(connection, project_id)
            connection.execute(
                """INSERT INTO characters(id,project_id,external_id,name,default_voice_id,profile_json,
                authorization_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (character_id, project_id, external_id, name, default_voice_id, canonical_json(profile or {}), authorization_status, now, now),
            )
            row = connection.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
        return _decode_character(row)

    def list_characters(self, project_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            self._require_project(connection, project_id)
            rows = connection.execute("SELECT * FROM characters WHERE project_id=? ORDER BY name", (project_id,)).fetchall()
        return [_decode_character(row) for row in rows]

    def update_character(
        self, character_id: str, changes: dict[str, Any], expected_revision: int | None = None
    ) -> dict[str, Any]:
        allowed = {"name", "default_voice_id", "profile", "authorization_status"}
        unknown = set(changes) - allowed
        if unknown:
            raise DomainError("invalid_fields", "包含不可修改的角色字段", details={"fields": sorted(unknown)})
        with self.db.transaction(immediate=True) as connection:
            current = connection.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
            if current is None:
                raise DomainError("character_not_found", "角色不存在", status_code=404)
            if expected_revision is not None and current["revision"] != expected_revision:
                raise DomainError("revision_conflict", "角色已被其他操作修改", status_code=409)
            assignments: list[str] = []
            values: list[Any] = []
            for key, value in changes.items():
                column = "profile_json" if key == "profile" else key
                assignments.append(f"{column}=?")
                values.append(canonical_json(value) if key == "profile" else value)
            assignments.extend(["revision=revision+1", "updated_at=?"])
            values.extend([utc_now(), character_id])
            connection.execute(f"UPDATE characters SET {','.join(assignments)} WHERE id=?", values)
            row = connection.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
        return _decode_character(row)

    def create_voice(
        self, name: str, *, project_id: str | None = None, locale: str = "ja-JP",
        engine_id: str = "mock", voice_profile: dict[str, Any] | None = None,
        authorization_status: str = "unverified", authorization: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        voice_id, now = new_id(), utc_now()
        with self.db.transaction(immediate=True) as connection:
            if project_id:
                self._require_project(connection, project_id)
            connection.execute(
                """INSERT INTO voices(id,project_id,name,locale,engine_id,voice_profile_json,
                authorization_status,authorization_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (voice_id, project_id, name, locale, engine_id, canonical_json(voice_profile or {}),
                 authorization_status, canonical_json(authorization or {}), now, now),
            )
            row = connection.execute("SELECT * FROM voices WHERE id=?", (voice_id,)).fetchone()
        return _decode_voice(row)

    def list_voices(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            if project_id:
                rows = connection.execute(
                    "SELECT * FROM voices WHERE project_id IS NULL OR project_id=? ORDER BY name", (project_id,)
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM voices ORDER BY name").fetchall()
        return [_decode_voice(row) for row in rows]

    def _line_hash(self, values: dict[str, Any]) -> str:
        return stable_hash({key: values.get(key) for key in LINE_HASH_FIELDS})

    def _scene_for_import(
        self, connection: sqlite3.Connection, project_id: str, external_id: str | None,
        label: str, ordinal: int,
    ) -> str | None:
        if not external_id and not label:
            return None
        lookup = external_id or f"label:{label}"
        row = connection.execute(
            "SELECT id FROM scenes WHERE project_id=? AND external_id=?", (project_id, lookup)
        ).fetchone()
        if row:
            return row["id"]
        scene_id, now = new_id(), utc_now()
        connection.execute(
            "INSERT INTO scenes(id,project_id,external_id,name,ordinal,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (scene_id, project_id, lookup, label or lookup, ordinal, now, now),
        )
        return scene_id

    def _character_for_import(
        self, connection: sqlite3.Connection, project_id: str, external_id: str | None, name: str
    ) -> str | None:
        if not external_id and not name:
            return None
        lookup = external_id or name
        row = connection.execute(
            "SELECT id FROM characters WHERE project_id=? AND external_id=?", (project_id, lookup)
        ).fetchone()
        if row:
            return row["id"]
        character_id, now = new_id(), utc_now()
        connection.execute(
            """INSERT INTO characters(id,project_id,external_id,name,profile_json,
            authorization_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)""",
            (character_id, project_id, lookup, name or lookup, "{}", "unverified", now, now),
        )
        return character_id

    def _insert_line(
        self, connection: sqlite3.Connection, project_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        line_id, now = new_id(), utc_now()
        scene_id = record.get("scene_id") or self._scene_for_import(
            connection, project_id, record.get("scene_external_id"), record.get("scene_label", ""), record.get("ordinal", 0)
        )
        character_id = record.get("character_id") or self._character_for_import(
            connection, project_id, record.get("character_external_id"), record.get("speaker", "")
        )
        values = {
            "text": record["text"], "speaker": record.get("speaker", ""),
            "listener": record.get("listener", ""), "scene_label": record.get("scene_label", ""),
            "intent": record.get("intent", ""), "subtext": record.get("subtext", ""),
            "emotion": record.get("emotion", "neutral"), "emotion_intensity": record.get("emotion_intensity", 0.5),
            "pace": record.get("pace", 1.0), "pitch": record.get("pitch", 0.0),
            "volume": record.get("volume", 1.0), "breath": record.get("breath", ""),
            "pause": record.get("pause", ""), "pronunciation": record.get("pronunciation", {}),
            "duration_budget_ms": record.get("duration_budget_ms"), "voice_id": record.get("voice_id"),
            "engine_id": record.get("engine_id", "mock"), "locale": record.get("locale", "ja-JP"),
        }
        content_hash = self._line_hash(values)
        connection.execute(
            """
            INSERT INTO lines(
                id,project_id,scene_id,external_line_id,ordinal,character_id,voice_id,source_text,text,
                speaker,listener,scene_label,intent,subtext,emotion,emotion_intensity,pace,pitch,volume,
                breath,pause,pronunciation_json,duration_budget_ms,engine_id,seed,context,variation,locale,
                asset_name,start_ms,end_ms,duration_limit_ms,source_payload_json,content_hash,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                line_id, project_id, scene_id, record.get("external_line_id"), record.get("ordinal", 0),
                character_id, record.get("voice_id"), record.get("source_text", record["text"]), record["text"],
                record.get("speaker", ""), record.get("listener", ""), record.get("scene_label", ""),
                record.get("intent", ""), record.get("subtext", ""), record.get("emotion", "neutral"),
                record.get("emotion_intensity", 0.5), record.get("pace", 1.0), record.get("pitch", 0.0),
                record.get("volume", 1.0), record.get("breath", ""), record.get("pause", ""),
                canonical_json(record.get("pronunciation", {})), record.get("duration_budget_ms"),
                record.get("engine_id", "mock"), record.get("seed", 42), record.get("context", ""),
                record.get("variation", ""), record.get("locale", "ja-JP"), record.get("asset_name", ""),
                record.get("start_ms"), record.get("end_ms"), record.get("duration_limit_ms"),
                canonical_json(record.get("source_payload", {})), content_hash, now, now,
            ),
        )
        row = connection.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
        decoded = _decode_line(row)
        connection.execute(
            "INSERT INTO line_revisions(line_id,revision,snapshot_json,operation,created_at) VALUES(?,?,?,?,?)",
            (line_id, 1, canonical_json(decoded), "create", now),
        )
        return decoded

    def import_lines(
        self, project_id: str, source_format: str, filename: str, content: str,
        records: list[dict[str, Any]], warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        run_id, now = new_id(), utc_now()
        project_dir = self.settings.data_root / "projects" / project_id / "imports"
        project_dir.mkdir(parents=True, exist_ok=True)
        destination = project_dir / f"{run_id}_{safe_filename(filename, f'import.{source_format}')}"
        partial = destination.with_suffix(destination.suffix + ".part")
        partial.write_text(content, encoding="utf-8", newline="")
        os.replace(partial, destination)
        inserted: list[dict[str, Any]] = []
        try:
            with self.db.transaction(immediate=True) as connection:
                self._require_project(connection, project_id)
                for record in records:
                    inserted.append(self._insert_line(connection, project_id, record))
                connection.execute(
                    """INSERT INTO import_runs(id,project_id,source_format,filename,source_hash,row_count,warnings_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (run_id, project_id, source_format, filename, stable_hash(content), len(inserted), canonical_json(warnings or []), now),
                )
                connection.execute("UPDATE projects SET revision=revision+1,updated_at=? WHERE id=?", (now, project_id))
        except sqlite3.IntegrityError as exc:
            destination.unlink(missing_ok=True)
            raise DomainError(
                "duplicate_external_id",
                "导入内容包含重复 line_id/scene_id/character_id；未写入任何台词",
                status_code=409,
            ) from exc
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return {"id": run_id, "project_id": project_id, "format": source_format, "filename": filename,
                "row_count": len(inserted), "warnings": warnings or [], "lines": inserted,
                "source_path": relative_posix(destination, self.settings.data_root), "created_at": now}

    def create_line(self, project_id: str, record: dict[str, Any]) -> dict[str, Any]:
        if not str(record.get("text", "")).strip():
            raise DomainError("missing_line_text", "台词文本不能为空")
        with self.db.transaction(immediate=True) as connection:
            self._require_project(connection, project_id)
            result = self._insert_line(connection, project_id, record)
            connection.execute("UPDATE projects SET revision=revision+1,updated_at=? WHERE id=?", (utc_now(), project_id))
        return result

    def list_lines(self, project_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            self._require_project(connection, project_id)
            rows = connection.execute(
                "SELECT * FROM lines WHERE project_id=? ORDER BY ordinal,id", (project_id,)
            ).fetchall()
        return [_decode_line(row) for row in rows]

    def get_line(self, line_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
        if row is None:
            raise DomainError("line_not_found", "台词不存在", status_code=404, details={"id": line_id})
        return _decode_line(row)

    def update_line(
        self, line_id: str, changes: dict[str, Any], expected_revision: int | None = None,
        *, operation: str = "update",
    ) -> dict[str, Any]:
        unknown = set(changes) - LINE_MUTABLE_FIELDS
        if unknown:
            raise DomainError("invalid_fields", "包含不可修改的台词字段", details={"fields": sorted(unknown)})
        with self.db.transaction(immediate=True) as connection:
            current_row = connection.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
            if current_row is None:
                raise DomainError("line_not_found", "台词不存在", status_code=404)
            current = _decode_line(current_row)
            if expected_revision is not None and current["revision"] != expected_revision:
                raise DomainError(
                    "revision_conflict", "台词已被其他操作修改", status_code=409,
                    details={"expected": expected_revision, "actual": current["revision"]},
                )
            merged = {**current, **changes}
            new_hash = self._line_hash(merged)
            assignments: list[str] = []
            values: list[Any] = []
            for key, value in changes.items():
                column = "pronunciation_json" if key == "pronunciation" else key
                assignments.append(f"{column}=?")
                values.append(canonical_json(value) if key == "pronunciation" else value)
            revision = current["revision"] + 1
            assignments.extend(["content_hash=?", "revision=?", "updated_at=?"])
            values.extend([new_hash, revision, utc_now(), line_id])
            connection.execute(f"UPDATE lines SET {','.join(assignments)} WHERE id=?", values)
            if new_hash != current["content_hash"]:
                connection.execute("UPDATE takes SET is_stale=1,status='stale' WHERE line_id=?", (line_id,))
            row = connection.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
            result = _decode_line(row)
            connection.execute(
                "INSERT INTO line_revisions(line_id,revision,snapshot_json,operation,created_at) VALUES(?,?,?,?,?)",
                (line_id, revision, canonical_json(result), operation, utc_now()),
            )
            connection.execute(
                "UPDATE projects SET revision=revision+1,updated_at=? WHERE id=?", (utc_now(), current["project_id"])
            )
        return result

    def line_history(self, line_id: str) -> list[dict[str, Any]]:
        self.get_line(line_id)
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT revision,snapshot_json,operation,created_at FROM line_revisions WHERE line_id=? ORDER BY revision DESC",
                (line_id,),
            ).fetchall()
        return [{"revision": row["revision"], "snapshot": json_load(row["snapshot_json"], {}),
                 "operation": row["operation"], "created_at": row["created_at"]} for row in rows]

    def restore_line(self, line_id: str, revision: int, expected_revision: int | None = None) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM line_revisions WHERE line_id=? AND revision=?", (line_id, revision)
            ).fetchone()
        if row is None:
            raise DomainError("revision_not_found", "指定台词版本不存在", status_code=404)
        snapshot = json_load(row["snapshot_json"], {})
        changes = {key: snapshot.get(key) for key in LINE_MUTABLE_FIELDS if key in snapshot}
        return self.update_line(line_id, changes, expected_revision, operation=f"restore:{revision}")

    def register_asset(
        self, connection: sqlite3.Connection, project_id: str, kind: str, path: Path,
        *, mime_type: str | None = None, sample_rate_hz: int | None = None,
        bit_depth: int | None = None, channels: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        relative = relative_posix(path, self.settings.data_root)
        existing = connection.execute(
            "SELECT * FROM assets WHERE project_id=? AND relative_path=?", (project_id, relative)
        ).fetchone()
        if existing:
            return dict(existing)
        asset_id, now = new_id(), utc_now()
        connection.execute(
            """INSERT INTO assets(id,project_id,kind,relative_path,sha256,byte_size,mime_type,
            sample_rate_hz,bit_depth,channels,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (asset_id, project_id, kind, relative, sha256_file(path), path.stat().st_size, mime_type,
             sample_rate_hz, bit_depth, channels, canonical_json(metadata or {}), now),
        )
        return dict(connection.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone())

    def register_take(
        self, *, line_id: str, task_id: str, variant_no: int, engine_id: str,
        engine_version: str, seed: int, parameters: dict[str, Any], input_hash: str,
        path: Path, duration_ms: int, qc: dict[str, Any],
    ) -> dict[str, Any]:
        with self.db.transaction(immediate=True) as connection:
            line = connection.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
            if line is None:
                raise DomainError("line_not_found", "台词不存在", status_code=404)
            existing = connection.execute(
                "SELECT * FROM takes WHERE line_id=? AND input_hash=? AND variant_no=?",
                (line_id, input_hash, variant_no),
            ).fetchone()
            if existing:
                return _decode_take(existing)
            asset = self.register_asset(
                connection, line["project_id"], "take_audio", path, mime_type="audio/wav",
                sample_rate_hz=48000, bit_depth=24, channels=1, metadata={"mock": engine_id == "mock"},
            )
            take_id = new_id()
            connection.execute(
                """INSERT INTO takes(id,line_id,task_id,variant_no,engine_id,engine_version,seed,
                parameters_json,input_hash,asset_id,duration_ms,sample_rate_hz,bit_depth,channels,qc_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (take_id, line_id, task_id, variant_no, engine_id, engine_version, seed,
                 canonical_json(parameters), input_hash, asset["id"], duration_ms, 48000, 24, 1,
                 canonical_json(qc), utc_now()),
            )
            row = connection.execute(
                """SELECT t.*,a.relative_path AS asset_path FROM takes t JOIN assets a ON a.id=t.asset_id
                WHERE t.id=?""", (take_id,)
            ).fetchone()
        return _decode_take(row)

    def list_takes(self, line_id: str) -> list[dict[str, Any]]:
        self.get_line(line_id)
        with self.db.connection() as connection:
            rows = connection.execute(
                """SELECT t.*,a.relative_path AS asset_path FROM takes t JOIN assets a ON a.id=t.asset_id
                WHERE t.line_id=? ORDER BY t.created_at,t.variant_no""", (line_id,)
            ).fetchall()
        return [_decode_take(row) for row in rows]

    def get_take(self, take_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute(
                """SELECT t.*,a.relative_path AS asset_path,l.project_id FROM takes t
                JOIN assets a ON a.id=t.asset_id JOIN lines l ON l.id=t.line_id WHERE t.id=?""", (take_id,)
            ).fetchone()
        if row is None:
            raise DomainError("take_not_found", "候选 take 不存在", status_code=404)
        return _decode_take(row)

    def take_audio_path(self, take_id: str) -> Path:
        take = self.get_take(take_id)
        path = resolve_relative(take["asset_path"], self.settings.data_root)
        if not path.is_file():
            raise DomainError("asset_missing", "take 音频文件不存在", status_code=404)
        return path

    def select_take(self, line_id: str, take_id: str, expected_revision: int | None = None) -> dict[str, Any]:
        with self.db.transaction(immediate=True) as connection:
            line = connection.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
            if line is None:
                raise DomainError("line_not_found", "台词不存在", status_code=404)
            if expected_revision is not None and line["revision"] != expected_revision:
                raise DomainError("revision_conflict", "台词已被其他操作修改", status_code=409)
            take = connection.execute("SELECT * FROM takes WHERE id=? AND line_id=?", (take_id, line_id)).fetchone()
            if take is None:
                raise DomainError("take_line_mismatch", "take 不属于该台词", status_code=409)
            now, revision = utc_now(), line["revision"] + 1
            connection.execute(
                "UPDATE lines SET selected_take_id=?,selection_locked=1,revision=?,updated_at=? WHERE id=?",
                (take_id, revision, now, line_id),
            )
            row = connection.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
            result = _decode_line(row)
            connection.execute(
                "INSERT INTO line_revisions(line_id,revision,snapshot_json,operation,created_at) VALUES(?,?,?,?,?)",
                (line_id, revision, canonical_json(result), "select_take", now),
            )
        result["selected_take"] = self.get_take(take_id)
        return result

    def unlock_selection(self, line_id: str) -> dict[str, Any]:
        line = self.get_line(line_id)
        return self.update_line_selection_lock(line_id, False, line["revision"])

    def update_line_selection_lock(self, line_id: str, locked: bool, expected_revision: int) -> dict[str, Any]:
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
            if row is None:
                raise DomainError("line_not_found", "台词不存在", status_code=404)
            if row["revision"] != expected_revision:
                raise DomainError("revision_conflict", "台词已被其他操作修改", status_code=409)
            revision, now = row["revision"] + 1, utc_now()
            connection.execute(
                "UPDATE lines SET selection_locked=?,revision=?,updated_at=? WHERE id=?",
                (int(locked), revision, now, line_id),
            )
            updated = _decode_line(connection.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone())
            connection.execute(
                "INSERT INTO line_revisions(line_id,revision,snapshot_json,operation,created_at) VALUES(?,?,?,?,?)",
                (line_id, revision, canonical_json(updated), "lock_selection" if locked else "unlock_selection", now),
            )
        return updated

    def create_task(
        self, task_type: str, payload: dict[str, Any], *, project_id: str | None = None,
        resource_class: str = "cpu", priority: int = 0, max_attempts: int = 3,
        depends_on: list[str] | None = None,
    ) -> dict[str, Any]:
        if resource_class not in {"cpu", "gpu_heavy"}:
            raise DomainError("invalid_resource_class", "resource_class 必须是 cpu 或 gpu_heavy")
        task_id, now = new_id(), utc_now()
        with self.db.transaction(immediate=True) as connection:
            if project_id:
                self._require_project(connection, project_id)
            connection.execute(
                """INSERT INTO tasks(id,project_id,task_type,status,resource_class,priority,payload_json,
                input_hash,max_attempts,depends_on_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (task_id, project_id, task_type, "queued", resource_class, priority, canonical_json(payload),
                 stable_hash({"type": task_type, "payload": payload}), max_attempts,
                 canonical_json(depends_on or []), now, now),
            )
            self._event(connection, task_id, project_id, "task.created", None, "queued", 0.0, "queued", "任务已入队")
        return self.get_task(task_id)

    def _event(
        self, connection: sqlite3.Connection, task_id: str, project_id: str | None,
        event_type: str, from_status: str | None, to_status: str | None,
        progress: float | None, phase: str | None, message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """INSERT INTO task_events(task_id,project_id,event_type,from_status,to_status,progress,
            phase,message,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (task_id, project_id, event_type, from_status, to_status, progress, phase, message,
             canonical_json(payload or {}), utc_now()),
        )

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise DomainError("task_not_found", "任务不存在", status_code=404, details={"id": task_id})
        return _decode_task(row)

    def list_tasks(self, *, project_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        clauses, values = [], []
        if project_id:
            clauses.append("project_id=?")
            values.append(project_id)
        if status:
            if status not in TASK_STATES:
                raise DomainError("invalid_task_status", f"无效任务状态：{status}")
            clauses.append("status=?")
            values.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.db.connection() as connection:
            rows = connection.execute(f"SELECT * FROM tasks{where} ORDER BY created_at DESC", values).fetchall()
        return [_decode_task(row) for row in rows]

    def list_task_events(
        self, *, task_id: str | None = None, project_id: str | None = None,
        after_event_id: int = 0, limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses, values = ["event_id>?"], [after_event_id]
        if task_id:
            clauses.append("task_id=?")
            values.append(task_id)
        if project_id:
            clauses.append("project_id=?")
            values.append(project_id)
        values.append(min(max(limit, 1), 1000))
        with self.db.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM task_events WHERE {' AND '.join(clauses)} ORDER BY event_id LIMIT ?", values
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json_load(item.pop("payload_json"), {})
            result.append(item)
        return result

    def _transition(
        self, connection: sqlite3.Connection, row: sqlite3.Row, target: str, *,
        message: str, phase: str | None = None, progress: float | None = None,
        result: dict[str, Any] | None = None, error: dict[str, Any] | None = None,
    ) -> None:
        source = row["status"]
        if target not in ALLOWED_TRANSITIONS[source]:
            raise DomainError(
                "invalid_state_transition", f"任务处于 {source}，不能转为 {target}", status_code=409,
                details={"from": source, "to": target},
            )
        updates = ["status=?", "updated_at=?"]
        values: list[Any] = [target, utc_now()]
        if phase is not None:
            updates.append("phase=?")
            values.append(phase)
        if progress is not None:
            updates.append("progress=?")
            values.append(progress)
        if result is not None:
            updates.append("result_json=?")
            values.append(canonical_json(result))
        if error is not None:
            updates.append("error_json=?")
            values.append(canonical_json(error))
        if target == "running":
            updates.append("started_at=COALESCE(started_at,?)")
            values.append(utc_now())
        if target in {"completed", "failed", "cancelled"}:
            updates.append("finished_at=?")
            values.append(utc_now())
        values.append(row["id"])
        connection.execute(f"UPDATE tasks SET {','.join(updates)} WHERE id=?", values)
        self._event(connection, row["id"], row["project_id"], "task.transition", source, target,
                    progress if progress is not None else row["progress"], phase or row["phase"], message)

    def claim_next_task(self, worker_id: str, lease_seconds: int = 30) -> dict[str, Any] | None:
        now, expires = utc_now(), _iso_after(lease_seconds)
        with self.db.transaction(immediate=True) as connection:
            connection.execute("DELETE FROM resource_leases WHERE expires_at<?", (now,))
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status='queued' ORDER BY priority DESC,created_at"
            ).fetchall()
            for row in rows:
                dependencies = json_load(row["depends_on_json"], [])
                if dependencies:
                    placeholders = ",".join("?" for _ in dependencies)
                    states = connection.execute(
                        f"SELECT status FROM tasks WHERE id IN ({placeholders})", dependencies
                    ).fetchall()
                    if len(states) != len(dependencies) or any(item["status"] != "completed" for item in states):
                        continue
                lease_token = new_id()
                if row["resource_class"] == "gpu_heavy":
                    try:
                        connection.execute(
                            "INSERT INTO resource_leases(resource_key,task_id,owner_id,lease_token,acquired_at,expires_at) VALUES(?,?,?,?,?,?)",
                            ("gpu:0", row["id"], worker_id, lease_token, now, expires),
                        )
                    except sqlite3.IntegrityError:
                        continue
                updated = connection.execute(
                    """UPDATE tasks SET status='running',worker_id=?,lease_token=?,lease_expires_at=?,
                    attempt=attempt+1,started_at=COALESCE(started_at,?),updated_at=? WHERE id=? AND status='queued'""",
                    (worker_id, lease_token, expires, now, now, row["id"]),
                )
                if updated.rowcount != 1:
                    connection.execute("DELETE FROM resource_leases WHERE task_id=? AND lease_token=?", (row["id"], lease_token))
                    continue
                self._event(connection, row["id"], row["project_id"], "task.transition", "queued", "running",
                            row["progress"], "starting", "任务开始执行")
                claimed = connection.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone()
                return _decode_task(claimed)
        return None

    def update_task_progress(self, task_id: str, progress: float, phase: str, message: str) -> dict[str, Any]:
        progress = min(1.0, max(0.0, progress))
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise DomainError("task_not_found", "任务不存在", status_code=404)
            if row["status"] != "running":
                return _decode_task(row)
            connection.execute(
                "UPDATE tasks SET progress=?,phase=?,lease_expires_at=?,updated_at=? WHERE id=?",
                (progress, phase, _iso_after(30), utc_now(), task_id),
            )
            if row["resource_class"] == "gpu_heavy":
                connection.execute(
                    "UPDATE resource_leases SET expires_at=? WHERE task_id=? AND lease_token=?",
                    (_iso_after(30), task_id, row["lease_token"]),
                )
            self._event(connection, task_id, row["project_id"], "task.progress", "running", "running",
                        progress, phase, message)
            updated = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _decode_task(updated)

    def task_control(self, task_id: str) -> str | None:
        task = self.get_task(task_id)
        if task["cancel_requested"]:
            return "cancel"
        if task["pause_requested"]:
            return "pause"
        return None

    def finish_task(self, task_id: str, result: dict[str, Any]) -> dict[str, Any]:
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise DomainError("task_not_found", "任务不存在", status_code=404)
            if row["status"] != "running":
                return _decode_task(row)
            self._transition(connection, row, "completed", message="任务完成", phase="completed", progress=1.0, result=result)
            connection.execute("DELETE FROM resource_leases WHERE task_id=? AND lease_token=?", (task_id, row["lease_token"]))
            updated = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _decode_task(updated)

    def fail_task(self, task_id: str, error: dict[str, Any]) -> dict[str, Any]:
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise DomainError("task_not_found", "任务不存在", status_code=404)
            if row["status"] != "running":
                return _decode_task(row)
            self._transition(connection, row, "failed", message=error.get("message", "任务失败"),
                             phase="failed", error=error)
            connection.execute("DELETE FROM resource_leases WHERE task_id=? AND lease_token=?", (task_id, row["lease_token"]))
            updated = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _decode_task(updated)

    def request_cancel(self, task_id: str) -> dict[str, Any]:
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise DomainError("task_not_found", "任务不存在", status_code=404)
            if row["status"] in {"completed", "cancelled"}:
                raise DomainError("invalid_state_transition", f"任务处于 {row['status']}，不能取消", status_code=409)
            if row["status"] == "running":
                connection.execute("UPDATE tasks SET cancel_requested=1,updated_at=? WHERE id=?", (utc_now(), task_id))
                self._event(connection, task_id, row["project_id"], "task.control_requested", "running", "running",
                            row["progress"], row["phase"], "已请求取消")
            else:
                self._transition(connection, row, "cancelled", message="任务已取消", phase="cancelled")
            updated = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _decode_task(updated)

    def request_pause(self, task_id: str) -> dict[str, Any]:
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise DomainError("task_not_found", "任务不存在", status_code=404)
            if row["status"] == "running":
                connection.execute("UPDATE tasks SET pause_requested=1,updated_at=? WHERE id=?", (utc_now(), task_id))
                self._event(connection, task_id, row["project_id"], "task.control_requested", "running", "running",
                            row["progress"], row["phase"], "已请求暂停")
            else:
                self._transition(connection, row, "paused", message="任务已暂停", phase="paused")
            updated = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _decode_task(updated)

    def apply_running_control(self, task_id: str, control: str) -> dict[str, Any]:
        target = "cancelled" if control == "cancel" else "paused"
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None or row["status"] != "running":
                return self.get_task(task_id)
            self._transition(connection, row, target, message="任务已取消" if control == "cancel" else "任务已暂停", phase=target)
            connection.execute(
                "UPDATE tasks SET cancel_requested=0,pause_requested=0 WHERE id=?", (task_id,)
            )
            connection.execute("DELETE FROM resource_leases WHERE task_id=? AND lease_token=?", (task_id, row["lease_token"]))
            updated = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _decode_task(updated)

    def resume_task(self, task_id: str) -> dict[str, Any]:
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise DomainError("task_not_found", "任务不存在", status_code=404)
            self._transition(connection, row, "queued", message="任务已恢复并重新入队", phase="queued")
            connection.execute("UPDATE tasks SET pause_requested=0,cancel_requested=0 WHERE id=?", (task_id,))
            updated = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _decode_task(updated)

    def retry_task(self, task_id: str) -> dict[str, Any]:
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise DomainError("task_not_found", "任务不存在", status_code=404)
            if row["status"] not in {"failed", "stale"}:
                raise DomainError("invalid_state_transition", "只有 failed/stale 任务可以重试", status_code=409)
            if row["attempt"] >= row["max_attempts"]:
                raise DomainError("retry_limit_reached", "任务已达到最大重试次数", status_code=409)
            self._transition(connection, row, "queued", message="失败任务已重新入队", phase="queued")
            connection.execute(
                "UPDATE tasks SET error_json='{}',cancel_requested=0,pause_requested=0,finished_at=NULL WHERE id=?", (task_id,)
            )
            updated = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _decode_task(updated)

    def recover_expired_tasks(self) -> list[str]:
        recovered: list[str] = []
        now = utc_now()
        with self.db.transaction(immediate=True) as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status='running' AND (lease_expires_at IS NULL OR lease_expires_at<?)", (now,)
            ).fetchall()
            for row in rows:
                self._transition(connection, row, "stale", message="检测到进程中断，任务标记为 stale", phase="recovery")
                stale = connection.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone()
                connection.execute("DELETE FROM resource_leases WHERE task_id=?", (row["id"],))
                if row["cancel_requested"]:
                    self._transition(connection, stale, "cancelled", message="恢复时应用取消请求", phase="cancelled")
                elif row["attempt"] < row["max_attempts"]:
                    self._transition(connection, stale, "queued", message="中断任务已恢复入队", phase="queued")
                    recovered.append(row["id"])
                else:
                    self._transition(connection, stale, "failed", message="中断任务已达到重试上限", phase="failed")
        return recovered

    def gpu_lease(self) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM resource_leases WHERE resource_key='gpu:0'").fetchone()
        return dict(row) if row else None

    def record_export(
        self, *, project_id: str, export_format: str, path: Path, input_hash: str,
        warnings: list[str], task_id: str,
    ) -> dict[str, Any]:
        export_id, now = new_id(), utc_now()
        relative = relative_posix(path, self.settings.data_root)
        with self.db.transaction(immediate=True) as connection:
            self._require_project(connection, project_id)
            connection.execute(
                """INSERT INTO export_runs(id,project_id,export_format,relative_path,input_hash,
                warnings_json,task_id,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                (export_id, project_id, export_format, relative, input_hash,
                 canonical_json(warnings), task_id, now),
            )
        return {"id": export_id, "project_id": project_id, "format": export_format,
                "relative_path": relative, "input_hash": input_hash,
                "warnings": warnings, "task_id": task_id, "created_at": now}
