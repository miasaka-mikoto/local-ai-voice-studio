from __future__ import annotations

import os
import shutil
import subprocess
import wave
from pathlib import Path


class AudioNormalizationError(ValueError):
    pass


SUPPORTED_UPLOAD_TYPES = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "application/octet-stream": ".bin",
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
}


def resolve_ffmpeg() -> Path | None:
    configured = os.getenv("VOICE_STUDIO_FFMPEG")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))

    studio_root = Path(__file__).resolve().parents[4]
    candidates.append(studio_root / "tools" / "ffmpeg" / "ffmpeg.exe")
    on_path = shutil.which("ffmpeg")
    if on_path:
        candidates.append(Path(on_path))
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file():
            return resolved
    return None


def _inspect_pcm_wav(path: Path) -> tuple[int, int, int, int] | None:
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getcomptype() != "NONE":
                return None
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frame_count = wav.getnframes()
            expected_bytes = frame_count * channels * sample_width
            actual_bytes = len(wav.readframes(frame_count))
            if actual_bytes != expected_bytes:
                raise AudioNormalizationError(
                    f"PCM WAV 数据截断：声明 {expected_bytes} 字节，实际 {actual_bytes} 字节。"
                )
            return channels, sample_width, sample_rate, frame_count
    except (wave.Error, EOFError):
        return None


def _is_target_pcm_wav(path: Path) -> bool:
    metadata = _inspect_pcm_wav(path)
    if metadata is None:
        return False
    channels, sample_width, sample_rate, frame_count = metadata
    return (
        channels == 1
        and sample_rate == 48_000
        and sample_width == 3
        and 0 < frame_count <= 48_000 * 300
    )


def _validate_pcm_wav(path: Path) -> None:
    metadata = _inspect_pcm_wav(path)
    if metadata is None:
        raise AudioNormalizationError("规范化结果不是有效的未压缩 PCM WAV。")
    channels, sample_width, sample_rate, frame_count = metadata
    if frame_count == 0:
        raise AudioNormalizationError("规范化结果没有音频帧。")
    if channels != 1 or sample_rate != 48_000 or sample_width != 3:
        raise AudioNormalizationError("规范化结果必须是 48 kHz 单声道 PCM-24 WAV。")
    if frame_count > 48_000 * 300:
        raise AudioNormalizationError("单次口语录音不能超过 5 分钟。")


def validate_reference_audio(path: str | Path) -> tuple[int, int, int, int]:
    """Validate a playable PCM WAV reference without buffering the full file."""

    source = Path(path)
    try:
        if source.stat().st_size > 100 * 1024 * 1024:
            raise AudioNormalizationError("参考音频不能超过 100 MB。")
        with wave.open(str(source), "rb") as wav:
            if wav.getcomptype() != "NONE":
                raise AudioNormalizationError("参考音频必须是未压缩 PCM WAV。")
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frame_count = wav.getnframes()
            if channels not in (1, 2) or sample_width not in (1, 2, 3, 4):
                raise AudioNormalizationError("参考音频声道数或采样位深不受支持。")
            if not 8_000 <= sample_rate <= 192_000 or not 0 < frame_count <= sample_rate * 300:
                raise AudioNormalizationError("参考音频采样率或时长不受支持。")
            frame_bytes = channels * sample_width
            expected_bytes = frame_count * frame_bytes
            actual_bytes = 0
            while actual_bytes < expected_bytes:
                remaining_frames = (expected_bytes - actual_bytes + frame_bytes - 1) // frame_bytes
                chunk = wav.readframes(min(4096, remaining_frames))
                if not chunk:
                    break
                actual_bytes += len(chunk)
            if actual_bytes != expected_bytes:
                raise AudioNormalizationError("参考音频 PCM 数据截断，请重新生成或选择完整文件。")
            return channels, sample_width, sample_rate, frame_count
    except (OSError, wave.Error, EOFError) as exc:
        raise AudioNormalizationError("参考音频不是可读取的 PCM WAV。") from exc


def normalize_browser_audio(
    content: bytes,
    content_type: str,
    output_path: str | Path,
) -> Path:
    """Normalize a browser recording to 48 kHz mono PCM-24.

    The conversion is local, bounded, shell-free, and never starts an AI model.
    """

    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type not in SUPPORTED_UPLOAD_TYPES:
        raise AudioNormalizationError(f"不支持的录音媒体类型：{normalized_type or 'unknown'}")
    if not content:
        raise AudioNormalizationError("录音内容为空。")
    if len(content) > 20 * 1024 * 1024:
        raise AudioNormalizationError("单个录音不能超过 20 MB。")

    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    extension = SUPPORTED_UPLOAD_TYPES[normalized_type]
    source = output.with_name(output.stem + ".upload" + extension)
    temporary_output = output.with_name(output.stem + ".normalized.wav")
    source.write_bytes(content)
    try:
        if _is_target_pcm_wav(source):
            source.replace(output)
            return output

        ffmpeg = resolve_ffmpeg()
        if ffmpeg is None:
            raise AudioNormalizationError(
                "浏览器录音需要本地 FFmpeg 转为 PCM WAV；请设置 VOICE_STUDIO_FFMPEG。"
            )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        command = [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-t",
            "301",
            "-map_metadata",
            "-1",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s24le",
            str(temporary_output),
        ]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
                creationflags=creationflags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AudioNormalizationError("本地 FFmpeg 未能完成录音规范化。") from exc
        if completed.returncode != 0 or not temporary_output.is_file():
            raise AudioNormalizationError("浏览器录音无法解码；原始 FFmpeg 输出未写入日志。")
        _validate_pcm_wav(temporary_output)
        temporary_output.replace(output)
        return output
    finally:
        source.unlink(missing_ok=True)
        temporary_output.unlink(missing_ok=True)
