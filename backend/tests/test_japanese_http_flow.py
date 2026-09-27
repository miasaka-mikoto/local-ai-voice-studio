from __future__ import annotations

import asyncio
import json
import math
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.japanese.adapters import (  # noqa: E402
    AdapterBundle,
    MockASRAdapter,
    MockTTSAdapter,
    MockTeacherAdapter,
)
from app.modules.japanese.repository import JapaneseRepository  # noqa: E402
from app.modules.japanese.router import create_router  # noqa: E402
from app.modules.japanese.service import JapaneseLearningService  # noqa: E402


async def asgi_request(
    application: FastAPI,
    method: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    body: bytes = b"",
    content_type: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    messages: list[dict] = []
    delivered = False

    async def receive() -> dict:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    headers = [(b"host", b"127.0.0.1")]
    if content_type:
        headers.append((b"content-type", content_type.encode("ascii")))
    for key, value in (extra_headers or {}).items():
        headers.append((key.lower().encode("ascii"), value.encode("ascii")))
    query_string = urlencode(query or {}).encode("ascii")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query_string,
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8766),
    }
    await application(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start.get("headers", [])
    }
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return start["status"], response_headers, response_body


def json_body(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class JapaneseHttpFlowTests(unittest.TestCase):
    def test_project_lesson_reopens_and_scores_only_uploaded_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "studio.sqlite3"
            assets = root / "assets"
            service = JapaneseLearningService(
                JapaneseRepository(database), assets,
                AdapterBundle(MockASRAdapter(), MockTeacherAdapter(), MockTTSAdapter()),
            )
            learner = service.create_learner("课程学习者", "N4", [], [])
            application = FastAPI()
            application.include_router(create_router(service))

            status, _, body = asyncio.run(asgi_request(
                application, "POST",
                f"/api/japanese/learners/{learner.id}/project-lessons",
                body=json_body({
                    "source_project_id": "project-1", "lesson_mode": "shadowing",
                    "scenario": "游戏第一幕", "lines": [
                        {"line_id": "line-1", "scene_id": "scene-1", "text": "新宿までお願いします"},
                    ],
                }),
                content_type="application/json",
            ))
            self.assertEqual(status, 201)
            lesson = json.loads(body)
            session_id = lesson["session"]["id"]
            exercise_id = lesson["exercises"][0]["id"]

            reopened = JapaneseLearningService(
                JapaneseRepository(database), assets,
                AdapterBundle(MockASRAdapter(), MockTeacherAdapter(), MockTTSAdapter()),
            )
            reopened_app = FastAPI()
            reopened_app.include_router(create_router(reopened))
            status, _, body = asyncio.run(asgi_request(
                reopened_app, "GET", f"/api/japanese/learners/{learner.id}/sessions"
            ))
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)[0]["metadata"]["source_project_id"], "project-1")
            status, _, body = asyncio.run(asgi_request(
                reopened_app, "GET", f"/api/japanese/sessions/{session_id}/exercises"
            ))
            self.assertEqual(status, 200)
            exercises = json.loads(body)
            self.assertEqual(exercises[0]["id"], exercise_id)
            self.assertEqual(exercises[0]["metadata"]["source_line_id"], "line-1")
            status, _, audio = asyncio.run(asgi_request(
                reopened_app, "GET", exercises[0]["reference_audio_url"]
            ))
            self.assertEqual(status, 200)
            self.assertEqual(audio[:4], b"RIFF")

            microphone = root / "microphone.wav"
            with wave.open(str(microphone), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(3)
                wav.setframerate(48_000)
                wav.writeframes(b"".join(
                    int(0.15 * 8_388_607 * math.sin(2 * math.pi * 220 * index / 48_000)).to_bytes(
                        3, "little", signed=True
                    ) for index in range(9_600)
                ))
            status, _, body = asyncio.run(asgi_request(
                reopened_app, "POST", "/api/japanese/recordings",
                query={"session_id": session_id, "filename": "microphone.wav"},
                body=microphone.read_bytes(), content_type="audio/wav",
            ))
            self.assertEqual(status, 201)
            recording_id = json.loads(body)["recording_id"]
            status, _, body = asyncio.run(asgi_request(
                reopened_app, "POST",
                f"/api/japanese/sessions/{session_id}/shadowing/exercises/{exercise_id}/attempts",
                body=json_body({"recording_id": recording_id}), content_type="application/json",
            ))
            self.assertEqual(status, 201)
            attempt = json.loads(body)
            self.assertEqual(attempt["ab_playback"]["recording_id"], recording_id)
            self.assertEqual(attempt["feedback"]["scoring_source_kind"], "original_uncolored")
            self.assertNotIn("overall_score", attempt["feedback"])

    def test_silent_conversation_upload_returns_rerecord_error_without_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = JapaneseLearningService(
                JapaneseRepository(root / "studio.sqlite3"),
                root / "assets",
                AdapterBundle(MockASRAdapter(), MockTeacherAdapter(), MockTTSAdapter()),
            )
            learner = service.create_learner("HTTP 学习者", "N4", [], [])
            session = service.start_session(learner.id, "conversation", "strict", "车站")
            application = FastAPI()
            application.include_router(create_router(service))

            silence = root / "silence.wav"
            with wave.open(str(silence), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(3)
                wav.setframerate(48_000)
                wav.writeframes(b"\x00\x00\x00" * 48_000)
            status, _, body = asyncio.run(asgi_request(
                application,
                "POST",
                "/api/japanese/recordings",
                query={"session_id": session.id, "filename": "silence.wav"},
                body=silence.read_bytes(),
                content_type="audio/wav",
            ))
            self.assertEqual(status, 201)
            recording_id = json.loads(body)["recording_id"]

            status, _, body = asyncio.run(asgi_request(
                application,
                "POST",
                f"/api/japanese/sessions/{session.id}/turns",
                body=json_body({"recording_id": recording_id, "transcript_hint": "こんにちは"}),
                content_type="application/json",
            ))
            self.assertEqual(status, 400)
            self.assertIn("重录", json.loads(body)["detail"])
            self.assertEqual(service.list_turns(session.id), [])

    def test_full_mock_http_learning_and_shadowing_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = JapaneseLearningService(
                JapaneseRepository(root / "studio.sqlite3"),
                root / "assets",
                AdapterBundle(MockASRAdapter(), MockTeacherAdapter(), MockTTSAdapter()),
            )
            application = FastAPI()
            application.include_router(create_router(service))

            status, _, body = asyncio.run(
                asgi_request(
                    application,
                    "POST",
                    "/api/japanese/learners",
                    body=json_body({"display_name": "HTTP 学习者", "level": "N4"}),
                    content_type="application/json",
                )
            )
            self.assertEqual(status, 201)
            learner = json.loads(body)

            status, _, body = asyncio.run(
                asgi_request(
                    application,
                    "POST",
                    "/api/japanese/sessions",
                    body=json_body(
                        {
                            "learner_id": learner["id"],
                            "mode": "shadowing",
                            "coach_mode": "strict",
                            "scenario": "车站",
                        }
                    ),
                    content_type="application/json",
                )
            )
            self.assertEqual(status, 201)
            session = json.loads(body)

            status, _, _ = asyncio.run(
                asgi_request(
                    application,
                    "POST",
                    "/api/japanese/recordings",
                    query={"session_id": session["id"], "filename": "too-large.webm"},
                    content_type="audio/webm",
                    extra_headers={"content-length": str(20 * 1024 * 1024 + 1)},
                )
            )
            self.assertEqual(status, 413)

            microphone = root / "assets" / "fixture.wav"
            microphone.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(microphone), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(3)
                wav.setframerate(48_000)
                wav.writeframes(b"".join(
                    int(0.15 * 8_388_607 * math.sin(2 * math.pi * 220 * index / 48_000)).to_bytes(
                        3, "little", signed=True
                    )
                    for index in range(9_600)
                ))
            status, _, body = asyncio.run(
                asgi_request(
                    application,
                    "POST",
                    "/api/japanese/recordings",
                    query={"session_id": session["id"], "filename": "microphone.wav"},
                    body=microphone.read_bytes(),
                    content_type="audio/wav",
                )
            )
            self.assertEqual(status, 201)
            recording = json.loads(body)
            self.assertEqual(recording["recording_id"], recording["id"])

            status, _, body = asyncio.run(
                asgi_request(
                    application,
                    "POST",
                    f"/api/japanese/sessions/{session['id']}/turns",
                    body=json_body(
                        {
                            "recording_id": recording["id"],
                            "transcript_hint": "日本語勉強します",
                        }
                    ),
                    content_type="application/json",
                )
            )
            self.assertEqual(status, 201)
            turn = json.loads(body)
            self.assertTrue(turn["demonstration"]["audio_url"].endswith("/demonstration"))
            self.assertEqual(turn["scoring_source_kind"], "original_uncolored")

            status, headers, audio = asyncio.run(
                asgi_request(application, "GET", turn["demonstration"]["audio_url"])
            )
            self.assertEqual(status, 200)
            self.assertEqual(headers["content-type"], "audio/wav")
            self.assertEqual(audio[:4], b"RIFF")

            status, _, history_body = asyncio.run(
                asgi_request(
                    application,
                    "GET",
                    f"/api/japanese/sessions/{session['id']}/turns",
                )
            )
            self.assertEqual(status, 200)
            history = json.loads(history_body)
            self.assertEqual(
                history[0]["demonstration"]["audio_url"],
                turn["demonstration"]["audio_url"],
            )

            status, _, body = asyncio.run(
                asgi_request(
                    application,
                    "POST",
                    f"/api/japanese/sessions/{session['id']}/shadowing/references",
                    body=json_body({"expected_text": "新宿まで一枚お願いします。"}),
                    content_type="application/json",
                )
            )
            self.assertEqual(status, 201)
            reference = json.loads(body)
            exercise_id = reference["exercise"]["id"]
            status, _, body = asyncio.run(asgi_request(
                application, "GET", f"/api/japanese/sessions/{session['id']}/exercises"
            ))
            self.assertEqual(status, 200)
            listed = json.loads(body)
            self.assertEqual([item["id"] for item in listed], [exercise_id])
            self.assertEqual(listed[0]["reference_audio_url"], reference["synthesis"]["audio_url"])
            status, _, reference_audio = asyncio.run(
                asgi_request(application, "GET", reference["synthesis"]["audio_url"])
            )
            self.assertEqual(status, 200)
            self.assertEqual(reference_audio[:4], b"RIFF")

            status, _, body = asyncio.run(
                asgi_request(
                    application,
                    "POST",
                    f"/api/japanese/sessions/{session['id']}/shadowing/exercises/{exercise_id}/attempts",
                    body=json_body(
                        {
                            "recording_id": recording["id"],
                            "transcript_hint": "新宿まで一枚お願いします。",
                        }
                    ),
                    content_type="application/json",
                )
            )
            self.assertEqual(status, 201)
            attempt = json.loads(body)
            self.assertNotIn("overall_score", attempt["feedback"])
            self.assertIsNone(attempt["feedback"]["mora"]["value"])
            self.assertIn("reference_audio_url", attempt["ab_playback"])
            self.assertLessEqual(len(attempt["feedback"]["priorities"]), 2)


if __name__ == "__main__":
    unittest.main()
