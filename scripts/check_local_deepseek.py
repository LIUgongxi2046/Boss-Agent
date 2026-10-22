#!/usr/bin/env python3
"""A real *local* DeepSeek Chat Completions smoke check for Boss-Agent.

This script deliberately does not print, persist, send to GitHub or include the
credential in CLI arguments. It sends one short synthetic prompt directly to
the configured provider. It is opt-in because a real API call can incur cost.

Run in the developer's local Mac Python environment after configuring a local
secret: validation/.venv/bin/python scripts/check_local_deepseek.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "validation"))

from connection import settings  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

HEALTH_PATH = PROJECT / "validation" / ".work" / "local-deepseek-health.json"
PROBE_PROMPT = "仅作为接口连通性自检。请用简体中文回复‘已连接’。"


async def check() -> dict[str, object]:
    config = settings()
    if config["provider"] != "deepseek" or config["model_id"] != "deepseek-flash":
        raise ValueError("接入配置不是已固定的 DeepSeek 型号；没有启动调用。")
    if os.environ.get("BOSS_PRODUCT_UI") == "0":
        # This flag is not required, just avoid confusing the T02 test context.
        pass
    async with AsyncOpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=config["base_url"],
        max_retries=0,
        timeout=30,
    ) as client:
        answer = await client.chat.completions.create(
            model=config["model_id"],
            messages=[{"role": "user", "content": PROBE_PROMPT}],
            max_tokens=80,
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
    response = answer.choices[0] if answer.choices else None
    if not answer.id or not response or not response.message.content:
        raise RuntimeError("模型响应内容或响应标识缺失，连通性检查不通过。")
    usage = answer.usage
    return {
        "status": "PASS_PROVIDER_RESPONSE_ONLY",
        "at": datetime.now(timezone.utc).isoformat(),
        "provider": "deepseek",
        "model_requested": config["model_id"],
        "model_observed": answer.model,
        "api_type": "chat_completions",
        "response_id": answer.id,
        "finish_reason": response.finish_reason,
        "usage": {
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
        },
        "business_test_completed": False,
        "runtime_session_test_completed": False,
        "credential_recorded": False,
    }


def main() -> None:
    try:
        result = asyncio.run(check())
    except Exception as error:
        # Avoid printing the original SDK exception: it may include a URL,
        # request body or private response. No local credential is included.
        print(
            "DeepSeek 实时连通性未通过（"
            + type(error).__name__
            + "）。请在本机检查 key、官方 API 状态及网络；未写入成功记录。",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(HEALTH_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("仅证明本机 DeepSeek API 有真实响应；不能替代 Boss Agent 的完整联调或 PRD 验收。")


if __name__ == "__main__":
    main()
