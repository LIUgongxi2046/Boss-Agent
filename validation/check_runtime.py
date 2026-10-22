import subprocess
import sys

from business import ROOT


for script in ("check_materials.py", "check_local.py", "check_scheduler.py", "check_controls.py"):
    subprocess.run([sys.executable, str(ROOT / script)], check=True, cwd=ROOT, timeout=60)
