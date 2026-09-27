from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from .engines import MockEngine
from .errors import DomainError
from .exporter import ProjectExporter
from .repository import Repository
from .util import safe_filename


class TaskRunner:
    def __init__(self, repository: Repository, worker_id: str) -> None:
        self.repository = repository
        self.worker_id = worker_id
        self.mock = MockEngine()
        self.exporter = ProjectExporter(repository)

    def run_once(self) -> dict[str, Any] | None:
        self.repository.recover_expired_tasks()
        task = self.repository.claim_next_task(self.worker_id)
        if task is None:
            return None
        try:
            if task["task_type"] == "generate_takes":
                result = self._generate_takes(task)
            elif task["task_type"] == "export_project":
                result = self._export(task)
            else:
                raise DomainError("unknown_task_type", f"没有任务处理器：{task['task_type']}")
            latest = self.repository.get_task(task["id"])
            if latest["status"] == "running":
                return self.repository.finish_task(task["id"], result)
            return latest
        except DomainError as exc:
            return self.repository.fail_task(
                task["id"],
                {"code": exc.code, "message": exc.message, "details": exc.details, "retryable": exc.retryable},
            )
        except Exception as exc:  # defensive worker boundary; traceback is not persisted
            return self.repository.fail_task(
                task["id"],
                {"code": "worker_error", "message": str(exc), "details": {}, "retryable": True},
            )

    def _check_control(self, task_id: str) -> bool:
        control = self.repository.task_control(task_id)
        if control:
            self.repository.apply_running_control(task_id, control)
            return True
        return False

    def _generate_takes(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = task["payload"]
        if payload.get("engine_id", "mock") != "mock":
            raise DomainError(
                "engine_not_enabled",
                "MVP 仅启用 mock 引擎；真实模型适配器必须在资源安全评审后显式启用",
                status_code=409,
            )
        project_id = task["project_id"]
        line_ids = payload.get("line_ids") or [line["id"] for line in self.repository.list_lines(project_id)]
        take_count = int(payload.get("take_count", 3))
        if not 1 <= take_count <= 8:
            raise DomainError("invalid_take_count", "take_count 必须在 1..8 范围内")
        base_seed = int(payload.get("seed", 42))
        seeds = payload.get("seeds") or []
        parameters = payload.get("parameters") or {}
        total = max(1, len(line_ids) * take_count)
        completed = 0
        take_ids: list[str] = []
        for line_id in line_ids:
            line = self.repository.get_line(line_id)
            if line["project_id"] != project_id:
                raise DomainError("line_project_mismatch", "生成列表包含其他项目的台词", status_code=409)
            for variant in range(1, take_count + 1):
                if self._check_control(task["id"]):
                    return {"take_ids": take_ids, "interrupted": True}
                seed_index = completed
                seed = int(seeds[seed_index]) if seed_index < len(seeds) else base_seed + seed_index
                input_hash = self.mock.input_hash(line, seed, parameters)
                filename = safe_filename(
                    f"{line.get('asset_name') or line.get('external_line_id') or line['id']}_v{variant}_{input_hash[:10]}.wav"
                )
                path = (
                    self.repository.settings.data_root / "projects" / project_id / "takes" /
                    line["id"] / filename
                )
                generated = self.mock.generate(line, seed, parameters, path)
                take = self.repository.register_take(
                    line_id=line["id"], task_id=task["id"], variant_no=variant,
                    engine_id=self.mock.id, engine_version=self.mock.version, seed=seed,
                    parameters=parameters, input_hash=input_hash, path=generated.path,
                    duration_ms=generated.duration_ms, qc=generated.qc,
                )
                take_ids.append(take["id"])
                completed += 1
                self.repository.update_task_progress(
                    task["id"], completed / total, "mock_generate",
                    f"已生成 {completed}/{total} 个 mock take",
                )
        return {"take_ids": take_ids, "line_count": len(line_ids), "take_count": take_count,
                "engine_id": "mock", "audio_format": "48kHz PCM 24-bit mono"}

    def _export(self, task: dict[str, Any]) -> dict[str, Any]:
        if self._check_control(task["id"]):
            return {"interrupted": True}
        self.repository.update_task_progress(task["id"], 0.2, "export", "正在收集人工选择")
        result = self.exporter.export(
            task["project_id"], task["payload"].get("format", "project_json"), task["id"]
        )
        self.repository.update_task_progress(task["id"], 0.95, "export", "导出文件已写入")
        return result

    def run_until_idle(self, max_tasks: int = 100) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for _ in range(max_tasks):
            result = self.run_once()
            if result is None:
                break
            results.append(result)
        return results
