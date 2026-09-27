from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from .models import SentenceRepair, SynthesisResult, TeacherResult, TranscriptResult


class AdapterError(RuntimeError):
    """Recoverable error from an external ASR, teacher, or TTS adapter."""


class ASRAdapter(Protocol):
    def transcribe(self, audio_path: Path, transcript_hint: str | None = None) -> TranscriptResult:
        ...


class TeacherAdapter(Protocol):
    def teach(self, payload: dict[str, Any]) -> TeacherResult:
        ...


class TTSAdapter(Protocol):
    def synthesize(self, text: str, output_path: Path, voice_role: str) -> SynthesisResult:
        ...


@dataclass(slots=True)
class AdapterBundle:
    asr: ASRAdapter
    teacher: TeacherAdapter
    tts: TTSAdapter


class MockASRAdapter:
    """Deterministic ASR fallback.

    Browser/client tests pass ``transcript_hint``.  A ``.txt`` sidecar with the
    same stem is also accepted, which makes offline fixtures convenient without
    pretending that mock ASR decoded speech from waveform samples.
    """

    provider = "mock-asr/1"

    def transcribe(self, audio_path: Path, transcript_hint: str | None = None) -> TranscriptResult:
        if not audio_path.is_file():
            raise AdapterError(f"录音文件不存在：{audio_path}")
        sidecar = audio_path.with_suffix(".txt")
        if transcript_hint and transcript_hint.strip():
            text = transcript_hint.strip()
            evidence = ["转写来自客户端提供的 mock transcript_hint，未运行语音模型。"]
            confidence = 0.65
        elif sidecar.is_file():
            text = sidecar.read_text(encoding="utf-8").strip()
            evidence = [f"转写来自离线测试旁车文本：{sidecar.name}，未运行语音模型。"]
            confidence = 0.6
        else:
            text = ""
            evidence = ["没有 transcript_hint 或旁车文本；mock ASR 无法从波形推断内容。"]
            confidence = 0.0
        return TranscriptResult(
            text=text,
            confidence=confidence,
            provider=self.provider,
            evidence=evidence,
        )


class SubprocessASRAdapter:
    """Run an explicitly configured local ASR command without a shell.

    The command is a JSON string array and may contain ``{input}`` and
    ``{output}`` placeholders.  The output must be JSON or JSONL compatible
    with ``workers/transcribe_japanese.py``.
    """

    def __init__(self, command: Sequence[str], timeout_seconds: int = 180) -> None:
        if not command:
            raise ValueError("ASR 命令不能为空")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def transcribe(self, audio_path: Path, transcript_hint: str | None = None) -> TranscriptResult:
        del transcript_hint
        if not audio_path.is_file():
            raise AdapterError(f"录音文件不存在：{audio_path}")
        with tempfile.TemporaryDirectory(prefix="voice-studio-asr-") as tmp:
            output = Path(tmp) / "transcript.jsonl"
            command = [
                token.replace("{input}", str(audio_path)).replace("{output}", str(output))
                for token in self.command
            ]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                    creationflags=creationflags,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise AdapterError("本地 ASR 进程未能完成；已切换后备适配器。") from exc
            if completed.returncode != 0 or not output.is_file():
                raise AdapterError("本地 ASR 返回失败；详细输出未写入日志以避免泄露路径或内容。")
            lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
            if not lines:
                raise AdapterError("本地 ASR 没有返回转写结果。")
            try:
                result = json.loads(lines[0])
            except json.JSONDecodeError as exc:
                raise AdapterError("本地 ASR 输出不是有效 JSON。") from exc
            try:
                confidence = float(result.get("language_probability", 0.5))
                segments = list(result.get("segments", []))
            except (TypeError, ValueError) as exc:
                raise AdapterError("本地 ASR JSON 字段类型无效。") from exc
            return TranscriptResult(
                text=str(result.get("text", "")).strip(),
                confidence=max(0.0, min(1.0, confidence)),
                provider="local-subprocess-asr",
                segments=segments,
                evidence=["转写由显式配置的本地 ASR 子进程生成。"],
            )


class MockTeacherAdapter:
    provider = "mock-teacher/1"

    _RULES = (
        ("日本語勉強します", "日本語を勉強します", "补充宾语助词「を」。"),
        ("日本語を好き", "日本語が好き", "「好き」的对象通常使用助词「が」。"),
        ("学生だです", "学生です", "避免同时使用「だ」和「です」。"),
        ("昨日学校に行きます", "昨日学校に行きました", "过去时间「昨日」需要过去式。"),
    )

    def _repair(self, original: str) -> SentenceRepair:
        minimal = original.strip()
        issues: list[str] = []
        for before, after, issue in self._RULES:
            if before in minimal:
                minimal = minimal.replace(before, after)
                issues.append(issue)
        natural = minimal
        if minimal and not minimal.endswith(("。", "！", "？", ".", "!", "?")):
            natural = minimal + "。"
        evidence = (
            ["命中本地 mock 教师的显式语法规则。"]
            if issues
            else ["未命中本地 mock 规则；此结果不代表句子已通过完整语法审校。"]
        )
        return SentenceRepair(
            original=original,
            minimal_correction=minimal,
            natural_expression=natural,
            model_answer=natural,
            issues=issues,
            confidence=0.72 if issues else 0.25,
            evidence=evidence,
        )

    def teach(self, payload: dict[str, Any]) -> TeacherResult:
        transcript = str(payload.get("transcript", "")).strip()
        repair = self._repair(transcript)
        scenario = str(payload.get("scenario", "日常会话"))
        if not transcript:
            reply = "もう一度、ゆっくり話してみましょう。"
            feedback = ["没有可用转写；请重录并确认麦克风输入。"]
            confidence = 0.9
        else:
            reply = (
                "はい、承知しました。では、続けてください。"
                if payload.get("task") == "project_role_play_turn"
                else f"いいですね。{scenario}の場面でもう一度言ってみましょう。"
            )
            feedback = repair.issues or ["mock 教师仅确认收到内容，未作完整自然度判断。"]
            confidence = repair.confidence
        return TeacherResult(
            reply_text=reply,
            demonstration_text=repair.natural_expression or reply,
            feedback=feedback,
            repair=repair,
            provider=self.provider,
            confidence=confidence,
        )


class OpenAICompatibleTeacherAdapter:
    """Minimal OpenAI-compatible teacher client using only the standard library."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: int = 45) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("教师接口地址必须是有效的 http/https URL")
        if not api_key or not model:
            raise ValueError("教师接口需要从环境变量提供密钥和模型名")
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def teach(self, payload: dict[str, Any]) -> TeacherResult:
        system = (
            "你是日语口语教师。只返回 JSON：reply_text、demonstration_text、feedback（最多两项）、"
            "repair（original、minimal_correction、natural_expression、model_answer、issues、confidence、evidence）。"
            "每项判断要承认不确定性，不给伪精确总分。"
        )
        if payload.get("task") == "project_role_play_turn":
            system += (
                "当前是项目台词角色扮演。先以场景中的对话对象身份自然回复用户，再给出最多两项具体纠错；"
                "目标台词与来源场景在用户 JSON 中，不能把目标台词匹配视作发音已被准确测量。"
            )
        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read()
            outer = json.loads(response_body)
            content = outer["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (
            urllib.error.URLError,
            TimeoutError,
            KeyError,
            IndexError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            raise AdapterError("教师接口调用失败或返回格式无效；密钥和原始响应均未记录。") from exc

        try:
            if not isinstance(parsed, dict):
                raise TypeError("teacher payload must be an object")
            repair_data = parsed.get("repair") or {}
            if not isinstance(repair_data, dict):
                raise TypeError("repair must be an object")
            issues_raw = repair_data.get("issues", [])
            evidence_raw = repair_data.get("evidence", [])
            feedback_raw = parsed.get("feedback", [])
            if not all(isinstance(value, list) for value in (issues_raw, evidence_raw, feedback_raw)):
                raise TypeError("teacher list fields must be arrays")
            repair = SentenceRepair(
                original=str(repair_data.get("original", payload.get("transcript", ""))),
                minimal_correction=str(repair_data.get("minimal_correction", payload.get("transcript", ""))),
                natural_expression=str(repair_data.get("natural_expression", payload.get("transcript", ""))),
                model_answer=str(repair_data.get("model_answer", parsed.get("demonstration_text", ""))),
                issues=[str(item) for item in issues_raw][:2],
                confidence=max(0.0, min(1.0, float(repair_data.get("confidence", 0.5)))),
                evidence=[str(item) for item in evidence_raw],
            )
        except (TypeError, ValueError) as exc:
            raise AdapterError("教师接口 JSON 字段类型无效；原始响应未写入日志。") from exc
        return TeacherResult(
            reply_text=str(parsed.get("reply_text", "")),
            demonstration_text=str(parsed.get("demonstration_text", repair.natural_expression)),
            feedback=[str(item) for item in feedback_raw][:2],
            repair=repair,
            provider=f"openai-compatible:{self.model}",
            confidence=repair.confidence,
        )


class MockTTSAdapter:
    """Create a small valid 48 kHz PCM-24 WAV without loading a model."""

    provider = "mock-tts/1"

    @staticmethod
    def _pcm24(sample: float) -> bytes:
        integer = max(-(1 << 23), min((1 << 23) - 1, round(sample * ((1 << 23) - 1))))
        if integer < 0:
            integer += 1 << 24
        return struct.pack("<I", integer)[:3]

    def synthesize(self, text: str, output_path: Path, voice_role: str) -> SynthesisResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 48_000
        duration = min(4.0, max(0.45, len(text.strip()) * 0.075))
        base_frequency = 220.0 if voice_role == "standard_tokyo" else 196.0
        frames = bytearray()
        for index in range(int(sample_rate * duration)):
            attack = min(1.0, index / (sample_rate * 0.02))
            remaining = int(sample_rate * duration) - index
            release = min(1.0, remaining / (sample_rate * 0.03))
            sample = 0.08 * attack * release * math.sin(2.0 * math.pi * base_frequency * index / sample_rate)
            frames.extend(self._pcm24(sample))
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(3)
            wav.setframerate(sample_rate)
            wav.writeframes(frames)
        return SynthesisResult(
            audio_path=str(output_path),
            provider=self.provider,
            voice_role=voice_role,
            sample_rate=sample_rate,
            subtype="PCM_24",
        )


class SubprocessTTSAdapter:
    def __init__(self, command: Sequence[str], timeout_seconds: int = 180) -> None:
        if not command:
            raise ValueError("TTS 命令不能为空")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def synthesize(self, text: str, output_path: Path, voice_role: str) -> SynthesisResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            token.replace("{text}", text)
            .replace("{output}", str(output_path))
            .replace("{voice_role}", voice_role)
            for token in self.command
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                creationflags=creationflags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdapterError("本地 TTS 进程未能完成；已切换后备适配器。") from exc
        if completed.returncode != 0 or not output_path.is_file():
            raise AdapterError("本地 TTS 返回失败；详细输出未写入日志。")
        with wave.open(str(output_path), "rb") as wav:
            sample_rate = wav.getframerate()
            subtype = f"PCM_{wav.getsampwidth() * 8}"
        return SynthesisResult(
            audio_path=str(output_path),
            provider="local-subprocess-tts",
            voice_role=voice_role,
            sample_rate=sample_rate,
            subtype=subtype,
        )


class FallbackASRAdapter:
    def __init__(self, primary: ASRAdapter | None, fallback: ASRAdapter) -> None:
        self.primary = primary
        self.fallback = fallback

    def transcribe(self, audio_path: Path, transcript_hint: str | None = None) -> TranscriptResult:
        if self.primary is not None:
            try:
                return self.primary.transcribe(audio_path, transcript_hint)
            except AdapterError:
                pass
        result = self.fallback.transcribe(audio_path, transcript_hint)
        result.fallback_used = self.primary is not None
        return result


class FallbackTeacherAdapter:
    def __init__(self, primary: TeacherAdapter | None, fallback: TeacherAdapter) -> None:
        self.primary = primary
        self.fallback = fallback

    def teach(self, payload: dict[str, Any]) -> TeacherResult:
        if self.primary is not None:
            try:
                return self.primary.teach(payload)
            except AdapterError:
                pass
        result = self.fallback.teach(payload)
        result.fallback_used = self.primary is not None
        return result


class FallbackTTSAdapter:
    def __init__(self, primary: TTSAdapter | None, fallback: TTSAdapter) -> None:
        self.primary = primary
        self.fallback = fallback

    def synthesize(self, text: str, output_path: Path, voice_role: str) -> SynthesisResult:
        if self.primary is not None:
            try:
                return self.primary.synthesize(text, output_path, voice_role)
            except AdapterError:
                pass
        result = self.fallback.synthesize(text, output_path, voice_role)
        result.fallback_used = self.primary is not None
        return result


def _command_from_environment(name: str) -> list[str] | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        command = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} 必须是 JSON 字符串数组") from exc
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise ValueError(f"{name} 必须是非空 JSON 字符串数组")
    return command


def build_adapters_from_environment() -> AdapterBundle:
    asr_command = _command_from_environment("VOICE_STUDIO_JP_ASR_COMMAND_JSON")
    tts_command = _command_from_environment("VOICE_STUDIO_JP_TTS_COMMAND_JSON")

    teacher_primary: TeacherAdapter | None = None
    teacher_base_url = os.getenv("VOICE_STUDIO_TEACHER_BASE_URL")
    teacher_api_key = os.getenv("VOICE_STUDIO_TEACHER_API_KEY")
    teacher_model = os.getenv("VOICE_STUDIO_TEACHER_MODEL")
    if teacher_base_url and teacher_api_key and teacher_model:
        teacher_primary = OpenAICompatibleTeacherAdapter(
            base_url=teacher_base_url,
            api_key=teacher_api_key,
            model=teacher_model,
        )

    return AdapterBundle(
        asr=FallbackASRAdapter(
            SubprocessASRAdapter(asr_command) if asr_command else None,
            MockASRAdapter(),
        ),
        teacher=FallbackTeacherAdapter(teacher_primary, MockTeacherAdapter()),
        tts=FallbackTTSAdapter(
            SubprocessTTSAdapter(tts_command) if tts_command else None,
            MockTTSAdapter(),
        ),
    )
