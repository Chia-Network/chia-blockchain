from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any, Collection, Dict, Iterator, List, Optional, Set, Tuple

from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.full_node_protocol import RespondBlock
from chia.rpc.rpc_server import default_get_connections
from chia.server.outbound_message import NodeType
from chia.simulator.block_tools import BlockTools
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, GetAllCoinsProtocol, ReorgProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.full_block import FullBlock
from chia.types.spend_bundle import SpendBundle
from chia.util.config import lock_and_load_config, save_config
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import AmountWithPuzzlehash
from chia.wallet.wallet import Wallet


def backoff_times(
    initial: float = 0.001,
    final: float = 0.100,
    time_to_final: float = 0.5,
    clock=time.monotonic,
) -> Iterator[float]:
    # initially implemented as a simple linear backoff

    start = clock()
    delta = 0

    result_range = final - initial

    while True:
        yield min(final, initial + ((delta / time_to_final) * result_range))
        delta = clock() - start


async def wait_for_coins_in_wallet(coins: Set[Coin], wallet: Wallet):
    """Wait until all of the specified coins are simultaneously reported as spendable
    in by the wallet.

    Arguments:
        coins: The coins expected to be received.
        wallet: The wallet expected to receive the coins.
    """
    while True:
        spendable_wallet_coin_records = await wallet.wallet_state_manager.get_spendable_coins_for_wallet(
            wallet_id=wallet.id()
        )
        spendable_wallet_coins = {record.coin for record in spendable_wallet_coin_records}

        if coins.issubset(spendable_wallet_coins):
            return

        await asyncio.sleep(0.050)


class FullNodeSimulator(FullNodeAPI):
    def __init__(self, full_node: FullNode, block_tools: BlockTools, config: Dict) -> None:
        super().__init__(full_node)
        self.bt = block_tools
        self.full_node = full_node
        self.config = config
        self.time_per_block: Optional[float] = None
        self.full_node.simulator_transaction_callback = self.autofarm_transaction
        self.use_current_time: bool = self.config.get("simulator", {}).get("use_current_time", False)
        self.auto_farm: bool = self.config.get("simulator", {}).get("auto_farm", False)

    def get_connections(self, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

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
                raise ValueError("We can't revert without any blocks.")
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

    async def farm_new_transaction_block(
        self, request: FarmNewBlockProtocol, force_wait_for_timestamp: bool = False
    ) -> FullBlock:
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
        return more[-1]

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

    async def process_blocks(self, count: int, farm_to: bytes32 = bytes32([0] * 32)) -> int:
        """Process the requested number of blocks including farming to the passed puzzle
        hash. Note that the rewards for the last block will not have been processed.
        Consider `.farm_blocks()` or `.farm_rewards()` if the goal is to receive XCH at
        an address.

        Arguments:
            count: The number of blocks to process.
            farm_to: The puzzle hash to farm the block rewards to.

        Returns:
            The total number of reward mojos for the processed blocks.
        """
        rewards = 0
        height = uint32(0)

        if count == 0:
            return rewards

        for _ in range(count):
            block: FullBlock = await self.farm_new_transaction_block(FarmNewBlockProtocol(farm_to))
            height = uint32(block.height)
            rewards += calculate_pool_reward(height) + calculate_base_farmer_reward(height)

        while True:
            peak_height = self.full_node.blockchain.get_peak_height()
            if peak_height is None:
                raise RuntimeError("Peak height still None after processing at least one block")

            if peak_height >= height:
                break

            await asyncio.sleep(0.050)

        return rewards

    async def farm_blocks(self, count: int, wallet: Wallet) -> int:
        """Farm the requested number of blocks to the passed wallet. This will
        process additional blocks as needed to process the reward transactions
        and also wait for the rewards to be present in the wallet.

        Arguments:
            count: The number of blocks to farm.
            wallet: The wallet to farm the block rewards to.

        Returns:
            The total number of reward mojos farmed to the requested address.
        """
        if count == 0:
            return 0

        rewards = await self.process_blocks(count=count, farm_to=await wallet.get_new_puzzlehash())
        await self.process_blocks(count=1)

        peak_height = self.full_node.blockchain.get_peak_height()
        if peak_height is None:
            raise RuntimeError("Peak height still None after processing at least one block")

        coin_records = await self.full_node.coin_store.get_coins_added_at_height(height=peak_height)
        block_reward_coins = {record.coin for record in coin_records}

        await wait_for_coins_in_wallet(coins=block_reward_coins, wallet=wallet)

        return rewards

    async def farm_rewards(self, amount: int, wallet: Wallet) -> int:
        """Farm at least the requested amount of mojos to the passed wallet. Extra
        mojos will be received based on the block rewards at the present block height.
        The rewards will be present in the wall before returning.

        Arguments:
            amount: The minimum number of mojos to farm.
            wallet: The wallet to farm the block rewards to.

        Returns:
            The total number of reward mojos farmed to the requested wallet.
        """
        rewards = 0

        if amount == 0:
            return rewards

        height_before = self.full_node.blockchain.get_peak_height()
        if height_before is None:
            height_before = uint32(0)

        for count in itertools.count(1):
            height = uint32(height_before + count)
            rewards += calculate_pool_reward(height) + calculate_base_farmer_reward(height)

            if rewards >= amount:
                await self.farm_blocks(count=count, wallet=wallet)
                return rewards

        raise Exception("internal error")

    async def wait_transaction_records_entered_mempool(self, records: Collection[TransactionRecord]) -> None:
        """Wait until the transaction records have entered the mempool.  Transaction
        records with no spend bundle are ignored.

        Arguments:
            records: The transaction records to wait for.
        """
        ids_to_check: Set[bytes32] = set()
        for record in records:
            if record.spend_bundle is None:
                continue

            ids_to_check.add(record.spend_bundle.name())

        while True:
            found = set()
            for spend_bundle_name in ids_to_check:
                tx = self.full_node.mempool_manager.get_spendbundle(spend_bundle_name)
                if tx is not None:
                    found.add(spend_bundle_name)
            ids_to_check = ids_to_check.difference(found)

            if len(ids_to_check) == 0:
                return

            await asyncio.sleep(0.050)

    async def process_transaction_records(self, records: Collection[TransactionRecord] = ()) -> None:
        """Process the specified transaction records and wait until they have been
        included in a block.

        Arguments:
            records: The transaction records to process.
        """

        coins_to_wait_for: Set[Coin] = set()
        for record in records:
            if record.spend_bundle is None:
                continue

            coins_to_wait_for.update(record.spend_bundle.additions())

        await self.wait_transaction_records_entered_mempool(records=records)

        return await self.process_coin_spends(coins=coins_to_wait_for)

    async def process_spend_bundles(self, bundles: Collection[SpendBundle] = ()) -> None:
        """Process the specified spend bundles and wait until they have been included
        in a block.

        Arguments:
            bundles: The spend bundles to process.
        """

        coins_to_wait_for: Set[Coin] = {addition for bundle in bundles for addition in bundle.additions()}
        return await self.process_coin_spends(coins=coins_to_wait_for)

    async def process_coin_spends(self, coins: Collection[Coin] = ()) -> None:
        """Process the specified coin names and wait until they have been created in a
        block.

        Arguments:
            coin_names: The coin names to process.
        """

        coin_set = set(coins)
        coin_store = self.full_node.coin_store

        while True:
            await self.process_blocks(count=1)

            found: Set[Coin] = set()
            for coin in coin_set:
                # TODO: is this the proper check?
                if await coin_store.get_coin_record(coin.name()) is not None:
                    found.add(coin)

            coin_set = coin_set.difference(found)

            if len(coin_set) == 0:
                return

    async def create_coins_with_amounts(
        self,
        amounts: List[int],
        wallet: Wallet,
        per_transaction_record_group: int = 50,
    ) -> Set[Coin]:
        """Create coins with the requested amount.  This is useful when you need a
        bunch of coins for a test and don't need to farm that many.

        Arguments:
            amounts: A list with entries of mojo amounts corresponding to each
                coin to create.
            wallet: The wallet to send the new coins to.
            per_transaction_record_group: The maximum number of coins to create in each
                transaction record.

        Returns:
            A set of the generated coins.  Note that this does not include any change
            coins that were created.
        """
        invalid_amounts = [amount for amount in amounts if amount <= 0]
        if len(invalid_amounts) > 0:
            invalid_amounts_string = ", ".join(str(amount) for amount in invalid_amounts)
            raise Exception(f"Coins must have a positive value, request included: {invalid_amounts_string}")

        if len(amounts) == 0:
            return set()

        # TODO: This is a poor duplication of code in
        #       WalletRpcApi.create_signed_transaction().  Perhaps it should be moved
        #       somewhere more reusable.

        outputs: List[AmountWithPuzzlehash] = []
        for amount in amounts:
            puzzle_hash = await wallet.get_new_puzzlehash()
            outputs.append({"puzzlehash": puzzle_hash, "amount": uint64(amount), "memos": []})

        transaction_records: List[TransactionRecord] = []
        outputs_iterator = iter(outputs)
        while True:
            # The outputs iterator must be second in the zip() call otherwise we lose
            # an element when reaching the end of the range object.
            outputs_group = [output for _, output in zip(range(per_transaction_record_group), outputs_iterator)]

            if len(outputs_group) > 0:
                async with wallet.wallet_state_manager.lock:
                    tx = await wallet.generate_signed_transaction(
                        amount=outputs_group[0]["amount"],
                        puzzle_hash=outputs_group[0]["puzzlehash"],
                        primaries=outputs_group[1:],
                    )
                await wallet.push_transaction(tx=tx)
                transaction_records.append(tx)
            else:
                break

        await self.process_transaction_records(records=transaction_records)

        output_coins = {coin for transaction_record in transaction_records for coin in transaction_record.additions}
        puzzle_hashes = {output["puzzlehash"] for output in outputs}
        change_coins = {coin for coin in output_coins if coin.puzzle_hash not in puzzle_hashes}
        coins_to_receive = output_coins - change_coins
        await wait_for_coins_in_wallet(coins=coins_to_receive, wallet=wallet)

        return coins_to_receive
