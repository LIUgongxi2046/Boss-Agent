import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "validation/desktop/package-output.cjs"
CHECK = "const h=require(process.argv[1]); console.log(h.desktopPackageOutput(process.argv[2],process.argv[3]));"


def test_desktop_output_rejects_symlinked_directories():
    with tempfile.TemporaryDirectory(dir=ROOT / ".work/upgrade2/u2-01/temp", prefix="desktop-path-") as directory:
        base = Path(directory)
        root = base / "validation"
        root.mkdir()
        target = base / "target"
        target.mkdir()
        (root / ".work").symlink_to(target, target_is_directory=True)
        rejected = subprocess.run(["node", "-e", CHECK, str(HELPER), str(root), str(root / ".work/new")], capture_output=True, text=True)
        assert rejected.returncode != 0
        assert "桌面打包目录不能经过符号链接" in rejected.stderr

        safe = base / "safe"
        (safe / ".work").mkdir(parents=True)
        (safe / ".work/link").symlink_to(target, target_is_directory=True)
        rejected = subprocess.run(["node", "-e", CHECK, str(HELPER), str(safe), str(safe / ".work/link/new")], capture_output=True, text=True)
        assert rejected.returncode != 0
        assert "桌面打包目录不能经过符号链接" in rejected.stderr

        output = safe / ".work/new"
        accepted = subprocess.run(["node", "-e", CHECK, str(HELPER), str(safe), str(output)], capture_output=True, text=True)
        assert accepted.returncode == 0
        assert accepted.stdout.strip() == str(output)
