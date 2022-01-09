import logging
from typing import Dict

from chia.util.prometheus import Prometheus

# Default port for the seeder prometheus exporter
DEFAULT_PROMETHEUS_PORT = 9920


class PrometheusSeeder(Prometheus):
    def __init__(self, config: Dict, log: logging.Logger):
        if "seeder_prometheus" in config and "start_prometheus_server" in config["seeder_prometheus"]:
            enabled = config["seeder_prometheus"]["start_prometheus_server"]
        else:
            enabled = False

        if "seeder_prometheus" in config and "prometheus_exporter_port" in config["seeder_prometheus"]:
            port = config["seeder_prometheus"]["prometheus_exporter_port"]
        else:
            port = DEFAULT_PROMETHEUS_PORT

        super().__init__("seeder", enabled, port, log)

        self.handled_requests = self.new_counter(
            "handled_requests", "total requests handled by this server since starting"
        )
