"""Cross-platform stable naming for generated game voice assets."""

from __future__ import annotations

from hashlib import sha256
import json
import math
import re
import unicodedata


_UNSAFE = re.compile(r"[^a-z0-9]+")
_EXTENSION = re.compile(r"^[a-z0-9]{1,8}$")


def slug_component(value: object, *, fallback: str = "x", limit: int = 28) -> str:
    """Return a deterministic ASCII filename component.

    A hash suffix is added when Unicode or lossy normalization was needed, so
    two different non-ASCII identifiers cannot silently collapse to one name.
    """

    original = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    ascii_value = original.encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE.sub("_", ascii_value).strip("_") or fallback
    cleaned = cleaned[:limit].rstrip("_") or fallback
    if cleaned != original:
        digest = sha256(original.encode("utf-8")).hexdigest()[:8]
        room = max(1, limit - 9)
        cleaned = f"{cleaned[:room].rstrip('_')}_{digest}"
    return cleaned


def stable_asset_name(
    *,
    line_id: object,
    character_id: object,
    locale: object = "und",
    emotion: object = "neutral",
    emotion_intensity: float = 0.5,
    variation: int = 0,
    seed: int = 0,
    take_index: int = 0,
    text: object = "",
    engine_id: object = "",
    voice_profile: object = "",
    model_revision: object = "",
    input_hash: object = "",
    extension: str = "wav",
) -> str:
    """Build a readable stable name; all generation identity is in the digest."""

    normalized_extension = str(extension).lower().lstrip(".")
    if not _EXTENSION.fullmatch(normalized_extension):
        raise ValueError("extension must contain 1-8 lowercase letters or digits")
    if variation < 0 or take_index < 0:
        raise ValueError("variation and take_index must be non-negative")
    intensity = float(emotion_intensity)
    if not math.isfinite(intensity) or not 0.0 <= intensity <= 1.0:
        raise ValueError("emotion_intensity must be between 0 and 1")
    identity = {
        "line_id": str(line_id),
        "character_id": str(character_id),
        "locale": str(locale),
        "emotion": str(emotion),
        "emotion_intensity_hex": intensity.hex(),
        "variation": int(variation),
        "seed": int(seed),
        "take_index": int(take_index),
        "text": str(text),
        "engine_id": str(engine_id),
        "voice_profile": str(voice_profile),
        "model_revision": str(model_revision),
        "input_hash": str(input_hash),
    }
    digest = sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    stem = "__".join(
        [
            slug_component(line_id),
            slug_component(character_id),
            slug_component(locale, fallback="und", limit=16),
            slug_component(emotion, fallback="neutral", limit=20),
            f"v{variation:02d}",
            f"t{take_index:02d}",
            digest,
        ]
    )
    return f"{stem}.{normalized_extension}"
