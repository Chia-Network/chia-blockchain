import asyncio
import time
from typing import Dict, List, Optional, Tuple

from chia.consensus.block_record import BlockRecord
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.full_node_protocol import RespondBlock
from chia.simulator.block_tools import BlockTools
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, GetAllCoinsProtocol, ReorgProtocol
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.full_block import FullBlock
from chia.util.api_decorators import api_request
from chia.util.config import lock_and_load_config, save_config
from chia.util.ints import uint8, uint32, uint128


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
    async def get_all_coins(self, request: GetAllCoinsProtocol) -> List[CoinRecord]:
        return await self.full_node.coin_store.get_all_coins(request.include_spent_coins)

    async def revert_block_height(self, new_height: uint32) -> None:
        """
        This completely deletes blocks from the blockchain.
        While reorgs are preferred, this is also an option
        Note: This does not broadcast the changes, and all wallets will need to be wiped.
        """
        async with self.full_node._blockchain_lock_high_priority:
            peak_height: Optional[uint32] = self.full_node.blockchain.get_peak_height()
            if peak_height is None:
                raise ValueError("We cant revert without any blocks.")
            elif peak_height - 1 < new_height:
                raise ValueError("Cannot revert to a height greater than the current peak height.")
            elif new_height < 1:
                raise ValueError("Cannot revert to a height less than 1.")
            block_record: BlockRecord = self.full_node.blockchain.height_to_block_record(new_height)
            # remove enough data to allow a bunch of blocks to be wiped.
            async with self.full_node.block_store.db_wrapper.writer():
                # set coinstore
                await self.full_node.coin_store.rollback_to_block(new_height)
                # set blockstore to new height
                await self.full_node.block_store.rollback(new_height)
                await self.full_node.block_store.set_peak(block_record.header_hash)
                self.full_node.blockchain._peak_height = new_height
        # reload mempool
        await self.full_node.mempool_manager.new_peak(block_record, None)

    async def get_all_puzzle_hashes(self) -> Dict[bytes32, Tuple[uint128, int]]:
        # puzzle_hash, (total_amount, num_transactions)
        ph_total_amount: Dict[bytes32, Tuple[uint128, int]] = {}
        all_non_spent_coins: List[CoinRecord] = await self.get_all_coins(GetAllCoinsProtocol(False))
        for cr in all_non_spent_coins:
            if cr.coin.puzzle_hash not in ph_total_amount:
                ph_total_amount[cr.coin.puzzle_hash] = (uint128(cr.coin.amount), 1)
            else:
                dict_value: Tuple[uint128, int] = ph_total_amount[cr.coin.puzzle_hash]
                ph_total_amount[cr.coin.puzzle_hash] = (uint128(cr.coin.amount + dict_value[0]), dict_value[1] + 1)
        return ph_total_amount

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
        seed = request.seed
        if seed is None:
            seed = bytes32(32 * b"1")

        current_blocks = await self.get_all_full_blocks()
        block_count = new_index - old_index

        more_blocks = self.bt.get_consecutive_blocks(
            block_count,
            farmer_reward_puzzle_hash=coinbase_ph,
            pool_reward_puzzle_hash=coinbase_ph,
            block_list_input=current_blocks[: old_index + 1],
            force_overflow=True,
            guarantee_transaction_block=True,
            seed=seed,
        )

        for block in more_blocks:
            await self.full_node.respond_block(RespondBlock(block))
