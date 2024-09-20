from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from chia_rs import G1Element, G2Element, compute_merkle_set_root
from chiabip158 import PyBIP158

from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.consensus.constants import ConsensusConstants
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.full_node.bundle_tools import simple_solution_generator
from chia.simulator.block_tools import BlockTools, compute_additions_unchecked
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin, hash_coin_ids
from chia.types.blockchain_format.foliage import Foliage, FoliageBlockData, FoliageTransactionBlock, TransactionsInfo
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock, RewardChainBlockUnfinished
from chia.types.blockchain_format.sized_bytes import bytes32, bytes100
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.block_cache import BlockCache
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128

DEFAULT_PROOF_OF_SPACE = ProofOfSpace(
    bytes32([0] * 32),
    G1Element(),
    None,
    G1Element(),
    uint8(20),
    bytes(32 * 5),
)
DEFAULT_VDF_INFO = VDFInfo(bytes32([0] * 32), uint64(1), ClassgroupElement(bytes100([0] * 100)))
DEFAULT_VDF_PROOF = VDFProof(uint8(0), bytes(100), False)


class WalletBlockTools(BlockTools):
    """
    Tools to generate blocks for wallet testing.
    (Differs from standard block tools by patching away as much consensus logic as possible)
    """

    def get_consecutive_blocks(
        self,
        num_blocks: int,
        block_list_input: Optional[List[FullBlock]] = None,
        *,
        farmer_reward_puzzle_hash: Optional[bytes32] = None,
        pool_reward_puzzle_hash: Optional[bytes32] = None,
        transaction_data: Optional[SpendBundle] = None,
        genesis_timestamp: Optional[uint64] = None,
        **kwargs: Any,  # We're overriding so there's many arguments no longer used.
    ) -> List[FullBlock]:
        assert num_blocks > 0
        constants = self.constants

        if farmer_reward_puzzle_hash is None:
            farmer_reward_puzzle_hash = self.farmer_ph

        if block_list_input is None:
            block_list_input = []

        blocks: Dict[bytes32, BlockRecord]
        if len(block_list_input) == 0:
            height_to_hash = {}
            blocks = {}
        elif block_list_input[-1].header_hash == self._block_cache_header:
            height_to_hash = self._block_cache_height_to_hash
            blocks = self._block_cache
        else:
            height_to_hash, _, blocks = load_block_list(block_list_input, constants)

        if len(block_list_input) > 0:
            latest_block: Optional[BlockRecord] = blocks[block_list_input[-1].header_hash]
            assert latest_block is not None
            assert latest_block.timestamp is not None
            last_timestamp = latest_block.timestamp
        else:
            latest_block = None
            last_timestamp = uint64((int(time.time()) if genesis_timestamp is None else genesis_timestamp) - 20)

        for _ in range(0, num_blocks):
            additions = []
            removals = []
            block_generator: Optional[BlockGenerator] = None
            if transaction_data is not None and len(block_list_input) > 0:
                additions = compute_additions_unchecked(transaction_data)
                removals = transaction_data.removals()
                block_generator = simple_solution_generator(transaction_data)
            pool_target = PoolTarget(
                pool_reward_puzzle_hash if pool_reward_puzzle_hash is not None else self.pool_ph, uint32(0)
            )

            (
                full_block,
                block_record,
                new_timestamp,
            ) = get_full_block_and_block_record(
                constants,
                blocks,
                last_timestamp,
                farmer_reward_puzzle_hash,
                pool_target,
                latest_block,
                block_generator,
                additions,
                removals,
            )

            transaction_data = None

            last_timestamp = uint64(new_timestamp)
            block_list_input.append(full_block)
            blocks[full_block.header_hash] = block_record
            height_to_hash[uint32(full_block.height)] = full_block.header_hash
            latest_block = block_record

        self._block_cache_header = block_list_input[-1].header_hash
        self._block_cache_height_to_hash = height_to_hash
        self._block_cache_difficulty = uint64(1)
        self._block_cache = blocks
        return block_list_input


def load_block_list(
    block_list: List[FullBlock], constants: ConsensusConstants
) -> Tuple[Dict[uint32, bytes32], uint64, Dict[bytes32, BlockRecord]]:
    height_to_hash: Dict[uint32, bytes32] = {}
    blocks: Dict[bytes32, BlockRecord] = {}
    sub_slot_iters = constants.SUB_SLOT_ITERS_STARTING
    for full_block in block_list:
        if full_block.height != 0 and len(full_block.finished_sub_slots) > 0:
            if full_block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None:  # pragma: no cover
                sub_slot_iters = full_block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters
        blocks[full_block.header_hash] = block_to_block_record(
            constants,
            BlockCache(blocks),
            uint64(1),
            full_block,
            sub_slot_iters,
        )
        height_to_hash[uint32(full_block.height)] = full_block.header_hash
    return height_to_hash, uint64(1), blocks


def finish_block(
    constants: ConsensusConstants,
    unfinished_block: UnfinishedBlock,
    prev_block: Optional[BlockRecord],
    blocks: Dict[bytes32, BlockRecord],
) -> Tuple[FullBlock, BlockRecord]:
    if prev_block is None:
        new_weight = uint128(1)
        new_height = uint32(0)
    else:
        new_weight = uint128(prev_block.weight + 1)
        new_height = uint32(prev_block.height + 1)

    full_block = FullBlock(
        [],
        RewardChainBlock(
            new_weight,
            new_height,
            uint128(1),
            uint8(1),
            bytes32([0] * 32),
            unfinished_block.reward_chain_block.proof_of_space,
            DEFAULT_VDF_INFO,
            G2Element(),
            DEFAULT_VDF_INFO,
            DEFAULT_VDF_INFO,
            G2Element(),
            DEFAULT_VDF_INFO,
            DEFAULT_VDF_INFO,
            prev_block is not None,
        ),
        DEFAULT_VDF_PROOF,
        DEFAULT_VDF_PROOF,
        DEFAULT_VDF_PROOF,
        DEFAULT_VDF_PROOF,
        DEFAULT_VDF_PROOF,
        unfinished_block.foliage,
        unfinished_block.foliage_transaction_block,
        unfinished_block.transactions_info,
        unfinished_block.transactions_generator,
        [],
    )

    block_record = block_to_block_record(constants, BlockCache(blocks), uint64(1), full_block, uint64(1))
    return full_block, block_record


def get_full_block_and_block_record(
    constants: ConsensusConstants,
    blocks: Dict[bytes32, BlockRecord],
    last_timestamp: uint64,
    farmer_reward_puzzlehash: bytes32,
    pool_target: PoolTarget,
    prev_block: Optional[BlockRecord],
    block_generator: Optional[BlockGenerator],
    additions: List[Coin],
    removals: List[Coin],
) -> Tuple[FullBlock, BlockRecord, float]:
    timestamp = last_timestamp + 20
    if prev_block is None:
        height: uint32 = uint32(0)
        prev_block_hash: bytes32 = constants.GENESIS_CHALLENGE
    else:
        height = uint32(prev_block.height + 1)
        prev_block_hash = prev_block.header_hash

    fees: uint64 = uint64(sum(c.amount for c in removals) - sum(c.amount for c in additions))

    if height > 0:
        assert prev_block is not None
        additions.append(
            create_pool_coin(
                prev_block.height,
                prev_block.pool_puzzle_hash,
                calculate_pool_reward(prev_block.height),
                constants.GENESIS_CHALLENGE,
            )
        )
        additions.append(
            create_farmer_coin(
                prev_block.height,
                prev_block.farmer_puzzle_hash,
                uint64(
                    calculate_base_farmer_reward(prev_block.height) + prev_block.fees
                    if prev_block.fees is not None
                    else 0
                ),
                constants.GENESIS_CHALLENGE,
            )
        )

    byte_array_tx: List[bytearray] = []
    removal_ids: List[bytes32] = []
    puzzlehash_coin_map: Dict[bytes32, List[bytes32]] = {}
    for coin in additions:
        puzzlehash_coin_map.setdefault(coin.puzzle_hash, [])
        puzzlehash_coin_map[coin.puzzle_hash].append(coin.name())
        byte_array_tx.append(bytearray(coin.puzzle_hash))
    for coin in removals:
        cname = coin.name()
        removal_ids.append(cname)
        byte_array_tx.append(bytearray(cname))
    bip158: PyBIP158 = PyBIP158(byte_array_tx)
    filter_hash = std_hash(bytes(bip158.GetEncoded()))

    additions_merkle_items: List[bytes32] = []
    for puzzle, coin_ids in puzzlehash_coin_map.items():
        additions_merkle_items.append(puzzle)
        additions_merkle_items.append(hash_coin_ids(coin_ids))

    additions_root = bytes32(compute_merkle_set_root(additions_merkle_items))
    removals_root = bytes32(compute_merkle_set_root(removal_ids))

    generator_hash = bytes32([0] * 32)
    if block_generator is not None:
        generator_hash = std_hash(block_generator.program)

    foliage_data = FoliageBlockData(
        bytes32([0] * 32),
        pool_target,
        G2Element(),
        farmer_reward_puzzlehash,
        bytes32([0] * 32),
    )

    transactions_info = TransactionsInfo(
        generator_hash,
        bytes32([0] * 32),
        G2Element(),
        fees,
        uint64(constants.MAX_BLOCK_COST_CLVM),
        additions[-2:],
    )

    foliage_transaction_block = FoliageTransactionBlock(
        prev_block_hash,
        uint64(timestamp),
        filter_hash,
        additions_root,
        removals_root,
        transactions_info.get_hash(),
    )

    foliage = Foliage(
        prev_block_hash,
        bytes32([0] * 32),
        foliage_data,
        G2Element(),
        foliage_transaction_block.get_hash(),
        G2Element(),
    )
    unfinished_block = UnfinishedBlock(
        [],
        RewardChainBlockUnfinished(
            uint128(1),
            uint8(1),
            bytes32([0] * 32),
            DEFAULT_PROOF_OF_SPACE,
            None,
            G2Element(),
            None,
            G2Element(),
        ),
        None,
        None,
        foliage,
        foliage_transaction_block,
        transactions_info,
        block_generator.program if block_generator else None,
        [],
    )

    full_block, block_record = finish_block(constants, unfinished_block, prev_block, blocks)

    return full_block, block_record, timestamp
