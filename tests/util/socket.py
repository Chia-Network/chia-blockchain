import socket


def find_available_listen_port(name: str = "free") -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    addr = s.getsockname()
    assert addr[1] > 0
    s.close()
    print(f"{name} port: {addr[1]}")
    return int(addr[1])
