from __future__ import annotations

import filelock
import secrets
import socket
from typing import Set

recent_ports: Set[int] = set()


def find_available_listen_port(name: str = "free") -> int:
    global recent_ports

    lock = filelock.FileLock("bind.lock")
    with lock:
        while True:
            port = secrets.randbelow(0xFFFF - 1024) + 1024
            if port in recent_ports:
                continue

            with socket.socket() as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(("127.0.0.1", port))
                except OSError:
                    recent_ports.add(port)
                    continue

            recent_ports.add(port)
            print(f"{name} port: {port}")
            return port
