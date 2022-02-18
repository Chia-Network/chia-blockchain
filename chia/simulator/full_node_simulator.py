from typing import List, Optional

from chia.consensus.block_record import BlockRecord
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.full_node_protocol import RespondBlock
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.types.full_block import FullBlock
from chia.util.api_decorators import api_request
from chia.util.ints import uint8


class FullNodeSimulator(FullNodeAPI):
    def __init__(self, full_node, block_tools) -> None:
        super().__init__(full_node)
        self.bt = block_tools
        self.full_node = full_node
        self.config = full_node.config
        self.time_per_block = None
        if "simulation" in self.config and self.config["simulation"] is True:
            self.use_current_time = True
        else:
            self.use_current_time = False

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

    @api_request
    async def farm_new_transaction_block(self, request: FarmNewBlockProtocol):
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
            mempool_bundle = await self.full_node.mempool_manager.create_bundle_from_mempool(curr.header_hash)
            if mempool_bundle is None:
                spend_bundle = None
            else:
                spend_bundle = mempool_bundle[0]

            current_blocks = await self.get_all_full_blocks()
            target = request.puzzle_hash
            more = self.bt.get_consecutive_blocks(
                1,
                time_per_block=self.time_per_block,
                transaction_data=spend_bundle,
                farmer_reward_puzzle_hash=target,
                pool_reward_puzzle_hash=target,
                block_list_input=current_blocks,
                guarantee_transaction_block=True,
                current_time=self.use_current_time,
                previous_generator=self.full_node.full_node_store.previous_generator,
            )
            rr = RespondBlock(more[-1])
        await self.full_node.respond_block(rr)

    @api_request
    async def farm_new_block(self, request: FarmNewBlockProtocol):
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
                current_time=self.use_current_time,
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
