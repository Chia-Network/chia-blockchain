import asyncio
import time
from typing import Dict, List, Optional

from chia.consensus.block_record import BlockRecord
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.full_node_protocol import RespondBlock
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.util.api_decorators import api_request
from chia.util.config import lock_and_load_config, save_config
from chia.util.ints import uint8
from tests.block_tools import BlockTools


class FullNodeSimulator(FullNodeAPI):
    def __init__(self, full_node: FullNode, block_tools: BlockTools, config: Dict) -> None:
        super().__init__(full_node)
        self.bt = block_tools
        self.full_node = full_node
        self.config = config
        self.time_per_block = None
        self.full_node.simulator_transaction_callback = self.autofarm_transaction
        self.use_current_time: bool = self.config.get("simulator", {}).get("use_current_time", False)
        self.auto_farm: bool = self.config.get("simulator", {}).get("auto_farm", False)

    async def get_all_full_blocks(self) -> List[FullBlock]:
        peak: Optional[BlockRecord] = self.full_node.blockchain.get_peak()
        if peak is None:
            return []
        blocks = []
        peak_block = await self.full_node.blockchain.get_full_block(peak.header_hash)
        if peak_block is None:
            return []
        blocks.append(peak_block)
        current = peak_block
        while True:
            prev = await self.full_node.blockchain.get_full_block(current.prev_header_hash)
            if prev is not None:
                current = prev
                blocks.append(prev)
            else:
                break

        blocks.reverse()
        return blocks

    async def autofarm_transaction(self, spend_name: bytes32) -> None:
        if self.auto_farm:
            self.log.info(f"Autofarm triggered by tx-id: {spend_name.hex()}")
            new_block = FarmNewBlockProtocol(self.bt.farmer_ph)
            await self.farm_new_transaction_block(new_block, force_wait_for_timestamp=True)

    async def update_autofarm_config(self, enable_autofarm: bool) -> bool:
        if enable_autofarm == self.auto_farm:
            return self.auto_farm
        else:
            self.auto_farm = enable_autofarm
            with lock_and_load_config(self.bt.root_path, "config.yaml") as config:
                if "simulator" in config:
                    config["simulator"]["auto_farm"] = self.auto_farm
                save_config(self.bt.root_path, "config.yaml", config)
            self.config = config
            if self.auto_farm is True and self.full_node.mempool_manager.mempool.total_mempool_cost > 0:
                # if mempool is not empty and auto farm was just enabled, farm a block
                await self.farm_new_transaction_block(FarmNewBlockProtocol(self.bt.farmer_ph))
            return self.auto_farm

    @api_request
    async def farm_new_transaction_block(self, request: FarmNewBlockProtocol, force_wait_for_timestamp: bool = False):
        async with self.full_node._blockchain_lock_high_priority:
            self.log.info("Farming new block!")
            current_blocks = await self.get_all_full_blocks()
            if len(current_blocks) == 0:
                genesis = self.bt.get_consecutive_blocks(uint8(1))[0]
                pre_validation_results: List[
                    PreValidationResult
                ] = await self.full_node.blockchain.pre_validate_blocks_multiprocessing(
                    [genesis], {}, validate_signatures=True
                )
                assert pre_validation_results is not None
                await self.full_node.blockchain.receive_block(genesis, pre_validation_results[0])

            peak = self.full_node.blockchain.get_peak()
            assert peak is not None
            curr: BlockRecord = peak
            while not curr.is_transaction_block:
                curr = self.full_node.blockchain.block_record(curr.prev_hash)
            current_time = self.use_current_time
            time_per_block = self.time_per_block
            assert curr.timestamp is not None
            if int(time.time()) <= int(curr.timestamp):
                if force_wait_for_timestamp:
                    await asyncio.sleep(1)
                else:
                    current_time = False
                    time_per_block = 1
            mempool_bundle = await self.full_node.mempool_manager.create_bundle_from_mempool(curr.header_hash)
            if mempool_bundle is None:
                spend_bundle = None
            else:
                spend_bundle = mempool_bundle[0]

            current_blocks = await self.get_all_full_blocks()
            target = request.puzzle_hash
            more = self.bt.get_consecutive_blocks(
                1,
                time_per_block=time_per_block,
                transaction_data=spend_bundle,
                farmer_reward_puzzle_hash=target,
                pool_reward_puzzle_hash=target,
                block_list_input=current_blocks,
                guarantee_transaction_block=True,
                current_time=current_time,
                previous_generator=self.full_node.full_node_store.previous_generator,
            )
            rr = RespondBlock(more[-1])
        await self.full_node.respond_block(rr)

    @api_request
    async def farm_new_block(self, request: FarmNewBlockProtocol, force_wait_for_timestamp: bool = False):
        async with self.full_node._blockchain_lock_high_priority:
            self.log.info("Farming new block!")
            current_blocks = await self.get_all_full_blocks()
            if len(current_blocks) == 0:
                genesis = self.bt.get_consecutive_blocks(uint8(1))[0]
                pre_validation_results: List[
                    PreValidationResult
                ] = await self.full_node.blockchain.pre_validate_blocks_multiprocessing(
                    [genesis], {}, validate_signatures=True
                )
                assert pre_validation_results is not None
                await self.full_node.blockchain.receive_block(genesis, pre_validation_results[0])

            peak = self.full_node.blockchain.get_peak()
            assert peak is not None
            curr: BlockRecord = peak
            while not curr.is_transaction_block:
                curr = self.full_node.blockchain.block_record(curr.prev_hash)
            current_time = self.use_current_time
            time_per_block = self.time_per_block
            assert curr.timestamp is not None
            if int(time.time()) <= int(curr.timestamp):
                if force_wait_for_timestamp:
                    await asyncio.sleep(1)
                else:
                    current_time = False
                    time_per_block = 1
            mempool_bundle = await self.full_node.mempool_manager.create_bundle_from_mempool(curr.header_hash)
            if mempool_bundle is None:
                spend_bundle = None
            else:
                spend_bundle = mempool_bundle[0]
            current_blocks = await self.get_all_full_blocks()
            target = request.puzzle_hash
            more = self.bt.get_consecutive_blocks(
                1,
                transaction_data=spend_bundle,
                farmer_reward_puzzle_hash=target,
                pool_reward_puzzle_hash=target,
                block_list_input=current_blocks,
                current_time=current_time,
                time_per_block=time_per_block,
            )
            rr: RespondBlock = RespondBlock(more[-1])
        await self.full_node.respond_block(rr)

    @api_request
    async def reorg_from_index_to_new_index(self, request: ReorgProtocol):
        new_index = request.new_index
        old_index = request.old_index
        coinbase_ph = request.puzzle_hash

        current_blocks = await self.get_all_full_blocks()
        block_count = new_index - old_index

        more_blocks = self.bt.get_consecutive_blocks(
            block_count,
            farmer_reward_puzzle_hash=coinbase_ph,
            pool_reward_puzzle_hash=coinbase_ph,
            block_list_input=current_blocks[: old_index + 1],
            force_overflow=True,
            guarantee_transaction_block=True,
            seed=32 * b"1",
        )

        for block in more_blocks:
            await self.full_node.respond_block(RespondBlock(block))
