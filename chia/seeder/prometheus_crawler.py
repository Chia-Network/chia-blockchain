from dataclasses import dataclass
import logging
from typing import Dict

from chia.util.prometheus_server import PrometheusServer, Gauge

# Default port for the crawler prometheus exporter
DEFAULT_PROMETHEUS_PORT = 9919


@dataclass
class PrometheusCrawler:
    server: PrometheusServer
    total_5d: Gauge
    reliable_nodes: Gauge
    ipv4_5d: Gauge
    ipv6_5d: Gauge
    version_buckets: Gauge

    @classmethod
    def create(cls, config: Dict, log: logging.Logger):
        prometheus_config = config.get("crawler_prometheus", {})
        enabled = prometheus_config.get("start_prometheus_server", False)
        port = prometheus_config.get("prometheus_exporter_port", DEFAULT_PROMETHEUS_PORT)
        prometheus_server = PrometheusServer("crawler", enabled, port, log)

        return cls(
            server=prometheus_server,
            total_5d=prometheus_server.new_gauge(
                "total_nodes_5_days",
                "Total nodes gossiped with timestamp in the last 5 days with respond_peers messages",
            ),
            reliable_nodes=prometheus_server.new_gauge(
                "reliable_nodes", "High quality reachable nodes, used by DNS introducer in replies"
            ),
            ipv4_5d=prometheus_server.new_gauge(
                "ipv4_nodes_5_days",
                "IPv4 addresses gossiped with timestamp in the last 5 days with respond_peers messages",
            ),
            ipv6_5d=prometheus_server.new_gauge(
                "ipv6_nodes_5_days",
                "IPv6 addresses gossiped with timestamp in the last 5 days with respond_peers messages",
            ),
            version_buckets=prometheus_server.new_gauge(
                "version_bucket", "Number of peers on a particular version", ("version",)
            ),
        )
