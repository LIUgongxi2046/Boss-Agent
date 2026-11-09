import argparse
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from hermes_vm_channel import require_peer_certificate
from hermes_vm_credentials import load_vm_credential_pair, vm_id_from_machine_sha256
from hermes_vm_manager import HermesVMManager


parser = argparse.ArgumentParser()
parser.add_argument("--executable", type=Path, required=True)
parser.add_argument("--executable-sha256", required=True)
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--credentials", type=Path, required=True)
parser.add_argument("--dependencies", type=Path, required=True)
parser.add_argument("--engine", type=Path, required=True)
parser.add_argument("--runtime-port", type=int, required=True)
parser.add_argument("--control-port", type=int, required=True)
parser.add_argument("--runtime-probe", action="store_true")
arguments = parser.parse_args()
executor = None
listener = None
manager = None
try:
    if arguments.runtime_probe:
        identity = subprocess.run([str(arguments.executable), "--check-identity", str(arguments.directory / "machine-identity")],
                                  check=True, capture_output=True, text=True, timeout=15).stdout.strip().split()
        if len(identity) != 2 or identity[0] != "VM_IDENTITY_SHA256":
            raise ValueError("虚拟机机器身份不可核查")
        host, _ = load_vm_credential_pair(arguments.credentials, vm_id_from_machine_sha256(identity[1]))
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.settimeout(40)
        listener.bind(("127.0.0.1", arguments.runtime_port))
        listener.listen(1)

        def serve_runtime():
            connection, _ = listener.accept()
            with host.server.wrap_socket(connection, server_side=True) as secured:
                require_peer_certificate(secured.getpeercert(binary_form=True), host.peer_sha256)
                payload = b"BOSS_VSOCK_RUNTIME_CHECK"
                received = b""
                while len(received) < len(payload):
                    part = secured.recv(len(payload) - len(received))
                    if not part:
                        raise ValueError("运行通信提前结束")
                    received += part
                if received != payload:
                    raise ValueError("运行通信内容不匹配")
                secured.sendall(received)
            return "HOST_GUEST_VSOCK_RUNTIME_TLS_OK"

        executor = ThreadPoolExecutor(max_workers=1)
        runtime = executor.submit(serve_runtime)
    manager = HermesVMManager.start(
        arguments.executable, arguments.directory, arguments.credentials, arguments.executable_sha256,
        arguments.runtime_port, arguments.control_port,
        {"memory_bytes": 1073741824, "processes": 64, "cpu_percent": 100},
        dependencies_directory=arguments.dependencies, engine_directory=arguments.engine,
    )
    print("VM_MANAGER_STARTED", flush=True)
    if not sys.stdin.readline():
        raise ValueError("客体启动等待被中断")
    boot_id = manager.control.identity()
    print("HOST_GUEST_VSOCK_TLS_IDENTITY_OK", boot_id, flush=True)
    rejected = subprocess.run(
        ["openssl", "s_client", "-quiet", "-verify_return_error", "-connect",
         "127.0.0.1:" + str(arguments.control_port), "-servername", manager.control.guest_name,
         "-CAfile", str(arguments.credentials / "host/ca.pem")],
        input=b"POST /internal/v1/guest/identity HTTP/1.0\r\n\r\n", capture_output=True, timeout=15,
    )
    if rejected.returncode == 0 or b"verify return:1" not in rejected.stderr or b"200 OK" in rejected.stdout:
        raise ValueError("没有客户端证书的连接未被拒绝")
    if manager.control.identity() != boot_id:
        raise ValueError("客体启动身份已经变化")
    print("HOST_GUEST_MISSING_CERTIFICATE_REJECTED", flush=True)
    if arguments.runtime_probe:
        print(runtime.result(timeout=30), flush=True)
finally:
    if manager is not None:
        manager.stop()
        print("VM_MANAGER_GRACEFUL_STOP_OK", flush=True)
    if listener is not None:
        listener.close()
    if executor is not None:
        executor.shutdown(wait=True)
