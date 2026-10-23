import asyncio
import hashlib
import io
import os
import subprocess
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_transcription import DoubaoTranscriptionProvider, load_doubao_api_key, normalize_recording


def test_missing_recording_is_rejected_before_network():
    with pytest.raises(ValueError, match="录音文件不存在"):
        asyncio.run(normalize_recording(ROOT / "missing-approved-recording.wav"))


def test_existing_markdown_is_rejected_by_real_decoder():
    with pytest.raises(ValueError, match="无法解码有效录音"):
        asyncio.run(normalize_recording(ROOT / "docs" / "development" / "T20.md"))


def test_missing_credential_reference_fails_immediately():
    with pytest.raises(ValueError, match="唯一的服务端凭据引用"):
        DoubaoTranscriptionProvider()


@pytest.mark.skipif(not os.environ.get("BOSS_APPROVED_RECORDING"), reason="需要获准真实语音样本")
@pytest.mark.parametrize("container", ["original", "webm", "m4a"])
def test_real_recording_and_browser_containers_normalize_to_valid_wav(tmp_path, container):
    source = Path(os.environ["BOSS_APPROVED_RECORDING"])
    if container != "original":
        destination = tmp_path / ("approved-speech." + container)
        subprocess.run([
            "ffmpeg", "-v", "error", "-nostdin", "-i", str(source),
            "-c:a", "libopus" if container == "webm" else "aac", str(destination),
        ], check=True, capture_output=True, timeout=15)
        source = destination
    data, duration_ms, source_sha256 = asyncio.run(normalize_recording(source))
    assert 0 < duration_ms <= 60_000
    assert source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    with wave.open(io.BytesIO(data), "rb") as recording:
        assert recording.getnchannels() == 1
        assert recording.getsampwidth() == 2
        assert recording.getframerate() == 16_000
        assert recording.getnframes() > 0


@pytest.mark.skipif(not os.environ.get("BOSS_CREDENTIAL_FILE"), reason="需要用户提供的本地凭据引用")
def test_real_doubao_credential_reference_stays_private():
    key = load_doubao_api_key(Path(os.environ["BOSS_CREDENTIAL_FILE"]))
    provider = DoubaoTranscriptionProvider(credential_file=Path(os.environ["BOSS_CREDENTIAL_FILE"]))
    assert bool(key) and key not in repr(provider)


@pytest.mark.skipif(
    os.environ.get("BOSS_RUN_LIVE") != "1" or not os.environ.get("BOSS_APPROVED_RECORDING"),
    reason="需要明确启用真实服务并提供获准录音路径",
)
def test_live_approved_recording_transcription():
    provider = DoubaoTranscriptionProvider(credential_file=Path(os.environ["BOSS_CREDENTIAL_FILE"]))
    result = asyncio.run(provider.transcribe_result(Path(os.environ["BOSS_APPROVED_RECORDING"])))
    assert result.text.strip()
    assert result.local_duration_ms <= 60_000
    assert result.provider_duration_ms > 0
    assert result.request_id and result.provider_log_id
    assert result.cost_total is None
    assert result.text not in repr(result)
