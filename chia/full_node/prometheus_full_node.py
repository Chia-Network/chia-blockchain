import logging
from typing import Dict

from chia.util.prometheus import Prometheus

# Default port for the full_node prometheus exporter
DEFAULT_PROMETHEUS_PORT = 9914


class PrometheusFullNode(Prometheus):

    def __init__(self, config: Dict, log: logging.Logger):
        enabled = False if "start_prometheus_server" not in config else config["start_prometheus_server"]
        port = (
            DEFAULT_PROMETHEUS_PORT
            if "prometheus_exporter_port" not in config
            else config["prometheus_exporter_port"]
        )
        super().__init__("full_node", enabled, port, log)

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

