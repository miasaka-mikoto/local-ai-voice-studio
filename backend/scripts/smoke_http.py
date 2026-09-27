from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


HOST = "127.0.0.1"
PORT = int(os.getenv("VOICE_STUDIO_SMOKE_PORT", "8766"))
ROOT = Path(__file__).resolve().parents[1]


def request(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://{HOST}:{PORT}{path}", data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def request_text(path: str) -> str:
    req = urllib.request.Request(
        f"http://{HOST}:{PORT}{path}",
        headers={"Accept": "text/html"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        return response.read().decode("utf-8")


def main() -> int:
    with socket.socket() as probe:
        try:
            probe.bind((HOST, PORT))
        except OSError:
            print(f"smoke port {PORT} is already occupied; refusing to stop or reuse it", file=sys.stderr)
            return 2
    with tempfile.TemporaryDirectory() as directory:
        env = os.environ.copy()
        env.update(
            {
                "VOICE_STUDIO_HOST": HOST,
                "VOICE_STUDIO_PORT": str(PORT),
                "VOICE_STUDIO_DATA_ROOT": str(Path(directory) / "data"),
                "VOICE_STUDIO_DATABASE": str(Path(directory) / "data" / "smoke.sqlite3"),
                "VOICE_STUDIO_WORKER_ENABLED": "true",
                "PYTHONUTF8": "1",
            }
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "app.main", "--host", HOST, "--port", str(PORT)],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, creationflags=creationflags,
        )
        try:
            deadline = time.monotonic() + 15
            health = None
            while time.monotonic() < deadline:
                try:
                    health = request("/api/v1/health")
                    break
                except (urllib.error.URLError, TimeoutError):
                    if process.poll() is not None:
                        break
                    time.sleep(0.15)
            if not health or not health.get("ok"):
                output = process.stdout.read() if process.stdout else ""
                print(output, file=sys.stderr)
                return 1
            landing = request_text("/")
            assert "<title>Local AI Voice Studio</title>" in landing
            snapshot = request(
                "/api/v1/projects",
                {"name": "HTTP smoke", "kind": "game_voice", "description": "mock only", "locale": "ja-JP"},
            )
            assert len(snapshot["projects"]) == 1
            project_id = snapshot["projects"][0]["id"]
            snapshot = request(
                f"/api/v1/projects/{project_id}/imports",
                {"lines": [{"lineId": "L001", "sceneId": "S01", "speaker": "Aki",
                             "text": "始めましょう", "emotion": "focused", "locale": "ja-JP",
                             "durationLimitMs": 900, "assetName": "smoke_001"}]},
            )
            line_id = snapshot["lines"][0]["id"]
            request(
                f"/api/v1/projects/{project_id}/lines/{line_id}/takes",
                {"count": 2, "engine_id": "mock", "seed": 7},
            )
            deadline = time.monotonic() + 12
            bootstrap = None
            while time.monotonic() < deadline:
                bootstrap = request("/api/v1/bootstrap")
                if len(bootstrap["takes"]) == 2 and any(job["status"] == "completed" for job in bootstrap["jobs"]):
                    break
                time.sleep(0.15)
            assert bootstrap is not None and len(bootstrap["takes"]) == 2
            take_id = bootstrap["takes"][0]["id"]
            selected = request(
                f"/api/v1/projects/{project_id}/lines/{line_id}/takes/{take_id}/select",
                {"locked": True},
            )
            assert selected["lines"][0]["selectedTakeId"] == take_id
            export_task = request(f"/api/v1/projects/{project_id}/exports", {"format": "project_json"})
            deadline = time.monotonic() + 12
            finished = None
            while time.monotonic() < deadline:
                finished = request(f"/api/v1/tasks/{export_task['id']}")
                if finished["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.15)
            assert finished and finished["status"] == "completed"
            assert Path(finished["result"]["manifest_path"]).is_file()
            print(
                json.dumps(
                    {"health": health, "projectCount": len(bootstrap["projects"]),
                     "lineCount": len(bootstrap["lines"]), "takeCount": len(bootstrap["takes"]),
                     "exportStatus": finished["status"], "frontendServed": True},
                    ensure_ascii=False,
                )
            )
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
