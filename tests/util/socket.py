import random
import secrets
import socket
from typing import Set

recent_ports: Set[int] = set()
prng = random.Random()
prng.seed(secrets.randbits(32))


def find_available_listen_port(name: str = "free") -> int:
    global recent_ports

    while True:
        port = prng.randint(2000, 65535)
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
