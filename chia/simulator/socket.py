from __future__ import annotations

import random
import socket
import time
from typing import Set

recent_ports: Set[int] = set()


def find_available_listen_port(name: str = "free") -> int:
    global recent_ports

    while True:
        port = random.randint(49152, 65535)
        if port in recent_ports:
            continue

        errored = False
        for _ in range(10):
            with socket.socket() as s:
                try:
                    s.bind(("127.0.0.1", port))
                except OSError:
                    recent_ports.add(port)
                    errored = True
                    break
                time.sleep(0.5)

        if errored:
            continue
        recent_ports.add(port)
        print(f"{name} port: {port}")
        return port
