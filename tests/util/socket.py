import secrets
import socket
from typing import Set

from chia.util.ints import uint16

recent_ports: Set[int] = set()


def find_available_listen_port(name: str = "free") -> uint16:
    global recent_ports

    while True:
        port = uint16(secrets.randbits(15) + 2000)
        if port in recent_ports:
            continue

        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                recent_ports.add(port)
                continue

        recent_ports.add(port)
        print(f"{name} port: {port}")
        return port
