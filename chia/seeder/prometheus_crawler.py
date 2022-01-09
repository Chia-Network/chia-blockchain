import logging
from typing import Dict

from chia.util.prometheus import Prometheus

# Default port for the crawler prometheus exporter
DEFAULT_PROMETHEUS_PORT = 9919


class PrometheusCrawler(Prometheus):
    def __init__(self, config: Dict, log: logging.Logger):
        prometheus_config = config.get("crawler_prometheus", {})
        enabled = prometheus_config.get("start_prometheus_server", False)
        port = prometheus_config.get("prometheus_exporter_port", DEFAULT_PROMETHEUS_PORT)
        super().__init__("crawler", enabled, port, log)

        self.total_5d = self.new_gauge(
            "total_nodes_5_days", "Total nodes gossiped with timestamp in the last 5 days with respond_peers messages"
        )
        self.reliable_nodes = self.new_gauge(
            "reliable_nodes", "High quality reachable nodes, used by DNS introducer in replies"
        )
        self.ipv4_5d = self.new_gauge(
            "ipv4_nodes_5_days", "IPv4 addresses gossiped with timestamp in the last 5 days with respond_peers messages"
        )
        self.ipv6_5d = self.new_gauge(
            "ipv6_nodes_5_days", "IPv6 addresses gossiped with timestamp in the last 5 days with respond_peers messages"
        )
        self.version_buckets = self.new_gauge("version_bucket", "Number of peers on a particular version", ("version",))
