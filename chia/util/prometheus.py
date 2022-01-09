import logging
from prometheus_client import start_http_server, Gauge


class Prometheus:
    service_name: str
    server_enabled: bool
    server_port: int
    log: logging.Logger

    def __init__(self, service_name: str, server_enabled: bool, server_port: int, log: logging.Logger):
        self.service_name = service_name
        self.log = log
        self.server_enabled = server_enabled
        self.server_port = server_port

    async def start_server(self):
        # Start prometheus exporter server for the full node
        if self.server_enabled:
            self.log.info(f"Starting full_node prometheus server on port {self.server_port}")
            start_http_server(self.server_port)

    def new_gauge(self, name: str, description: str) -> Gauge:
        return Gauge(f"chia_{self.service_name}_{name}", description)
