import hashlib
import json
import os
import subprocess
import sys
import uuid

import httpx

from business import ROOT, now


def main():
    output = ROOT.parent / "evidence/T02" / ("reuse-" + str(uuid.uuid4()))
    output.mkdir(parents=True)
    access = json.loads((ROOT / ".work/application/access.json").read_text())
    config_path = ROOT / ".work/application/config.json"
    before = json.loads(config_path.read_text())["agents"]["defaults"]["maxToolIterations"]
    assert before == 8, "本次原生两端检查要求当前已保存轮数为 8"
    env = dict(os.environ, TMPDIR=str(ROOT / ".work/tmp"))
    command = [sys.executable, str(ROOT / "application.py")]
    with (output / "application.log").open("w") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log)

        def ready():
            with httpx.Client(transport=httpx.HTTPTransport(retries=8), trust_env=False) as client:
                client.get("http://127.0.0.1:8871/health", headers={"Authorization": "Bearer " + access["BOSS"]}).raise_for_status()

        def run(script):
            subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, env=env, stdout=log, stderr=log, timeout=180, check=True)

        try:
            ready()
            initial_pid = process.pid
            run("check_ui_business.py")
            run("check_admin.py")
            assert json.loads(config_path.read_text())["agents"]["defaults"]["maxToolIterations"] == 9
            run("check_admin.py")
            assert json.loads(config_path.read_text())["agents"]["defaults"]["maxToolIterations"] == 8
            process.terminate()
            assert process.wait(timeout=20) == 0
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log)
            ready()
            run("check_ui_business.py")
            events = json.loads((ROOT.parent / "evidence/T02/application/events.json").read_text())
            current = [event for event in events if event["type"] == "runtime_admission"][-1]["configuration"]
            assert current["max_tool_rounds"] == 8
            assert current["config_sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
            result = {"status": "PASS", "at": now(), "scope": "实际原生用户端 DOM 与正式状态、维护管理配置保存重载、角色拒绝、实际重启后下一任务采用及有效配置 hash", "initial_pid": initial_pid, "restarted_pid": process.pid, "adopted_configuration": current, "details": "application.log 中各实际 DOM 命令输出定位原始证据目录；同一逻辑交办复跑使用服务端同一幂等意图，不产生重复任务或发送"}
            (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps({**result, "evidence": str(output)}, ensure_ascii=False))
        finally:
            process.terminate()
            process.wait(timeout=20)


if __name__ == "__main__":
    main()
