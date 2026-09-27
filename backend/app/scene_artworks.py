from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from .errors import DomainError


SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_IMAGE_DIMENSION = 16_384
MAX_IMAGE_PIXELS = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ImageInfo:
    mime_type: str
    width: int
    height: int


def _png_dimensions(content: bytes) -> tuple[int, int] | None:
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    offset = 8
    dimensions: tuple[int, int] | None = None
    saw_image_data = False
    while offset + 12 <= len(content):
        length = int.from_bytes(content[offset : offset + 4], "big")
        chunk_type = content[offset + 4 : offset + 8]
        payload_start = offset + 8
        payload_end = payload_start + length
        chunk_end = payload_end + 4
        if payload_end < payload_start or chunk_end > len(content):
            return None
        expected_crc = int.from_bytes(content[payload_end:chunk_end], "big")
        if zlib.crc32(chunk_type + content[payload_start:payload_end]) & 0xFFFFFFFF != expected_crc:
            return None
        if offset == 8:
            if chunk_type != b"IHDR" or length != 13:
                return None
            dimensions = struct.unpack(">II", content[payload_start : payload_start + 8])
        elif chunk_type == b"IDAT":
            saw_image_data = True
        elif chunk_type == b"IEND":
            if length != 0 or chunk_end != len(content):
                return None
            return dimensions if dimensions is not None and saw_image_data else None
        offset = chunk_end
    return None


_JPEG_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


def _jpeg_dimensions(content: bytes) -> tuple[int, int] | None:
    if len(content) < 4 or content[:2] != b"\xff\xd8" or content[-2:] != b"\xff\xd9":
        return None
    offset = 2
    dimensions: tuple[int, int] | None = None
    while offset < len(content) - 2:
        if content[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        if offset >= len(content):
            return None
        marker = content[offset]
        offset += 1
        if marker in {0x00, 0x01, *range(0xD0, 0xDA)}:
            continue
        if marker == 0xDA:
            if offset + 2 > len(content):
                return None
            scan_header_length = int.from_bytes(content[offset : offset + 2], "big")
            scan_data_start = offset + scan_header_length
            # A JPEG with an SOS header immediately followed by EOI has no
            # compressed scan data even though its SOF dimensions look valid.
            return dimensions if scan_header_length >= 2 and scan_data_start < len(content) - 2 else None
        if offset + 2 > len(content):
            return None
        segment_length = int.from_bytes(content[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(content):
            return None
        if marker in _JPEG_SOF_MARKERS:
            if segment_length < 7:
                return None
            height = int.from_bytes(content[offset + 3 : offset + 5], "big")
            width = int.from_bytes(content[offset + 5 : offset + 7], "big")
            dimensions = (width, height)
        offset += segment_length
    return dimensions


def _webp_dimensions(content: bytes) -> tuple[int, int] | None:
    if len(content) < 20 or content[:4] != b"RIFF" or content[8:12] != b"WEBP":
        return None
    if int.from_bytes(content[4:8], "little") + 8 != len(content):
        return None
    offset = 12
    while offset + 8 <= len(content):
        chunk_type = content[offset : offset + 4]
        chunk_size = int.from_bytes(content[offset + 4 : offset + 8], "little")
        payload = offset + 8
        chunk_end = payload + chunk_size
        if chunk_end < payload or chunk_end > len(content):
            return None
        if chunk_type == b"VP8X" and chunk_size >= 10:
            width = 1 + int.from_bytes(content[payload + 4 : payload + 7], "little")
            height = 1 + int.from_bytes(content[payload + 7 : payload + 10], "little")
            return width, height
        if chunk_type == b"VP8 " and chunk_size >= 10:
            if content[payload + 3 : payload + 6] != b"\x9d\x01\x2a":
                return None
            width = int.from_bytes(content[payload + 6 : payload + 8], "little") & 0x3FFF
            height = int.from_bytes(content[payload + 8 : payload + 10], "little") & 0x3FFF
            return width, height
        if chunk_type == b"VP8L" and chunk_size >= 5:
            if content[payload] != 0x2F:
                return None
            bits = int.from_bytes(content[payload + 1 : payload + 5], "little")
            return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
        offset = chunk_end + (chunk_size & 1)
    return None


def inspect_image(content: bytes, declared_mime: str, max_bytes: int) -> ImageInfo:
    if not content:
        raise DomainError("empty_scene_artwork", "场景插画内容为空")
    if len(content) > max_bytes:
        raise DomainError(
            "scene_artwork_too_large",
            "场景插画超过本地大小上限",
            status_code=413,
            details={"max_bytes": max_bytes},
        )
    normalized_mime = declared_mime.split(";", 1)[0].strip().lower()
    if normalized_mime not in SUPPORTED_IMAGE_TYPES:
        raise DomainError(
            "unsupported_scene_artwork_type",
            "场景插画仅支持 PNG、JPEG 或 WebP",
            status_code=415,
        )
    candidates = (
        ("image/png", _png_dimensions(content)),
        ("image/jpeg", _jpeg_dimensions(content)),
        ("image/webp", _webp_dimensions(content)),
    )
    detected = next(((mime, size) for mime, size in candidates if size is not None), None)
    if detected is None or detected[0] != normalized_mime:
        raise DomainError(
            "invalid_scene_artwork",
            "图片内容无效或与声明的媒体类型不一致",
            status_code=415,
        )
    width, height = detected[1]
    if (
        width <= 0
        or height <= 0
        or width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise DomainError("invalid_scene_artwork_dimensions", "场景插画尺寸超出安全范围")
    try:
        # Header parsing gives us strict, cheap bounds before a decoder sees
        # the payload. Pillow then verifies the complete container and decodes
        # pixel data so empty IDAT / missing JPEG scan data cannot be stored as
        # an apparently valid artwork.
        with Image.open(BytesIO(content)) as image:
            decoded_mime = Image.MIME.get(image.format or "")
            decoded_size = image.size
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise DomainError(
            "invalid_scene_artwork",
            "图片内容无法完整解码",
            status_code=415,
        ) from error
    if decoded_mime != detected[0] or decoded_size != (width, height):
        raise DomainError(
            "invalid_scene_artwork",
            "图片解码结果与声明的媒体类型或尺寸不一致",
            status_code=415,
        )
    return ImageInfo(detected[0], width, height)


def validate_local_source(value: str) -> str:
    source = value.strip()
    if re.match(r"(?i)^(?:https?|ftp|file):", source) or source.startswith(("//", "\\\\")):
        raise DomainError(
            "remote_scene_artwork_source_rejected",
            "场景插画必须由本地字节提交，不能登记远程地址",
        )
    return source


def extension_for_mime(mime_type: str) -> str:
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime_type]
