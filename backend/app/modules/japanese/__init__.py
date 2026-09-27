"""Japanese learning MVP for Local AI Voice Studio.

The module is intentionally self-contained.  The core backend can mount it with
``build_japanese_router`` without importing any heavyweight ASR or TTS package.
"""

from .router import build_japanese_router, create_router
from .service import JapaneseLearningService, build_default_service

__all__ = [
    "JapaneseLearningService",
    "build_default_service",
    "build_japanese_router",
    "create_router",
]
