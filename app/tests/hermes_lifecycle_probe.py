import os
import sys
import time
from pathlib import Path

if sys.argv[1] == "child":
    time.sleep(float(sys.argv[2]))
elif sys.argv[1] == "registered":
    from agent_run_store import RunStore
    from agent_run_launch_transaction import RunLaunchTransaction
    from hermes_process_evidence import HermesProcessEvidence
    store = RunStore(sys.argv[2], allow_migration=False)
    evidence = HermesProcessEvidence(store)
    with RunLaunchTransaction(store).hold(sys.argv[3], "worker", int(sys.argv[4])) as db:
        evidence.record_start_in_transaction(db, sys.argv[3], "slot", "digest", "worker", int(sys.argv[4]), "boss-1", "ui-check")
    os._exit(17)
else:
    from agent_run_store import RunStore
    from hermes_process_evidence import HermesProcessEvidence
    store = RunStore(sys.argv[2], allow_migration=False)
    evidence = HermesProcessEvidence(store)
    evidence.start(sys.argv[3], "slot", "digest", "worker", int(sys.argv[4]), "boss-1", "ui-check",
                   [sys.executable, str(Path(__file__).resolve()), "child", "3"], cwd=Path(__file__).resolve().parent)
    os._exit(17)
