from __future__ import annotations

import math
import re
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .models import MetricFeedback, ShadowingFeedback, SourceAudioKind


class ScoringError(ValueError):
    pass


@dataclass(slots=True)
class WaveFeatures:
    sample_rate: int
    duration_seconds: float
    rms: float
    active_ratio: float
    pauses: list[tuple[float, float]]
    f0_hz: list[float]
    pitch_frame_count: int


_PUNCTUATION = re.compile(r"[\s、。！？!?,，．・…「」『』（）()【】\[\]：:；;〜～]+")
_SMALL_KANA = set("ゃゅょぁぃぅぇぉャュョァィゥェォゎヮヵヶ")


def normalize_japanese_text(text: str) -> str:
    return _PUNCTUATION.sub("", unicodedata.normalize("NFKC", text)).lower()


def approximate_mora_count(text: str) -> int:
    return len(approximate_mora_segments(text))


def approximate_mora_segments(text: str) -> list[str]:
    normalized = normalize_japanese_text(text)
    segments: list[str] = []
    for character in normalized:
        if character in _SMALL_KANA and segments:
            segments[-1] += character
            continue
        if character.isascii() and character.isalnum():
            continue
        segments.append(character)
    return segments


def _alignment(expected: str, actual: str) -> tuple[int, list[str], list[str], list[str]]:
    if len(expected) > 2_000 or len(actual) > 2_000:
        raise ScoringError("文本过长，首版评分每次最多处理 2000 个规范化字符。")
    rows = len(expected) + 1
    columns = len(actual) + 1
    matrix = [[0] * columns for _ in range(rows)]
    for i in range(rows):
        matrix[i][0] = i
    for j in range(columns):
        matrix[0][j] = j
    for i in range(1, rows):
        for j in range(1, columns):
            substitution = matrix[i - 1][j - 1] + (expected[i - 1] != actual[j - 1])
            matrix[i][j] = min(matrix[i - 1][j] + 1, matrix[i][j - 1] + 1, substitution)

    missing: list[str] = []
    unexpected: list[str] = []
    substitutions: list[str] = []
    i, j = len(expected), len(actual)
    while i or j:
        if i and j and expected[i - 1] == actual[j - 1]:
            i -= 1
            j -= 1
        elif i and j and matrix[i][j] == matrix[i - 1][j - 1] + 1:
            substitutions.append(f"{expected[i - 1]}→{actual[j - 1]}")
            i -= 1
            j -= 1
        elif i and matrix[i][j] == matrix[i - 1][j] + 1:
            missing.append(expected[i - 1])
            i -= 1
        else:
            unexpected.append(actual[j - 1])
            j -= 1
    return matrix[-1][-1], list(reversed(missing)), list(reversed(unexpected)), list(reversed(substitutions))


def analyze_content(expected_text: str, actual_text: str, asr_confidence: float) -> MetricFeedback:
    expected = normalize_japanese_text(expected_text)
    actual = normalize_japanese_text(actual_text)
    if not expected:
        return MetricFeedback(
            metric="content",
            value=None,
            confidence=0.0,
            summary="没有参考文本，无法比较内容。",
            evidence={"expected": expected, "actual": actual},
            limitations=["内容指标依赖参考文本和 ASR 转写。"],
        )
    distance, missing, unexpected, substitutions = _alignment(expected, actual)
    value = max(0.0, 1.0 - distance / max(len(expected), len(actual), 1))
    confidence = max(0.05, min(0.95, asr_confidence * min(1.0, len(expected) / 8.0)))
    if not actual:
        summary = "ASR 没有得到可比较文本，请优先检查录音或重说。"
    elif distance == 0:
        summary = "规范化转写与参考文本一致。"
    else:
        summary = "检测到转写与参考文本不一致；请结合证据逐项复听。"
    return MetricFeedback(
        metric="content",
        value=round(value, 4),
        confidence=round(confidence, 4),
        summary=summary,
        evidence={
            "expected_normalized": expected,
            "actual_normalized": actual,
            "edit_distance": distance,
            "missing_characters": missing[:20],
            "unexpected_characters": unexpected[:20],
            "substitutions": substitutions[:20],
            "asr_confidence": round(max(0.0, min(1.0, asr_confidence)), 4),
        },
        limitations=[
            "这是字符级转写比较，不等同于音素或 mora 强制对齐。",
            "ASR 错误会直接影响内容结果，因此同时返回 ASR 置信度。",
        ],
    )


def analyze_mora_evidence(
    expected_text: str, actual_text: str, asr_confidence: float
) -> MetricFeedback:
    expected_segments = approximate_mora_segments(expected_text)
    actual_segments = approximate_mora_segments(actual_text)

    def markers(text: str) -> dict[str, int]:
        normalized = normalize_japanese_text(text)
        return {
            "long_vowel_mark": normalized.count("ー"),
            "sokuon": normalized.count("っ") + normalized.count("ッ"),
            "hatsuon": normalized.count("ん") + normalized.count("ン"),
        }

    return MetricFeedback(
        metric="mora",
        value=None,
        confidence=round(min(0.35, max(0.0, asr_confidence) * 0.4), 4),
        summary="已给出文本级 mora 近似证据；未做音素强制对齐，因此不生成 mora 分数。",
        evidence={
            "expected_segments_approx": expected_segments[:100],
            "actual_segments_approx": actual_segments[:100],
            "expected_count_approx": len(expected_segments),
            "actual_count_approx": len(actual_segments),
            "expected_markers": markers(expected_text),
            "actual_markers_from_asr": markers(actual_text),
            "asr_confidence": round(max(0.0, min(1.0, asr_confidence)), 4),
        },
        limitations=[
            "ASR 是否写出「っ」「ん」「ー」不能证明用户实际时值正确。",
            "汉字读音尚未通过 pyopenjtalk/Julius/MFA/JATTS 展开或强制对齐。",
            "接入并标定日语音素边界前，mora value 固定为 null。",
        ],
    )


def _decode_pcm(raw: bytes, sample_width: int) -> np.ndarray:
    if sample_width == 1:
        return (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    if sample_width == 2:
        return np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if sample_width == 3:
        values = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        integers = (
            values[:, 0].astype(np.int32)
            | (values[:, 1].astype(np.int32) << 8)
            | (values[:, 2].astype(np.int32) << 16)
        )
        integers = np.where(integers & 0x800000, integers - 0x1000000, integers)
        return integers.astype(np.float64) / float(1 << 23)
    if sample_width == 4:
        return np.frombuffer(raw, dtype="<i4").astype(np.float64) / float(1 << 31)
    raise ScoringError(f"不支持 {sample_width * 8}-bit PCM WAV。")


def _framed_rms(samples: np.ndarray, frame: int, hop: int) -> tuple[np.ndarray, np.ndarray]:
    if len(samples) < frame:
        padded = np.pad(samples, (0, frame - len(samples)))
        return np.array([math.sqrt(float(np.mean(padded * padded)) + 1e-12)]), np.array([0.0])
    starts = np.arange(0, len(samples) - frame + 1, hop)
    values = np.array(
        [math.sqrt(float(np.mean(samples[start : start + frame] ** 2)) + 1e-12) for start in starts]
    )
    return values, starts.astype(np.float64)


def _pause_ranges(active: np.ndarray, hop_seconds: float) -> list[tuple[float, float]]:
    pauses: list[tuple[float, float]] = []
    if not np.any(active):
        return pauses
    first = int(np.argmax(active))
    last = len(active) - int(np.argmax(active[::-1]))
    start: int | None = None
    for index in range(first, last):
        if not active[index] and start is None:
            start = index
        if active[index] and start is not None:
            if (index - start) * hop_seconds >= 0.12:
                pauses.append((round(start * hop_seconds, 3), round(index * hop_seconds, 3)))
            start = None
    if start is not None and (last - start) * hop_seconds >= 0.12:
        pauses.append((round(start * hop_seconds, 3), round(last * hop_seconds, 3)))
    return pauses


def _f0_contour(samples: np.ndarray, sample_rate: int, energy_threshold: float) -> tuple[list[float], int]:
    target_rate = 12_000
    step = max(1, round(sample_rate / target_rate))
    reduced = samples[::step]
    reduced_rate = sample_rate / step
    frame = max(64, round(reduced_rate * 0.04))
    hop = max(32, round(reduced_rate * 0.01))
    min_lag = max(1, round(reduced_rate / 400.0))
    max_lag = min(frame - 2, round(reduced_rate / 70.0))
    if len(reduced) < frame or min_lag >= max_lag:
        return [], 0
    values: list[float] = []
    frame_count = 0
    window = np.hanning(frame)
    for start in range(0, len(reduced) - frame + 1, hop):
        frame_count += 1
        chunk = reduced[start : start + frame]
        if math.sqrt(float(np.mean(chunk * chunk)) + 1e-12) < energy_threshold:
            continue
        chunk = (chunk - float(np.mean(chunk))) * window
        correlation = np.correlate(chunk, chunk, mode="full")[frame - 1 :]
        baseline = float(correlation[0])
        if baseline <= 1e-10:
            continue
        search = correlation[min_lag : max_lag + 1]
        lag = int(np.argmax(search)) + min_lag
        periodicity = float(correlation[lag] / baseline)
        if periodicity < 0.28:
            continue
        values.append(float(reduced_rate / lag))
    return values, frame_count


def extract_wave_features(path: str | Path, *, include_pitch: bool = True) -> WaveFeatures:
    audio_path = Path(path)
    if not audio_path.is_file():
        raise ScoringError(f"WAV 文件不存在：{audio_path}")
    try:
        with wave.open(str(audio_path), "rb") as wav:
            if wav.getcomptype() != "NONE":
                raise ScoringError("首版仅支持未压缩 PCM WAV。")
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frame_count = wav.getnframes()
            if channels < 1 or sample_rate < 8_000:
                raise ScoringError("WAV 声道数或采样率无效。")
            if frame_count / sample_rate > 300:
                raise ScoringError("单次口语评分录音不能超过 5 分钟。")
            samples = _decode_pcm(wav.readframes(frame_count), sample_width)
    except (wave.Error, EOFError) as exc:
        raise ScoringError("录音不是可读取的 PCM WAV。") from exc

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if not len(samples):
        raise ScoringError("录音没有音频帧。")
    samples = np.nan_to_num(samples.astype(np.float64), copy=False)
    duration = len(samples) / float(sample_rate)
    rms = math.sqrt(float(np.mean(samples * samples)) + 1e-12)
    frame = max(1, round(sample_rate * 0.02))
    hop = max(1, round(sample_rate * 0.01))
    envelope, _ = _framed_rms(samples, frame, hop)
    peak_rms = float(np.max(envelope))
    noise_candidate = float(np.percentile(envelope, 20)) * 2.5
    # A continuously voiced short exercise has no silent noise-floor frames.
    # Clamp the adaptive threshold below the signal peak so it is not mistaken
    # for all-silence, while still rejecting low-level background noise.
    threshold = max(1e-4, min(peak_rms * 0.35, max(peak_rms * 0.08, noise_candidate)))
    active = envelope >= threshold
    active_ratio = float(np.mean(active)) if len(active) else 0.0
    pauses = _pause_ranges(active, hop / sample_rate)
    f0_hz, pitch_frames = (
        _f0_contour(samples, sample_rate, max(1e-4, threshold * 0.65))
        if include_pitch else ([], 0)
    )
    return WaveFeatures(
        sample_rate=sample_rate,
        duration_seconds=duration,
        rms=rms,
        active_ratio=active_ratio,
        pauses=pauses,
        f0_hz=f0_hz,
        pitch_frame_count=pitch_frames,
    )


def compare_rhythm(
    reference: WaveFeatures,
    recording: WaveFeatures,
    expected_text: str,
    actual_text: str,
) -> MetricFeedback:
    duration_ratio = recording.duration_seconds / max(reference.duration_seconds, 1e-6)
    duration_score = math.exp(-1.35 * abs(math.log(max(duration_ratio, 1e-6))))
    activity_score = max(0.0, 1.0 - abs(recording.active_ratio - reference.active_ratio) / 0.6)
    pause_difference = abs(len(recording.pauses) - len(reference.pauses))
    pause_score = 1.0 / (1.0 + 0.45 * pause_difference)
    value = 0.55 * duration_score + 0.25 * activity_score + 0.20 * pause_score

    expected_segments = approximate_mora_segments(expected_text)
    actual_segments = approximate_mora_segments(actual_text)
    expected_mora = len(expected_segments)
    actual_mora = len(actual_segments)
    expected_rate = expected_mora / max(reference.duration_seconds, 1e-6)
    actual_rate = actual_mora / max(recording.duration_seconds, 1e-6)
    confidence = min(0.88, 0.45 + min(reference.duration_seconds, recording.duration_seconds) / 8.0)
    summary = (
        "录音时长和停顿结构接近参考。"
        if value >= 0.82
        else "录音与参考的时长、发声占比或停顿结构存在可听差异。"
    )
    return MetricFeedback(
        metric="rhythm",
        value=round(value, 4),
        confidence=round(confidence, 4),
        summary=summary,
        evidence={
            "reference_duration_seconds": round(reference.duration_seconds, 4),
            "recording_duration_seconds": round(recording.duration_seconds, 4),
            "duration_ratio": round(duration_ratio, 4),
            "reference_active_ratio": round(reference.active_ratio, 4),
            "recording_active_ratio": round(recording.active_ratio, 4),
            "reference_pauses": reference.pauses,
            "recording_pauses": recording.pauses,
            "expected_mora_approx": expected_mora,
            "actual_mora_approx": actual_mora,
            "expected_mora_segments_approx": expected_segments[:100],
            "actual_mora_segments_approx": actual_segments[:100],
            "reference_mora_per_second_approx": round(expected_rate, 4),
            "recording_mora_per_second_approx": round(actual_rate, 4),
        },
        limitations=[
            "停顿由能量阈值估计，噪声和麦克风增益会影响结果。",
            "mora 数是基于文本的近似值，尚未使用日语强制对齐器。",
        ],
    )


def _resample_contour(values: list[float], length: int = 64) -> np.ndarray:
    source = np.asarray(values, dtype=np.float64)
    if len(source) == 1:
        return np.repeat(source, length)
    positions = np.linspace(0.0, 1.0, len(source))
    targets = np.linspace(0.0, 1.0, length)
    return np.interp(targets, positions, source)


def compare_pitch(reference: WaveFeatures, recording: WaveFeatures) -> MetricFeedback:
    if len(reference.f0_hz) < 5 or len(recording.f0_hz) < 5:
        return MetricFeedback(
            metric="pitch",
            value=None,
            confidence=0.1,
            summary="有效有声音高帧不足，暂不判断音高重音。",
            evidence={
                "reference_voiced_frames": len(reference.f0_hz),
                "recording_voiced_frames": len(recording.f0_hz),
            },
            limitations=["首版使用轻量自相关 F0，清音、耳语和噪声中可能无法取值。"],
        )

    reference_log = np.log2(_resample_contour(reference.f0_hz))
    recording_log = np.log2(_resample_contour(recording.f0_hz))
    reference_shape = reference_log - float(np.median(reference_log))
    recording_shape = recording_log - float(np.median(recording_log))
    reference_std = float(np.std(reference_shape))
    recording_std = float(np.std(recording_shape))
    if reference_std < 1e-5 and recording_std < 1e-5:
        correlation = 1.0
    elif reference_std < 1e-5 or recording_std < 1e-5:
        correlation = 0.0
    else:
        correlation = float(np.corrcoef(reference_shape, recording_shape)[0, 1])
        if not math.isfinite(correlation):
            correlation = 0.0
    mae_cents = float(np.mean(np.abs(reference_shape - recording_shape)) * 1200.0)
    shape_score = math.exp(-mae_cents / 260.0)
    correlation_score = max(0.0, min(1.0, (correlation + 1.0) / 2.0))
    value = 0.6 * shape_score + 0.4 * correlation_score
    reference_median = float(np.median(reference.f0_hz))
    recording_median = float(np.median(recording.f0_hz))
    median_offset_cents = 1200.0 * math.log2(recording_median / reference_median)
    reference_coverage = len(reference.f0_hz) / max(reference.pitch_frame_count, 1)
    recording_coverage = len(recording.f0_hz) / max(recording.pitch_frame_count, 1)
    confidence = min(0.86, min(reference_coverage, recording_coverage) * 1.15)
    contour_indexes = np.linspace(0, len(reference_shape) - 1, 32).round().astype(int)
    reference_semitones = [round(float(reference_shape[index] * 12.0), 4) for index in contour_indexes]
    recording_semitones = [round(float(recording_shape[index] * 12.0), 4) for index in contour_indexes]
    return MetricFeedback(
        metric="pitch",
        value=round(value, 4),
        confidence=round(max(0.1, confidence), 4),
        summary=(
            "归一化 F0 走势与参考较接近。"
            if value >= 0.78
            else "归一化 F0 走势与参考存在差异，可重点复听重音核附近。"
        ),
        evidence={
            "reference_voiced_frames": len(reference.f0_hz),
            "recording_voiced_frames": len(recording.f0_hz),
            "reference_voiced_coverage": round(reference_coverage, 4),
            "recording_voiced_coverage": round(recording_coverage, 4),
            "normalized_shape_correlation": round(correlation, 4),
            "normalized_shape_mae_cents": round(mae_cents, 2),
            "reference_median_f0_hz": round(reference_median, 2),
            "recording_median_f0_hz": round(recording_median, 2),
            "median_register_offset_cents": round(median_offset_cents, 2),
            "normalized_time": [round(index / 31.0, 4) for index in range(32)],
            "normalized_reference_f0_semitones": reference_semitones,
            "normalized_recording_f0_semitones": recording_semitones,
        },
        limitations=[
            "此指标比较归一化 F0 走势，不把男女声或音域差异直接当作错误。",
            "尚未接入东京式音高词典、mora 边界或 PESTO/WORLD，因此不能视为绝对重音判定。",
        ],
    )


def analyze_shadowing(
    reference_audio_path: str | Path,
    original_recording_path: str | Path,
    expected_text: str,
    actual_transcript: str,
    asr_confidence: float,
    source_kind: SourceAudioKind = SourceAudioKind.ORIGINAL_UNCOLORED,
) -> ShadowingFeedback:
    if source_kind != SourceAudioKind.ORIGINAL_UNCOLORED:
        raise ScoringError("评分必须使用音色染色前的原始录音。")
    reference_path = Path(reference_audio_path).resolve()
    recording_path = Path(original_recording_path).resolve()
    reference = extract_wave_features(reference_path)
    recording = extract_wave_features(recording_path)
    if recording.rms < 0.001 or recording.active_ratio < 0.02:
        acoustic_evidence = {
            "recording_rms": round(recording.rms, 8),
            "recording_active_ratio": round(recording.active_ratio, 4),
            "minimum_rms": 0.001,
            "minimum_active_ratio": 0.02,
            "transcript_text_ignored_without_voice_evidence": bool(actual_transcript.strip()),
        }

        def no_voice(metric: str) -> MetricFeedback:
            return MetricFeedback(
                metric=metric,
                value=None,
                confidence=0.0,
                summary="原始录音缺少可检测语音证据，本项不评分，请检查麦克风并重录。",
                evidence=dict(acoustic_evidence),
                limitations=[
                    "transcript_hint 或旁车文本不能替代声学语音证据。",
                    "低于能量/活动帧门槛时不推断内容、mora、节奏或 F0。",
                ],
            )

        return ShadowingFeedback(
            content=no_voice("content"),
            mora=no_voice("mora"),
            rhythm=no_voice("rhythm"),
            pitch=no_voice("pitch"),
            priorities=["原始录音没有可检测语音；请检查麦克风输入并完整重录。"],
            scoring_source_path=str(recording_path),
            scoring_source_kind=source_kind,
            reference_audio_path=str(reference_path),
        )
    content = analyze_content(expected_text, actual_transcript, asr_confidence)
    mora = analyze_mora_evidence(expected_text, actual_transcript, asr_confidence)
    rhythm = compare_rhythm(reference, recording, expected_text, actual_transcript)
    pitch = compare_pitch(reference, recording)

    messages = {
        "content": "先修正漏词、错词或助词，再立即重说同一句。",
        "rhythm": "下一遍先贴近参考的句长和自然停顿，不要只做整体加速。",
        "pitch": "下一遍重点模仿 F0 上下行走势；当前证据不足时先改善录音清晰度。",
    }
    ranked = sorted(
        (content, rhythm, pitch),
        key=lambda item: -1.0 if item.value is None else item.value,
    )
    priorities = [messages[item.metric] for item in ranked if item.value is None or item.value < 0.88][:2]
    if not priorities:
        priorities = ["三项初步指标均接近参考；下一遍保持自然表达并人工复听细节。"]
    return ShadowingFeedback(
        content=content,
        mora=mora,
        rhythm=rhythm,
        pitch=pitch,
        priorities=priorities,
        scoring_source_path=str(recording_path),
        scoring_source_kind=source_kind,
        reference_audio_path=str(reference_path),
    )
