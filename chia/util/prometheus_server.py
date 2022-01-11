from dataclasses import dataclass
import logging
from typing import Tuple
from prometheus_client import start_http_server, Counter, Gauge


@dataclass
class PrometheusServer:
    service_name: str
    server_enabled: bool
    server_port: int
    log: logging.Logger

    async def start_server(self):
        # Start prometheus exporter server for the full node
        if self.server_enabled:
            self.log.info(f"Starting full_node prometheus server on port {self.server_port}")
            start_http_server(self.server_port)

    def new_gauge(self, name: str, description: str, labelnames: Tuple = ()) -> Gauge:
        return Gauge(name, description, labelnames, "chia", self.service_name)

    def new_counter(self, name: str, description: str, labelnames: Tuple = ()) -> Counter:
        return Counter(name, description, labelnames, "chia", self.service_name)
