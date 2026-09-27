from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import LOOPBACK_HOSTS, Settings
from .database import Database
from .errors import DomainError
from .importers import decode_bytes, normalize_record, parse_import
from .repository import Repository
from .snapshot import SnapshotBuilder
from .task_runner import TaskRunner
from .util import new_id, safe_filename


PROJECT_KIND_FROM_UI = {
    "video_dubbing": "video", "game_voice": "game", "voice_dataset": "character",
    "japanese_learning": "japanese", "video": "video", "game": "game",
    "character": "character", "japanese": "japanese",
}

LINE_PATCH_MAP = {
    "sceneId": "scene_id", "lineId": "external_line_id", "index": "ordinal",
    "sourceText": "source_text", "speakerId": "character_id", "emotionIntensity": "emotion_intensity",
    "durationBudgetMs": "duration_budget_ms", "voiceProfileId": "voice_id", "engineId": "engine_id",
    "startMs": "start_ms", "endMs": "end_ms", "selectionLocked": "selection_locked",
}


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str | None = None
    project_type: str | None = None
    description: str = Field(default="", max_length=5000)
    locale: str = Field(default="ja-JP", max_length=40)
    default_locale: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    default_locale: str | None = None
    settings: dict[str, Any] | None = None
    expected_revision: int | None = None


class SceneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    external_id: str | None = None
    ordinal: int = 0
    start_ms: int | None = None
    end_ms: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class CharacterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    external_id: str | None = None
    default_voice_id: str | None = None
    profile: dict[str, Any] = Field(default_factory=dict)
    authorization_status: str = "unverified"


class VoiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    project_id: str | None = None
    locale: str = "ja-JP"
    engine_id: str = "mock"
    voice_profile: dict[str, Any] = Field(default_factory=dict)
    authorization_status: str = "unverified"
    authorization: dict[str, Any] = Field(default_factory=dict)


class LineCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    external_line_id: str | None = None
    scene_external_id: str | None = None
    speaker: str = ""
    character_external_id: str | None = None
    listener: str = ""
    emotion: str = "neutral"
    locale: str = "ja-JP"
    ordinal: int = 0
    start_ms: int | None = None
    end_ms: int | None = None
    duration_limit_ms: int | None = None


class LinePatchEnvelope(BaseModel):
    patch: dict[str, Any]
    revision: int | None = None


class DirectLinePatch(BaseModel):
    changes: dict[str, Any]
    expected_revision: int | None = None


class RestoreLineRequest(BaseModel):
    revision: int
    expected_revision: int | None = None


class ImportRequest(BaseModel):
    format: str | None = None
    filename: str | None = None
    encoding: str | None = None
    content: str | None = None
    source_path: str | None = None
    lines: list[dict[str, Any]] | None = None


class GenerationRequest(BaseModel):
    line_ids: list[str] | None = None
    engine_id: str = "mock"
    take_count: int = Field(default=3, ge=1, le=8)
    count: int | None = Field(default=None, ge=1, le=8)
    seed: int = 42
    seeds: list[int] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class SelectTakeRequest(BaseModel):
    expected_revision: int | None = None
    locked: bool = True


class ExportRequest(BaseModel):
    format: str = "project_json"


class PreviewConversationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    coachMode: str = Field(default="flow", pattern="^(flow|strict)$")


async def _bounded_body(request: Request, max_bytes: int) -> bytes:
    declared_length = request.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) > max_bytes:
                raise DomainError(
                    "scene_artwork_too_large",
                    "场景插画超过本地大小上限",
                    status_code=413,
                    details={"max_bytes": max_bytes},
                )
        except ValueError:
            pass
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise DomainError(
                "scene_artwork_too_large",
                "场景插画超过本地大小上限",
                status_code=413,
                details={"max_bytes": max_bytes},
            )
    return bytes(body)


def _snake_patch(patch: dict[str, Any]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for key, value in patch.items():
        target = LINE_PATCH_MAP.get(key, key)
        if target == "selection_locked":
            continue
        if target == "pronunciation" and isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = {"instruction": value}
        converted[target] = value
    return converted


def _import_line_from_ui(value: dict[str, Any], index: int) -> dict[str, Any]:
    mapped = {
        "line_id": value.get("lineId"), "scene_id": value.get("sceneId"),
        "start_ms": value.get("startMs"), "end_ms": value.get("endMs"),
        "speaker": value.get("speaker", ""), "listener": value.get("listener", ""),
        "text": value.get("text", ""), "emotion": value.get("emotion", "neutral"),
        "locale": value.get("locale", "ja-JP"), "duration_limit_ms": value.get("durationLimitMs"),
        "asset_name": value.get("assetName", ""),
    }
    return normalize_record(mapped, index)


async def _worker_loop(runner: TaskRunner, stop: asyncio.Event, poll_seconds: float) -> None:
    while not stop.is_set():
        result = await asyncio.to_thread(runner.run_once)
        if result is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
            except TimeoutError:
                pass


def _mount_bundled_japanese_router(application: FastAPI, configured: Settings) -> None:
    """Mount the required built-in Japanese module.

    This intentionally has no ImportError fallback. The Japanese learning module is
    part of the product, so a missing module or one of its broken imports must stop
    application construction instead of silently removing the complete API surface.
    """
    from .modules.japanese.router import build_japanese_router

    application.include_router(
        build_japanese_router(configured.database_path, configured.data_root / "projects")
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or Settings.load()
    configured.ensure_directories()
    database = Database(configured.database_path)
    database.initialize()
    repository = Repository(database, configured)
    repository.recover_expired_tasks()
    worker_id = f"api-{os.getpid()}-{new_id()[:8]}"
    runner = TaskRunner(repository, worker_id)
    voice_root = configured.backend_root.parent
    snapshots = SnapshotBuilder(repository, voice_root)
    stop_event = asyncio.Event()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task: asyncio.Task[None] | None = None
        if configured.worker_enabled:
            task = asyncio.create_task(_worker_loop(runner, stop_event, configured.worker_poll_seconds))
        yield
        stop_event.set()
        if task is not None:
            await task

    application = FastAPI(
        title="Local AI Voice Studio API",
        version=__version__,
        description="本机项目、台词、多 take、可恢复任务与导出后端。真实模型默认禁用。",
        lifespan=lifespan,
    )
    application.state.settings = configured
    application.state.database = database
    application.state.repository = repository
    application.state.runner = runner
    application.state.snapshots = snapshots

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "tauri://localhost"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "If-Match", "Idempotency-Key"],
    )

    @application.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "details": exc.details,
                     "recoverable": exc.retryable or exc.status_code in {408, 409, 500, 503}},
        )

    @application.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "message": "Local AI Voice Studio 后端就绪（mock-only）",
                "bind": configured.host, "port": configured.port, "worker": configured.worker_enabled}

    @application.get("/api/v1/bootstrap")
    def bootstrap() -> dict[str, Any]:
        return snapshots.build()

    @application.get("/api/v1/projects")
    def list_projects() -> list[dict[str, Any]]:
        return repository.list_projects()

    @application.post("/api/v1/projects", status_code=status.HTTP_201_CREATED)
    def create_project(payload: ProjectCreate) -> dict[str, Any]:
        kind = payload.project_type or payload.kind or "video"
        mapped = PROJECT_KIND_FROM_UI.get(kind)
        if mapped is None:
            raise DomainError("invalid_project_type", f"不支持项目类型：{kind}")
        repository.create_project(
            payload.name, mapped, description=payload.description,
            default_locale=payload.default_locale or payload.locale, settings=payload.settings,
        )
        return snapshots.build()

    @application.get("/api/v1/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return repository.get_project(project_id)

    @application.patch("/api/v1/projects/{project_id}")
    def patch_project(project_id: str, payload: ProjectPatch) -> dict[str, Any]:
        changes = payload.model_dump(exclude={"expected_revision"}, exclude_none=True)
        return repository.update_project(project_id, changes, payload.expected_revision)

    @application.post("/api/v1/projects/{project_id}/scenes", status_code=status.HTTP_201_CREATED)
    def create_scene(project_id: str, payload: SceneCreate) -> dict[str, Any]:
        return repository.create_scene(project_id, **payload.model_dump())

    @application.get("/api/v1/projects/{project_id}/scenes")
    def list_scenes(project_id: str) -> list[dict[str, Any]]:
        return repository.list_scenes(project_id)

    @application.post(
        "/api/v1/projects/{project_id}/scenes/{scene_id}/artworks",
        status_code=status.HTTP_201_CREATED,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "image/png": {"schema": {"type": "string", "format": "binary"}},
                    "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                    "image/webp": {"schema": {"type": "string", "format": "binary"}},
                },
            }
        },
    )
    async def create_scene_artwork(
        project_id: str,
        scene_id: str,
        request: Request,
        filename: str = Query(default="scene-artwork.png", min_length=1, max_length=240),
        source_kind: str = Query(default="user_upload", pattern="^(user_upload|local_generated)$"),
        prompt: str = Query(default="", max_length=20_000),
        source: str = Query(default="", max_length=500),
        license: str = Query(default="", max_length=500),
        select: bool = Query(default=False),
    ) -> dict[str, Any]:
        mime_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        content = await _bounded_body(request, configured.max_scene_artwork_bytes)
        return repository.create_scene_artwork(
            project_id,
            scene_id,
            content,
            filename=filename,
            mime_type=mime_type,
            source_kind=source_kind,
            prompt=prompt,
            source=source,
            license=license,
            select=select,
        )

    @application.get("/api/v1/projects/{project_id}/scenes/{scene_id}/artworks")
    def list_scene_artworks(project_id: str, scene_id: str) -> list[dict[str, Any]]:
        return repository.list_scene_artworks(project_id, scene_id)

    @application.post(
        "/api/v1/projects/{project_id}/scenes/{scene_id}/artworks/{artwork_id}/select"
    )
    def select_scene_artwork(project_id: str, scene_id: str, artwork_id: str) -> dict[str, Any]:
        return repository.select_scene_artwork(project_id, scene_id, artwork_id)

    @application.get(
        "/api/v1/projects/{project_id}/scenes/{scene_id}/artworks/{artwork_id}/content",
        response_class=FileResponse,
    )
    def scene_artwork_content(
        project_id: str, scene_id: str, artwork_id: str
    ) -> FileResponse:
        artwork, path = repository.scene_artwork_content_path(project_id, scene_id, artwork_id)
        return FileResponse(
            path,
            media_type=artwork["mime_type"],
            headers={
                "ETag": f'"{artwork["sha256"]}"',
                "Cache-Control": "private, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @application.post("/api/v1/projects/{project_id}/characters", status_code=status.HTTP_201_CREATED)
    def create_character(project_id: str, payload: CharacterCreate) -> dict[str, Any]:
        return repository.create_character(project_id, **payload.model_dump())

    @application.get("/api/v1/projects/{project_id}/characters")
    def list_characters(project_id: str) -> list[dict[str, Any]]:
        return repository.list_characters(project_id)

    @application.patch("/api/v1/characters/{character_id}")
    def patch_character(character_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = next((item for project in repository.list_projects()
                        for item in repository.list_characters(project["id"]) if item["id"] == character_id), None)
        if current is None:
            raise DomainError("character_not_found", "角色不存在", status_code=404)
        profile = dict(current["profile"])
        frontend_profile = {
            "color": "color", "identity": "identity", "ageImpression": "age_impression",
            "timbre": "timbre", "speechHabits": "speech_habits", "politeness": "politeness",
        }
        for source, target in frontend_profile.items():
            if source in payload:
                profile[target] = payload[source]
        changes: dict[str, Any] = {"profile": profile}
        if "name" in payload:
            changes["name"] = payload["name"]
        if "voiceProfileId" in payload:
            changes["default_voice_id"] = payload["voiceProfileId"]
        if "authorizationStatus" in payload:
            changes["authorization_status"] = payload["authorizationStatus"]
        repository.update_character(character_id, changes)
        return snapshots.build()

    @application.post("/api/v1/voices", status_code=status.HTTP_201_CREATED)
    def create_voice(payload: VoiceCreate) -> dict[str, Any]:
        return repository.create_voice(**payload.model_dump())

    @application.get("/api/v1/voices")
    def list_voices(project_id: str | None = None) -> list[dict[str, Any]]:
        return repository.list_voices(project_id)

    @application.post("/api/v1/projects/{project_id}/lines", status_code=status.HTTP_201_CREATED)
    def create_line(project_id: str, payload: LineCreate) -> dict[str, Any]:
        value = payload.model_dump()
        value["source_text"] = value["text"]
        return repository.create_line(project_id, value)

    @application.get("/api/v1/projects/{project_id}/lines")
    def list_lines(project_id: str) -> list[dict[str, Any]]:
        return repository.list_lines(project_id)

    @application.patch("/api/v1/projects/{project_id}/lines/{line_id}")
    def patch_line_compat(project_id: str, line_id: str, payload: LinePatchEnvelope) -> dict[str, Any]:
        line = repository.get_line(line_id)
        if line["project_id"] != project_id:
            raise DomainError("line_project_mismatch", "台词不属于该项目", status_code=409)
        repository.update_line(line_id, _snake_patch(payload.patch), payload.revision)
        return snapshots.build()

    @application.patch("/api/v1/lines/{line_id}")
    def patch_line(line_id: str, payload: DirectLinePatch) -> dict[str, Any]:
        return repository.update_line(line_id, _snake_patch(payload.changes), payload.expected_revision)

    @application.get("/api/v1/lines/{line_id}/history")
    def line_history(line_id: str) -> list[dict[str, Any]]:
        return repository.line_history(line_id)

    @application.post("/api/v1/lines/{line_id}/restore")
    def restore_line(line_id: str, payload: RestoreLineRequest) -> dict[str, Any]:
        return repository.restore_line(line_id, payload.revision, payload.expected_revision)

    @application.post("/api/v1/projects/{project_id}/imports")
    def import_lines(project_id: str, payload: ImportRequest) -> dict[str, Any]:
        if payload.lines is not None:
            records = [_import_line_from_ui(value, index) for index, value in enumerate(payload.lines)]
            content = json.dumps(payload.lines, ensure_ascii=False)
            source_format, filename, warnings = "json", payload.filename or "frontend-lines.json", []
        else:
            content = payload.content
            filename = payload.filename
            if payload.source_path:
                source = Path(payload.source_path).expanduser().resolve()
                if not source.is_file():
                    raise DomainError("import_file_not_found", "导入文件不存在", status_code=404)
                if source.stat().st_size > configured.max_import_bytes:
                    raise DomainError("import_too_large", "台词导入文件超过大小上限")
                content = decode_bytes(source.read_bytes(), payload.encoding)
                filename = filename or source.name
            if content is None:
                raise DomainError("missing_import_content", "必须提供 content、source_path 或 lines")
            if len(content.encode("utf-8")) > configured.max_import_bytes:
                raise DomainError("import_too_large", "台词导入内容超过大小上限")
            source_format = (payload.format or Path(filename or "").suffix.lstrip(".")).lower()
            if not source_format:
                raise DomainError("missing_import_format", "无法判断导入格式")
            parsed = parse_import(source_format, content)
            records, warnings = parsed.lines, parsed.warnings
            filename = filename or f"import.{source_format}"
        repository.import_lines(project_id, source_format, filename, content, records, warnings)
        return snapshots.build()

    @application.post("/api/v1/projects/{project_id}/generations", status_code=status.HTTP_202_ACCEPTED)
    def generate(project_id: str, payload: GenerationRequest, response: Response) -> dict[str, Any]:
        request = payload.model_dump()
        request["take_count"] = payload.count or payload.take_count
        task = repository.create_task(
            "generate_takes", request, project_id=project_id,
            resource_class="cpu" if payload.engine_id == "mock" else "gpu_heavy",
        )
        response.headers["Location"] = f"/api/v1/tasks/{task['id']}"
        return task

    @application.post("/api/v1/projects/{project_id}/lines/{line_id}/takes")
    def generate_line_takes(project_id: str, line_id: str, payload: GenerationRequest) -> dict[str, Any]:
        line = repository.get_line(line_id)
        if line["project_id"] != project_id:
            raise DomainError("line_project_mismatch", "台词不属于该项目", status_code=409)
        request = payload.model_dump()
        request.update({"line_ids": [line_id], "take_count": payload.count or payload.take_count})
        repository.create_task(
            "generate_takes", request, project_id=project_id,
            resource_class="cpu" if payload.engine_id == "mock" else "gpu_heavy",
        )
        return snapshots.build()

    @application.get("/api/v1/lines/{line_id}/takes")
    def list_takes(line_id: str) -> list[dict[str, Any]]:
        return repository.list_takes(line_id)

    @application.get("/api/v1/takes/{take_id}/audio")
    def take_audio(take_id: str) -> FileResponse:
        path = repository.take_audio_path(take_id)
        return FileResponse(path, media_type="audio/wav", filename=path.name)

    @application.post("/api/v1/lines/{line_id}/takes/{take_id}/select")
    def select_take(line_id: str, take_id: str, payload: SelectTakeRequest) -> dict[str, Any]:
        result = repository.select_take(line_id, take_id, payload.expected_revision)
        if not payload.locked:
            result = repository.update_line_selection_lock(line_id, False, result["revision"])
        return result

    @application.post("/api/v1/projects/{project_id}/lines/{line_id}/takes/{take_id}/select")
    def select_take_compat(project_id: str, line_id: str, take_id: str, payload: SelectTakeRequest) -> dict[str, Any]:
        line = repository.get_line(line_id)
        if line["project_id"] != project_id:
            raise DomainError("line_project_mismatch", "台词不属于该项目", status_code=409)
        selected = repository.select_take(line_id, take_id, payload.expected_revision)
        if not payload.locked:
            repository.update_line_selection_lock(line_id, False, selected["revision"])
        return snapshots.build()

    @application.post("/api/v1/projects/{project_id}/exports", status_code=status.HTTP_202_ACCEPTED)
    def export_project(project_id: str, payload: ExportRequest, response: Response) -> dict[str, Any]:
        task = repository.create_task("export_project", {"format": payload.format}, project_id=project_id)
        response.headers["Location"] = f"/api/v1/tasks/{task['id']}"
        return task

    @application.get("/api/v1/tasks")
    def list_tasks(project_id: str | None = None, task_status: str | None = Query(default=None, alias="status")):
        return repository.list_tasks(project_id=project_id, status=task_status)

    @application.get("/api/v1/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        return repository.get_task(task_id)

    @application.get("/api/v1/tasks/{task_id}/events")
    def task_events(task_id: str, after_event_id: int = 0) -> list[dict[str, Any]]:
        repository.get_task(task_id)
        return repository.list_task_events(task_id=task_id, after_event_id=after_event_id)

    @application.post("/api/v1/tasks/{task_id}/{action}")
    def task_action(task_id: str, action: str) -> dict[str, Any]:
        if action == "cancel":
            repository.request_cancel(task_id)
        elif action == "pause":
            repository.request_pause(task_id)
        elif action == "resume":
            repository.resume_task(task_id)
        elif action in {"retry", "recompute"}:
            repository.retry_task(task_id)
        else:
            raise DomainError("unknown_task_action", f"未知任务操作：{action}", status_code=404)
        return snapshots.build()

    @application.get("/api/v1/engines")
    def engines() -> list[dict[str, Any]]:
        return snapshots.catalog.list()

    @application.get("/api/v1/system/gpu-lease")
    def gpu_lease() -> dict[str, Any]:
        return {"resource": "gpu:0", "lease": repository.gpu_lease(), "policy": "one_heavy_model_at_a_time"}

    @application.get("/api/v1/system/diagnostics")
    def diagnostics() -> dict[str, Any]:
        with database.connection() as connection:
            schema = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
            counts = {
                table: connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
                for table in ("projects", "scenes", "scene_artworks", "lines", "takes", "tasks", "task_events")
            }
        return {
            "generated_at": snapshots.build()["system"]["lastUpdatedAt"],
            "api_version": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "bind": {"host": configured.host, "port": configured.port, "loopback_only": True},
            "database": {"schema_version": schema["version"], "counts": counts, "wal": True},
            "worker": {"enabled": configured.worker_enabled, "gpu_lease": repository.gpu_lease()},
            "engines": [{"id": item["id"], "status": item.get("status"), "license": item.get("license")}
                        for item in snapshots.catalog.list()],
            "secrets_included": False,
            "note": "不包含环境变量、API 密钥、完整本机路径、台词正文或错误堆栈",
        }

    @application.post("/api/v1/japanese/sessions/default/turns")
    def preview_conversation(payload: PreviewConversationRequest) -> dict[str, Any]:
        snapshots.add_preview_conversation(payload.text, payload.coachMode)
        return snapshots.build()

    async def websocket_events(websocket: WebSocket) -> None:
        await websocket.accept()
        project_id = websocket.query_params.get("project_id")
        after = int(websocket.query_params.get("after_event_id", "0"))
        try:
            while True:
                events = await asyncio.to_thread(
                    repository.list_task_events, project_id=project_id, after_event_id=after, limit=200
                )
                for event in events:
                    after = event["event_id"]
                    await websocket.send_json(
                        {"type": event["event_type"], "event_id": event["event_id"],
                         "task_id": event["task_id"], "project_id": event["project_id"],
                         "state": event["to_status"], "progress": event["progress"],
                         "phase": event["phase"], "message": event["message"],
                         "occurred_at": event["created_at"], "payload": event["payload"]}
                    )
                await asyncio.sleep(0.25)
        except WebSocketDisconnect:
            return

    application.websocket("/api/v1/ws/tasks")(websocket_events)
    application.websocket("/api/v1/ws/jobs")(websocket_events)

    # The Japanese learning task owns this module. Core integration uses only its public factory.
    # It is a required product module: import/factory failures are deliberately fail-fast.
    _mount_bundled_japanese_router(application, configured)

    frontend_dist = configured.backend_root.parent / "frontend" / "dist"
    if (frontend_dist / "index.html").is_file():
        application.mount(
            "/",
            StaticFiles(directory=str(frontend_dist), html=True),
            name="studio-frontend",
        )

    return application


app = create_app()


def cli() -> None:
    defaults = Settings.load()
    parser = argparse.ArgumentParser(description="Local AI Voice Studio backend")
    parser.add_argument("--host", default=defaults.host)
    parser.add_argument("--port", type=int, default=defaults.port)
    parser.add_argument("--no-worker", action="store_true", help="禁用内置持久任务 worker")
    arguments = parser.parse_args()
    if arguments.host not in LOOPBACK_HOSTS:
        parser.error("--host 只允许 127.0.0.1、localhost 或 ::1")
    configured = replace(defaults, host=arguments.host, port=arguments.port, worker_enabled=not arguments.no_worker)
    uvicorn.run(create_app(configured), host=configured.host, port=configured.port, workers=1, log_level="info")


if __name__ == "__main__":
    cli()
