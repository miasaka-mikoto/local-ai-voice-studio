from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path


SCHEMA_VERSION = 2


SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    project_type TEXT NOT NULL CHECK(project_type IN ('video','game','character','japanese')),
    description TEXT NOT NULL DEFAULT '',
    default_locale TEXT NOT NULL DEFAULT 'ja-JP',
    settings_json TEXT NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    external_id TEXT,
    name TEXT NOT NULL,
    ordinal INTEGER NOT NULL DEFAULT 0,
    start_ms INTEGER,
    end_ms INTEGER,
    context_json TEXT NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, external_id)
);

CREATE TABLE IF NOT EXISTS voices (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    locale TEXT NOT NULL DEFAULT 'ja-JP',
    engine_id TEXT NOT NULL DEFAULT 'mock',
    voice_profile_json TEXT NOT NULL DEFAULT '{}',
    reference_asset_id TEXT,
    authorization_status TEXT NOT NULL DEFAULT 'unverified',
    authorization_json TEXT NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    external_id TEXT,
    name TEXT NOT NULL,
    default_voice_id TEXT REFERENCES voices(id) ON DELETE SET NULL,
    profile_json TEXT NOT NULL DEFAULT '{}',
    authorization_status TEXT NOT NULL DEFAULT 'unverified',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, external_id)
);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    mime_type TEXT,
    sample_rate_hz INTEGER,
    bit_depth INTEGER,
    channels INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(project_id, relative_path)
);

CREATE TABLE IF NOT EXISTS lines (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scene_id TEXT REFERENCES scenes(id) ON DELETE SET NULL,
    external_line_id TEXT,
    ordinal INTEGER NOT NULL DEFAULT 0,
    character_id TEXT REFERENCES characters(id) ON DELETE SET NULL,
    voice_id TEXT REFERENCES voices(id) ON DELETE SET NULL,
    source_text TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    speaker TEXT NOT NULL DEFAULT '',
    listener TEXT NOT NULL DEFAULT '',
    scene_label TEXT NOT NULL DEFAULT '',
    intent TEXT NOT NULL DEFAULT '',
    subtext TEXT NOT NULL DEFAULT '',
    emotion TEXT NOT NULL DEFAULT 'neutral',
    emotion_intensity REAL NOT NULL DEFAULT 0.5,
    pace REAL NOT NULL DEFAULT 1.0,
    pitch REAL NOT NULL DEFAULT 0.0,
    volume REAL NOT NULL DEFAULT 1.0,
    breath TEXT NOT NULL DEFAULT '',
    pause TEXT NOT NULL DEFAULT '',
    pronunciation_json TEXT NOT NULL DEFAULT '{}',
    duration_budget_ms INTEGER,
    engine_id TEXT NOT NULL DEFAULT 'mock',
    seed INTEGER NOT NULL DEFAULT 42,
    context TEXT NOT NULL DEFAULT '',
    variation TEXT NOT NULL DEFAULT '',
    locale TEXT NOT NULL DEFAULT 'ja-JP',
    asset_name TEXT NOT NULL DEFAULT '',
    start_ms INTEGER,
    end_ms INTEGER,
    duration_limit_ms INTEGER,
    source_payload_json TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL,
    selected_take_id TEXT,
    selection_locked INTEGER NOT NULL DEFAULT 0 CHECK(selection_locked IN (0,1)),
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, external_line_id)
);

CREATE TABLE IF NOT EXISTS line_revisions (
    line_id TEXT NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    operation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(line_id, revision)
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','running','paused','failed','completed','stale','cancelled')),
    resource_class TEXT NOT NULL DEFAULT 'cpu' CHECK(resource_class IN ('cpu','gpu_heavy')),
    priority INTEGER NOT NULL DEFAULT 0,
    progress REAL NOT NULL DEFAULT 0.0,
    phase TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error_json TEXT NOT NULL DEFAULT '{}',
    input_hash TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    worker_id TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    pause_requested INTEGER NOT NULL DEFAULT 0 CHECK(pause_requested IN (0,1)),
    depends_on_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS task_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    project_id TEXT,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    progress REAL,
    phase TEXT,
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_leases (
    resource_key TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS takes (
    id TEXT PRIMARY KEY,
    line_id TEXT NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    variant_no INTEGER NOT NULL,
    engine_id TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    model_id TEXT NOT NULL DEFAULT 'mock-tone',
    model_version TEXT NOT NULL DEFAULT '1',
    seed INTEGER NOT NULL,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    reference_audio TEXT,
    input_hash TEXT NOT NULL,
    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
    duration_ms INTEGER NOT NULL,
    sample_rate_hz INTEGER NOT NULL,
    bit_depth INTEGER NOT NULL,
    channels INTEGER NOT NULL,
    qc_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'completed',
    is_stale INTEGER NOT NULL DEFAULT 0 CHECK(is_stale IN (0,1)),
    created_at TEXT NOT NULL,
    UNIQUE(line_id, input_hash, variant_no)
);

CREATE TABLE IF NOT EXISTS import_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_format TEXT NOT NULL,
    filename TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    export_format TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scenes_project_ordinal ON scenes(project_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_characters_project ON characters(project_id);
CREATE INDEX IF NOT EXISTS idx_voices_project ON voices(project_id);
CREATE INDEX IF NOT EXISTS idx_lines_project_ordinal ON lines(project_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_lines_scene_ordinal ON lines(project_id, scene_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_lines_character ON lines(character_id);
CREATE INDEX IF NOT EXISTS idx_takes_line_created ON takes(line_id, created_at);
CREATE INDEX IF NOT EXISTS idx_takes_input_hash ON takes(input_hash);
CREATE INDEX IF NOT EXISTS idx_tasks_claim ON tasks(status, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status);
CREATE INDEX IF NOT EXISTS idx_task_events_task_event ON task_events(task_id, event_id);
CREATE INDEX IF NOT EXISTS idx_task_events_project_event ON task_events(project_id, event_id);
CREATE INDEX IF NOT EXISTS idx_assets_project_kind ON assets(project_id, kind);
"""


SCENE_ARTWORKS_MIGRATION_SQL = r"""
CREATE TABLE IF NOT EXISTS scene_artworks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('user_upload','local_generated')),
    original_filename TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK(byte_size > 0),
    width INTEGER NOT NULL CHECK(width > 0),
    height INTEGER NOT NULL CHECK(height > 0),
    mime_type TEXT NOT NULL CHECK(mime_type IN ('image/png','image/jpeg','image/webp')),
    prompt TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    license TEXT NOT NULL DEFAULT '',
    selected INTEGER NOT NULL DEFAULT 0 CHECK(selected IN (0,1)),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_scene_artworks_scene_created
ON scene_artworks(scene_id, created_at, id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_scene_artworks_one_selected
ON scene_artworks(scene_id) WHERE selected=1;
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            connection.executescript(SCHEMA_SQL)
            from .util import utc_now

            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (1, "initial_backend_mvp", utc_now()),
            )
            connection.executescript(SCENE_ARTWORKS_MIGRATION_SQL)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (2, "scene_artworks", utc_now()),
            )
            connection.commit()
        finally:
            connection.close()

    @contextlib.contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextlib.contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()
