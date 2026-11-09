import gzip
import json
import os
from pathlib import Path


def test_actual_frontend_artifact_resources_and_compression():
    output = Path(os.environ["BOSS_FRONTEND_ARTIFACT"]).resolve(strict=True)
    manifest = json.loads((output / "asset-manifest.json").read_text(encoding="utf-8"))
    entry = manifest["index.html"]
    assert entry["isEntry"] is True
    for key in entry.get("imports", []):
        imported = Path(manifest[key]["file"]).name
        assert not imported.startswith(("markdown-vendor-", "syntax-highlight-", "katex-"))
    for item in manifest.values():
        assert (output / item["file"]).is_file()
        for name in item.get("css", []) + item.get("assets", []):
            assert (output / name).is_file()
    compressed = list(output.rglob("*.gz"))
    assert compressed
    for file in compressed:
        original = file.with_suffix("")
        assert original.is_file()
        assert gzip.decompress(file.read_bytes()) == original.read_bytes()
    for name in ("boss-logo-from-reference.png", "dapeng-front.png", "dapeng-side.png", "dapeng-think.png", "dapeng-execute.png", "01-待机悬浮.webp", "02-语音倾听.webp", "03-思考分析.webp", "04-执行推进.webp", "05-完成确认.webp", "06-通知提醒.webp", "boss-flight-sprite.png"):
        assert (output / "boss-brand" / name).is_file()
