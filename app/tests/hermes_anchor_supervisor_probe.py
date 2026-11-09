import json
import os
import sys
import time
from pathlib import Path

from hermes_process_anchor import AnchorProcessGroup


engine = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
child_output = Path(sys.argv[3]).resolve()
group = AnchorProcessGroup.start([sys.executable, str(engine), "sleep_child", str(child_output)],
                                 cwd=Path(__file__).resolve().parent,
                                 env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}, bootstrap=b"")
temporary = output.with_suffix(".tmp")
temporary.write_text(json.dumps({"supervisor_pid": os.getpid(), "anchor_pid": group.anchor_pid,
                                 "engine_pid": group.engine_pid}), encoding="utf-8")
os.replace(temporary, output)
time.sleep(60)
