from __future__ import annotations

import contextlib
import json
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import anyio
from chia_rs import (
    DONT_VALIDATE_SIGNATURE,
    CoinSpend,
    ConsensusConstants,
    G2Element,
    SpendBundle,
    get_flags_for_height_and_constants,
    run_block_generator2,
)
from chia_rs import get_puzzle_and_solution_for_coin2 as get_puzzle_and_solution_for_coin
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64
from typing_extensions import Self

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.full_node.mempool import Mempool
from chia.full_node.mempool_manager import MempoolManager
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST
from chia.types.coin_record import CoinRecord
from chia.types.generator_types import BlockGenerator
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.mempool_item import MempoolItem
from chia.util.db_wrapper import DBWrapper2
from chia.util.errors import Err, ValidationError
from chia.util.hash import std_hash
from chia.util.streamable import Streamable, streamable
from chia.wallet.util.compute_hints import HintedCoin, compute_spend_hints_and_additions
from chia.wallet.wallet_spend_bundle import T_SpendBundle

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
) -> AsyncIterator[tuple[SpendSim, SimClient]]:
    async with SpendSim.managed(db_path, defaults) as sim:
        client: SimClient = SimClient(sim)
        if pass_prefarm:
            await sim.farm_block()
        yield sim, client


class CostLogger:
    def __init__(self) -> None:
        self.cost_dict: dict[str, int] = {}
        self.cost_dict_no_puzs: dict[str, int] = {}

    def add_cost(self, descriptor: str, spend_bundle: T_SpendBundle) -> T_SpendBundle:
        program: BlockGenerator = simple_solution_generator(spend_bundle)
        flags = get_flags_for_height_and_constants(DEFAULT_CONSTANTS.HARD_FORK_HEIGHT, DEFAULT_CONSTANTS)
        _err, conds = run_block_generator2(
            bytes(program.program),
            [],
            INFINITE_COST,
            flags | DONT_VALIDATE_SIGNATURE,
            G2Element(),
            None,
            DEFAULT_CONSTANTS,
        )
        cost = uint64(0 if conds is None else conds.cost)
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


@streamable
@dataclass(frozen=True)
class SimBlockRecord(Streamable):
    reward_claims_incorporated: list[Coin]
    height: uint32
    prev_transaction_block_height: uint32
    timestamp: uint64
    is_transaction_block: bool
    header_hash: bytes32
    prev_transaction_block_hash: bytes32

    @classmethod
    def create(cls, rci: list[Coin], height: uint32, timestamp: uint64) -> Self:
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
    block_records: list[SimBlockRecord]
    blocks: list[SimFullBlock]


class SpendSim:
    db_wrapper: DBWrapper2
    coin_store: CoinStore
    mempool_manager: MempoolManager
    block_records: list[SimBlockRecord]
    blocks: list[SimFullBlock]
    timestamp: uint64
    block_height: uint32
    defaults: ConsensusConstants
    hint_store: HintStore

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(
        cls, db_path: Optional[Path] = None, defaults: ConsensusConstants = DEFAULT_CONSTANTS
    ) -> AsyncIterator[Self]:
        self = cls()
        if db_path is None:
            uri = f"file:db_{random.randint(0, 99999999)}?mode=memory&cache=shared"
        else:
            uri = f"file:{db_path}"

        async with DBWrapper2.managed(database=uri, uri=True, reader_count=1, db_version=2) as self.db_wrapper:
            self.coin_store = await CoinStore.create(self.db_wrapper)
            self.hint_store = await HintStore.create(self.db_wrapper)
            self.mempool_manager = MempoolManager(
                self.coin_store.get_coin_records, self.coin_store.get_unspent_lineage_info_for_puzzle_hash, defaults
            )
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

    async def new_peak(self, spent_coins_ids: Optional[list[bytes32]]) -> None:
        await self.mempool_manager.new_peak(self.block_records[-1], spent_coins_ids)

    def new_coin_record(self, coin: Coin, coinbase: bool = False) -> CoinRecord:
        return CoinRecord(
            coin,
            uint32(self.block_height + 1),
            uint32(0),
            coinbase,
            self.timestamp,
        )

    async def all_non_reward_coins(self) -> list[Coin]:
        coins = set()
        async with self.db_wrapper.reader_no_transaction() as conn:
            cursor = await conn.execute(
                "SELECT puzzle_hash,coin_parent,amount from coin_record WHERE coinbase=0 AND spent_index <= 0 ",
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

    async def farm_block(self, puzzle_hash: bytes32 = bytes32(b"0" * 32)) -> tuple[list[Coin], list[Coin]]:
        # Fees get calculated
        fees = uint64(0)
        for item in self.mempool_manager.mempool.all_items():
            fees = uint64(fees + item.fee)

        # Rewards get created
        next_block_height: uint32 = uint32(self.block_height + 1) if len(self.block_records) > 0 else self.block_height
        included_reward_coins = [
            create_pool_coin(
                next_block_height,
                puzzle_hash,
                calculate_pool_reward(next_block_height),
                self.defaults.GENESIS_CHALLENGE,
            ),
            create_farmer_coin(
                next_block_height,
                puzzle_hash,
                uint64(calculate_base_farmer_reward(next_block_height) + fees),
                self.defaults.GENESIS_CHALLENGE,
            ),
        ]
        # Coin store gets updated
        generator_bundle: Optional[SpendBundle] = None
        tx_additions = []
        tx_removals = []
        spent_coins_ids = None
        if (len(self.block_records) > 0) and (self.mempool_manager.mempool.size() > 0):
            peak = self.mempool_manager.peak
            if peak is not None:
                result = self.mempool_manager.create_bundle_from_mempool(last_tb_header_hash=peak.header_hash)
                if result is not None:
                    bundle, additions = result
                    generator_bundle = bundle
                    spent_coins: dict[bytes32, Coin] = {}
                    spent_coins_ids = []
                    for spend in generator_bundle.coin_spends:
                        hint_dict, _ = compute_spend_hints_and_additions(spend)
                        hints: list[tuple[bytes32, bytes]] = []
                        hint_obj: HintedCoin
                        for coin_name, hint_obj in hint_dict.items():
                            if hint_obj.hint is not None:
                                hints.append((coin_name, bytes(hint_obj.hint)))
                        await self.hint_store.add_hints(hints)
                        spend_id = spend.coin.name()
                        spent_coins[spend_id] = spend.coin
                        spent_coins_ids.append(spend_id)
                        tx_removals.append(spend.coin)
                    for child in additions:
                        parent = spent_coins.get(child.parent_coin_info)
                        assert parent is not None
                        same_as_parent = child.puzzle_hash == parent.puzzle_hash and child.amount == parent.amount
                        tx_additions.append((child.name(), child, same_as_parent))
        await self.coin_store.new_block(
            height=uint32(self.block_height + 1),
            timestamp=self.timestamp,
            included_reward_coins=included_reward_coins,
            tx_additions=tx_additions,
            tx_removals=spent_coins_ids if spent_coins_ids is not None else [],
        )
        # SimBlockRecord is created
        generator: Optional[BlockGenerator] = await self.generate_transaction_generator(generator_bundle)
        self.block_records.append(SimBlockRecord.create(included_reward_coins, next_block_height, self.timestamp))
        self.blocks.append(SimFullBlock(generator, next_block_height))

        # block_height is incremented
        self.block_height = next_block_height

        # mempool is reset
        await self.new_peak(spent_coins_ids)

        # return some debugging data
        return [a for _, a, _ in tx_additions], tx_removals

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

    async def push_tx(self, spend_bundle: SpendBundle) -> tuple[MempoolInclusionStatus, Optional[Err]]:
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
        names: list[bytes32],
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
        include_spent_coins: bool = False,
    ) -> list[CoinRecord]:
        kwargs: dict[str, Any] = {"include_spent_coins": include_spent_coins, "names": names}
        if start_height is not None:
            kwargs["start_height"] = start_height
        if end_height is not None:
            kwargs["end_height"] = end_height
        return await self.service.coin_store.get_coin_records_by_names(**kwargs)

    async def get_coin_records_by_parent_ids(
        self,
        parent_ids: list[bytes32],
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
        include_spent_coins: bool = False,
    ) -> list[CoinRecord]:
        kwargs: dict[str, Any] = {"include_spent_coins": include_spent_coins, "parent_ids": parent_ids}
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
    ) -> list[CoinRecord]:
        kwargs: dict[str, Any] = {"include_spent_coins": include_spent_coins, "puzzle_hash": puzzle_hash}
        if start_height is not None:
            kwargs["start_height"] = start_height
        if end_height is not None:
            kwargs["end_height"] = end_height
        return await self.service.coin_store.get_coin_records_by_puzzle_hash(**kwargs)

    async def get_coin_records_by_puzzle_hashes(
        self,
        puzzle_hashes: list[bytes32],
        include_spent_coins: bool = True,
        start_height: Optional[int] = None,
        end_height: Optional[int] = None,
    ) -> list[CoinRecord]:
        kwargs: dict[str, Any] = {"include_spent_coins": include_spent_coins, "puzzle_hashes": puzzle_hashes}
        if start_height is not None:
            kwargs["start_height"] = start_height
        if end_height is not None:
            kwargs["end_height"] = end_height
        return await self.service.coin_store.get_coin_records_by_puzzle_hashes(**kwargs)

    async def get_block_record_by_height(self, height: uint32) -> SimBlockRecord:
        return next(filter(lambda block: block.height == height, self.service.block_records))

    async def get_block_record(self, header_hash: bytes32) -> SimBlockRecord:
        return next(filter(lambda block: block.header_hash == header_hash, self.service.block_records))

    async def get_block_records(self, start: uint32, end: uint32) -> list[SimBlockRecord]:
        return list(filter(lambda block: (block.height >= start) and (block.height < end), self.service.block_records))

    async def get_block(self, header_hash: bytes32) -> SimFullBlock:
        selected_block: SimBlockRecord = next(
            filter(lambda br: br.header_hash == header_hash, self.service.block_records)
        )
        block_height: uint32 = selected_block.height
        block: SimFullBlock = next(filter(lambda block: block.height == block_height, self.service.blocks))
        return block

    async def get_all_block(self, start: uint32, end: uint32) -> list[SimFullBlock]:
        return list(filter(lambda block: (block.height >= start) and (block.height < end), self.service.blocks))

    async def get_additions_and_removals(self, header_hash: bytes32) -> tuple[list[CoinRecord], list[CoinRecord]]:
        selected_block: SimBlockRecord = next(
            filter(lambda br: br.header_hash == header_hash, self.service.block_records)
        )
        block_height: uint32 = selected_block.height
        additions: list[CoinRecord] = await self.service.coin_store.get_coins_added_at_height(block_height)
        removals: list[CoinRecord] = await self.service.coin_store.get_coins_removed_at_height(block_height)
        return additions, removals

    async def get_puzzle_and_solution(self, coin_id: bytes32, height: uint32) -> CoinSpend:
        filtered_generators = list(filter(lambda block: block.height == height, self.service.blocks))
        # real consideration should be made for the None cases instead of just hint ignoring
        generator: BlockGenerator = filtered_generators[0].transactions_generator  # type: ignore[assignment]
        coin_record = await self.service.coin_store.get_coin_record(coin_id)
        assert coin_record is not None
        puzzle, solution = get_puzzle_and_solution_for_coin(
            generator.program,
            generator.generator_refs,
            self.service.defaults.MAX_BLOCK_COST_CLVM,
            coin_record.coin,
            get_flags_for_height_and_constants(height, self.service.defaults),
        )
        return CoinSpend(coin_record.coin, puzzle, solution)

    async def get_all_mempool_tx_ids(self) -> list[bytes32]:
        return self.service.mempool_manager.mempool.all_item_ids()

    async def get_all_mempool_items(self) -> dict[bytes32, MempoolItem]:
        spends = {}
        for item in self.service.mempool_manager.mempool.all_items():
            spends[item.name] = item
        return spends

    async def get_mempool_item_by_tx_id(self, tx_id: bytes32) -> Optional[dict[str, Any]]:
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
    ) -> list[CoinRecord]:
        """
        Retrieves coins by hint, by default returns unspent coins.
        """
        names: list[bytes32] = await self.service.hint_store.get_coin_ids(hint)

        kwargs: dict[str, Any] = {
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
