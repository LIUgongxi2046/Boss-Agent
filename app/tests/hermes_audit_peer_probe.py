import socket
import sys
import time


with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
    connection.connect(sys.argv[1])
    connection.sendall(b"ready")
    time.sleep(5)
