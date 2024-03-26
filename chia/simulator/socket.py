from __future__ import annotations

import socket
from contextlib import closing
from typing import Set

recent_ports: Set[int] = set()


def find_available_listen_port(name: str = "free") -> int:
    global recent_ports

    while True:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            try:
                s.bind(("", 0))
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                port = s.getsockname()[1]
            except OSError:
                continue

        if port in recent_ports:
            continue

        recent_ports.add(port)
        print(f"{name} port: {port}")
        return port  # type: ignore
