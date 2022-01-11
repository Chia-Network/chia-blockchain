from dataclasses import dataclass
import logging
from typing import Dict

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain import Blockchain
from chia.consensus.constants import ConsensusConstants
from chia.full_node.block_store import BlockStore
from chia.full_node.hint_store import HintStore
from chia.util.ints import uint32
from chia.util.netspace import estimate_network_space_bytes
from chia.util.prometheus_server import PrometheusServer, Gauge

# Default port for the full_node prometheus exporter
DEFAULT_PROMETHEUS_PORT = 9914


@dataclass
class PrometheusFullNode:
    server: PrometheusServer

    block_store: BlockStore
    blockchain: Blockchain
    constants: ConsensusConstants
    hint_store: HintStore

    _height: Gauge
    _compact_blocks: Gauge
    _uncompact_blocks: Gauge
    _netspace_mib: Gauge
    _difficulty: Gauge
    _mempool_size: Gauge
    _mempool_cost: Gauge
    _mempool_min_fee: Gauge
    _block_percent_full: Gauge
    _hint_count: Gauge

    @classmethod
    def create(
        cls,
        config: Dict,
        log: logging.Logger,
        block_store: BlockStore,
        blockchain: Blockchain,
        constants: ConsensusConstants,
        hint_store: HintStore,
    ):
        enabled = config.get("start_prometheus_server", False)
        port = config.get("prometheus_exporter_port", DEFAULT_PROMETHEUS_PORT)
        prometheus_server = PrometheusServer("full_node", enabled, port, log)

        return cls(
            server=prometheus_server,
            block_store=block_store,
            blockchain=blockchain,
            constants=constants,
            hint_store=hint_store,
            _height=prometheus_server.new_gauge("height", "this node's current peak height"),
            _compact_blocks=prometheus_server.new_gauge("compact_blocks", "number of fully compact blocks in the DB"),
            _uncompact_blocks=prometheus_server.new_gauge("uncompact_blocks", "number of uncompact blocks in the DB"),
            _netspace_mib=prometheus_server.new_gauge("netspace_mib", "Estimated netspace in MiB"),
            _difficulty=prometheus_server.new_gauge("difficulty", "Current difficulty"),
            _mempool_size=prometheus_server.new_gauge("mempool_size", "Number of spends in the mempool"),
            _mempool_cost=prometheus_server.new_gauge("mempool_cost", "Total cost currently in mempool"),
            _mempool_min_fee=prometheus_server.new_gauge("mempool_min_fee", "Current minimum fee"),
            _block_percent_full=prometheus_server.new_gauge(
                "block_percent_full", "How full the last block was as a percent"
            ),
            _hint_count=prometheus_server.new_gauge("hint_count", "total number of hints in the DB"),
        )

    async def new_peak(
        self, height=None, difficulty=None, block_percent_full: float = None, record: BlockRecord = None
    ):
        if not self.server.server_enabled:
            return

        if height is not None:
            self._height.set(height)

        if difficulty is not None:
            self._difficulty.set(difficulty)

        if block_percent_full is not None:
            self._block_percent_full.set(block_percent_full)

        if record is not None:
            self._compact_blocks.set(await self.block_store.count_compactified_blocks())
            self._uncompact_blocks.set(await self.block_store.count_uncompactified_blocks())
            self._hint_count.set(await self.hint_store.count_hints())
            self._netspace_mib.set(await self._calculate_netspace(record))

    async def mempool_new_peak(self, spends=None, total_cost=None, min_fee=None):
        if not self.server.server_enabled:
            return

        if spends is not None:
            self._mempool_size.set(spends)

        if total_cost is not None:
            self._mempool_cost.set(total_cost)

        if min_fee is not None:
            self._mempool_min_fee.set(min_fee)

    async def _calculate_netspace(self, newer_block: BlockRecord):
        # Figure out current estimated netspace
        older_block_height = max(0, newer_block.height - int(4608))
        older_block_header_hash = self.blockchain.height_to_hash(uint32(older_block_height))
        if older_block_header_hash is None:
            raise ValueError(f"Older block hash not found for height {older_block_height}")
        older_block = await self.block_store.get_block_record(older_block_header_hash)
        if older_block is None:
            raise ValueError("Older block not found")

        estimated_netspace_bytes = estimate_network_space_bytes(newer_block, older_block, self.constants)

        # Converting to MiB because prometheus won't currently handle numbers large enough to deal in bytes
        netspace_mib_estimate = estimated_netspace_bytes / 1048576

        return netspace_mib_estimate
