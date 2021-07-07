from typing import Optional, List, Dict, Tuple

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.util.ints import uint64, uint32
from chia.util.hash import std_hash
from chia.util.errors import Err
from chia.types.coin_record import CoinRecord
from chia.types.spend_bundle import SpendBundle
from chia.types.generator_types import BlockGenerator
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_manager import MempoolManager
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.coinbase import create_pool_coin, create_farmer_coin
from chia.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from chia.consensus.cost_calculator import NPCResult


class CoinStore:
    def __init__(self):
        self.coin_records: Dict[bytes32, CoinRecord] = {}

    def add_coin_record(self, record: CoinRecord, allow_replace: bool = False):
        if (not allow_replace) and (record.coin.name() in self.coin_records.keys()):
            raise Exception("The coin is already in the coin store")
        else:
            self.coin_records[record.coin.name()] = record

    def delete_coin_record(self, name: bytes32):
        if name in self.coin_records.keys():
            del self.coin_records[name]

    async def get_coin_record(self, name: bytes32) -> Optional[CoinRecord]:
        if name not in self.coin_records:
            return None
        return self.coin_records[name]

    async def set_spent(self, name: bytes32, block_height: uint32):
        existing: Optional[CoinRecord] = await self.get_coin_record(name)
        if existing is None:
            raise Exception("There is no CoinRecord with the specified name")
        else:
            self.add_coin_record(
                CoinRecord(
                    existing.coin,
                    existing.confirmed_block_index,
                    block_height,
                    True,
                    existing.coinbase,
                    existing.timestamp,
                ),
                True,
            )

    def rewind(self, block_height: uint32):
        for coin_name, coin_record in list(self.coin_records.items()):
            if int(coin_record.spent_block_index) > block_height:
                new_record = CoinRecord(
                    coin_record.coin,
                    coin_record.confirmed_block_index,
                    uint32(0),
                    False,
                    coin_record.coinbase,
                    coin_record.timestamp,
                )
                self.add_coin_record(new_record, True)
            if int(coin_record.confirmed_block_index) > block_height:
                self.delete_coin_record(coin_name)


class Block:
    def __init__(self, rci: List[Coin], generator: BlockGenerator, height: uint32, timestamp: uint64):
        self.reward_claims_incorporated = rci
        self.transactions_generator = generator
        self.height = height
        self.previous_transaction_block_height = uint32(height - 1)
        self.timestamp = timestamp
        self.is_transaction_block = True
        self.header_hash = std_hash(bytes(height))


class Node:
    def __init__(self):
        self.mempool_manager = MempoolManager(CoinStore(), DEFAULT_CONSTANTS)
        self.blocks: List[Block] = []
        self.timestamp: uint64 = DEFAULT_CONSTANTS.INITIAL_FREEZE_END_TIMESTAMP + 1
        self.block_height: uint32 = 0

    async def push_tx(self, spend_bundle: SpendBundle) -> Tuple[MempoolInclusionStatus, Optional[Err]]:
        cost_result: NPCResult = await self.mempool_manager.pre_validate_spendbundle(spend_bundle)
        cost, status, error = await self.mempool_manager.add_spendbundle(spend_bundle, cost_result, spend_bundle.name())
        return status, error

    async def new_peak(self):
        await self.mempool_manager.new_peak(self.blocks[-1])

    def new_coin_record(self, coin: Coin, coinbase=False) -> CoinRecord:
        return CoinRecord(
            coin,
            uint32(self.block_height + 1),
            uint32(0),
            False,
            coinbase,
            self.timestamp,
        )

    def all_non_reward_coins(self) -> List[Coin]:
        return [
            item[1].coin
            for item in filter(
                lambda coin_record_item: (not coin_record_item[1].coinbase) and (not coin_record_item[1].spent),
                self.mempool_manager.coin_store.coin_records.items(),
            )
        ]

    async def generate_transaction_generator(self, bundle: SpendBundle) -> BlockGenerator:
        if bundle is None:
            return None
        return simple_solution_generator(bundle)

    async def farm_block(self, puzzle_hash: bytes32 = (b"0" * 32)):
        # Fees get calculated
        fees = uint64(0)
        if self.mempool_manager.mempool.spends:
            for _, item in self.mempool_manager.mempool.spends.items():
                fees += item.spend_bundle.fees()

        # Rewards get created
        next_block_height: uint32 = uint32(self.block_height + 1)
        pool_coin: Coin = create_pool_coin(
            next_block_height,
            puzzle_hash,
            calculate_pool_reward(next_block_height),
            DEFAULT_CONSTANTS.GENESIS_CHALLENGE,
        )
        farmer_coin: Coin = create_farmer_coin(
            next_block_height,
            puzzle_hash,
            uint64(calculate_base_farmer_reward(next_block_height) + fees),
            DEFAULT_CONSTANTS.GENESIS_CHALLENGE,
        )
        self.mempool_manager.coin_store.add_coin_record(self.new_coin_record(pool_coin, True))
        self.mempool_manager.coin_store.add_coin_record(self.new_coin_record(farmer_coin, True))

        # Coin store gets updated
        if (len(self.blocks) > 0) and (self.mempool_manager.mempool.spends):
            bundle, additions, removals = await self.mempool_manager.create_bundle_from_mempool(
                self.mempool_manager.peak.header_hash
            )

            for addition in additions:
                self.mempool_manager.coin_store.add_coin_record(self.new_coin_record(addition))
            for removal in removals:
                await self.mempool_manager.coin_store.set_spent(removal.name(), self.block_height + 1)
        else:
            bundle = None

        # Block is created
        generator: BlockGenerator = await self.generate_transaction_generator(bundle)
        self.blocks.append(
            Block(
                [pool_coin, farmer_coin],
                generator,
                self.block_height,
                self.timestamp,
            )
        )

        # block_height is incremented
        if len(self.blocks) != 1:
            self.block_height = next_block_height

        # mempool is reset
        await self.new_peak()

    def get_height(self) -> uint32:
        return self.block_height

    def pass_time(self, time: uint64):
        self.timestamp = uint64(self.timestamp + time)

    def pass_blocks(self, blocks: uint32):
        self.block_height = uint32(self.block_height + blocks)

    def rewind(self, block_height: uint32):
        new_block_list = list(filter(lambda block: block.height <= block_height, self.blocks))
        self.blocks = new_block_list
        self.mempool_manager.coin_store.rewind(block_height)
        self.mempool_manager.mempool.spends = {}
        self.block_height = block_height
        if new_block_list:
            self.timestamp = new_block_list[-1].timestamp
        else:
            self.timestamp = uint64(DEFAULT_CONSTANTS.INITIAL_FREEZE_END_TIMESTAMP + 1)

    def api_get_coin_record_by_name(self, name: bytes32) -> CoinRecord:
        return self.mempool_manager.coin_store.get_coin_record(name)

    def api_get_coin_records_by_puzzle_hash(self, puzzle_hash: bytes32) -> List[CoinRecord]:
        return [
            item[1]
            for item in filter(
                lambda coin_record_item: coin_record_item[1].coin.puzzle_hash == puzzle_hash,
                self.mempool_manager.coin_store.coin_records.items(),
            )
        ]
