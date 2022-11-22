import random
from pathlib import Path

from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, Any, Type, TypeVar, Callable

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.types.mempool_item import MempoolItem
from chia.util.ints import uint64, uint32
from chia.util.hash import std_hash
from chia.util.errors import Err, ValidationError
from chia.util.db_wrapper import DBWrapper2
from chia.util.streamable import Streamable, streamable
from chia.types.coin_record import CoinRecord
from chia.types.spend_bundle import SpendBundle
from chia.types.generator_types import BlockGenerator
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.coin_spend import CoinSpend
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_manager import MempoolManager
from chia.full_node.coin_store import CoinStore
from chia.full_node.mempool_check_conditions import get_puzzle_and_solution_for_coin
from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.coinbase import create_pool_coin, create_farmer_coin
from chia.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from chia.consensus.cost_calculator import NPCResult

"""
The purpose of this file is to provide a lightweight simulator for the testing of Chialisp smart contracts.

The Node object uses actual MempoolManager, Mempool and CoinStore objects, while substituting FullBlock and
BlockRecord objects for trimmed down versions.

There is also a provided NodeClient object which implements many of the methods from chia.rpc.full_node_rpc_client
and is designed so that you could test with it and then swap in a real rpc client that uses the same code you tested.
"""


@streamable
@dataclass(frozen=True)
class SimFullBlock(Streamable):
    transactions_generator: Optional[BlockGenerator]
    height: uint32  # Note that height is not on a regular FullBlock


_T_SimBlockRecord = TypeVar("_T_SimBlockRecord", bound="SimBlockRecord")


@streamable
@dataclass(frozen=True)
class SimBlockRecord(Streamable):
    reward_claims_incorporated: List[Coin]
    height: uint32
    prev_transaction_block_height: uint32
    timestamp: uint64
    is_transaction_block: bool
    header_hash: bytes32
    prev_transaction_block_hash: bytes32

    @classmethod
    def create(cls: Type[_T_SimBlockRecord], rci: List[Coin], height: uint32, timestamp: uint64) -> _T_SimBlockRecord:
        return cls(
            rci,
            height,
            uint32(height - 1 if height > 0 else 0),
            timestamp,
            True,
            std_hash(bytes(height)),
            std_hash(std_hash(height)),
        )


@streamable
@dataclass(frozen=True)
class SimStore(Streamable):
    timestamp: uint64
    block_height: uint32
    block_records: List[SimBlockRecord]
    blocks: List[SimFullBlock]


_T_SpendSim = TypeVar("_T_SpendSim", bound="SpendSim")


class SpendSim:

    db_wrapper: DBWrapper2
    mempool_manager: MempoolManager
    block_records: List[SimBlockRecord]
    blocks: List[SimFullBlock]
    timestamp: uint64
    block_height: uint32
    defaults: ConsensusConstants

    @classmethod
    async def create(
        cls: Type[_T_SpendSim], db_path: Optional[Path] = None, defaults: ConsensusConstants = DEFAULT_CONSTANTS
    ) -> _T_SpendSim:
        self = cls()
        if db_path is None:
            uri = f"file:db_{random.randint(0, 99999999)}?mode=memory&cache=shared"
        else:
            uri = f"file:{db_path}"

        self.db_wrapper = await DBWrapper2.create(database=uri, uri=True, reader_count=1)

        coin_store = await CoinStore.create(self.db_wrapper)
        self.mempool_manager = MempoolManager(coin_store, defaults)
        self.defaults = defaults

        # Load the next data if there is any
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS block_data(data blob PRIMARY_KEY)")
            cursor = await conn.execute("SELECT * from block_data")
            row = await cursor.fetchone()
            await cursor.close()
            if row is not None:
                store_data = SimStore.from_bytes(row[0])
                self.timestamp = store_data.timestamp
                self.block_height = store_data.block_height
                self.block_records = store_data.block_records
                self.blocks = store_data.blocks
                # Create a protocol to make BlockRecord and SimBlockRecord interchangeable.
                self.mempool_manager.peak = self.block_records[-1]  # type: ignore[assignment]
            else:
                self.timestamp = uint64(1)
                self.block_height = uint32(0)
                self.block_records = []
                self.blocks = []
            return self

    async def close(self) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            c = await conn.execute("DELETE FROM block_data")
            await c.close()
            c = await conn.execute(
                "INSERT INTO block_data VALUES(?)",
                (bytes(SimStore(self.timestamp, self.block_height, self.block_records, self.blocks)),),
            )
            await c.close()
        await self.db_wrapper.close()

    async def new_peak(self) -> None:
        # Create a protocol to make BlockRecord and SimBlockRecord interchangeable.
        await self.mempool_manager.new_peak(self.block_records[-1], None)  # type: ignore[arg-type]

    def new_coin_record(self, coin: Coin, coinbase: bool = False) -> CoinRecord:
        return CoinRecord(
            coin,
            uint32(self.block_height + 1),
            uint32(0),
            coinbase,
            self.timestamp,
        )

    async def all_non_reward_coins(self) -> List[Coin]:
        coins = set()
        async with self.mempool_manager.coin_store.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT * from coin_record WHERE coinbase=0 AND spent=0 ",
            )
            rows = await cursor.fetchall()

            await cursor.close()
        for row in rows:
            coin = Coin(bytes32(bytes.fromhex(row[6])), bytes32(bytes.fromhex(row[5])), uint64.from_bytes(row[7]))
            coins.add(coin)
        return list(coins)

    async def generate_transaction_generator(self, bundle: Optional[SpendBundle]) -> Optional[BlockGenerator]:
        if bundle is None:
            return None
        return simple_solution_generator(bundle)

    async def farm_block(
        self,
        puzzle_hash: bytes32 = bytes32(b"0" * 32),
        item_inclusion_filter: Optional[Callable[[MempoolManager, MempoolItem], bool]] = None,
    ) -> Tuple[List[Coin], List[Coin]]:
        # Fees get calculated
        fees = uint64(0)
        if self.mempool_manager.mempool.spends:
            for _, item in self.mempool_manager.mempool.spends.items():
                fees = uint64(fees + item.spend_bundle.fees())

        # Rewards get created
        next_block_height: uint32 = uint32(self.block_height + 1) if len(self.block_records) > 0 else self.block_height
        pool_coin: Coin = create_pool_coin(
            next_block_height,
            puzzle_hash,
            calculate_pool_reward(next_block_height),
            self.defaults.GENESIS_CHALLENGE,
        )
        farmer_coin: Coin = create_farmer_coin(
            next_block_height,
            puzzle_hash,
            uint64(calculate_base_farmer_reward(next_block_height) + fees),
            self.defaults.GENESIS_CHALLENGE,
        )
        await self.mempool_manager.coin_store._add_coin_records(
            [self.new_coin_record(pool_coin, True), self.new_coin_record(farmer_coin, True)]
        )

        # Coin store gets updated
        generator_bundle: Optional[SpendBundle] = None
        return_additions: List[Coin] = []
        return_removals: List[Coin] = []
        if (len(self.block_records) > 0) and (self.mempool_manager.mempool.spends):
            peak = self.mempool_manager.peak
            if peak is not None:
                result = await self.mempool_manager.create_bundle_from_mempool(peak.header_hash, item_inclusion_filter)

                if result is not None:
                    bundle, additions, removals = result
                    generator_bundle = bundle
                    return_additions = additions
                    return_removals = removals

                    await self.mempool_manager.coin_store._add_coin_records(
                        [self.new_coin_record(addition) for addition in additions]
                    )
                    await self.mempool_manager.coin_store._set_spent(
                        [r.name() for r in removals], uint32(self.block_height + 1)
                    )

        # SimBlockRecord is created
        generator: Optional[BlockGenerator] = await self.generate_transaction_generator(generator_bundle)
        self.block_records.append(
            SimBlockRecord.create(
                [pool_coin, farmer_coin],
                next_block_height,
                self.timestamp,
            )
        )
        self.blocks.append(SimFullBlock(generator, next_block_height))

        # block_height is incremented
        self.block_height = next_block_height

        # mempool is reset
        await self.new_peak()

        # return some debugging data
        return return_additions, return_removals

    def get_height(self) -> uint32:
        return self.block_height

    def pass_time(self, time: uint64) -> None:
        self.timestamp = uint64(self.timestamp + time)

    def pass_blocks(self, blocks: uint32) -> None:
        self.block_height = uint32(self.block_height + blocks)

    async def rewind(self, block_height: uint32) -> None:
        new_br_list = list(filter(lambda br: br.height <= block_height, self.block_records))
        new_block_list = list(filter(lambda block: block.height <= block_height, self.blocks))
        self.block_records = new_br_list
        self.blocks = new_block_list
        await self.mempool_manager.coin_store.rollback_to_block(block_height)
        self.mempool_manager.mempool.spends = {}
        self.block_height = block_height
        if new_br_list:
            self.timestamp = new_br_list[-1].timestamp
        else:
            self.timestamp = uint64(1)


class SimClient:
    def __init__(self, service: SpendSim) -> None:
        self.service = service

    async def push_tx(self, spend_bundle: SpendBundle) -> Tuple[MempoolInclusionStatus, Optional[Err]]:
        try:
            cost_result: NPCResult = await self.service.mempool_manager.pre_validate_spendbundle(
                spend_bundle, None, spend_bundle.name()
            )
        except ValidationError as e:
            return MempoolInclusionStatus.FAILED, e.code
        assert self.service.mempool_manager.peak
        cost, status, error = await self.service.mempool_manager.add_spend_bundle(
            spend_bundle, cost_result, spend_bundle.name(), self.service.mempool_manager.peak.height
        )
        return status, error

    async def get_coin_record_by_name(self, name: bytes32) -> Optional[CoinRecord]:
        return await self.service.mempool_manager.coin_store.get_coin_record(name)

    async def get_coin_records_by_names(
        self,
        names: List[bytes32],
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
        include_spent_coins: bool = False,
    ) -> List[CoinRecord]:
        kwargs: Dict[str, Any] = {"include_spent_coins": include_spent_coins, "names": names}
        if start_height is not None:
            kwargs["start_height"] = start_height
        if end_height is not None:
            kwargs["end_height"] = end_height
        return await self.service.mempool_manager.coin_store.get_coin_records_by_names(**kwargs)

    async def get_coin_records_by_parent_ids(
        self,
        parent_ids: List[bytes32],
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
        include_spent_coins: bool = False,
    ) -> List[CoinRecord]:
        kwargs: Dict[str, Any] = {"include_spent_coins": include_spent_coins, "parent_ids": parent_ids}
        if start_height is not None:
            kwargs["start_height"] = start_height
        if end_height is not None:
            kwargs["end_height"] = end_height
        return await self.service.mempool_manager.coin_store.get_coin_records_by_parent_ids(**kwargs)

    async def get_coin_records_by_puzzle_hash(
        self,
        puzzle_hash: bytes32,
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> List[CoinRecord]:
        kwargs: Dict[str, Any] = {"include_spent_coins": include_spent_coins, "puzzle_hash": puzzle_hash}
        if start_height is not None:
            kwargs["start_height"] = start_height
        if end_height is not None:
            kwargs["end_height"] = end_height
        return await self.service.mempool_manager.coin_store.get_coin_records_by_puzzle_hash(**kwargs)

    async def get_coin_records_by_puzzle_hashes(
        self,
        puzzle_hashes: List[bytes32],
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> List[CoinRecord]:
        kwargs: Dict[str, Any] = {"include_spent_coins": include_spent_coins, "puzzle_hashes": puzzle_hashes}
        if start_height is not None:
            kwargs["start_height"] = start_height
        if end_height is not None:
            kwargs["end_height"] = end_height
        return await self.service.mempool_manager.coin_store.get_coin_records_by_puzzle_hashes(**kwargs)

    async def get_block_record_by_height(self, height: uint32) -> SimBlockRecord:
        return list(filter(lambda block: block.height == height, self.service.block_records))[0]

    async def get_block_record(self, header_hash: bytes32) -> SimBlockRecord:
        return list(filter(lambda block: block.header_hash == header_hash, self.service.block_records))[0]

    async def get_block_records(self, start: uint32, end: uint32) -> List[SimBlockRecord]:
        return list(filter(lambda block: (block.height >= start) and (block.height < end), self.service.block_records))

    async def get_block(self, header_hash: bytes32) -> SimFullBlock:
        selected_block: SimBlockRecord = list(
            filter(lambda br: br.header_hash == header_hash, self.service.block_records)
        )[0]
        block_height: uint32 = selected_block.height
        block: SimFullBlock = list(filter(lambda block: block.height == block_height, self.service.blocks))[0]
        return block

    async def get_all_block(self, start: uint32, end: uint32) -> List[SimFullBlock]:
        return list(filter(lambda block: (block.height >= start) and (block.height < end), self.service.blocks))

    async def get_additions_and_removals(self, header_hash: bytes32) -> Tuple[List[CoinRecord], List[CoinRecord]]:
        selected_block: SimBlockRecord = list(
            filter(lambda br: br.header_hash == header_hash, self.service.block_records)
        )[0]
        block_height: uint32 = selected_block.height
        additions: List[CoinRecord] = await self.service.mempool_manager.coin_store.get_coins_added_at_height(
            block_height
        )  # noqa
        removals: List[CoinRecord] = await self.service.mempool_manager.coin_store.get_coins_removed_at_height(
            block_height
        )  # noqa
        return additions, removals

    async def get_puzzle_and_solution(self, coin_id: bytes32, height: uint32) -> Optional[CoinSpend]:
        filtered_generators = list(filter(lambda block: block.height == height, self.service.blocks))
        # real consideration should be made for the None cases instead of just hint ignoring
        generator: BlockGenerator = filtered_generators[0].transactions_generator  # type: ignore[assignment]
        coin_record: CoinRecord
        coin_record = await self.service.mempool_manager.coin_store.get_coin_record(  # type: ignore[assignment]
            coin_id,
        )
        error, puzzle, solution = get_puzzle_and_solution_for_coin(generator, coin_record.coin)
        if error:
            return None
        else:
            assert puzzle is not None
            assert solution is not None
            return CoinSpend(coin_record.coin, puzzle, solution)

    async def get_all_mempool_tx_ids(self) -> List[bytes32]:
        return list(self.service.mempool_manager.mempool.spends.keys())

    async def get_all_mempool_items(self) -> Dict[bytes32, MempoolItem]:
        spends = {}
        for tx_id, item in self.service.mempool_manager.mempool.spends.items():
            spends[tx_id] = item
        return spends

    async def get_mempool_item_by_tx_id(self, tx_id: bytes32) -> Optional[Dict[str, Any]]:
        item = self.service.mempool_manager.get_mempool_item(tx_id)
        if item is None:
            return None
        else:
            return item.__dict__
