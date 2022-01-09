import logging
from typing import Dict
from prometheus_client import start_http_server, Gauge

# Default port for the full_node prometheus exporter
DEFAULT_PROMETHEUS_PORT = 9914


class Prometheus:
    log: logging.Logger
    start_prometheus_server: bool
    prometheus_port: int

    def __init__(self, config: Dict, log: logging.Logger):
        self.log = log

        if "start_prometheus_server" in config:
            self.start_prometheus_server = config["start_prometheus_server"]
        else:
            self.start_prometheus_server = True

        if "prometheus_exporter_port" in config:
            self.prometheus_port = config["prometheus_exporter_port"]
        else:
            self.prometheus_port = DEFAULT_PROMETHEUS_PORT

        self.height = self.new_gauge('height', "this node's current peak height")
        self.compact_blocks = self.new_gauge('compact_blocks', 'number of fully compact blocks in the DB')
        self.uncompact_blocks = self.new_gauge('uncompact_blocks', 'number of uncompact blocks in the DB')
        self.netspace_mib = self.new_gauge('netspace_mib', 'Estimated netspace in MiB')
        self.difficulty = self.new_gauge('difficulty', 'Current difficulty')
        self.mempool_size = self.new_gauge('mempool_size', 'Number of spends in the mempool')
        self.mempool_cost = self.new_gauge('mempool_cost', 'Total cost currently in mempool')
        self.mempool_min_fee = self.new_gauge('mempool_min_fee', 'Current minimum fee')
        self.block_percent_full = self.new_gauge('block_percent_full', 'How full the last block was as a percent')
        self.hint_count = self.new_gauge('hint_count', 'total number of hints in the DB')

    async def start_server(self):
        # Start prometheus exporter server for the full node
        if self.start_prometheus_server:
            self.log.info(f"Starting full_node prometheus server on port {self.prometheus_port}")
            start_http_server(self.prometheus_port)

    def new_gauge(self, name: str, description: str) -> Gauge:
        return Gauge(f"chia_node_{name}", description)
