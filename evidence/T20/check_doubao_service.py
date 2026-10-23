import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation"))

from boss_transcription import DoubaoTranscriptionProvider, MAX_AUDIO_BYTES, normalize_recording

SAMPLE_URL = "https://las-ai-cn-beijing-online.tos-cn-beijing.volces.com/operator_cards_serving/public/online/las_asr/badaling.wav"
SOURCE_URL = "https://docs.volcengine.com/docs/LakeAIService/SpeechtotextautomaticspeechrecognitionDoubao-recordingfilerecognitionenhancedversion?lang=en"


async def main(args):
    directory = ROOT / ".work" / "w2-checks" / "stt"
    directory.mkdir(parents=True, exist_ok=True)
    sample = directory / "badaling.wav"
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        async with client.stream("GET", SAMPLE_URL) as response:
            response.raise_for_status()
            audio = bytearray()
            async for chunk in response.aiter_bytes():
                audio.extend(chunk)
                if len(audio) > MAX_AUDIO_BYTES:
                    raise ValueError("官方语音样本超过客户端大小限制")
    sample.write_bytes(audio)
    _, duration_ms, source_sha256 = await normalize_recording(sample)
    report = {
        "task_id": "T20", "sample_kind": "OFFICIAL_PUBLIC_SPEECH",
        "source_url": SOURCE_URL, "sample_url": SAMPLE_URL,
        "authorization": "用户委托选择真实公开样本验证 Doubao STT",
        "source_sha256": source_sha256, "sample_bytes": len(audio),
        "local_duration_ms": duration_ms, "status": "LOCAL_AUDIO_VALIDATED",
        "private_recording_used": False, "full_A20_accepted": False,
        "source_code_sha256": hashlib.sha256((ROOT / "validation" / "boss_transcription.py").read_bytes()).hexdigest(),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if args.local_only:
        print(json.dumps(report, ensure_ascii=False))
        return
    def record_observation(observation):
        report.update(observation)
        report["status"] = "RESPONSE_RECEIVED" if (
            observation["http_status"] == 200 and observation["provider_status"] == "20000000"
        ) else "SERVICE_REJECTED"
        report["cost_total"] = None
        report["cost_coverage"] = "PRICE_AND_FAILURE_USAGE_NOT_VERIFIED"
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    provider = DoubaoTranscriptionProvider(
        credential_file=args.credential_file, observation_sink=record_observation,
    )
    result = await provider.transcribe_result(sample)
    metadata = asdict(result)
    text = metadata.pop("text")
    report.update(metadata)
    report.update({
        "status": "PASS_SERVICE_TRANSCRIPTION", "response_text_nonempty": bool(text.strip()),
        "response_text_length": len(text),
        "response_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "transcript_body_recorded": False, "business_command_submitted": False,
        "ground_truth_accuracy_evaluated": False,
    })
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


parser = argparse.ArgumentParser()
parser.add_argument("--credential-file", type=Path, required=True)
parser.add_argument("--report", type=Path, required=True)
parser.add_argument("--local-only", action="store_true")
asyncio.run(main(parser.parse_args()))
