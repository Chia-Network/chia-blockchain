import sys
from typing import Tuple


def parse_host_port(api) -> Tuple[str, int]:
    host: str = sys.argv[1] if len(sys.argv) >= 3 else api.host
    port: int = int(sys.argv[2]) if len(sys.argv) >= 3 else api.port
    return (host, port)
