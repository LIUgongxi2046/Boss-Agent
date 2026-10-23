import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / "design/T27/assets/boss-flight-sprite.png"
with Image.open(source) as sprite:
    dimensions = sprite.size
    assert dimensions[0] == dimensions[1] * 2
    cells = [sprite.crop((round(column * dimensions[0] / 4), round(row * dimensions[1] / 2),
                         round((column + 1) * dimensions[0] / 4), round((row + 1) * dimensions[1] / 2)))
             for row in range(2) for column in range(4)]
    frame_hashes = [hashlib.sha256(cell.tobytes()).hexdigest() for cell in cells]
    assert len(set(frame_hashes)) == 8
with Image.open(ROOT / "validation/desktop/branding/boss-agent.icns") as icon:
    assert icon.format == "ICNS"
with Image.open(ROOT / "validation/desktop/branding/boss-agent-hd.png") as master:
    assert min(master.size) >= 1024
    icon_size = master.size
accounts = json.loads((ROOT / "validation/.work/application/accounts/credentials.json").read_text())
zoom_credentials = ROOT / "validation/.work/t27-native-zoom/service/accounts/credentials.json"
if zoom_credentials.exists():
    accounts.extend(json.loads(zoom_credentials.read_text()))
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
audits = [ROOT / "validation/.work" / name / "audit.jsonl" for name in
          ("t27", "t27-native-zoom/service", "t27-review/service", "t27-review-flight/service", "t27-review-natural/service")]
audits = [file for file in audits if file.exists()]
for file in audits:
    assert all(account["password"].encode() not in file.read_bytes() for account in accounts), "认证审计包含秘密"
files = ["app/webui/BossLogin.tsx", "app/webui/boss-login.css", "validation/boss_account_auth.py", "validation/desktop/branding.cjs",
         "design/T27/harness/main.tsx", "design/T27/harness/vite.config.ts", "design/T27/server.py", "design/T27/check-native-zoom.cjs",
         "design/T27/zoom-host.cjs", "design/T27/check-flight.cjs", "design/T27/open-review.cjs", "design/T27/review-host.cjs", "validation/desktop/check-login-polish.cjs"]
report = {"status": "PASS_ASSET_METADATA_AND_PASSWORD_EXCLUSION", "icon_master_size": icon_size, "animation": {"format": "PNG_SPRITE", "frames": 8, "grid": [4, 2], "size": dimensions,
          "frame_sha256": frame_hashes, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}, "repository_files_checked": checked, "audit_files_checked": len(audits),
          "source_sha256": {file: hashlib.sha256((ROOT / file).read_bytes()).hexdigest() for file in files}, "visual": "NOT_RUN"}
(ROOT / "evidence/T27/asset-privacy.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print("动画文件帧与账号秘密排除检查通过")
