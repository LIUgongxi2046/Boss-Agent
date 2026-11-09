import http.client
import json
import logging
import socket
import ssl
from uuid import UUID

from hermes_vm_channel import authenticate_vm_socket
from hermes_vm_identity import HermesVMRecoveryAccess, HermesVMRunAccess
from hermes_guest_slice import slice_name


logger = logging.getLogger(__name__)


class HermesVMControlClient:
    def __init__(self, context, guest_name, guest_certificate_sha256, control_port):
        if not isinstance(context, ssl.SSLContext) or context.protocol != ssl.PROTOCOL_TLS_CLIENT or context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname or context.minimum_version < ssl.TLSVersion.TLSv1_3:
            raise ValueError("宿主管理需要双向 TLS 1.3")
        if not isinstance(guest_name, str) or not guest_name or not isinstance(guest_certificate_sha256, str) or len(guest_certificate_sha256) != 64 or any(character not in "0123456789abcdef" for character in guest_certificate_sha256):
            raise ValueError("客体通信身份无效")
        if type(control_port) is not int or not 1 <= control_port <= 65535:
            raise ValueError("客体控制端口无效")
        self.context, self.guest_name = context, guest_name
        self.guest_certificate_sha256, self.control_port = guest_certificate_sha256, control_port

    def _request(self, path, body):
        if self.context.verify_mode != ssl.CERT_REQUIRED or not self.context.check_hostname or self.context.minimum_version < ssl.TLSVersion.TLSv1_3:
            raise ValueError("宿主管理需要双向 TLS 1.3")
        connection = http.client.HTTPConnection("127.0.0.1", self.control_port, timeout=15)
        try:
            logger.debug("虚拟机控制连接开始：%s", path)
            raw = socket.create_connection(("127.0.0.1", self.control_port), timeout=15)
            logger.debug("虚拟机控制连接已建立：%s", path)
            connection.sock = authenticate_vm_socket(raw, self.context, self.guest_certificate_sha256,
                                                      server_side=False, server_hostname=self.guest_name, timeout=15)
            logger.debug("虚拟机控制身份已核查：%s", path)
            payload = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            connection.request("POST", path, payload, {"Content-Type": "application/json"})
            response = connection.getresponse()
            logger.debug("虚拟机控制响应状态：%s %s", path, response.status)
            data = response.read(16385)
            if response.status != 200:
                raise ValueError("客体控制响应不可核查：HTTP " + str(response.status))
            if len(data) > 16384:
                raise ValueError("客体控制响应不可核查")
            return json.loads(data)
        finally:
            connection.close()

    def identity(self):
        result = self._request("/internal/v1/guest/identity", {})
        if not isinstance(result, dict) or set(result) != {"boot_id"} or not isinstance(result["boot_id"], str) or str(UUID(result["boot_id"])) != result["boot_id"]:
            raise ValueError("客体启动身份不可核查")
        return result["boot_id"]


class HermesVMHostClient(HermesVMControlClient):
    def __init__(self, access, context, guest_name, guest_certificate_sha256, control_port):
        if not isinstance(access, HermesVMRunAccess):
            raise ValueError("宿主管理需要运行绑定")
        super().__init__(context, guest_name, guest_certificate_sha256, control_port)
        self.access = access

    def _workspace_request(self, path, budget, bootstrap, state):
        workspace = self.access.require_workspace_context()
        unit = workspace.pop("unit")
        if not isinstance(bootstrap, dict) or bootstrap.get("run_id") != self.access.run_id:
            raise ValueError("客体启动信息与运行不匹配")
        result = self._request(path, {"run_id": self.access.run_id, "epoch": self.access.epoch,
            "boot_id": self.access.boot_id, "budget": budget, "bootstrap": bootstrap, "workspace": workspace})
        if result != {"unit": unit, "state": state}:
            raise ValueError("客体启动回执不可核查")
        if self.access.require_workspace_context() != {"unit": unit, **workspace}:
            raise ValueError("客体启动后根运行工作区身份已经变化")
        return result

    def prepare_workspace(self, budget, bootstrap):
        return self._workspace_request("/internal/v1/guest/workspace/prepare", budget, bootstrap, "READY")

    def workspace_status(self, budget, bootstrap):
        return self._workspace_request("/internal/v1/guest/workspace/status", budget, bootstrap, "READY")

    def start(self, budget, bootstrap):
        return self._workspace_request("/internal/v1/guest/start", budget, bootstrap, "UNKNOWN")

    def release_workspace(self):
        result = self._request("/internal/v1/guest/workspace/release", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        if result != {"state": "UNKNOWN"}:
            raise ValueError("客体工作区释放回执不可核查")
        return result

    def stop(self):
        if isinstance(self.access, HermesVMRecoveryAccess):
            raise ValueError("恢复访问不允许停止运行")
        result = self._request("/internal/v1/guest/stop", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        if result != {"state": "UNKNOWN"}:
            raise ValueError("客体停止回执不可核查")
        return result

    def stop_for_recovery(self):
        if not isinstance(self.access, HermesVMRecoveryAccess):
            raise ValueError("恢复停止需要本人恢复访问")
        self.access.require_final()
        observed_boot = self.identity()
        if observed_boot != self.access.boot_id:
            return
        result = self._request("/internal/v1/guest/stop", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        if result != {"state": "UNKNOWN"} or self.identity() != observed_boot:
            raise ValueError("客体恢复停止不可核查")
        self.access.require_final()

    def final_exit_status(self):
        if not isinstance(self.access, HermesVMRecoveryAccess):
            raise ValueError("最终退出状态需要本人恢复访问")
        self.access.require_final()
        observed_boot = self.identity()
        result = self._request("/internal/v1/guest/final-exit-status", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        if result not in ({"state": "FINAL"}, {"state": "UNKNOWN"}) or self.identity() != observed_boot:
            raise ValueError("客体最终退出状态不可核查")
        self.access.require_final()
        return result["state"]

    def inspect(self):
        unit = self.access.require()
        result = self._request("/internal/v1/guest/inspect", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        if not isinstance(result, dict) or set(result) != {"unit", "process_exited", "state"} or result["unit"] != unit or result["state"] != "UNKNOWN" or result["process_exited"] is not None and type(result["process_exited"]) is not bool:
            raise ValueError("客体运行状态不可核查")
        self.access.require()
        return result

    def monitor_read(self, authority, kind):
        from hermes_run_authority import HermesRunAuthority
        if not isinstance(authority, HermesRunAuthority) or authority.vm_access != self.access or kind not in {"inspect", "cpu-slice"}:
            raise ValueError("虚拟机监督读取授权不可核查")
        with self.access.bindings.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = authority.monitor_state_in_transaction(db)
            if state != "RUNNING":
                return state, None
            unit = self.access.require_final_in_transaction(db)
        result = self._request("/internal/v1/guest/" + kind, {"run_id": self.access.run_id, "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        with self.access.bindings.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = authority.monitor_state_in_transaction(db)
            if state != "RUNNING":
                return state, None
            if self.access.require_final_in_transaction(db) != unit:
                raise ValueError("虚拟机监督读取身份已经变化")
        if kind == "inspect":
            if not isinstance(result, dict) or set(result) != {"unit", "process_exited", "state"} or result["unit"] != unit or result["state"] != "UNKNOWN" or result["process_exited"] is not None and type(result["process_exited"]) is not bool:
                raise ValueError("客体运行状态不可核查")
            return state, result
        if result == {"unit": unit, "boot_id": self.access.boot_id, "state": "EXITED_UNVERIFIED"}:
            return state, None
        if not isinstance(result, dict) or set(result) != {"unit", "boot_id", "cpu_ns", "source"} or result["unit"] != unit or result["boot_id"] != self.access.boot_id or result["source"] != "SLICE_CPU_NSEC_V1" or type(result["cpu_ns"]) is not int or result["cpu_ns"] < 0:
            raise ValueError("客体 slice CPU 读数不可核查")
        return state, result

    def cpu_usage(self):
        unit = self.access.require()
        result = self._request("/internal/v1/guest/cpu", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        if not isinstance(result, dict) or set(result) != {"unit", "boot_id", "cpu_ns"} or result["unit"] != unit or result["boot_id"] != self.access.boot_id or type(result["cpu_ns"]) is not int or result["cpu_ns"] < 0:
            raise ValueError("客体 CPU 读数不可核查")
        self.access.require()
        return result

    def slice_cpu_usage(self):
        unit = self.access.require()
        result = self._request("/internal/v1/guest/cpu-slice", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        if result == {"unit": unit, "boot_id": self.access.boot_id, "state": "EXITED_UNVERIFIED"}:
            self.access.require()
            return None
        if not isinstance(result, dict) or set(result) != {"unit", "boot_id", "cpu_ns", "source"} or result["unit"] != unit or result["boot_id"] != self.access.boot_id or result["source"] != "SLICE_CPU_NSEC_V1" or type(result["cpu_ns"]) is not int or result["cpu_ns"] < 0:
            raise ValueError("客体 slice CPU 读数不可核查")
        self.access.require()
        return result

    def unknown_exit_receipt(self):
        unit = self.access.require_final()
        observed_boot = self.identity()
        if observed_boot != self.access.boot_id and not isinstance(self.access, HermesVMRecoveryAccess):
            raise ValueError("客体启动身份已经变化")
        result = self._request("/internal/v1/guest/exit", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        expected = {"run_id": self.access.run_id, "epoch": self.access.epoch, "boot_id": self.access.boot_id,
                    "unit": unit, "state": "UNKNOWN", "cpu_ns": None}
        if result != expected or type(result.get("epoch")) is not int:
            raise ValueError("客体退出记录不可核查")
        if self.identity() != observed_boot:
            raise ValueError("客体启动身份已经变化")
        self.access.require_final()
        return result

    def final_exit_receipt(self):
        unit = self.access.require_final()
        observed_boot = self.identity()
        if observed_boot != self.access.boot_id and not isinstance(self.access, HermesVMRecoveryAccess):
            raise ValueError("客体启动身份已经变化")
        result = self._request("/internal/v1/guest/final-exit", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        fields = {"run_id", "epoch", "boot_id", "unit", "invocation", "slice", "cpu_ns", "source"}
        if not isinstance(result, dict) or set(result) != fields or (result["run_id"], result["epoch"], result["boot_id"], result["unit"], result["slice"], result["source"]) != (self.access.run_id, self.access.epoch, self.access.boot_id, unit, slice_name(self.access.run_id, self.access.epoch), "SLICE_CPU_NSEC_V1"):
            raise ValueError("客体最终退出身份不可核查")
        if type(result["epoch"]) is not int or not isinstance(result["invocation"], str) or len(result["invocation"]) != 32 or any(character not in "0123456789abcdef" for character in result["invocation"]) or result["invocation"] == "0" * 32 or type(result["cpu_ns"]) is not int or not 0 <= result["cpu_ns"] < 2**63:
            raise ValueError("客体最终退出内容不可核查")
        if self.identity() != observed_boot:
            raise ValueError("客体启动身份已经变化")
        self.access.require_final()
        return result

    def tree_exit_receipt(self):
        unit = self.access.require_final()
        observed_boot = self.identity()
        if observed_boot != self.access.boot_id and not isinstance(self.access, HermesVMRecoveryAccess):
            raise ValueError("客体启动身份已经变化")
        result = self._request("/internal/v1/guest/tree-exit", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        fields = {"run_id", "epoch", "boot_id", "unit", "invocation", "slice", "cpu_ns", "source"}
        if not isinstance(result, dict) or set(result) != fields or (result["run_id"], result["epoch"], result["boot_id"], result["unit"], result["slice"], result["source"]) != (self.access.run_id, self.access.epoch, self.access.boot_id, unit, slice_name(self.access.run_id, self.access.epoch), "SYSTEMD_CGROUP_EXIT_V1"):
            raise ValueError("客体进程范围退出身份不可核查")
        if type(result["epoch"]) is not int or not isinstance(result["invocation"], str) or len(result["invocation"]) != 32 or any(character not in "0123456789abcdef" for character in result["invocation"]) or result["invocation"] == "0" * 32 or type(result["cpu_ns"]) is not int or not 0 <= result["cpu_ns"] < 2**63:
            raise ValueError("客体进程范围退出内容不可核查")
        if self.identity() != observed_boot:
            raise ValueError("客体启动身份已经变化")
        self.access.require_final()
        return result

    def cleanup_final_exit(self, receipt):
        self.access.require_final()
        if self.final_exit_receipt() != receipt:
            raise ValueError("客体最终清理记录不匹配")
        result = self._request("/internal/v1/guest/final-exit-cleanup", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        if result != receipt:
            raise ValueError("客体最终清理回执不匹配")
        self.access.require_final()
        return result

    def unknown_exit_observation(self):
        unit = self.access.require_final()
        observed_boot = self.identity()
        if observed_boot != self.access.boot_id and not isinstance(self.access, HermesVMRecoveryAccess):
            raise ValueError("客体启动身份已经变化")
        result = self._request("/internal/v1/guest/exit-observation", {"run_id": self.access.run_id,
            "epoch": self.access.epoch, "boot_id": self.access.boot_id})
        fields = {"run_id", "epoch", "boot_id", "unit", "invocation", "unit_state", "control_group", "cpu_ns", "kill_mode", "result", "state"}
        if not isinstance(result, dict) or set(result) != fields or (result["run_id"], result["epoch"], result["boot_id"], result["unit"], result["state"]) != (self.access.run_id, self.access.epoch, self.access.boot_id, unit, "UNKNOWN"):
            raise ValueError("客体退出观察身份不可核查")
        if type(result["epoch"]) is not int or not isinstance(result["invocation"], str) or len(result["invocation"]) != 32 or any(character not in "0123456789abcdef" for character in result["invocation"]) or result["invocation"] == "0" * 32 or result["unit_state"] not in {"inactive", "failed"} or result["kill_mode"] != "control-group" or type(result["cpu_ns"]) is not int or not 0 <= result["cpu_ns"] < 2**63 or not isinstance(result["control_group"], str) or not isinstance(result["result"], str):
            raise ValueError("客体退出观察内容不可核查")
        if self.identity() != observed_boot:
            raise ValueError("客体启动身份已经变化")
        self.access.require_final()
        return result
