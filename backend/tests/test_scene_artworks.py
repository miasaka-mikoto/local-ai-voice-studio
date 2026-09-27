from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sqlite3
import struct
import tempfile
import unittest
import zlib
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

from app.config import Settings
from app.database import SCHEMA_SQL, Database
from app.errors import DomainError
from app.main import create_app
from app.repository import Repository
from app.scene_artworks import inspect_image


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
JPEG_7X5 = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAFAAcDASIA"
    "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAA"
    "F9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6"
    "Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ip"
    "qrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEB"
    "AQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQ"
    "dhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldY"
    "WVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPEx"
    "cbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDi6KKK+ZP3E//Z"
)
WEBP_7X5 = base64.b64decode(
    "UklGRjwAAABXRUJQVlA4IDAAAADQAQCdASoHAAUAAUAmJaACdLoB+AADsAD+8ut//NgVzXPv9//S4P0uD9Lg/9KQAAA="
)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        len(payload).to_bytes(4, "big")
        + kind
        + payload
        + (zlib.crc32(kind + payload) & 0xFFFFFFFF).to_bytes(4, "big")
    )


PNG_EMPTY_IDAT = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    + _png_chunk(b"IDAT", b"")
    + _png_chunk(b"IEND", b"")
)
_JPEG_SOS = JPEG_7X5.index(b"\xff\xda")
_JPEG_SOS_END = _JPEG_SOS + 2 + int.from_bytes(JPEG_7X5[_JPEG_SOS + 2 : _JPEG_SOS + 4], "big")
JPEG_WITHOUT_SCAN_DATA = JPEG_7X5[:_JPEG_SOS_END] + b"\xff\xd9"


async def asgi_request(
    application,
    method: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    body: bytes = b"",
    content_type: str | None = None,
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

    headers = [(b"host", b"127.0.0.1"), (b"content-length", str(len(body)).encode("ascii"))]
    if content_type:
        headers.append((b"content-type", content_type.encode("ascii")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": urlencode(query or {}).encode("ascii"),
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


class SceneArtworkMigrationTests(unittest.TestCase):
    def test_v1_database_receives_additive_scene_artwork_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "studio.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript(SCHEMA_SQL)
            connection.execute(
                "INSERT INTO schema_migrations(version,name,applied_at) VALUES(1,'initial_backend_mvp','now')"
            )
            connection.execute(
                """
                INSERT INTO projects(id,name,project_type,created_at,updated_at)
                VALUES('project-legacy','Legacy','video','now','now')
                """
            )
            connection.execute(
                """
                INSERT INTO scenes(id,project_id,name,created_at,updated_at)
                VALUES('scene-legacy','project-legacy','Opening','now','now')
                """
            )
            connection.commit()
            connection.close()

            database = Database(path)
            database.initialize()
            with database.connection() as migrated:
                migrations = [
                    (row["version"], row["name"])
                    for row in migrated.execute(
                        "SELECT version,name FROM schema_migrations ORDER BY version"
                    ).fetchall()
                ]
                scene = migrated.execute("SELECT name FROM scenes WHERE id='scene-legacy'").fetchone()
                columns = {
                    row["name"] for row in migrated.execute("PRAGMA table_info(scene_artworks)").fetchall()
                }
            self.assertEqual([(1, "initial_backend_mvp"), (2, "scene_artworks")], migrations)
            self.assertEqual("Opening", scene["name"])
            self.assertTrue({"sha256", "width", "height", "prompt", "license", "selected"}.issubset(columns))


class SceneArtworkRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings.load(
            data_root=root / "data",
            database_path=root / "data" / "studio.sqlite3",
            worker_enabled=False,
        )
        self.settings.ensure_directories()
        self.database = Database(self.settings.database_path)
        self.database.initialize()
        self.repository = Repository(self.database, self.settings)
        self.project = self.repository.create_project("Illustrated", "video")
        self.scene = self.repository.create_scene(self.project["id"], "Opening")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create(self, **changes):
        values = {
            "filename": "../unsafe name.png",
            "mime_type": "image/png",
            "source_kind": "user_upload",
            "prompt": "night city",
            "source": "manual-upload",
            "license": "CC0-1.0",
        }
        values.update(changes)
        return self.repository.create_scene_artwork(
            self.project["id"], self.scene["id"], PNG_1X1, **values
        )

    def test_png_jpeg_and_webp_dimensions_are_detected_from_content(self) -> None:
        expected = (
            (PNG_1X1, "image/png", (1, 1)),
            (JPEG_7X5, "image/jpeg", (7, 5)),
            (WEBP_7X5, "image/webp", (7, 5)),
        )
        for content, mime_type, dimensions in expected:
            with self.subTest(mime_type=mime_type):
                image = inspect_image(content, mime_type, 1024 * 1024)
                self.assertEqual(dimensions, (image.width, image.height))
        with self.assertRaisesRegex(DomainError, "仅支持"):
            inspect_image(b"GIF89a", "image/gif", 1024)

    def test_structurally_plausible_but_undecodable_images_are_rejected(self) -> None:
        for content, mime_type in (
            (PNG_EMPTY_IDAT, "image/png"),
            (JPEG_WITHOUT_SCAN_DATA, "image/jpeg"),
        ):
            with self.subTest(mime_type=mime_type):
                with self.assertRaisesRegex(DomainError, "完整解码|媒体类型"):
                    inspect_image(content, mime_type, 1024 * 1024)

    def test_metadata_selection_and_restart_persistence(self) -> None:
        first = self._create()
        second = self._create(
            filename="generated.webp.png",
            source_kind="local_generated",
            source="local:imagegen",
            prompt="railway platform",
        )
        self.assertTrue(first["selected"])
        self.assertFalse(second["selected"])
        self.assertEqual((1, 1), (first["width"], first["height"]))
        self.assertEqual("image/png", first["mime_type"])
        self.assertEqual(hashlib.sha256(PNG_1X1).hexdigest(), first["sha256"])
        self.assertNotIn("..", first["original_filename"])
        self.assertFalse(Path(first["relative_path"]).is_absolute())

        selected = self.repository.select_scene_artwork(
            self.project["id"], self.scene["id"], second["id"]
        )
        self.assertTrue(selected["selected"])
        restarted = Repository(Database(self.settings.database_path), self.settings)
        artworks = restarted.list_scene_artworks(self.project["id"], self.scene["id"])
        self.assertEqual([second["id"], first["id"]], [item["id"] for item in artworks])
        self.assertEqual(1, sum(item["selected"] for item in artworks))
        metadata, path = restarted.scene_artwork_content_path(
            self.project["id"], self.scene["id"], second["id"]
        )
        self.assertEqual(second["sha256"], metadata["sha256"])
        self.assertEqual(PNG_1X1, path.read_bytes())

    def test_remote_invalid_mismatched_and_oversized_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(DomainError, "本地字节"):
            self._create(source="https://example.invalid/image.png")
        with self.assertRaisesRegex(DomainError, "媒体类型不一致"):
            self._create(mime_type="image/jpeg")
        with self.assertRaisesRegex(DomainError, "来源类型"):
            self._create(source_kind="remote_url")
        limited = Repository(
            self.database, replace(self.settings, max_scene_artwork_bytes=len(PNG_1X1) - 1)
        )
        with self.assertRaisesRegex(DomainError, "大小上限"):
            limited.create_scene_artwork(
                self.project["id"],
                self.scene["id"],
                PNG_1X1,
                filename="large.png",
                mime_type="image/png",
                source_kind="user_upload",
            )

    def test_cross_project_scene_and_path_escape_are_rejected(self) -> None:
        other = self.repository.create_project("Other", "japanese")
        with self.assertRaisesRegex(DomainError, "场景不存在"):
            self.repository.create_scene_artwork(
                other["id"],
                self.scene["id"],
                PNG_1X1,
                filename="cross.png",
                mime_type="image/png",
                source_kind="user_upload",
            )
        artwork = self._create()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE scene_artworks SET relative_path='../outside.png' WHERE id=?",
                (artwork["id"],),
            )
        with self.assertRaisesRegex(DomainError, "完整性"):
            self.repository.scene_artwork_content_path(
                self.project["id"], self.scene["id"], artwork["id"]
            )

    def test_tampered_file_is_not_served(self) -> None:
        artwork = self._create()
        path = self.settings.data_root / Path(artwork["relative_path"])
        path.write_bytes(PNG_1X1 + b"tamper")
        with self.assertRaisesRegex(DomainError, "完整性"):
            self.repository.scene_artwork_content_path(
                self.project["id"], self.scene["id"], artwork["id"]
            )


class SceneArtworkApiTests(unittest.TestCase):
    def test_openapi_upload_list_select_and_safe_content_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings.load(
                data_root=root / "data",
                database_path=root / "data" / "studio.sqlite3",
                worker_enabled=False,
            )
            application = create_app(settings)
            repository: Repository = application.state.repository
            project = repository.create_project("API art", "game")
            scene = repository.create_scene(project["id"], "Battle")
            collection = f"/api/v1/projects/{project['id']}/scenes/{scene['id']}/artworks"

            schema = application.openapi()
            self.assertIn(collection.replace(project["id"], "{project_id}").replace(scene["id"], "{scene_id}"), schema["paths"])
            self.assertIn(
                "/api/v1/projects/{project_id}/scenes/{scene_id}/artworks/{artwork_id}/content",
                schema["paths"],
            )

            upload_status, _, upload_body = asyncio.run(
                asgi_request(
                    application,
                    "POST",
                    collection,
                    query={
                        "filename": "opening.png",
                        "source_kind": "local_generated",
                        "prompt": "electric city",
                        "source": "local:test-generator",
                        "license": "CC0-1.0",
                    },
                    body=PNG_1X1,
                    content_type="image/png",
                )
            )
            self.assertEqual(201, upload_status)
            artwork = json.loads(upload_body)
            self.assertTrue(artwork["selected"])

            second_status, _, second_body = asyncio.run(
                asgi_request(
                    application,
                    "POST",
                    collection,
                    query={"filename": "alternate.png", "source_kind": "user_upload"},
                    body=PNG_1X1,
                    content_type="image/png",
                )
            )
            self.assertEqual(201, second_status)
            second = json.loads(second_body)
            self.assertFalse(second["selected"])
            select_status, _, select_body = asyncio.run(
                asgi_request(application, "POST", f"{collection}/{second['id']}/select")
            )
            self.assertEqual(200, select_status)
            self.assertTrue(json.loads(select_body)["selected"])

            list_status, _, list_body = asyncio.run(asgi_request(application, "GET", collection))
            self.assertEqual(200, list_status)
            listed = json.loads(list_body)
            self.assertEqual([second["id"], artwork["id"]], [item["id"] for item in listed])
            self.assertEqual(1, sum(item["selected"] for item in listed))

            content_status, headers, content = asyncio.run(
                asgi_request(application, "GET", artwork["image_url"])
            )
            self.assertEqual(200, content_status)
            self.assertEqual("image/png", headers["content-type"])
            self.assertEqual("nosniff", headers["x-content-type-options"])
            self.assertEqual(PNG_1X1, content)

    def test_http_size_limit_and_remote_source_return_sanitized_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = replace(
                Settings.load(
                    data_root=root / "data",
                    database_path=root / "data" / "studio.sqlite3",
                    worker_enabled=False,
                ),
                max_scene_artwork_bytes=32,
            )
            application = create_app(settings)
            repository: Repository = application.state.repository
            project = repository.create_project("API guard", "japanese")
            scene = repository.create_scene(project["id"], "Lesson")
            collection = f"/api/v1/projects/{project['id']}/scenes/{scene['id']}/artworks"

            too_large, _, body = asyncio.run(
                asgi_request(
                    application,
                    "POST",
                    collection,
                    body=PNG_1X1,
                    content_type="image/png",
                )
            )
            self.assertEqual(413, too_large)
            self.assertNotIn(str(root), body.decode("utf-8"))

            application = create_app(replace(settings, max_scene_artwork_bytes=1024))
            remote, _, body = asyncio.run(
                asgi_request(
                    application,
                    "POST",
                    collection,
                    query={"source": "https://user:secret@example.invalid/art.png"},
                    body=PNG_1X1,
                    content_type="image/png",
                )
            )
            self.assertEqual(400, remote)
            payload = json.loads(body)
            self.assertEqual("remote_scene_artwork_source_rejected", payload["code"])
            self.assertNotIn("secret", body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
