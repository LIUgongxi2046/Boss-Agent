#!/usr/bin/env python3
"""Provision a user-supplied DeepSeek credential for Boss-Agent *on this machine*.

Credentials are never sent to GitHub, printed, put into source, API URLs,
browser storage, CLI command arguments, CI variables or generated reports.
Only the local server-side, Git-ignored Markdown file contains the key.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRET_NAME = "boss agent.md"
CONNECTION_SETTINGS = {
    "provider": "deepseek",
    "credential_file": "../boss agent.md",
    "model_id": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "api_type": "chat_completions",
    "thinking": "disabled",
    "timeout_seconds": 120,
    "max_tool_rounds": 12,
    "max_output_tokens": 4096,
}
_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")


class CredentialConfigurationError(ValueError):
    pass


def _private_regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISREG(mode) and not stat.S_ISLNK(mode)


def _read_one_credential(path: Path) -> bytes:
    if not _private_regular_file(path):
        raise CredentialConfigurationError("凭据来源必须是本机普通文件，不能是符号链接。")
    if path.stat().st_size > 16_384:
        raise CredentialConfigurationError("凭据文件内容过大，拒绝读取。")
    payload = path.read_bytes()
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CredentialConfigurationError("凭据文件不是 UTF-8 文本。") from error
    found = _KEY_PATTERN.findall(content)
    if len(found) != 1:
        raise CredentialConfigurationError("凭据文件须包含且仅包含一个符合格式的 DeepSeek Key。")
    return payload


def _secure_write(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def configure(root: Path, source: Path, replace: bool = False) -> dict[str, str]:
    """Create local ignored files and return only non-sensitive status names."""
    root = root.resolve(strict=True)
    target = root / SECRET_NAME
    source = source.expanduser().absolute()
    payload = _read_one_credential(source)
    if target.is_symlink() or (target.exists() and not _private_regular_file(target)):
        raise CredentialConfigurationError("本机目标文件类型或链接不安全。")
    if target.exists():
        present = _read_one_credential(target)
        if present != payload:
            if not replace:
                raise CredentialConfigurationError(
                    "已存在不同凭据。仅在本人确认轮换后加 --replace，避免无意覆盖。"
                )
            temp = root / (".bossagent-credential-" + str(os.getpid()))
            _secure_write(temp, payload)
            os.replace(temp, target)
        target.chmod(0o600)
    else:
        _secure_write(target, payload)

    cfg_path = root / "validation" / "connection.json"
    if not (root / "validation").is_dir():
        raise CredentialConfigurationError("缺少 validation 工程，拒绝生成配置。")
    if cfg_path.exists():
        if not _private_regular_file(cfg_path):
            raise CredentialConfigurationError("现有连接配置文件类型不安全。")
        existing = json.loads(cfg_path.read_text(encoding="utf-8"))
        if existing != CONNECTION_SETTINGS:
            raise CredentialConfigurationError(
                "当前连接配置与固定选型不一致；请先人工审查，不自动覆盖。"
            )
        cfg_path.chmod(0o600)
    else:
        _secure_write(cfg_path, (json.dumps(CONNECTION_SETTINGS, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    ignored = (root / ".gitignore").read_text(encoding="utf-8")
    if SECRET_NAME not in ignored or "validation/connection.json" not in ignored:
        raise CredentialConfigurationError("项目未忽略全部本地凭据路径，拒绝宣称配置完成。")
    return {
        "credential": "LOCAL_FILE_ONLY",
        "connection": "PRIVATE_REFERENCE_ONLY",
        "provider": CONNECTION_SETTINGS["provider"],
        "model_id": CONNECTION_SETTINGS["model_id"],
        "api_request_sent": "NO",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="安全配置本机 Boss-Agent DeepSeek 服务端密钥")
    parser.add_argument(
        "--source",
        help="已下载到本机的凭据 Markdown 路径；不填时读取项目根目录的 boss agent.md",
    )
    parser.add_argument("--replace", action="store_true", help="明确允许轮换不同的本机凭据")
    args = parser.parse_args()
    given = args.source or os.environ.get("BOSS_AGENT_KEY_FILE") or str(PROJECT_ROOT / SECRET_NAME)
    try:
        report = configure(PROJECT_ROOT, Path(given), replace=args.replace)
    except (CredentialConfigurationError, OSError, json.JSONDecodeError) as error:
        # Deliberately do not print the exception repr, input bytes, or the key.
        print("本机 DeepSeek 配置未完成：" + str(error), file=sys.stderr)
        raise SystemExit(2) from None
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("只完成本地静态配置核验；真实 DeepSeek 连接必须另行执行本地运行检查。")


if __name__ == "__main__":
    main()
