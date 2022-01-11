from dataclasses import dataclass
import logging
from typing import Dict

from chia.util.prometheus_server import PrometheusServer, Counter

# Default port for the seeder prometheus exporter
DEFAULT_PROMETHEUS_PORT = 9920


@dataclass
class PrometheusSeeder:
    server: PrometheusServer

    _handled_requests: Counter

    @classmethod
    def create(cls, config: Dict, log: logging.Logger):
        prometheus_config = config.get("seeder_prometheus", {})
        enabled = prometheus_config.get("start_prometheus_server", False)
        port = prometheus_config.get("prometheus_exporter_port", DEFAULT_PROMETHEUS_PORT)
        prometheus_server = PrometheusServer("seeder", enabled, port, log)

        return cls(
            server=prometheus_server,
            _handled_requests=prometheus_server.new_counter(
                "handled_requests", "total requests handled by this server since starting"
            ),
        )

    async def handled_request(self):
        if not self.server.server_enabled:
            return

        self._handled_requests.inc()
