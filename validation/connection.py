import hashlib
import json
import os
import re
import uuid
from pathlib import Path

import httpx
from markdown_it import MarkdownIt
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name
from openai import AsyncOpenAI
from openai.resources.chat.completions import AsyncCompletions

from business import ROOT, checksum, now


class RecordedStream:
    def __init__(self, stream, recorder):
        self.stream, self.recorder = stream, recorder
        self.model_request_id = stream.response.request.extensions["boss_model_request_id"]

    async def __aiter__(self):
        first = True
        try:
            async for chunk in self.stream:
                finished = any(choice.finish_reason is not None for choice in chunk.choices)
                if first or chunk.usage is not None or finished:
                    self.recorder.record({"at": now(), "type": "stream_metadata", "model_request_id": self.model_request_id, "response_id": chunk.id, "model": chunk.model, "created": chunk.created, "usage": chunk.usage.model_dump(mode="json") if chunk.usage else None, "finish_reasons": [choice.finish_reason for choice in chunk.choices if choice.finish_reason is not None]})
                    first = False
                yield chunk
        finally:
            await self.stream.close()

    async def close(self):
        await self.stream.close()


class RecordedCompletions(AsyncCompletions):
    def __init__(self, client, recorder):
        super().__init__(client)
        self.recorder = recorder

    async def create(self, *args, **kwargs):
        result = await super().create(*args, **kwargs)
        return RecordedStream(result, self.recorder) if kwargs.get("stream") else result


def settings():
    config = json.loads((ROOT / "connection.json").read_text())
    credential_path = (ROOT / config["credential_file"]).resolve(strict=True)
    tokens = MarkdownIt().parse(credential_path.read_text())
    keys = [key for token in tokens if token.type in {"inline", "fence"} for key in re.findall(r"sk-[A-Za-z0-9_-]+", token.content)]
    if len(keys) != 1:
        raise ValueError("服务端配置文件必须包含唯一有效格式的 DeepSeek 密钥")
    if config["provider"] != "deepseek" or config["base_url"] != "https://api.deepseek.com" or config["model_id"] != "deepseek-flash":
        raise ValueError("连接配置超出已核查的 DeepSeek 型号与官方地址")
    os.environ["DEEPSEEK_API_KEY"] = keys[0]
    os.environ["DEEPSEEK_MODEL"] = config["model_id"]
    os.environ["DEEPSEEK_BASE_URL"] = config["base_url"]
    return config


class RecordedProvider(OpenAICompatProvider):
    def __init__(self, config, output, *, redact_payload=False, transport_observer=None):
        self.redact_payload = redact_payload
        self.transport_observer = transport_observer
        provider_name = config.get("provider", "deepseek")
        credential_reference = config.get("credential_reference", "DEEPSEEK_API_KEY")
        self.timeout_seconds = config.get("timeout_seconds", 120)
        super().__init__(api_key=os.environ[credential_reference], api_base=config["base_url"],
                         default_model=config["model_id"], spec=find_by_name(provider_name),
                         extra_body={"thinking": {"type": config["thinking"]}} if provider_name == "deepseek" else {},
                         api_type="chat_completions", provider_name=provider_name)
        self.output = Path(output)
        loaded = json.loads(self.output.read_text()) if self.output.exists() else []
        self.requests = ([self._sanitize_history(row) for row in loaded]
                         if self.redact_payload else loaded)
        if self.redact_payload and self.output.exists():
            self.save()

    @staticmethod
    def _sanitize_history(record):
        if not isinstance(record, dict):
            return {"type": "invalid_event", "private_contents_recorded": False}
        allowed = {
            "type", "at", "method", "url", "model", "stream", "max_tokens",
            "status", "request_id", "content_type", "response_id", "created",
            "request_sha256", "request_bytes", "message_count", "tool_count",
            "run_id", "session_id", "runtime_request_id", "configuration_version", "model_request_id", "tool_config_sha256",
        }
        result = {
            key: value for key, value in record.items()
            if key in allowed and isinstance(value, (int, float, str, bool, type(None)))
        }
        thinking = record.get("thinking")
        if isinstance(thinking, dict):
            result["thinking"] = {"type": thinking.get("type")} if thinking.get("type") in ("enabled", "disabled") else None
        usage = record.get("usage")
        if isinstance(usage, dict):
            result["usage"] = {
                k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens",
                                     "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
                if isinstance(usage.get(k), (int, float))
            }
        reasons = record.get("finish_reasons")
        if isinstance(reasons, list):
            result["finish_reasons"] = [str(x)[:50] for x in reasons[:8]]
        if record.get("error"):
            result["error_present"] = True
        result["private_contents_recorded"] = False
        return result

    def record(self, event):
        if self.transport_observer is not None:
            event.update(self.transport_observer(event))
        self.requests.append(event)
        self.save()

    def save(self):
        payload = json.dumps(self.requests, ensure_ascii=False, indent=2)
        if self.redact_payload:
            self.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.output.parent.chmod(0o700)
            fd = os.open(self.output, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(payload)
            return
        self.output.write_text(payload)

    def _build_client(self):
        async def request_hook(request):
            body = json.loads(request.content)
            request.extensions["boss_model_request_id"] = "model-request-" + str(uuid.uuid4())
            record = {"at": now(), "type": "request", "method": request.method, "url": str(request.url),
                      "model": body.get("model"), "stream": body.get("stream", False),
                      "max_tokens": body.get("max_tokens"), "thinking": body.get("thinking"),
                      "model_request_id": request.extensions["boss_model_request_id"],
                      "request_sha256": hashlib.sha256(request.content).hexdigest(),
                      "tool_config_sha256": checksum(body.get("tools") or [])}
            if self.redact_payload:
                record.update({
                    "request_sha256": hashlib.sha256(request.content).hexdigest(),
                    "request_bytes": len(request.content),
                    "message_count": len(body.get("messages", [])),
                    "tool_count": len(body.get("tools", [])),
                    "private_contents_recorded": False,
                })
            else:
                record["input"] = body
            self.record(record)

        async def response_hook(response):
            record = {"at": now(), "type": "response", "status": response.status_code, "url": str(response.request.url), "request_id": response.headers.get("x-request-id"), "content_type": response.headers.get("content-type"), "model_request_id": response.request.extensions["boss_model_request_id"]}
            if not response.request.url.path.endswith("/chat/completions"):
                raise ValueError("实际请求使用了未获准的模型协议路径")
            if response.headers.get("content-type", "").startswith("application/json"):
                await response.aread()
                body = response.json()
                record.update(response_id=body.get("id"), model=body.get("model"), usage=body.get("usage"))
                record["finish_reasons"] = [choice["finish_reason"] for choice in body.get("choices", []) if choice.get("finish_reason")]
                if self.redact_payload:
                    if body.get("error"):
                        record["error_present"] = True
                else:
                    record["error"] = body.get("error")
            self.record(record)

        self._client = AsyncOpenAI(api_key=self._api_key_for_client, base_url=self._effective_base, max_retries=0,
                                  timeout=self.timeout_seconds, http_client=httpx.AsyncClient(
                                      timeout=self.timeout_seconds, event_hooks={"request": [request_hook], "response": [response_hook]}))
        self._client.chat.completions = RecordedCompletions(self._client, self)


async def check_connection():
    config = settings()
    output = ROOT.parent / "evidence/T02/connection"
    output.mkdir(parents=True, exist_ok=True)
    async with AsyncOpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=config["base_url"], max_retries=0, timeout=30) as client:
        response = await client.models.with_raw_response.list()
        models = response.parse()
        ids = [model.id for model in models.data]
        report = {"at": now(), "status": response.status_code, "method": "GET", "url": str(response.http_request.url), "request_id": response.headers.get("x-request-id"), "models": ids, "selected_model": config["model_id"], "credential_ref": config["credential_file"]}
        (output / "models.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        if config["model_id"] not in ids:
            raise ValueError("账户返回的模型列表不包含已配置型号")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    import asyncio

    asyncio.run(check_connection())
