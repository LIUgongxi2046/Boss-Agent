import json
import os
import argparse
from pathlib import Path

from boss_transcription import load_doubao_api_key
from connection import settings

ROOT = Path(__file__).resolve().parents[1]


def check(application_directory=ROOT / "validation/.work/application"):
    application_directory = application_directory.resolve(strict=True)
    if application_directory.parent != (ROOT / "validation/.work").resolve(strict=True):
        raise ValueError("凭据检查必须使用本工程的独立应用目录")
    connection = settings()
    credential_file = (ROOT / "validation" / connection["credential_file"]).resolve(strict=True)
    access = json.loads((application_directory / "access.json").read_text())
    secrets = [os.environ["DEEPSEEK_API_KEY"], load_doubao_api_key(credential_file), *access.values()]
    assert all(isinstance(value, str) and value for value in secrets)
    secret_bytes = [value.encode() for value in secrets]
    count = 0
    for directory in ("evidence", "docs", "specs", "app", "scripts"):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and path.suffix in {".json", ".jsonl", ".xml", ".md", ".py", ".tsx", ".ts", ".cjs", ".css", ".yaml", ".sqlite"}:
                content = path.read_bytes()
                if any(value in content for value in secret_bytes):
                    raise ValueError("凭据检查未通过，文件=" + str(path.relative_to(ROOT)))
                count += 1
    return {"status": "PASS_LITERAL_SECRET_CHECK_ONLY", "files_checked": count,
            "secret_sources_checked": len(secrets), "secret_values_recorded": False,
            "application_directory": str(application_directory.relative_to(ROOT)),
            "scope": "evidence/docs/specs/app/scripts所列文本文件及SQLite文件的凭据字节检查；不替代全部隐私审查"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--application-directory", type=Path)
    args = parser.parse_args()
    result = check(args.application_directory) if args.application_directory is not None else check()
    filename = "credential-privacy-" + args.application_directory.name + ".json" if args.application_directory is not None else "credential-privacy.json"
    output = ROOT / "evidence/T09/w3-20261023" / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
