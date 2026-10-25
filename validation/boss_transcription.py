import asyncio
import base64
import hashlib
import io
import re
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx
from markdown_it import MarkdownIt
from pydantic import BaseModel, Field

ENDPOINT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
RESOURCE_ID = "volc.bigasr.auc_turbo"
MAX_AUDIO_BYTES = 3_000_000
MAX_DURATION_SECONDS = 60


def load_doubao_api_key(credential_file: Path) -> str:
    candidates = []
    for token in MarkdownIt().parse(credential_file.read_text()):
        for child in token.children or []:
            if child.type in {"text", "code_inline"} and re.search(
                r"doubao|豆包|火山|\bstt\b|\basr\b", child.content, re.IGNORECASE,
            ):
                candidates.extend(re.findall(r"\b[A-Za-z0-9_-]{20,}\b", child.content))
    if len(candidates) != 1:
        raise ValueError("Doubao 凭据引用必须包含唯一的服务凭据")
    return candidates[0]


async def normalize_recording(file_path: Path) -> tuple[bytes, int, str]:
    if not file_path.is_file():
        raise ValueError("录音文件不存在")
    size = file_path.stat().st_size
    if size == 0 or size > MAX_AUDIO_BYTES:
        raise ValueError("录音大小必须介于1字节与3000000字节之间")
    audio = file_path.read_bytes()
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("录音读取后的大小超出限制")
    # FFmpeg 解码和重采样处理容器，限制输出长度后核查完整业务时长。
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "pipe",
        "-i", "pipe:0", "-vn",
        "-ac", "1", "-ar", "16000", "-t", "61", "-f", "s16le", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(15):
            pcm, _ = await process.communicate(audio)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode != 0 or not pcm:
        raise ValueError("FFmpeg 无法解码有效录音")
    if len(pcm) > MAX_DURATION_SECONDS * 16_000 * 2:
        raise ValueError("录音时长超出60秒限制")
    duration_ms = (len(pcm) * 1000 + 31_999) // 32_000
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(pcm)
    return buffer.getvalue(), duration_ms, hashlib.sha256(audio).hexdigest()


class RecognitionBody(BaseModel):
    class Result(BaseModel):
        text: str = Field(min_length=1)

    class AudioInfo(BaseModel):
        duration: int = Field(gt=0)

    result: Result
    audio_info: AudioInfo


@dataclass(frozen=True)
class TranscriptionResult:
    text: str = field(repr=False)
    request_id: str
    provider_log_id: str
    source_sha256: str
    local_duration_ms: int
    provider_duration_ms: int
    elapsed_ms: int
    provider: str = "doubao"
    resource_id: str = RESOURCE_ID
    cost_total: str | None = None
    cost_coverage: str = "PRICE_NOT_VERIFIED"


class DoubaoTranscriptionProvider:
    def __init__(
        self, api_key: str | None = None, api_base: str | None = None,
        language: str | None = None, model: str | None = None,
        *, credential_file: Path | None = None,
        observation_sink: Callable[[dict], None] | None = None,
    ):
        if api_base not in {None, "", ENDPOINT}:
            raise ValueError("Doubao 转写只允许已核查的官方服务地址")
        if model not in {None, "", "bigmodel"}:
            raise ValueError("Doubao 转写模型必须为 bigmodel")
        if (api_key is None) == (credential_file is None):
            raise ValueError("必须提供唯一的服务端凭据引用")
        self._api_key = load_doubao_api_key(credential_file) if credential_file else api_key
        if not self._api_key or not self._api_key.isascii() or any(
            character.isspace() for character in self._api_key
        ):
            raise ValueError("Doubao 服务端凭据格式无效")
        self.language = language
        self._observation_sink = observation_sink

    async def transcribe_result(self, file_path: str | Path) -> TranscriptionResult:
        audio, duration_ms, source_sha256 = await normalize_recording(Path(file_path))
        request_id = str(uuid.uuid4())
        audio_input = {"data": base64.b64encode(audio).decode("ascii"), "format": "wav"}
        if self.language:
            audio_input["language"] = self.language
        started = time.monotonic()
        async with asyncio.timeout(90), httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
            response = await client.post(ENDPOINT, headers={
                "X-Api-Key": self._api_key, "X-Api-Resource-Id": RESOURCE_ID,
                "X-Api-Request-Id": request_id, "X-Api-Sequence": "-1",
            }, json={
                "user": {"uid": "boss-1"}, "audio": audio_input,
                "request": {"model_name": "bigmodel", "enable_itn": True,
                            "enable_punc": True, "enable_ddc": False},
            })
            status = response.headers.get("X-Api-Status-Code")
            log_id = response.headers.get("X-Tt-Logid", "")
            if self._observation_sink:
                self._observation_sink({
                    "request_id": request_id, "http_status": response.status_code,
                    "provider_status": status, "provider_log_id": log_id,
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "source_sha256": source_sha256, "local_duration_ms": duration_ms,
                })
            response.raise_for_status()
            if status != "20000000":
                raise RuntimeError("Doubao 转写失败，状态=" + str(status) + "，log_id=" + log_id)
            body = RecognitionBody.model_validate(response.json())
        if not body.result.text.strip():
            raise ValueError("Doubao 未返回有效转写文字")
        return TranscriptionResult(
            text=body.result.text, request_id=request_id, provider_log_id=log_id,
            source_sha256=source_sha256, local_duration_ms=duration_ms,
            provider_duration_ms=body.audio_info.duration,
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )

    async def transcribe(self, file_path: str | Path) -> str:
        return (await self.transcribe_result(file_path)).text
