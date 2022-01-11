from dataclasses import dataclass
import logging
from typing import Dict, Optional

from chia.util.prometheus_server import PrometheusServer, Gauge

# Default port for the crawler prometheus exporter
DEFAULT_PROMETHEUS_PORT = 9919


@dataclass
class PrometheusCrawler:
    server: PrometheusServer
    minimum_version_count: int

    _total_5d: Gauge
    _reliable_nodes: Gauge
    _ipv4_5d: Gauge
    _ipv6_5d: Gauge
    _version_buckets: Gauge

    @classmethod
    def create(cls, config: Dict, log: logging.Logger, minimum_version_count: int):
        prometheus_config = config.get("crawler_prometheus", {})
        enabled = prometheus_config.get("start_prometheus_server", False)
        port = prometheus_config.get("prometheus_exporter_port", DEFAULT_PROMETHEUS_PORT)
        prometheus_server = PrometheusServer("crawler", enabled, port, log)

        return cls(
            server=prometheus_server,
            minimum_version_count=minimum_version_count,
            _total_5d=prometheus_server.new_gauge(
                "total_nodes_5_days",
                "Total nodes gossiped with timestamp in the last 5 days with respond_peers messages",
            ),
            _reliable_nodes=prometheus_server.new_gauge(
                "reliable_nodes", "High quality reachable nodes, used by DNS introducer in replies"
            ),
            _ipv4_5d=prometheus_server.new_gauge(
                "ipv4_nodes_5_days",
                "IPv4 addresses gossiped with timestamp in the last 5 days with respond_peers messages",
            ),
            _ipv6_5d=prometheus_server.new_gauge(
                "ipv6_nodes_5_days",
                "IPv6 addresses gossiped with timestamp in the last 5 days with respond_peers messages",
            ),
            _version_buckets=prometheus_server.new_gauge(
                "version_bucket", "Number of peers on a particular version", ("version",)
            ),
        )

    async def crawling_batch_complete(
        self, reliable_nodes=None, total_5d=None, ipv4_5d=None, ipv6_5d=None, versions=Optional[Dict[str, int]]
    ):
        if not self.server.server_enabled:
            return

        if reliable_nodes is not None:
            self._reliable_nodes.set(reliable_nodes)

        if total_5d is not None:
            self._total_5d.set(total_5d)

        if ipv4_5d is not None:
            self._ipv4_5d.set(ipv4_5d)

        if ipv6_5d is not None:
            self._ipv6_5d.set(ipv6_5d)

        if versions is not None:
            for version, count in sorted(versions.items(), key=lambda kv: kv[1], reverse=True):
                if count >= self.minimum_version_count:
                    self._version_buckets.labels(version).set(count)
