#!/usr/bin/env python3
"""Quantitative design-v6 screenshot comparison, *not* automatic pixel acceptance.

Run after local visual_qa.cjs. Requires Pillow (optional QA-only dependency).
Dynamic timestamps, runtime data, browser text rasterization and real OS fonts
can cause differences; review images by eye before accepting each page.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageEnhance, ImageStat
except ImportError as exc:
    raise SystemExit("需要 QA 专用 Pillow：python -m pip install pillow") from exc

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "Boss-Agent-Desktop-Complete-v6"


def compare(reference: Path, rendered: Path, diff_path: Path):
    with Image.open(reference) as src, Image.open(rendered) as dst:
        src = src.convert("RGB")
        dst = dst.convert("RGB")
        if src.size != dst.size:
            return {"status": "SIZE_MISMATCH", "expected": src.size, "actual": dst.size}
        diff = ImageChops.difference(src, dst)
        stats = ImageStat.Stat(diff)
        mean_abs_error = sum(stats.mean) / 3
        normalized_mae = round(mean_abs_error / 255, 6)
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        ImageEnhance.Contrast(diff).enhance(3.0).save(diff_path)
        return {
            "status": "MEASURED_NOT_ACCEPTED",
            "pixel_mae_0_to_1": normalized_mae,
            "expected": src.size,
            "actual": dst.size,
            "diff_image": str(diff_path.relative_to(ROOT)),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", default="boss", choices=["boss", "maintainer"])
    args = parser.parse_args()
    folder = ROOT / ".work" / "visual-qa" / args.role
    manifest = json.loads((folder / "capture-report.json").read_text(encoding="utf-8"))
    comparisons = []
    for capture in manifest["captures"]:
        if capture["state"] != "SUCCESS" or capture["viewport"] != {"width": 1440, "height": 1024}:
            continue
        baseline = ROOT / capture["design_reference"]
        actual = ROOT / capture["screenshot"]
        diff_path = folder / "diff" / (capture["page_id"] + "-diff.png")
        comparisons.append({
            "page_id": capture["page_id"],
            "reference": str(baseline.relative_to(ROOT)),
            "rendered": str(actual.relative_to(ROOT)),
            "comparison": compare(baseline, actual, diff_path),
        })
    summary = {
        "basis": "Design v6 1440x1024 PNG vs locally rendered v6 React screenshot",
        "visual_acceptance": "NOT_RUN_MANUAL_REVIEW_REQUIRED",
        "comparisons": comparisons,
    }
    target = folder / "pixel-report.json"
    target.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"已输出 {target}；MAE 是诊断数值，不等于已通过像素验收。")


if __name__ == "__main__":
    main()
