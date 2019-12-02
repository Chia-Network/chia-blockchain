import socket
from src.types.sized_bytes import bytes16

mapped_v4_prefix = b'\0' * 10 + b'\xff\xff'


def ip_to_str(ip: bytes16) -> str:
    if ip[:12] == mapped_v4_prefix:
        return socket.inet_ntop(socket.AF_INET, ip[12:])
    return socket.inet_ntop(socket.AF_INET6, ip)


def ip_from_str(ip: str) -> bytes16:
    for af in socket.AF_INET, socket.AF_INET6:
        try:
            ip_bin = socket.inet_pton(af, ip)
            if af == socket.AF_INET:
                ip_bin = mapped_v4_prefix + ip_bin
            return bytes16(ip_bin)
        except OSError:
            pass
    raise ValueError(f"Invalid IP address: {ip}")
