import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from nanobot.config.schema import Config

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".work/upstream-instance"


def prepare():
    WORK.mkdir(parents=True, exist_ok=True)
    config = Config.model_validate({"agents": {"defaults": {"workspace": str(WORK / "workspace"), "provider": "deepseek", "model": "deepseek-flash", "maxToolIterations": 12, "maxTokens": 4096, "timezone": "Asia/Shanghai", "timezoneMode": "manual", "dream": {"enabled": False}, "idleCompactAfterMinutes": 0}}, "gateway": {"host": "127.0.0.1", "port": 18791, "heartbeat": {"enabled": False}}, "channels": {"websocket": {"enabled": True, "host": "127.0.0.1", "port": 8872, "tokenIssueSecret": "${NANOBOT_WEBUI_SECRET}", "websocketRequiresToken": True, "showReasoning": False}}, "tools": {"restrictToWorkspace": True}, "transcription": {"enabled": False}})
    path = WORK / "config.json"
    if not path.exists():
        path.write_text(config.model_dump_json(by_alias=True, indent=2))
    secret = WORK / "access.json"
    if not secret.exists():
        secret.write_text(json.dumps({"NANOBOT_WEBUI_SECRET": secrets.token_urlsafe(32)}))
        secret.chmod(0o600)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "start", "stop"])
    args = parser.parse_args()
    config = prepare()
    if args.command == "prepare":
        print(config)
        return
    env = dict(os.environ, **json.loads((WORK / "access.json").read_text()), TMPDIR=str(ROOT / ".work/tmp"))
    command = [str(ROOT / ".venv/bin/nanobot"), "gateway"]
    command += ["stop", "--config", str(config)] if args.command == "stop" else ["--config", str(config), "--foreground"]
    result = subprocess.run(command, env=env, check=True)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
