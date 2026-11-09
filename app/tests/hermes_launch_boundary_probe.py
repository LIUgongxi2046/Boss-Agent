import json
import os
import stat
import sys
import time
from pathlib import Path

null_stat = os.stat("/dev/null")
null_streams = [stat.S_ISCHR(os.fstat(fd).st_mode) and os.fstat(fd).st_rdev == null_stat.st_rdev for fd in (0, 1, 2)]
descriptor_present = os.path.exists("/dev/fd/" + sys.argv[2])
result = {"null_streams": null_streams, "descriptor_present": descriptor_present,
          "test_variable_present": "HERMES_PROCESS_TEST_VARIABLE" in os.environ,
          "environment_names": sorted(os.environ)}
Path(sys.argv[1]).write_text(json.dumps(result), encoding="utf-8")
time.sleep(0.2)
