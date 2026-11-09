import argparse
import asyncio
import socket
import time
from pathlib import Path

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("vm_id")
    arguments = parser.parse_args()
    directory = Path("/run/boss-vm") / arguments.vm_id
    deadline = time.monotonic() + 20
    names = ("ca.pem", "certificate.pem", "private-key.pem", "peer-certificate.pem")
    while not all((directory / name).is_file() for name in names) and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    if not all((directory / name).is_file() for name in names):
        raise TimeoutError("客体通信凭据未就绪")
    from hermes_guest_proxy import HermesGuestRuntimeProxy
    from hermes_vm_credentials import load_vm_credentials
    credentials = load_vm_credentials(directory, arguments.vm_id, "guest")
    proxy = HermesGuestRuntimeProxy(credentials.client, credentials.peer_name, credentials.peer_sha256, 1024)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = await proxy.listen(listener)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            payload = b"BOSS_VSOCK_RUNTIME_CHECK"
            writer.write(payload)
            await writer.drain()
            if await asyncio.wait_for(reader.readexactly(len(payload)), 15) != payload:
                raise ValueError("客体运行通信内容不匹配")
            print("GUEST_VSOCK_RUNTIME_TLS_OK", flush=True)
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()


asyncio.run(main())
