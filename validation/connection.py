import json
import os
import re
from pathlib import Path

import httpx
from markdown_it import MarkdownIt
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name
from openai import AsyncOpenAI
from openai.resources.chat.completions import AsyncCompletions

from business import ROOT, now


class RecordedStream:
    def __init__(self, stream, recorder):
        self.stream, self.recorder = stream, recorder

    async def __aiter__(self):
        first = True
        try:
            async for chunk in self.stream:
                finished = any(choice.finish_reason is not None for choice in chunk.choices)
                if first or chunk.usage is not None or finished:
                    self.recorder.requests.append({"at": now(), "type": "stream_metadata", "response_id": chunk.id, "model": chunk.model, "created": chunk.created, "usage": chunk.usage.model_dump(mode="json") if chunk.usage else None, "finish_reasons": [choice.finish_reason for choice in chunk.choices if choice.finish_reason is not None]})
                    self.recorder.save()
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
    def __init__(self, config, output):
        super().__init__(api_key=os.environ["DEEPSEEK_API_KEY"], api_base=config["base_url"], default_model=config["model_id"], spec=find_by_name("deepseek"), extra_body={"thinking": {"type": config["thinking"]}}, provider_name="deepseek")
        self.output = Path(output)
        self.requests = json.loads(self.output.read_text()) if self.output.exists() else []

    def save(self):
        self.output.write_text(json.dumps(self.requests, ensure_ascii=False, indent=2))

    def _build_client(self):
        async def request_hook(request):
            body = json.loads(request.content)
            self.requests.append({"at": now(), "type": "request", "method": request.method, "url": str(request.url), "model": body.get("model"), "stream": body.get("stream", False), "max_tokens": body.get("max_tokens"), "thinking": body.get("thinking"), "input": body})
            self.save()

        async def response_hook(response):
            record = {"at": now(), "type": "response", "status": response.status_code, "url": str(response.request.url), "request_id": response.headers.get("x-request-id"), "content_type": response.headers.get("content-type")}
            if not response.request.url.path.endswith("/chat/completions"):
                raise ValueError("实际请求使用了未获准的模型协议路径")
            if response.headers.get("content-type", "").startswith("application/json"):
                await response.aread()
                body = response.json()
                record.update(response_id=body.get("id"), model=body.get("model"), usage=body.get("usage"), error=body.get("error"))
            self.requests.append(record)
            self.save()

        self._client = AsyncOpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=self._effective_base, max_retries=0, timeout=120, http_client=httpx.AsyncClient(timeout=120, event_hooks={"request": [request_hook], "response": [response_hook]}))
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
