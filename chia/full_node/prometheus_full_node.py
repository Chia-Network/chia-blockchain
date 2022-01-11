from dataclasses import dataclass
import logging
from typing import Dict

from chia.util.prometheus_server import PrometheusServer, Gauge

# Default port for the full_node prometheus exporter
DEFAULT_PROMETHEUS_PORT = 9914


@dataclass
class PrometheusFullNode:
    server: PrometheusServer
    height: Gauge
    compact_blocks: Gauge
    uncompact_blocks: Gauge
    netspace_mib: Gauge
    difficulty: Gauge
    mempool_size: Gauge
    mempool_cost: Gauge
    mempool_min_fee: Gauge
    block_percent_full: Gauge
    hint_count: Gauge

    @classmethod
    def create(cls, config: Dict, log: logging.Logger):
        enabled = config.get("start_prometheus_server", False)
        port = config.get("prometheus_exporter_port", DEFAULT_PROMETHEUS_PORT)
        prometheus_server = PrometheusServer("full_node", enabled, port, log)

        return cls(
            server=prometheus_server,
            height=prometheus_server.new_gauge("height", "this node's current peak height"),
            compact_blocks=prometheus_server.new_gauge("compact_blocks", "number of fully compact blocks in the DB"),
            uncompact_blocks=prometheus_server.new_gauge("uncompact_blocks", "number of uncompact blocks in the DB"),
            netspace_mib=prometheus_server.new_gauge("netspace_mib", "Estimated netspace in MiB"),
            difficulty=prometheus_server.new_gauge("difficulty", "Current difficulty"),
            mempool_size=prometheus_server.new_gauge("mempool_size", "Number of spends in the mempool"),
            mempool_cost=prometheus_server.new_gauge("mempool_cost", "Total cost currently in mempool"),
            mempool_min_fee=prometheus_server.new_gauge("mempool_min_fee", "Current minimum fee"),
            block_percent_full=prometheus_server.new_gauge(
                "block_percent_full", "How full the last block was as a percent"
            ),
            hint_count=prometheus_server.new_gauge("hint_count", "total number of hints in the DB"),
        )
