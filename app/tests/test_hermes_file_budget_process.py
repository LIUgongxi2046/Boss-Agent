import subprocess
import sys
import os
import select
from pathlib import Path

import pytest

from agent_run_store import RunStore
from test_agent_run_result import setup_result


@pytest.mark.parametrize("limit", ["count", "bytes"])
def test_parent_child_independent_processes_share_file_budget(tmp_path, limit):
    business, runs, _, sink = setup_result(tmp_path)
    root = sink.config.run_id
    runs.configure_file_budget(root, sink.lease_owner, sink.config.lease_epoch,
                               1 if limit == "count" else 2, 1024 if limit == "count" else 150)
    child = runs.create_child_run(root, sink.lease_owner, sink.config.lease_epoch, "file-child", "file-child-digest")
    lease = runs.acquire_queued_for_execution(child, 0, "child-worker", 60)
    files = [tmp_path / "root.txt", tmp_path / "child.txt"]
    for path in files:
        path.write_bytes(b"A" * 100)
    probe = Path(__file__).with_name("hermes_file_budget_process.py")
    commands = [[sys.executable, str(probe), str(business.path), root, sink.lease_owner,
                 str(sink.config.lease_epoch), "root-file", str(files[0])],
                [sys.executable, str(probe), str(business.path), child, "child-worker",
                 str(lease["epoch"]), "child-file", str(files[1])]]
    read_fd, write_fd = os.pipe()
    processes = []
    try:
        for command in commands:
            processes.append(subprocess.Popen(command, stdin=read_fd, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for process in processes:
            assert select.select([process.stdout], [], [], 20)[0]
            assert process.stdout.readline() == b"READY\n"
        os.write(write_fd, b"xx")
        os.close(write_fd)
        write_fd = None
        results = [process.communicate(timeout=20) for process in processes]
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    assert sorted(process.returncode for process in processes) == [0, 1]
    assert any("运行文件预算不足" in stderr.decode() for _, stderr in results)
    reopened = RunStore(business.path, allow_migration=False)
    with reopened.connect() as db:
        rows = db.execute("SELECT root_run_id,run_id,size_bytes,status FROM agent_file_reservations").fetchall()
        assert len(rows) == 1 and rows[0][0] == root and rows[0][1] in {root, child}
        assert rows[0][2:] == (100, "RESERVED")
