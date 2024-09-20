from __future__ import annotations

import contextlib
import json
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple, Type, TypeVar

import anyio

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.full_node.mempool import Mempool
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions, get_puzzle_and_solution_for_coin
from chia.full_node.mempool_manager import MempoolManager
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.generator_types import BlockGenerator
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.mempool_item import MempoolItem
from chia.types.spend_bundle import SpendBundle, T_SpendBundle
from chia.util.db_wrapper import DBWrapper2
from chia.util.errors import Err, ValidationError
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.util.compute_hints import HintedCoin, compute_spend_hints_and_additions

"""
The purpose of this file is to provide a lightweight simulator for the testing of Chialisp smart contracts.

The Node object uses actual MempoolManager, Mempool and CoinStore objects, while substituting FullBlock and
BlockRecord objects for trimmed down versions.

There is also a provided NodeClient object which implements many of the methods from chia.rpc.full_node_rpc_client
and is designed so that you could test with it and then swap in a real rpc client that uses the same code you tested.
"""


@asynccontextmanager
async def sim_and_client(
    db_path: Optional[Path] = None, defaults: ConsensusConstants = DEFAULT_CONSTANTS, pass_prefarm: bool = True
) -> AsyncIterator[Tuple[SpendSim, SimClient]]:
    async with SpendSim.managed(db_path, defaults) as sim:
        client: SimClient = SimClient(sim)
        if pass_prefarm:
            await sim.farm_block()
        yield sim, client


class CostLogger:
    def __init__(self) -> None:
        self.cost_dict: Dict[str, int] = {}
        self.cost_dict_no_puzs: Dict[str, int] = {}

    def add_cost(self, descriptor: str, spend_bundle: T_SpendBundle) -> T_SpendBundle:
        program: BlockGenerator = simple_solution_generator(spend_bundle)
        npc_result: NPCResult = get_name_puzzle_conditions(
            program,
            INFINITE_COST,
            mempool_mode=True,
            height=DEFAULT_CONSTANTS.HARD_FORK_HEIGHT,
            constants=DEFAULT_CONSTANTS,
        )
        cost = uint64(0 if npc_result.conds is None else npc_result.conds.cost)
        self.cost_dict[descriptor] = cost
        cost_to_subtract: int = 0
        for cs in spend_bundle.coin_spends:
            cost_to_subtract += len(bytes(cs.puzzle_reveal)) * DEFAULT_CONSTANTS.COST_PER_BYTE
        self.cost_dict_no_puzs[descriptor] = cost - cost_to_subtract
        return spend_bundle

    def log_cost_statistics(self) -> str:
        merged_dict = {
            "standard cost": self.cost_dict,
            "no puzzle reveals": self.cost_dict_no_puzs,
        }
        return json.dumps(merged_dict, indent=2)


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
        prev_transaction_block_height = uint32(height - 1 if height > 0 else 0)
        return cls(
            rci,
            height,
            prev_transaction_block_height,
            timestamp,
            True,
            std_hash(height.stream_to_bytes()),
            std_hash(prev_transaction_block_height.stream_to_bytes()),
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
    coin_store: CoinStore
    mempool_manager: MempoolManager
    block_records: List[SimBlockRecord]
    blocks: List[SimFullBlock]
    timestamp: uint64
    block_height: uint32
    defaults: ConsensusConstants
    hint_store: HintStore

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(
        cls: Type[_T_SpendSim], db_path: Optional[Path] = None, defaults: ConsensusConstants = DEFAULT_CONSTANTS
    ) -> AsyncIterator[_T_SpendSim]:
        self = cls()
        if db_path is None:
            uri = f"file:db_{random.randint(0, 99999999)}?mode=memory&cache=shared"
        else:
            uri = f"file:{db_path}"

        async with DBWrapper2.managed(database=uri, uri=True, reader_count=1, db_version=2) as self.db_wrapper:
            self.coin_store = await CoinStore.create(self.db_wrapper)
            self.hint_store = await HintStore.create(self.db_wrapper)
            self.mempool_manager = MempoolManager(self.coin_store.get_coin_records, defaults)
            self.defaults = defaults

            # Load the next data if there is any
            async with self.db_wrapper.writer_maybe_transaction() as conn:
                await conn.execute("CREATE TABLE IF NOT EXISTS block_data(data blob PRIMARY KEY)")
                cursor = await conn.execute("SELECT * from block_data")
                row = await cursor.fetchone()
                await cursor.close()
                if row is not None:
                    store_data = SimStore.from_bytes(row[0])
                    self.timestamp = store_data.timestamp
                    self.block_height = store_data.block_height
                    self.block_records = store_data.block_records
                    self.blocks = store_data.blocks
                    self.mempool_manager.peak = self.block_records[-1]
                else:
                    self.timestamp = uint64(1)
                    self.block_height = uint32(0)
                    self.block_records = []
                    self.blocks = []

            try:
                yield self
            finally:
                with anyio.CancelScope(shield=True):
                    async with self.db_wrapper.writer_maybe_transaction() as conn:
                        c = await conn.execute("DELETE FROM block_data")
                        await c.close()
                        c = await conn.execute(
                            "INSERT INTO block_data VALUES(?)",
                            (bytes(SimStore(self.timestamp, self.block_height, self.block_records, self.blocks)),),
                        )
                        await c.close()

    async def new_peak(self, spent_coins_ids: Optional[List[bytes32]]) -> None:
        await self.mempool_manager.new_peak(self.block_records[-1], spent_coins_ids)

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
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT puzzle_hash,coin_parent,amount from coin_record WHERE coinbase=0 AND spent_index==0 ",
            )
            rows = await cursor.fetchall()

            await cursor.close()
        for row in rows:
            coin = Coin(bytes32(row[1]), bytes32(row[0]), uint64.from_bytes(row[2]))
            coins.add(coin)
        return list(coins)

    async def generate_transaction_generator(self, bundle: Optional[SpendBundle]) -> Optional[BlockGenerator]:
        if bundle is None:
            return None
        return simple_solution_generator(bundle)

    async def farm_block(
        self,
        puzzle_hash: bytes32 = bytes32(b"0" * 32),
        item_inclusion_filter: Optional[Callable[[bytes32], bool]] = None,
    ) -> Tuple[List[Coin], List[Coin]]:
        # Fees get calculated
        fees = uint64(0)
        for item in self.mempool_manager.mempool.all_items():
            fees = uint64(fees + item.fee)

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
        await self.coin_store._add_coin_records(
            [self.new_coin_record(pool_coin, True), self.new_coin_record(farmer_coin, True)]
        )

        # Coin store gets updated
        generator_bundle: Optional[SpendBundle] = None
        return_additions: List[Coin] = []
        return_removals: List[Coin] = []
        spent_coins_ids = None
        if (len(self.block_records) > 0) and (self.mempool_manager.mempool.size() > 0):
            peak = self.mempool_manager.peak
            if peak is not None:
                result = await self.mempool_manager.create_bundle_from_mempool(
                    last_tb_header_hash=peak.header_hash,
                    get_unspent_lineage_info_for_puzzle_hash=self.coin_store.get_unspent_lineage_info_for_puzzle_hash,
                    item_inclusion_filter=item_inclusion_filter,
                )

                if result is not None:
                    bundle, additions = result
                    generator_bundle = bundle
                    for spend in generator_bundle.coin_spends:
                        hint_dict, _ = compute_spend_hints_and_additions(spend)
                        hints: List[Tuple[bytes32, bytes]] = []
                        hint_obj: HintedCoin
                        for coin_name, hint_obj in hint_dict.items():
                            if hint_obj.hint is not None:
                                hints.append((coin_name, bytes(hint_obj.hint)))
                        await self.hint_store.add_hints(hints)
                    return_additions = additions
                    return_removals = bundle.removals()
                    spent_coins_ids = [r.name() for r in return_removals]
                    await self.coin_store._add_coin_records([self.new_coin_record(addition) for addition in additions])
                    await self.coin_store._set_spent(spent_coins_ids, uint32(self.block_height + 1))

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
        await self.new_peak(spent_coins_ids)

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
        await self.coin_store.rollback_to_block(block_height)
        old_pool = self.mempool_manager.mempool
        self.mempool_manager.mempool = Mempool(old_pool.mempool_info, old_pool.fee_estimator)
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
            spend_bundle_id = spend_bundle.name()
            sbc = await self.service.mempool_manager.pre_validate_spendbundle(spend_bundle, spend_bundle_id)
        except ValidationError as e:
            return MempoolInclusionStatus.FAILED, e.code
        assert self.service.mempool_manager.peak is not None
        info = await self.service.mempool_manager.add_spend_bundle(
            spend_bundle, sbc, spend_bundle_id, self.service.mempool_manager.peak.height
        )
        return info.status, info.error

    async def get_coin_record_by_name(self, name: bytes32) -> Optional[CoinRecord]:
        return await self.service.coin_store.get_coin_record(name)

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
        return await self.service.coin_store.get_coin_records_by_names(**kwargs)

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
        return await self.service.coin_store.get_coin_records_by_parent_ids(**kwargs)

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
        return await self.service.coin_store.get_coin_records_by_puzzle_hash(**kwargs)

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
        return await self.service.coin_store.get_coin_records_by_puzzle_hashes(**kwargs)

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
        additions: List[CoinRecord] = await self.service.coin_store.get_coins_added_at_height(block_height)
        removals: List[CoinRecord] = await self.service.coin_store.get_coins_removed_at_height(block_height)
        return additions, removals

    async def get_puzzle_and_solution(self, coin_id: bytes32, height: uint32) -> CoinSpend:
        filtered_generators = list(filter(lambda block: block.height == height, self.service.blocks))
        # real consideration should be made for the None cases instead of just hint ignoring
        generator: BlockGenerator = filtered_generators[0].transactions_generator  # type: ignore[assignment]
        coin_record = await self.service.coin_store.get_coin_record(coin_id)
        assert coin_record is not None
        spend_info = get_puzzle_and_solution_for_coin(generator, coin_record.coin, height, self.service.defaults)
        return CoinSpend(coin_record.coin, spend_info.puzzle, spend_info.solution)

    async def get_all_mempool_tx_ids(self) -> List[bytes32]:
        return self.service.mempool_manager.mempool.all_item_ids()

    async def get_all_mempool_items(self) -> Dict[bytes32, MempoolItem]:
        spends = {}
        for item in self.service.mempool_manager.mempool.all_items():
            spends[item.name] = item
        return spends

    async def get_mempool_item_by_tx_id(self, tx_id: bytes32) -> Optional[Dict[str, Any]]:
        item = self.service.mempool_manager.get_mempool_item(tx_id)
        if item is None:
            return None
        else:
            return item.__dict__

    async def get_coin_records_by_hint(
        self,
        hint: bytes32,
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> List[CoinRecord]:
        """
        Retrieves coins by hint, by default returns unspent coins.
        """
        names: List[bytes32] = await self.service.hint_store.get_coin_ids(hint)

        kwargs: Dict[str, Any] = {
            "include_spent_coins": False,
            "names": names,
        }
        if start_height:
            kwargs["start_height"] = uint32(start_height)
        if end_height:
            kwargs["end_height"] = uint32(end_height)

        if include_spent_coins:
            kwargs["include_spent_coins"] = include_spent_coins

        coin_records = await self.service.coin_store.get_coin_records_by_names(**kwargs)

        return coin_records
