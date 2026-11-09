import getpass
import hashlib
import hmac
import socket

token = getpass.getpass("Probe token: ").encode()
with socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM) as connection:
    connection.settimeout(10)
    connection.connect((socket.VMADDR_CID_HOST, 1024))
    challenge = b""
    while len(challenge) < 32:
        part = connection.recv(32 - len(challenge))
        if not part:
            raise RuntimeError("challenge incomplete")
        challenge += part
    connection.sendall(hmac.digest(token, challenge, hashlib.sha256))
    print("VSOCK_RESPONSE", connection.recv(16).decode())
