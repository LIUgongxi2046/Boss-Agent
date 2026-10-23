import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / "Boss-Agent-Desktop-Complete-v6/animation/01-待机悬浮.webp"
with Image.open(source) as animation:
    assert animation.n_frames > 1
    assert animation.info["loop"] == 0
    frames = animation.n_frames
    dimensions = animation.size
with Image.open(ROOT / "validation/desktop/branding/boss-agent.icns") as icon:
    assert icon.format == "ICNS"
accounts = json.loads((ROOT / "validation/.work/application/accounts/credentials.json").read_text())
paths = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT, check=True, capture_output=True).stdout.split(b"\0")
checked = 0
for value in paths:
    if not value:
        continue
    file = ROOT / value.decode()
    if not file.is_file():
        continue
    content = file.read_bytes()
    assert all(account["password"].encode() not in content for account in accounts), "文件包含账号秘密"
    checked += 1
for file in (ROOT / "validation/.work/t27").glob("*.jsonl"):
    assert all(account["password"].encode() not in file.read_bytes() for account in accounts), "认证审计包含秘密"
files = ["app/webui/BossLogin.tsx", "app/webui/boss-login.css", "validation/boss_account_auth.py", "validation/desktop/branding.cjs"]
report = {"status": "PASS_ASSET_METADATA_AND_PASSWORD_EXCLUSION", "animation": {"format": "WEBP", "frames": frames, "size": dimensions,
          "loop": 0, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}, "repository_files_checked": checked,
          "source_sha256": {file: hashlib.sha256((ROOT / file).read_bytes()).hexdigest() for file in files}, "visual": "NOT_RUN"}
(ROOT / "evidence/T27/asset-privacy.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print("动画文件帧与账号秘密排除检查通过")
