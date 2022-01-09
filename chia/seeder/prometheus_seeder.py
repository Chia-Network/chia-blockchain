import logging
from typing import Dict

from chia.util.prometheus import Prometheus

# Default port for the seeder prometheus exporter
DEFAULT_PROMETHEUS_PORT = 9920


class PrometheusSeeder(Prometheus):
    def __init__(self, config: Dict, log: logging.Logger):
        prometheus_config = config.get("seeder_prometheus", {})
        enabled = prometheus_config.get("start_prometheus_server", False)
        port = prometheus_config.get("prometheus_exporter_port", DEFAULT_PROMETHEUS_PORT)
        super().__init__("seeder", enabled, port, log)

        self.handled_requests = self.new_counter(
            "handled_requests", "total requests handled by this server since starting"
        )
