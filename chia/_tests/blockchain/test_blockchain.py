from __future__ import annotations

import logging
import random
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import AsyncIterator, Dict, List, Optional

import pytest
from chia_rs import AugSchemeMPL, G2Element, MerkleSet
from clvm.casts import int_to_bytes

from chia._tests.blockchain.blockchain_test_utils import (
    _validate_and_add_block,
    _validate_and_add_block_multi_error,
    _validate_and_add_block_multi_result,
    _validate_and_add_block_no_error,
    check_block_store_invariant,
)
from chia._tests.conftest import ConsensusMode
from chia._tests.util.blockchain import create_blockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward
from chia.consensus.blockchain import AddBlockResult, Blockchain
from chia.consensus.coinbase import create_farmer_coin
from chia.consensus.constants import ConsensusConstants
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.get_block_generator import get_block_generator
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.consensus.pot_iterations import is_overflow_block
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.simulator.block_tools import BlockTools, create_block_tools_async
from chia.simulator.keyring import TempKeyring
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.foliage import TransactionsInfo
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import InfusedChallengeChainSubSlot
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof, validate_vdf
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.cpu import available_logical_cores
from chia.util.errors import Err
from chia.util.generator_tools import get_block_header
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64
from chia.util.keychain import Keychain
from chia.util.recursive_replace import recursive_replace
from chia.util.vdf_prover import get_vdf_info_and_proof
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
)

log = logging.getLogger(__name__)
bad_element = ClassgroupElement.create(b"\x00")


@asynccontextmanager
async def make_empty_blockchain(constants: ConsensusConstants) -> AsyncIterator[Blockchain]:
    """
    Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
    """

    async with create_blockchain(constants, 2) as (bc, db_wrapper):
        yield bc


class TestGenesisBlock:
    @pytest.mark.anyio
    async def test_block_tools_proofs_400(
        self, default_400_blocks: List[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        vdf, proof = get_vdf_info_and_proof(
            blockchain_constants,
            ClassgroupElement.get_default_element(),
            blockchain_constants.GENESIS_CHALLENGE,
            uint64(231),
        )
        if validate_vdf(proof, blockchain_constants, ClassgroupElement.get_default_element(), vdf) is False:
            raise Exception("invalid proof")

    @pytest.mark.anyio
    async def test_block_tools_proofs_1000(
        self, default_1000_blocks: List[FullBlock], blockchain_constants: ConsensusConstants
    ) -> None:
        vdf, proof = get_vdf_info_and_proof(
            blockchain_constants,
            ClassgroupElement.get_default_element(),
            blockchain_constants.GENESIS_CHALLENGE,
            uint64(231),
        )
        if validate_vdf(proof, blockchain_constants, ClassgroupElement.get_default_element(), vdf) is False:
            raise Exception("invalid proof")

    @pytest.mark.anyio
    async def test_block_tools_proofs(self, blockchain_constants: ConsensusConstants) -> None:
        vdf, proof = get_vdf_info_and_proof(
            blockchain_constants,
            ClassgroupElement.get_default_element(),
            blockchain_constants.GENESIS_CHALLENGE,
            uint64(231),
        )
        if validate_vdf(proof, blockchain_constants, ClassgroupElement.get_default_element(), vdf) is False:
            raise Exception("invalid proof")

    @pytest.mark.anyio
    async def test_non_overflow_genesis(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        assert empty_blockchain.get_peak() is None
        genesis = bt.get_consecutive_blocks(1, force_overflow=False)[0]
        await _validate_and_add_block(empty_blockchain, genesis)
        peak = empty_blockchain.get_peak()
        assert peak is not None
        assert peak.height == 0

    @pytest.mark.anyio
    async def test_overflow_genesis(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        genesis = bt.get_consecutive_blocks(1, force_overflow=True)[0]
        await _validate_and_add_block(empty_blockchain, genesis)

    @pytest.mark.anyio
    async def test_genesis_empty_slots(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        genesis = bt.get_consecutive_blocks(1, force_overflow=False, skip_slots=30)[0]
        await _validate_and_add_block(empty_blockchain, genesis)

    @pytest.mark.anyio
    async def test_overflow_genesis_empty_slots(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        genesis = bt.get_consecutive_blocks(1, force_overflow=True, skip_slots=3)[0]
        await _validate_and_add_block(empty_blockchain, genesis)

    @pytest.mark.anyio
    async def test_genesis_validate_1(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        genesis = bt.get_consecutive_blocks(1, force_overflow=False)[0]
        bad_prev = bytes([1] * 32)
        genesis = recursive_replace(genesis, "foliage.prev_block_hash", bad_prev)
        await _validate_and_add_block(empty_blockchain, genesis, expected_error=Err.INVALID_PREV_BLOCK_HASH)


class TestBlockHeaderValidation:
    @pytest.mark.limit_consensus_modes(reason="save time")
    @pytest.mark.anyio
    async def test_long_chain(self, empty_blockchain: Blockchain, default_1000_blocks: List[FullBlock]) -> None:
        blocks = default_1000_blocks
        for block in blocks:
            if (
                len(block.finished_sub_slots) > 0
                and block.finished_sub_slots[0].challenge_chain.subepoch_summary_hash is not None
            ):
                # Sub/Epoch. Try using a bad ssi and difficulty to test 2m and 2n
                new_finished_ss = recursive_replace(
                    block.finished_sub_slots[0],
                    "challenge_chain.new_sub_slot_iters",
                    uint64(10_000_000),
                )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", [new_finished_ss] + block.finished_sub_slots[1:]
                )
                header_block_bad = get_block_header(block_bad, [], [])
                # TODO: Inspect these block values as they are currently None
                expected_difficulty = block.finished_sub_slots[0].challenge_chain.new_difficulty or uint64(0)
                expected_sub_slot_iters = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters or uint64(0)
                _, error = validate_finished_header_block(
                    empty_blockchain.constants,
                    empty_blockchain,
                    header_block_bad,
                    False,
                    expected_difficulty,
                    expected_sub_slot_iters,
                )
                assert error is not None
                assert error.code == Err.INVALID_NEW_SUB_SLOT_ITERS

                # Also fails calling the outer methods, but potentially with a different error
                await _validate_and_add_block(empty_blockchain, block_bad, expected_result=AddBlockResult.INVALID_BLOCK)

                new_finished_ss_2 = recursive_replace(
                    block.finished_sub_slots[0],
                    "challenge_chain.new_difficulty",
                    uint64(10_000_000),
                )
                block_bad_2 = recursive_replace(
                    block, "finished_sub_slots", [new_finished_ss_2] + block.finished_sub_slots[1:]
                )

                header_block_bad_2 = get_block_header(block_bad_2, [], [])
                # TODO: Inspect these block values as they are currently None
                expected_difficulty = block.finished_sub_slots[0].challenge_chain.new_difficulty or uint64(0)
                expected_sub_slot_iters = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters or uint64(0)
                _, error = validate_finished_header_block(
                    empty_blockchain.constants,
                    empty_blockchain,
                    header_block_bad_2,
                    False,
                    expected_difficulty,
                    expected_sub_slot_iters,
                )
                assert error is not None
                assert error.code == Err.INVALID_NEW_DIFFICULTY

                # Also fails calling the outer methods, but potentially with a different error
                await _validate_and_add_block(
                    empty_blockchain, block_bad_2, expected_result=AddBlockResult.INVALID_BLOCK
                )

                # 3c
                new_finished_ss_3: EndOfSubSlotBundle = recursive_replace(
                    block.finished_sub_slots[0],
                    "challenge_chain.subepoch_summary_hash",
                    bytes([0] * 32),
                )
                new_finished_ss_3 = recursive_replace(
                    new_finished_ss_3,
                    "reward_chain.challenge_chain_sub_slot_hash",
                    new_finished_ss_3.challenge_chain.get_hash(),
                )
                log.warning(f"Number of slots: {len(block.finished_sub_slots)}")
                block_bad_3 = recursive_replace(block, "finished_sub_slots", [new_finished_ss_3])

                header_block_bad_3 = get_block_header(block_bad_3, [], [])
                # TODO: Inspect these block values as they are currently None
                expected_difficulty = block.finished_sub_slots[0].challenge_chain.new_difficulty or uint64(0)
                expected_sub_slot_iters = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters or uint64(0)
                _, error = validate_finished_header_block(
                    empty_blockchain.constants,
                    empty_blockchain,
                    header_block_bad_3,
                    False,
                    expected_difficulty,
                    expected_sub_slot_iters,
                )
                assert error is not None
                assert error.code == Err.INVALID_SUB_EPOCH_SUMMARY

                # Also fails calling the outer methods, but potentially with a different error
                await _validate_and_add_block(
                    empty_blockchain, block_bad_3, expected_result=AddBlockResult.INVALID_BLOCK
                )

                # 3d
                new_finished_ss_4 = recursive_replace(
                    block.finished_sub_slots[0],
                    "challenge_chain.subepoch_summary_hash",
                    std_hash(b"123"),
                )
                new_finished_ss_4 = recursive_replace(
                    new_finished_ss_4,
                    "reward_chain.challenge_chain_sub_slot_hash",
                    new_finished_ss_4.challenge_chain.get_hash(),
                )
                block_bad_4 = recursive_replace(block, "finished_sub_slots", [new_finished_ss_4])

                header_block_bad_4 = get_block_header(block_bad_4, [], [])
                # TODO: Inspect these block values as they are currently None
                expected_difficulty = block.finished_sub_slots[0].challenge_chain.new_difficulty or uint64(0)
                expected_sub_slot_iters = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters or uint64(0)
                _, error = validate_finished_header_block(
                    empty_blockchain.constants,
                    empty_blockchain,
                    header_block_bad_4,
                    False,
                    expected_difficulty,
                    expected_sub_slot_iters,
                )
                assert error is not None
                assert error.code == Err.INVALID_SUB_EPOCH_SUMMARY

                # Also fails calling the outer methods, but potentially with a different error
                await _validate_and_add_block(
                    empty_blockchain, block_bad_4, expected_result=AddBlockResult.INVALID_BLOCK
                )
            await _validate_and_add_block(empty_blockchain, block)
            log.info(
                f"Added block {block.height} total iters {block.total_iters} "
                f"new slot? {len(block.finished_sub_slots)}"
            )
        peak = empty_blockchain.get_peak()
        assert peak is not None
        assert peak.height == len(blocks) - 1

    @pytest.mark.anyio
    async def test_unfinished_blocks(
        self, empty_blockchain: Blockchain, softfork_height: uint32, bt: BlockTools
    ) -> None:
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(3)
        for block in blocks[:-1]:
            await _validate_and_add_block(empty_blockchain, block)
        block = blocks[-1]
        unf = UnfinishedBlock(
            block.finished_sub_slots,
            block.reward_chain_block.get_unfinished(),
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage,
            block.foliage_transaction_block,
            block.transactions_info,
            block.transactions_generator,
            [],
        )
        npc_result = None
        # if this assert fires, remove it along with the pragma for the block
        # below
        assert unf.transactions_generator is None
        if unf.transactions_generator is not None:  # pragma: no cover
            block_generator = await get_block_generator(blockchain.lookup_block_generators, unf)
            assert block_generator is not None
            block_bytes = bytes(unf)
            npc_result = await blockchain.run_generator(block_bytes, block_generator, height=softfork_height)

        validate_res = await blockchain.validate_unfinished_block(unf, npc_result, False)
        err = validate_res.error
        assert err is None

        await _validate_and_add_block(empty_blockchain, block)
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, force_overflow=True)
        block = blocks[-1]
        unf = UnfinishedBlock(
            block.finished_sub_slots,
            block.reward_chain_block.get_unfinished(),
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage,
            block.foliage_transaction_block,
            block.transactions_info,
            block.transactions_generator,
            [],
        )
        npc_result = None
        # if this assert fires, remove it along with the pragma for the block
        # below
        assert unf.transactions_generator is None
        if unf.transactions_generator is not None:  # pragma: no cover
            block_generator = await get_block_generator(blockchain.lookup_block_generators, unf)
            assert block_generator is not None
            block_bytes = bytes(unf)
            npc_result = await blockchain.run_generator(block_bytes, block_generator, height=softfork_height)
        validate_res = await blockchain.validate_unfinished_block(unf, npc_result, False)
        assert validate_res.error is None

    @pytest.mark.anyio
    async def test_empty_genesis(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        for block in bt.get_consecutive_blocks(2, skip_slots=3):
            await _validate_and_add_block(empty_blockchain, block)

    @pytest.mark.anyio
    async def test_empty_slots_non_genesis(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(10)
        for block in blocks:
            await _validate_and_add_block(empty_blockchain, block)

        blocks = bt.get_consecutive_blocks(10, skip_slots=2, block_list_input=blocks)
        for block in blocks[10:]:
            await _validate_and_add_block(empty_blockchain, block)
        peak = blockchain.get_peak()
        assert peak is not None
        assert peak.height == 19

    @pytest.mark.anyio
    async def test_one_sb_per_slot(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        blockchain = empty_blockchain
        num_blocks = 20
        blocks: List[FullBlock] = []
        for _ in range(num_blocks):
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1)
            await _validate_and_add_block(empty_blockchain, blocks[-1])
        peak = blockchain.get_peak()
        assert peak is not None
        assert peak.height == num_blocks - 1

    @pytest.mark.anyio
    async def test_all_overflow(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        blockchain = empty_blockchain
        num_rounds = 5
        blocks: List[FullBlock] = []
        num_blocks = 0
        for i in range(1, num_rounds):
            num_blocks += i
            blocks = bt.get_consecutive_blocks(i, block_list_input=blocks, skip_slots=1, force_overflow=True)
            for block in blocks[-i:]:
                await _validate_and_add_block(empty_blockchain, block)
        peak = blockchain.get_peak()
        assert peak is not None
        assert peak.height == num_blocks - 1

    @pytest.mark.anyio
    async def test_unf_block_overflow(
        self, empty_blockchain: Blockchain, softfork_height: uint32, bt: BlockTools
    ) -> None:
        blockchain = empty_blockchain

        blocks: List[FullBlock] = []
        while True:
            # This creates an overflow block, then a normal block, and then an overflow in the next sub-slot
            # blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, force_overflow=True)
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, force_overflow=True)

            await _validate_and_add_block(blockchain, blocks[-2])

            sb_1 = blockchain.block_record(blocks[-2].header_hash)

            sb_2_next_ss = blocks[-1].total_iters - blocks[-2].total_iters < sb_1.sub_slot_iters
            # We might not get a normal block for sb_2, and we might not get them in the right slots
            # So this while loop keeps trying
            if sb_1.overflow and sb_2_next_ss:
                block = blocks[-1]
                unf = UnfinishedBlock(
                    [],
                    block.reward_chain_block.get_unfinished(),
                    block.challenge_chain_sp_proof,
                    block.reward_chain_sp_proof,
                    block.foliage,
                    block.foliage_transaction_block,
                    block.transactions_info,
                    block.transactions_generator,
                    [],
                )
                npc_result = None
                # if this assert fires, remove it along with the pragma for the block
                # below
                assert block.transactions_generator is None
                if block.transactions_generator is not None:  # pragma: no cover
                    block_generator = await get_block_generator(blockchain.lookup_block_generators, unf)
                    assert block_generator is not None
                    block_bytes = bytes(unf)
                    npc_result = await blockchain.run_generator(block_bytes, block_generator, height=softfork_height)
                validate_res = await blockchain.validate_unfinished_block(
                    unf, npc_result, skip_overflow_ss_validation=True
                )
                assert validate_res.error is None
                return None

            await _validate_and_add_block(blockchain, blocks[-1])

    @pytest.mark.anyio
    async def test_one_sb_per_two_slots(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        blockchain = empty_blockchain
        num_blocks = 20
        blocks: List[FullBlock] = []
        for _ in range(num_blocks):  # Same thing, but 2 sub-slots per block
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=2)
            await _validate_and_add_block(blockchain, blocks[-1])
        peak = blockchain.get_peak()
        assert peak is not None
        assert peak.height == num_blocks - 1

    @pytest.mark.anyio
    async def test_one_sb_per_five_slots(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        blockchain = empty_blockchain
        num_blocks = 10
        blocks: List[FullBlock] = []
        for _ in range(num_blocks):  # Same thing, but 5 sub-slots per block
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=5)
            await _validate_and_add_block(blockchain, blocks[-1])
        peak = blockchain.get_peak()
        assert peak is not None
        assert peak.height == num_blocks - 1

    @pytest.mark.anyio
    async def test_basic_chain_overflow(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        blocks = bt.get_consecutive_blocks(5, force_overflow=True)
        for block in blocks:
            await _validate_and_add_block(empty_blockchain, block)
        peak = empty_blockchain.get_peak()
        assert peak is not None
        assert peak.height == len(blocks) - 1

    @pytest.mark.anyio
    async def test_one_sb_per_two_slots_force_overflow(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        blockchain = empty_blockchain
        num_blocks = 10
        blocks: List[FullBlock] = []
        for _ in range(num_blocks):
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=2, force_overflow=True)
            await _validate_and_add_block(blockchain, blocks[-1])
        peak = blockchain.get_peak()
        assert peak is not None
        assert peak.height == num_blocks - 1

    @pytest.mark.anyio
    async def test_invalid_prev(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 1
        blocks = bt.get_consecutive_blocks(2, force_overflow=False)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_1_bad = recursive_replace(blocks[-1], "foliage.prev_block_hash", bytes([0] * 32))

        await _validate_and_add_block(empty_blockchain, block_1_bad, expected_error=Err.INVALID_PREV_BLOCK_HASH)

    @pytest.mark.anyio
    async def test_invalid_pospace(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2
        blocks = bt.get_consecutive_blocks(2, force_overflow=False)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_1_bad = recursive_replace(blocks[-1], "reward_chain_block.proof_of_space.proof", bytes([0] * 32))

        await _validate_and_add_block(empty_blockchain, block_1_bad, expected_error=Err.INVALID_POSPACE)

    @pytest.mark.anyio
    async def test_invalid_sub_slot_challenge_hash_genesis(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2a
        blocks = bt.get_consecutive_blocks(1, force_overflow=False, skip_slots=1)
        new_finished_ss = recursive_replace(
            blocks[0].finished_sub_slots[0],
            "challenge_chain.challenge_chain_end_of_slot_vdf.challenge",
            bytes([2] * 32),
        )
        block_0_bad = recursive_replace(
            blocks[0], "finished_sub_slots", [new_finished_ss] + blocks[0].finished_sub_slots[1:]
        )

        header_block_bad = get_block_header(block_0_bad, [], [])
        _, error = validate_finished_header_block(
            empty_blockchain.constants,
            empty_blockchain,
            header_block_bad,
            False,
            empty_blockchain.constants.DIFFICULTY_STARTING,
            empty_blockchain.constants.SUB_SLOT_ITERS_STARTING,
        )

        assert error is not None
        assert error.code == Err.INVALID_PREV_CHALLENGE_SLOT_HASH
        await _validate_and_add_block(empty_blockchain, block_0_bad, expected_result=AddBlockResult.INVALID_BLOCK)

    @pytest.mark.anyio
    async def test_invalid_sub_slot_challenge_hash_non_genesis(
        self, empty_blockchain: Blockchain, bt: BlockTools
    ) -> None:
        # 2b
        blocks = bt.get_consecutive_blocks(1, force_overflow=False, skip_slots=0)
        blocks = bt.get_consecutive_blocks(1, force_overflow=False, skip_slots=1, block_list_input=blocks)
        new_finished_ss = recursive_replace(
            blocks[1].finished_sub_slots[0],
            "challenge_chain.challenge_chain_end_of_slot_vdf.challenge",
            bytes([2] * 32),
        )
        block_1_bad = recursive_replace(
            blocks[1], "finished_sub_slots", [new_finished_ss] + blocks[1].finished_sub_slots[1:]
        )

        await _validate_and_add_block(empty_blockchain, blocks[0])
        header_block_bad = get_block_header(block_1_bad, [], [])
        # TODO: Inspect these block values as they are currently None
        expected_difficulty = blocks[1].finished_sub_slots[0].challenge_chain.new_difficulty or uint64(0)
        expected_sub_slot_iters = blocks[1].finished_sub_slots[0].challenge_chain.new_sub_slot_iters or uint64(0)
        _, error = validate_finished_header_block(
            empty_blockchain.constants,
            empty_blockchain,
            header_block_bad,
            False,
            expected_difficulty,
            expected_sub_slot_iters,
        )
        assert error is not None
        assert error.code == Err.INVALID_PREV_CHALLENGE_SLOT_HASH
        await _validate_and_add_block(empty_blockchain, block_1_bad, expected_result=AddBlockResult.INVALID_BLOCK)

    @pytest.mark.anyio
    async def test_invalid_sub_slot_challenge_hash_empty_ss(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2c
        blocks = bt.get_consecutive_blocks(1, force_overflow=False, skip_slots=0)
        blocks = bt.get_consecutive_blocks(1, force_overflow=False, skip_slots=2, block_list_input=blocks)
        new_finished_ss = recursive_replace(
            blocks[1].finished_sub_slots[-1],
            "challenge_chain.challenge_chain_end_of_slot_vdf.challenge",
            bytes([2] * 32),
        )
        block_1_bad = recursive_replace(
            blocks[1], "finished_sub_slots", blocks[1].finished_sub_slots[:-1] + [new_finished_ss]
        )
        await _validate_and_add_block(empty_blockchain, blocks[0])

        header_block_bad = get_block_header(block_1_bad, [], [])
        # TODO: Inspect these block values as they are currently None
        expected_difficulty = blocks[1].finished_sub_slots[0].challenge_chain.new_difficulty or uint64(0)
        expected_sub_slot_iters = blocks[1].finished_sub_slots[0].challenge_chain.new_sub_slot_iters or uint64(0)
        _, error = validate_finished_header_block(
            empty_blockchain.constants,
            empty_blockchain,
            header_block_bad,
            False,
            expected_difficulty,
            expected_sub_slot_iters,
        )
        assert error is not None
        assert error.code == Err.INVALID_PREV_CHALLENGE_SLOT_HASH
        await _validate_and_add_block(empty_blockchain, block_1_bad, expected_result=AddBlockResult.INVALID_BLOCK)

    @pytest.mark.anyio
    async def test_genesis_no_icc(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2d
        blocks = bt.get_consecutive_blocks(1, force_overflow=False, skip_slots=1)
        new_finished_ss = recursive_replace(
            blocks[0].finished_sub_slots[0],
            "infused_challenge_chain",
            InfusedChallengeChainSubSlot(
                VDFInfo(
                    bytes32([0] * 32),
                    uint64(1200),
                    ClassgroupElement.get_default_element(),
                )
            ),
        )
        block_0_bad = recursive_replace(
            blocks[0], "finished_sub_slots", [new_finished_ss] + blocks[0].finished_sub_slots[1:]
        )
        await _validate_and_add_block(empty_blockchain, block_0_bad, expected_error=Err.SHOULD_NOT_HAVE_ICC)

    async def do_test_invalid_icc_sub_slot_vdf(
        self, keychain: Keychain, db_version: int, constants: ConsensusConstants
    ) -> None:
        bt_high_iters = await create_block_tools_async(
            constants=constants.replace(
                SUB_SLOT_ITERS_STARTING=uint64(2**12),
                DIFFICULTY_STARTING=uint64(2**14),
            ),
            keychain=keychain,
        )
        async with create_blockchain(bt_high_iters.constants, db_version) as (bc1, db_wrapper):
            blocks = bt_high_iters.get_consecutive_blocks(10)
            for block in blocks:
                if (
                    len(block.finished_sub_slots) > 0
                    and block.finished_sub_slots[-1].infused_challenge_chain is not None
                ):
                    # Bad iters
                    new_finished_ss = recursive_replace(
                        block.finished_sub_slots[-1],
                        "infused_challenge_chain",
                        InfusedChallengeChainSubSlot(
                            block.finished_sub_slots[
                                -1
                            ].infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.replace(
                                number_of_iterations=uint64(10000000),
                            )
                        ),
                    )
                    block_bad = recursive_replace(
                        block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss]
                    )
                    await _validate_and_add_block(bc1, block_bad, expected_error=Err.INVALID_ICC_EOS_VDF)

                    # Bad output
                    new_finished_ss_2 = recursive_replace(
                        block.finished_sub_slots[-1],
                        "infused_challenge_chain",
                        InfusedChallengeChainSubSlot(
                            block.finished_sub_slots[
                                -1
                            ].infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.replace(
                                output=ClassgroupElement.get_default_element(),
                            )
                        ),
                    )
                    log.warning(f"Proof: {block.finished_sub_slots[-1].proofs}")
                    block_bad_2 = recursive_replace(
                        block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_2]
                    )
                    await _validate_and_add_block(bc1, block_bad_2, expected_error=Err.INVALID_ICC_EOS_VDF)

                    # Bad challenge hash
                    new_finished_ss_3 = recursive_replace(
                        block.finished_sub_slots[-1],
                        "infused_challenge_chain",
                        InfusedChallengeChainSubSlot(
                            block.finished_sub_slots[
                                -1
                            ].infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.replace(
                                challenge=bytes32([0] * 32)
                            )
                        ),
                    )
                    block_bad_3 = recursive_replace(
                        block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_3]
                    )
                    await _validate_and_add_block(bc1, block_bad_3, expected_error=Err.INVALID_ICC_EOS_VDF)

                    # Bad proof
                    new_finished_ss_5 = recursive_replace(
                        block.finished_sub_slots[-1],
                        "proofs.infused_challenge_chain_slot_proof",
                        VDFProof(uint8(0), b"1239819023890", False),
                    )
                    block_bad_5 = recursive_replace(
                        block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_5]
                    )
                    await _validate_and_add_block(bc1, block_bad_5, expected_error=Err.INVALID_ICC_EOS_VDF)

                await _validate_and_add_block(bc1, block)

    @pytest.mark.anyio
    async def test_invalid_icc_sub_slot_vdf(self, db_version: int, blockchain_constants: ConsensusConstants) -> None:
        with TempKeyring() as keychain:
            await self.do_test_invalid_icc_sub_slot_vdf(keychain, db_version, blockchain_constants)

    @pytest.mark.anyio
    async def test_invalid_icc_into_cc(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(blockchain, blocks[0])
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1)
            block = blocks[-1]
            if len(block.finished_sub_slots) > 0 and block.finished_sub_slots[-1].infused_challenge_chain is not None:
                if block.finished_sub_slots[-1].reward_chain.deficit == bt.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                    # 2g
                    case_1 = True
                    new_finished_ss = recursive_replace(
                        block.finished_sub_slots[-1],
                        "challenge_chain",
                        block.finished_sub_slots[-1].challenge_chain.replace(
                            infused_challenge_chain_sub_slot_hash=bytes32([1] * 32)
                        ),
                    )
                else:
                    # 2h
                    case_2 = True
                    new_finished_ss = recursive_replace(
                        block.finished_sub_slots[-1],
                        "challenge_chain",
                        block.finished_sub_slots[-1].challenge_chain.replace(
                            infused_challenge_chain_sub_slot_hash=block.finished_sub_slots[
                                -1
                            ].infused_challenge_chain.get_hash(),
                        ),
                    )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss]
                )

                header_block_bad = get_block_header(block_bad, [], [])
                # TODO: Inspect these block values as they are currently None
                expected_difficulty = block.finished_sub_slots[0].challenge_chain.new_difficulty or uint64(0)
                expected_sub_slot_iters = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters or uint64(0)
                _, error = validate_finished_header_block(
                    empty_blockchain.constants,
                    empty_blockchain,
                    header_block_bad,
                    False,
                    expected_difficulty,
                    expected_sub_slot_iters,
                )
                assert error is not None
                assert error.code == Err.INVALID_ICC_HASH_CC
                await _validate_and_add_block(blockchain, block_bad, expected_result=AddBlockResult.INVALID_BLOCK)

                # 2i
                new_finished_ss_bad_rc = recursive_replace(
                    block.finished_sub_slots[-1],
                    "reward_chain",
                    block.finished_sub_slots[-1].reward_chain.replace(infused_challenge_chain_sub_slot_hash=None),
                )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_bad_rc]
                )
                await _validate_and_add_block(blockchain, block_bad, expected_error=Err.INVALID_ICC_HASH_RC)
            elif len(block.finished_sub_slots) > 0 and block.finished_sub_slots[-1].infused_challenge_chain is None:
                # 2j
                # TODO: This code path is currently not exercised
                new_finished_ss_bad_cc = recursive_replace(
                    block.finished_sub_slots[-1],
                    "challenge_chain",
                    block.finished_sub_slots[-1].challenge_chain.replace(
                        infused_challenge_chain_sub_slot_hash=bytes32([1] * 32)
                    ),
                )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_bad_cc]
                )
                await _validate_and_add_block(blockchain, block_bad, expected_error=Err.INVALID_ICC_HASH_CC)

                # 2k
                # TODO: This code path is currently not exercised
                new_finished_ss_bad_rc = recursive_replace(
                    block.finished_sub_slots[-1],
                    "reward_chain",
                    block.finished_sub_slots[-1].reward_chain.replace(
                        infused_challenge_chain_sub_slot_hash=bytes32([1] * 32)
                    ),
                )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_bad_rc]
                )
                await _validate_and_add_block(blockchain, block_bad, expected_error=Err.INVALID_ICC_HASH_RC)

            # Finally, add the block properly
            await _validate_and_add_block(blockchain, block)

    @pytest.mark.anyio
    async def test_empty_slot_no_ses(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2l
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(blockchain, blocks[0])
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=4)

        new_finished_ss = recursive_replace(
            blocks[-1].finished_sub_slots[-1],
            "challenge_chain",
            blocks[-1].finished_sub_slots[-1].challenge_chain.replace(subepoch_summary_hash=std_hash(b"0")),
        )
        block_bad = recursive_replace(
            blocks[-1], "finished_sub_slots", blocks[-1].finished_sub_slots[:-1] + [new_finished_ss]
        )

        header_block_bad = get_block_header(block_bad, [], [])
        _, error = validate_finished_header_block(
            empty_blockchain.constants,
            empty_blockchain,
            header_block_bad,
            False,
            empty_blockchain.constants.DIFFICULTY_STARTING,
            empty_blockchain.constants.SUB_SLOT_ITERS_STARTING,
        )
        assert error is not None
        assert error.code == Err.INVALID_SUB_EPOCH_SUMMARY_HASH
        await _validate_and_add_block(blockchain, block_bad, expected_result=AddBlockResult.INVALID_BLOCK)

    @pytest.mark.anyio
    async def test_empty_sub_slots_epoch(
        self, empty_blockchain: Blockchain, default_400_blocks: List[FullBlock], bt: BlockTools
    ) -> None:
        # 2m
        # Tests adding an empty sub slot after the sub-epoch / epoch.
        # Also tests overflow block in epoch
        blocks_base = default_400_blocks[: bt.constants.EPOCH_BLOCKS]
        assert len(blocks_base) == bt.constants.EPOCH_BLOCKS
        blocks_1 = bt.get_consecutive_blocks(1, block_list_input=blocks_base, force_overflow=True)
        blocks_2 = bt.get_consecutive_blocks(1, skip_slots=5, block_list_input=blocks_base, force_overflow=True)
        for block in blocks_base:
            await _validate_and_add_block(empty_blockchain, block, skip_prevalidation=True)
        await _validate_and_add_block(
            empty_blockchain, blocks_1[-1], expected_result=AddBlockResult.NEW_PEAK, skip_prevalidation=True
        )
        assert blocks_1[-1].header_hash != blocks_2[-1].header_hash
        await _validate_and_add_block(
            empty_blockchain, blocks_2[-1], expected_result=AddBlockResult.ADDED_AS_ORPHAN, skip_prevalidation=True
        )

    @pytest.mark.anyio
    async def test_wrong_cc_hash_rc(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2o
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(1, skip_slots=1)
        blocks = bt.get_consecutive_blocks(1, skip_slots=1, block_list_input=blocks)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        new_finished_ss = recursive_replace(
            blocks[-1].finished_sub_slots[-1],
            "reward_chain",
            blocks[-1].finished_sub_slots[-1].reward_chain.replace(challenge_chain_sub_slot_hash=bytes32([3] * 32)),
        )
        block_1_bad = recursive_replace(
            blocks[-1], "finished_sub_slots", blocks[-1].finished_sub_slots[:-1] + [new_finished_ss]
        )

        await _validate_and_add_block(blockchain, block_1_bad, expected_error=Err.INVALID_CHALLENGE_SLOT_HASH_RC)

    @pytest.mark.anyio
    async def test_invalid_cc_sub_slot_vdf(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2q
        blocks: List[FullBlock] = []
        found_overflow_slot: bool = False

        while not found_overflow_slot:
            blocks = bt.get_consecutive_blocks(1, blocks)
            block = blocks[-1]
            if (
                len(block.finished_sub_slots)
                and is_overflow_block(bt.constants, block.reward_chain_block.signage_point_index)
                and block.finished_sub_slots[-1].challenge_chain.challenge_chain_end_of_slot_vdf.output
                != ClassgroupElement.get_default_element()
            ):
                found_overflow_slot = True
                # Bad iters
                new_finished_ss = recursive_replace(
                    block.finished_sub_slots[-1],
                    "challenge_chain",
                    recursive_replace(
                        block.finished_sub_slots[-1].challenge_chain,
                        "challenge_chain_end_of_slot_vdf.number_of_iterations",
                        uint64(10000000),
                    ),
                )
                new_finished_ss = recursive_replace(
                    new_finished_ss,
                    "reward_chain.challenge_chain_sub_slot_hash",
                    new_finished_ss.challenge_chain.get_hash(),
                )
                log.warning(f"Num slots: {len(block.finished_sub_slots)}")
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss]
                )
                log.warning(f"Signage point index: {block_bad.reward_chain_block.signage_point_index}")
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_CC_EOS_VDF)

                # Bad output
                new_finished_ss_2 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "challenge_chain",
                    recursive_replace(
                        block.finished_sub_slots[-1].challenge_chain,
                        "challenge_chain_end_of_slot_vdf.output",
                        ClassgroupElement.get_default_element(),
                    ),
                )

                new_finished_ss_2 = recursive_replace(
                    new_finished_ss_2,
                    "reward_chain.challenge_chain_sub_slot_hash",
                    new_finished_ss_2.challenge_chain.get_hash(),
                )
                block_bad_2 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_2]
                )
                await _validate_and_add_block(empty_blockchain, block_bad_2, expected_error=Err.INVALID_CC_EOS_VDF)

                # Bad challenge hash
                new_finished_ss_3 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "challenge_chain",
                    recursive_replace(
                        block.finished_sub_slots[-1].challenge_chain,
                        "challenge_chain_end_of_slot_vdf.challenge",
                        bytes([1] * 32),
                    ),
                )

                new_finished_ss_3 = recursive_replace(
                    new_finished_ss_3,
                    "reward_chain.challenge_chain_sub_slot_hash",
                    new_finished_ss_3.challenge_chain.get_hash(),
                )
                block_bad_3 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_3]
                )

                await _validate_and_add_block_multi_error(
                    empty_blockchain,
                    block_bad_3,
                    [Err.INVALID_CC_EOS_VDF, Err.INVALID_PREV_CHALLENGE_SLOT_HASH, Err.INVALID_POSPACE],
                )

                # Bad proof
                new_finished_ss_5 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "proofs.challenge_chain_slot_proof",
                    VDFProof(uint8(0), b"1239819023890", False),
                )
                block_bad_5 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_5]
                )
                await _validate_and_add_block(empty_blockchain, block_bad_5, expected_error=Err.INVALID_CC_EOS_VDF)

            await _validate_and_add_block(empty_blockchain, block)

    @pytest.mark.anyio
    async def test_invalid_rc_sub_slot_vdf(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2p
        blocks: List[FullBlock] = []
        found_block: bool = False

        while not found_block:
            blocks = bt.get_consecutive_blocks(1, blocks)
            block = blocks[-1]
            if (
                len(block.finished_sub_slots)
                and block.finished_sub_slots[-1].reward_chain.end_of_slot_vdf.output
                != ClassgroupElement.get_default_element()
            ):
                found_block = True
                # Bad iters
                new_finished_ss = recursive_replace(
                    block.finished_sub_slots[-1],
                    "reward_chain",
                    recursive_replace(
                        block.finished_sub_slots[-1].reward_chain,
                        "end_of_slot_vdf.number_of_iterations",
                        uint64(10000000),
                    ),
                )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss]
                )
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_RC_EOS_VDF)

                # Bad output
                new_finished_ss_2 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "reward_chain",
                    recursive_replace(
                        block.finished_sub_slots[-1].reward_chain,
                        "end_of_slot_vdf.output",
                        ClassgroupElement.get_default_element(),
                    ),
                )
                block_bad_2 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_2]
                )
                await _validate_and_add_block(empty_blockchain, block_bad_2, expected_error=Err.INVALID_RC_EOS_VDF)

                # Bad challenge hash
                new_finished_ss_3 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "reward_chain",
                    recursive_replace(
                        block.finished_sub_slots[-1].reward_chain,
                        "end_of_slot_vdf.challenge",
                        bytes32([1] * 32),
                    ),
                )
                block_bad_3 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_3]
                )
                await _validate_and_add_block(empty_blockchain, block_bad_3, expected_error=Err.INVALID_RC_EOS_VDF)

                # Bad proof
                new_finished_ss_5 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "proofs.reward_chain_slot_proof",
                    VDFProof(uint8(0), b"1239819023890", False),
                )
                block_bad_5 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_5]
                )
                await _validate_and_add_block(empty_blockchain, block_bad_5, expected_error=Err.INVALID_RC_EOS_VDF)

            await _validate_and_add_block(empty_blockchain, block)

    @pytest.mark.anyio
    async def test_genesis_bad_deficit(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2r
        block = bt.get_consecutive_blocks(1, skip_slots=2)[0]
        new_finished_ss = recursive_replace(
            block.finished_sub_slots[-1],
            "reward_chain",
            recursive_replace(
                block.finished_sub_slots[-1].reward_chain,
                "deficit",
                bt.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1,
            ),
        )
        block_bad = recursive_replace(block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss])
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_DEFICIT)

    @pytest.mark.anyio
    async def test_reset_deficit(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2s, 2t
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1)
            if len(blocks[-1].finished_sub_slots) > 0:
                new_finished_ss = recursive_replace(
                    blocks[-1].finished_sub_slots[-1],
                    "reward_chain",
                    recursive_replace(
                        blocks[-1].finished_sub_slots[-1].reward_chain,
                        "deficit",
                        uint8(0),
                    ),
                )
                if blockchain.block_record(blocks[-2].header_hash).deficit == 0:
                    case_1 = True
                else:
                    case_2 = True

                block_bad = recursive_replace(
                    blocks[-1], "finished_sub_slots", blocks[-1].finished_sub_slots[:-1] + [new_finished_ss]
                )
                await _validate_and_add_block_multi_error(
                    empty_blockchain, block_bad, [Err.INVALID_DEFICIT, Err.INVALID_ICC_HASH_CC]
                )

            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.anyio
    async def test_genesis_has_ses(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 3a
        block = bt.get_consecutive_blocks(1, skip_slots=1)[0]
        new_finished_ss = recursive_replace(
            block.finished_sub_slots[0],
            "challenge_chain",
            recursive_replace(
                block.finished_sub_slots[0].challenge_chain,
                "subepoch_summary_hash",
                bytes32([0] * 32),
            ),
        )

        new_finished_ss = recursive_replace(
            new_finished_ss,
            "reward_chain",
            new_finished_ss.reward_chain.replace(
                challenge_chain_sub_slot_hash=new_finished_ss.challenge_chain.get_hash()
            ),
        )
        block_bad = recursive_replace(block, "finished_sub_slots", [new_finished_ss] + block.finished_sub_slots[1:])
        with pytest.raises(AssertionError):
            # Fails pre validation
            await _validate_and_add_block(
                empty_blockchain, block_bad, expected_error=Err.INVALID_SUB_EPOCH_SUMMARY_HASH
            )

    @pytest.mark.anyio
    async def test_no_ses_if_no_se(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 3b
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if len(blocks[-1].finished_sub_slots) > 0 and is_overflow_block(
                bt.constants, blocks[-1].reward_chain_block.signage_point_index
            ):
                new_finished_ss: EndOfSubSlotBundle = recursive_replace(
                    blocks[-1].finished_sub_slots[0],
                    "challenge_chain",
                    recursive_replace(
                        blocks[-1].finished_sub_slots[0].challenge_chain,
                        "subepoch_summary_hash",
                        bytes32([0] * 32),
                    ),
                )

                new_finished_ss = recursive_replace(
                    new_finished_ss,
                    "reward_chain",
                    new_finished_ss.reward_chain.replace(
                        challenge_chain_sub_slot_hash=new_finished_ss.challenge_chain.get_hash(),
                    ),
                )
                block_bad = recursive_replace(
                    blocks[-1], "finished_sub_slots", [new_finished_ss] + blocks[-1].finished_sub_slots[1:]
                )
                await _validate_and_add_block_multi_error(
                    empty_blockchain,
                    block_bad,
                    expected_errors=[
                        Err.INVALID_SUB_EPOCH_SUMMARY_HASH,
                        Err.INVALID_SUB_EPOCH_SUMMARY,
                    ],
                )
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.anyio
    async def test_too_many_blocks(self, empty_blockchain: Blockchain) -> None:
        # 4: TODO
        pass

    @pytest.mark.anyio
    async def test_bad_pos(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 5
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        block_bad = recursive_replace(blocks[-1], "reward_chain_block.proof_of_space.challenge", std_hash(b""))
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_POSPACE)

        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.proof_of_space.pool_contract_puzzle_hash", std_hash(b"")
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_POSPACE)

        block_bad = recursive_replace(blocks[-1], "reward_chain_block.proof_of_space.size", 62)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_POSPACE)

        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.proof_of_space.plot_public_key",
            AugSchemeMPL.key_gen(std_hash(b"1231n")).get_g1(),
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_POSPACE)
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.proof_of_space.size",
            32,
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_POSPACE)
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.proof_of_space.proof",
            bytes([1] * int(blocks[-1].reward_chain_block.proof_of_space.size * 64 / 8)),
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_POSPACE)

        # TODO: test not passing the plot filter

    @pytest.mark.anyio
    async def test_bad_signage_point_index(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 6
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        with pytest.raises(ValueError):
            block_bad = recursive_replace(
                blocks[-1], "reward_chain_block.signage_point_index", bt.constants.NUM_SPS_SUB_SLOT
            )
            await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_SP_INDEX)
        with pytest.raises(ValueError):
            block_bad = recursive_replace(
                blocks[-1], "reward_chain_block.signage_point_index", bt.constants.NUM_SPS_SUB_SLOT + 1
            )
            await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_SP_INDEX)

    @pytest.mark.anyio
    async def test_sp_0_no_sp(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 7
        blocks: List[FullBlock] = []
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].reward_chain_block.signage_point_index == 0:
                case_1 = True
                block_bad = recursive_replace(blocks[-1], "reward_chain_block.signage_point_index", uint8(1))
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_SP_INDEX)

            elif not is_overflow_block(bt.constants, blocks[-1].reward_chain_block.signage_point_index):
                case_2 = True
                block_bad = recursive_replace(blocks[-1], "reward_chain_block.signage_point_index", uint8(0))
                await _validate_and_add_block_multi_error(
                    empty_blockchain, block_bad, [Err.INVALID_SP_INDEX, Err.INVALID_POSPACE]
                )
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.anyio
    async def test_epoch_overflows(self, empty_blockchain: Blockchain) -> None:
        # 9. TODO. This is hard to test because it requires modifying the block tools to make these special blocks
        pass

    @pytest.mark.anyio
    async def test_bad_total_iters(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 10
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.total_iters", blocks[-1].reward_chain_block.total_iters + 1
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_TOTAL_ITERS)

    @pytest.mark.anyio
    async def test_bad_rc_sp_vdf(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 11
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].reward_chain_block.signage_point_index != 0:
                block_bad = recursive_replace(
                    blocks[-1], "reward_chain_block.reward_chain_sp_vdf.challenge", std_hash(b"1")
                )
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_RC_SP_VDF)
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_block.reward_chain_sp_vdf.output",
                    bad_element,
                )
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_RC_SP_VDF)
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_block.reward_chain_sp_vdf.number_of_iterations",
                    uint64(1111111111111),
                )
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_RC_SP_VDF)
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_sp_proof",
                    VDFProof(uint8(0), std_hash(b""), False),
                )
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_RC_SP_VDF)
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.anyio
    async def test_bad_rc_sp_sig(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 12
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad = recursive_replace(blocks[-1], "reward_chain_block.reward_chain_sp_signature", G2Element.generator())
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_RC_SIGNATURE)

    @pytest.mark.anyio
    async def test_bad_cc_sp_vdf(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 13. Note: does not validate fully due to proof of space being validated first

        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].reward_chain_block.signage_point_index != 0:
                block_bad = recursive_replace(
                    blocks[-1], "reward_chain_block.challenge_chain_sp_vdf.challenge", std_hash(b"1")
                )
                await _validate_and_add_block(empty_blockchain, block_bad, expected_result=AddBlockResult.INVALID_BLOCK)
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_block.challenge_chain_sp_vdf.output",
                    bad_element,
                )
                await _validate_and_add_block(empty_blockchain, block_bad, expected_result=AddBlockResult.INVALID_BLOCK)
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_block.challenge_chain_sp_vdf.number_of_iterations",
                    uint64(1111111111111),
                )
                await _validate_and_add_block(empty_blockchain, block_bad, expected_result=AddBlockResult.INVALID_BLOCK)
                block_bad = recursive_replace(
                    blocks[-1],
                    "challenge_chain_sp_proof",
                    VDFProof(uint8(0), std_hash(b""), False),
                )
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_CC_SP_VDF)
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.anyio
    async def test_bad_cc_sp_sig(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 14
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.challenge_chain_sp_signature", G2Element.generator()
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_CC_SIGNATURE)

    @pytest.mark.anyio
    async def test_is_transaction_block(self, empty_blockchain: Blockchain) -> None:
        # 15: TODO
        pass

    @pytest.mark.anyio
    async def test_bad_foliage_sb_sig(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 16
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad = recursive_replace(blocks[-1], "foliage.foliage_block_data_signature", G2Element.generator())
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_PLOT_SIGNATURE)

    @pytest.mark.anyio
    async def test_bad_foliage_transaction_block_sig(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 17
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_transaction_block is not None:
                block_bad = recursive_replace(
                    blocks[-1], "foliage.foliage_transaction_block_signature", G2Element.generator()
                )
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_PLOT_SIGNATURE)
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.anyio
    async def test_unfinished_reward_chain_sb_hash(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 18
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage.foliage_block_data.unfinished_reward_block_hash", std_hash(b"2")
        )
        new_m = block_bad.foliage.foliage_block_data.get_hash()
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_URSB_HASH)

    @pytest.mark.anyio
    async def test_pool_target_height(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 19
        blocks = bt.get_consecutive_blocks(3)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        block_bad: FullBlock = recursive_replace(blocks[-1], "foliage.foliage_block_data.pool_target.max_height", 1)
        new_m = block_bad.foliage.foliage_block_data.get_hash()
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.OLD_POOL_TARGET)

    @pytest.mark.anyio
    async def test_pool_target_pre_farm(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 20a
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage.foliage_block_data.pool_target.puzzle_hash", std_hash(b"12")
        )
        new_m = block_bad.foliage.foliage_block_data.get_hash()
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_PREFARM)

    @pytest.mark.anyio
    async def test_pool_target_signature(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 20b
        blocks_initial = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks_initial[0])
        await _validate_and_add_block(empty_blockchain, blocks_initial[1])

        attempts = 0
        while True:
            # Go until we get a block that has a pool pk, as opposed to a pool contract
            blocks = bt.get_consecutive_blocks(
                1, blocks_initial, seed=std_hash(attempts.to_bytes(4, byteorder="big", signed=False))
            )
            if blocks[-1].foliage.foliage_block_data.pool_signature is not None:
                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage.foliage_block_data.pool_signature", G2Element.generator()
                )
                new_m = block_bad.foliage.foliage_block_data.get_hash()
                assert new_m is not None
                new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_POOL_SIGNATURE)
                return None
            attempts += 1

    @pytest.mark.anyio
    async def test_pool_target_contract(
        self, empty_blockchain: Blockchain, bt: BlockTools, seeded_random: random.Random
    ) -> None:
        # 20c invalid pool target with contract
        blocks_initial = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks_initial[0])
        await _validate_and_add_block(empty_blockchain, blocks_initial[1])

        attempts = 0
        while True:
            # Go until we get a block that has a pool contract opposed to a pool pk
            blocks = bt.get_consecutive_blocks(
                1, blocks_initial, seed=std_hash(attempts.to_bytes(4, byteorder="big", signed=False))
            )
            if blocks[-1].foliage.foliage_block_data.pool_signature is None:
                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage.foliage_block_data.pool_target.puzzle_hash", bytes32.random(seeded_random)
                )
                new_m = block_bad.foliage.foliage_block_data.get_hash()
                assert new_m is not None
                new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_POOL_TARGET)
                return None
            attempts += 1

    @pytest.mark.anyio
    async def test_foliage_data_presence(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 22
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_transaction_block is not None:
                case_1 = True
                block_bad: FullBlock = recursive_replace(blocks[-1], "foliage.foliage_transaction_block_hash", None)
            else:
                case_2 = True
                block_bad = recursive_replace(blocks[-1], "foliage.foliage_transaction_block_hash", std_hash(b""))
            await _validate_and_add_block_multi_error(
                empty_blockchain,
                block_bad,
                [
                    Err.INVALID_FOLIAGE_BLOCK_PRESENCE,
                    Err.INVALID_IS_TRANSACTION_BLOCK,
                    Err.INVALID_PREV_BLOCK_HASH,
                    Err.INVALID_PREV_BLOCK_HASH,
                ],
            )

    @pytest.mark.anyio
    async def test_foliage_transaction_block_hash(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 23
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_transaction_block is not None:
                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage.foliage_transaction_block_hash", std_hash(b"2")
                )

                new_m = block_bad.foliage.foliage_transaction_block_hash
                assert new_m is not None
                new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                await _validate_and_add_block(
                    empty_blockchain, block_bad, expected_error=Err.INVALID_FOLIAGE_BLOCK_HASH
                )
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.anyio
    async def test_genesis_bad_prev_block(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 24a
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage_transaction_block.prev_transaction_block_hash", std_hash(b"2")
        )
        assert block_bad.foliage_transaction_block is not None
        block_bad = recursive_replace(
            block_bad, "foliage.foliage_transaction_block_hash", block_bad.foliage_transaction_block.get_hash()
        )
        new_m = block_bad.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_PREV_BLOCK_HASH)

    @pytest.mark.anyio
    async def test_bad_prev_block_non_genesis(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 24b
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_transaction_block is not None:
                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage_transaction_block.prev_transaction_block_hash", std_hash(b"2")
                )
                assert block_bad.foliage_transaction_block is not None
                block_bad = recursive_replace(
                    block_bad, "foliage.foliage_transaction_block_hash", block_bad.foliage_transaction_block.get_hash()
                )
                new_m = block_bad.foliage.foliage_transaction_block_hash
                assert new_m is not None
                new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_PREV_BLOCK_HASH)
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.anyio
    async def test_bad_filter_hash(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 25
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_transaction_block is not None:
                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage_transaction_block.filter_hash", std_hash(b"2")
                )
                assert block_bad.foliage_transaction_block is not None
                block_bad = recursive_replace(
                    block_bad, "foliage.foliage_transaction_block_hash", block_bad.foliage_transaction_block.get_hash()
                )
                new_m = block_bad.foliage.foliage_transaction_block_hash
                assert new_m is not None
                new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                await _validate_and_add_block(
                    empty_blockchain, block_bad, expected_error=Err.INVALID_TRANSACTIONS_FILTER_HASH
                )
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.anyio
    async def test_bad_timestamp(self, bt: BlockTools) -> None:
        # 26
        # the test constants set MAX_FUTURE_TIME to 10 days, restore it to
        # default for this test
        constants = bt.constants.replace(MAX_FUTURE_TIME2=uint32(2 * 60))
        time_delta = 2 * 60 + 1

        blocks = bt.get_consecutive_blocks(1)

        async with make_empty_blockchain(constants) as b:
            await _validate_and_add_block(b, blocks[0])
            while True:
                blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
                if blocks[-1].foliage_transaction_block is not None:
                    assert blocks[0].foliage_transaction_block is not None
                    block_bad: FullBlock = recursive_replace(
                        blocks[-1],
                        "foliage_transaction_block.timestamp",
                        blocks[0].foliage_transaction_block.timestamp - 10,
                    )
                    assert block_bad.foliage_transaction_block is not None
                    block_bad = recursive_replace(
                        block_bad,
                        "foliage.foliage_transaction_block_hash",
                        block_bad.foliage_transaction_block.get_hash(),
                    )
                    new_m = block_bad.foliage.foliage_transaction_block_hash
                    assert new_m is not None
                    new_fbh_sig = bt.get_plot_signature(
                        new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key
                    )
                    block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                    await _validate_and_add_block(b, block_bad, expected_error=Err.TIMESTAMP_TOO_FAR_IN_PAST)

                    assert blocks[0].foliage_transaction_block is not None
                    block_bad = recursive_replace(
                        blocks[-1],
                        "foliage_transaction_block.timestamp",
                        blocks[0].foliage_transaction_block.timestamp,
                    )
                    assert block_bad.foliage_transaction_block is not None
                    block_bad = recursive_replace(
                        block_bad,
                        "foliage.foliage_transaction_block_hash",
                        block_bad.foliage_transaction_block.get_hash(),
                    )
                    new_m = block_bad.foliage.foliage_transaction_block_hash
                    assert new_m is not None
                    new_fbh_sig = bt.get_plot_signature(
                        new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key
                    )
                    block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                    await _validate_and_add_block(b, block_bad, expected_error=Err.TIMESTAMP_TOO_FAR_IN_PAST)

                    # since tests can run slow sometimes, and since we're using
                    # the system clock, add some extra slack
                    slack = 30
                    block_bad = recursive_replace(
                        blocks[-1],
                        "foliage_transaction_block.timestamp",
                        blocks[0].foliage_transaction_block.timestamp + time_delta + slack,
                    )
                    assert block_bad.foliage_transaction_block is not None
                    block_bad = recursive_replace(
                        block_bad,
                        "foliage.foliage_transaction_block_hash",
                        block_bad.foliage_transaction_block.get_hash(),
                    )
                    new_m = block_bad.foliage.foliage_transaction_block_hash
                    assert new_m is not None
                    new_fbh_sig = bt.get_plot_signature(
                        new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key
                    )
                    block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                    await _validate_and_add_block(b, block_bad, expected_error=Err.TIMESTAMP_TOO_FAR_IN_FUTURE)
                    return None
                await _validate_and_add_block(b, blocks[-1])

    @pytest.mark.anyio
    async def test_height(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 27
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.height", 2)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_HEIGHT)

    @pytest.mark.anyio
    async def test_height_genesis(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 27
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.height", 1)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_PREV_BLOCK_HASH)

    @pytest.mark.anyio
    async def test_weight(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 28
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.weight", 22131)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_WEIGHT)

    @pytest.mark.anyio
    async def test_weight_genesis(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 28
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.weight", 0)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_WEIGHT)

    @pytest.mark.anyio
    async def test_bad_cc_ip_vdf(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 29
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block_bad = recursive_replace(blocks[-1], "reward_chain_block.challenge_chain_ip_vdf.challenge", std_hash(b"1"))
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_CC_IP_VDF)
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.challenge_chain_ip_vdf.output",
            bad_element,
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_CC_IP_VDF)
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.challenge_chain_ip_vdf.number_of_iterations",
            uint64(1111111111111),
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_CC_IP_VDF)
        block_bad = recursive_replace(
            blocks[-1],
            "challenge_chain_ip_proof",
            VDFProof(uint8(0), std_hash(b""), False),
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_CC_IP_VDF)

    @pytest.mark.anyio
    async def test_bad_rc_ip_vdf(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 30
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block_bad = recursive_replace(blocks[-1], "reward_chain_block.reward_chain_ip_vdf.challenge", std_hash(b"1"))
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_RC_IP_VDF)
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.reward_chain_ip_vdf.output",
            bad_element,
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_RC_IP_VDF)
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.reward_chain_ip_vdf.number_of_iterations",
            uint64(1111111111111),
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_RC_IP_VDF)
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_ip_proof",
            VDFProof(uint8(0), std_hash(b""), False),
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_RC_IP_VDF)

    @pytest.mark.anyio
    async def test_bad_icc_ip_vdf(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 31
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.infused_challenge_chain_ip_vdf.challenge", std_hash(b"1")
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_ICC_VDF)
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.infused_challenge_chain_ip_vdf.output",
            bad_element,
        )

        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_ICC_VDF)
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.infused_challenge_chain_ip_vdf.number_of_iterations",
            uint64(1111111111111),
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_ICC_VDF)
        block_bad = recursive_replace(
            blocks[-1],
            "infused_challenge_chain_ip_proof",
            VDFProof(uint8(0), std_hash(b""), False),
        )

        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_ICC_VDF)

    @pytest.mark.anyio
    async def test_reward_block_hash(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 32
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad: FullBlock = recursive_replace(blocks[-1], "foliage.reward_block_hash", std_hash(b""))
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_REWARD_BLOCK_HASH)

    @pytest.mark.anyio
    async def test_reward_block_hash_2(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 33
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[0], "reward_chain_block.is_transaction_block", False)
        block_bad = recursive_replace(block_bad, "foliage.reward_block_hash", block_bad.reward_chain_block.get_hash())
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_FOLIAGE_BLOCK_PRESENCE)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        # Test one which should not be a tx block
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if not blocks[-1].is_transaction_block():
                block_bad = recursive_replace(blocks[-1], "reward_chain_block.is_transaction_block", True)
                block_bad = recursive_replace(
                    block_bad, "foliage.reward_block_hash", block_bad.reward_chain_block.get_hash()
                )
                await _validate_and_add_block(
                    empty_blockchain, block_bad, expected_error=Err.INVALID_FOLIAGE_BLOCK_PRESENCE
                )
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])


co = ConditionOpcode
rbr = AddBlockResult


class TestPreValidation:
    @pytest.mark.anyio
    async def test_pre_validation_fails_bad_blocks(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        ssi = empty_blockchain.constants.SUB_SLOT_ITERS_STARTING
        difficulty = empty_blockchain.constants.DIFFICULTY_STARTING
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.total_iters", blocks[-1].reward_chain_block.total_iters + 1
        )
        res = await empty_blockchain.pre_validate_blocks_multiprocessing(
            [blocks[0], block_bad],
            {},
            sub_slot_iters=ssi,
            difficulty=difficulty,
            prev_ses_block=None,
            validate_signatures=True,
        )
        assert res[0].error is None
        assert res[1].error is not None

    @pytest.mark.anyio
    async def test_pre_validation(
        self, empty_blockchain: Blockchain, default_1000_blocks: List[FullBlock], bt: BlockTools
    ) -> None:
        blocks = default_1000_blocks[:100]
        start = time.time()
        n_at_a_time = min(available_logical_cores(), 32)
        times_pv = []
        times_rb = []
        ssi = empty_blockchain.constants.SUB_SLOT_ITERS_STARTING
        difficulty = empty_blockchain.constants.DIFFICULTY_STARTING
        for i in range(0, len(blocks), n_at_a_time):
            end_i = min(i + n_at_a_time, len(blocks))
            blocks_to_validate = blocks[i:end_i]
            start_pv = time.time()
            res = await empty_blockchain.pre_validate_blocks_multiprocessing(
                blocks_to_validate,
                {},
                sub_slot_iters=ssi,
                difficulty=difficulty,
                prev_ses_block=None,
                validate_signatures=True,
            )
            end_pv = time.time()
            times_pv.append(end_pv - start_pv)
            assert res is not None
            for n in range(end_i - i):
                assert res[n] is not None
                assert res[n].error is None
                block = blocks_to_validate[n]
                start_rb = time.time()
                result, err, _ = await empty_blockchain.add_block(block, res[n], None, ssi)
                end_rb = time.time()
                times_rb.append(end_rb - start_rb)
                assert err is None
                assert result == AddBlockResult.NEW_PEAK
                log.info(
                    f"Added block {block.height} total iters {block.total_iters} "
                    f"new slot? {len(block.finished_sub_slots)}, time {end_rb - start_rb}"
                )
        end = time.time()
        log.info(f"Total time: {end - start} seconds")
        log.info(f"Average pv: {sum(times_pv)/(len(blocks)/n_at_a_time)}")
        log.info(f"Average rb: {sum(times_rb)/(len(blocks))}")


class TestBodyValidation:
    # TODO: add test for
    # ASSERT_COIN_ANNOUNCEMENT,
    # CREATE_COIN_ANNOUNCEMENT,
    # CREATE_PUZZLE_ANNOUNCEMENT,
    # ASSERT_PUZZLE_ANNOUNCEMENT,

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_MY_AMOUNT,
            ConditionOpcode.ASSERT_MY_PUZZLEHASH,
            ConditionOpcode.ASSERT_MY_COIN_ID,
            ConditionOpcode.ASSERT_MY_PARENT_ID,
        ],
    )
    @pytest.mark.parametrize("with_garbage", [True, False])
    async def test_conditions(
        self, empty_blockchain: Blockchain, opcode: ConditionOpcode, with_garbage: bool, bt: BlockTools
    ) -> None:
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
            genesis_timestamp=uint64(10_000),
            time_per_block=10,
        )
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        await _validate_and_add_block(empty_blockchain, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx1 = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )
        coin1: Coin = tx1.additions()[0]

        if opcode == ConditionOpcode.ASSERT_MY_AMOUNT:
            args = [int_to_bytes(coin1.amount)]
        elif opcode == ConditionOpcode.ASSERT_MY_PUZZLEHASH:
            args = [coin1.puzzle_hash]
        elif opcode == ConditionOpcode.ASSERT_MY_COIN_ID:
            args = [coin1.name()]
        elif opcode == ConditionOpcode.ASSERT_MY_PARENT_ID:
            args = [coin1.parent_coin_info]
        # elif opcode == ConditionOpcode.RESERVE_FEE:
        # args = [int_to_bytes(5)]
        # TODO: since we use the production wallet code, we can't (easily)
        # create a transaction with fee without also including a valid
        # RESERVE_FEE condition
        else:
            assert False

        conditions: Dict[ConditionOpcode, List[ConditionWithArgs]] = {
            opcode: [ConditionWithArgs(opcode, args + ([b"garbage"] if with_garbage else []))]
        }

        tx2 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin1, condition_dic=conditions)
        assert coin1 in tx2.removals()

        bundles = SpendBundle.aggregate([tx1, tx2])
        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=bundles,
            time_per_block=10,
        )
        ssi = b.constants.SUB_SLOT_ITERS_STARTING
        diff = b.constants.DIFFICULTY_STARTING
        pre_validation_results: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
            [blocks[-1]], {}, sub_slot_iters=ssi, difficulty=diff, prev_ses_block=None, validate_signatures=False
        )
        # Ignore errors from pre-validation, we are testing block_body_validation
        repl_preval_results = replace(pre_validation_results[0], error=None, required_iters=uint64(1))
        code, err, state_change = await b.add_block(blocks[-1], repl_preval_results, None, sub_slot_iters=ssi)
        assert code == AddBlockResult.NEW_PEAK
        assert err is None
        assert state_change is not None
        assert state_change.fork_height == 2

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "opcode,lock_value,expected",
        [
            # the 3 blocks, starting at timestamp 10000 (and height 0).
            # each block is 10 seconds apart.
            # the 4th block (height 3, time 10030) spends a coin with the condition specified
            # by the test case. The coin was born in height 2 at time 10020
            # MY BIRHT HEIGHT
            (co.ASSERT_MY_BIRTH_HEIGHT, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_HEIGHT, 0x100000000, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_HEIGHT, 2, rbr.NEW_PEAK),  # <- coin birth height
            (co.ASSERT_MY_BIRTH_HEIGHT, 3, rbr.INVALID_BLOCK),
            # MY BIRHT SECONDS
            (co.ASSERT_MY_BIRTH_SECONDS, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 0x10000000000000000, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 10019, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 10020, rbr.NEW_PEAK),  # <- coin birth time
            (co.ASSERT_MY_BIRTH_SECONDS, 10021, rbr.INVALID_BLOCK),
            # SECONDS RELATIVE
            (co.ASSERT_SECONDS_RELATIVE, -2, rbr.NEW_PEAK),
            (co.ASSERT_SECONDS_RELATIVE, -1, rbr.NEW_PEAK),
            (co.ASSERT_SECONDS_RELATIVE, 0, rbr.NEW_PEAK),  # <- birth time
            (co.ASSERT_SECONDS_RELATIVE, 1, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_RELATIVE, 9, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_RELATIVE, 10, rbr.INVALID_BLOCK),  # <- current block time
            (co.ASSERT_SECONDS_RELATIVE, 11, rbr.INVALID_BLOCK),
            # BEFORE SECONDS RELATIVE
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 0, rbr.INVALID_BLOCK),  # <- birth time
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 1, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 9, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 10, rbr.NEW_PEAK),  # <- current block time
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 11, rbr.NEW_PEAK),
            # HEIGHT RELATIVE
            (co.ASSERT_HEIGHT_RELATIVE, -2, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_RELATIVE, -1, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_RELATIVE, 0, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_RELATIVE, 1, rbr.INVALID_BLOCK),
            # BEFORE HEIGHT RELATIVE
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 0, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 1, rbr.NEW_PEAK),
            # HEIGHT ABSOLUTE
            (co.ASSERT_HEIGHT_ABSOLUTE, 1, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_ABSOLUTE, 2, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_ABSOLUTE, 3, rbr.INVALID_BLOCK),
            (co.ASSERT_HEIGHT_ABSOLUTE, 4, rbr.INVALID_BLOCK),
            # BEFORE HEIGHT ABSOLUTE
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 3, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 4, rbr.NEW_PEAK),
            # SECONDS ABSOLUTE
            # genesis timestamp is 10000 and each block is 10 seconds
            (co.ASSERT_SECONDS_ABSOLUTE, 10019, rbr.NEW_PEAK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10020, rbr.NEW_PEAK),  # <- previous tx-block
            (co.ASSERT_SECONDS_ABSOLUTE, 10021, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10029, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10030, rbr.INVALID_BLOCK),  # <- current block
            (co.ASSERT_SECONDS_ABSOLUTE, 10031, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10032, rbr.INVALID_BLOCK),
            # BEFORE SECONDS ABSOLUTE
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10019, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10020, rbr.INVALID_BLOCK),  # <- previous tx-block
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10021, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10029, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10030, rbr.NEW_PEAK),  # <- current block
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10031, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10032, rbr.NEW_PEAK),
        ],
    )
    async def test_timelock_conditions(
        self, opcode: ConditionOpcode, lock_value: int, expected: AddBlockResult, bt: BlockTools
    ) -> None:
        async with make_empty_blockchain(bt.constants) as b:
            blocks = bt.get_consecutive_blocks(
                3,
                guarantee_transaction_block=True,
                farmer_reward_puzzle_hash=bt.pool_ph,
                pool_reward_puzzle_hash=bt.pool_ph,
                genesis_timestamp=uint64(10_000),
                time_per_block=10,
            )
            for bl in blocks:
                await _validate_and_add_block(b, bl)

            wt: WalletTool = bt.get_pool_wallet_tool()

            conditions = {opcode: [ConditionWithArgs(opcode, [int_to_bytes(lock_value)])]}

            coin = blocks[-1].get_included_reward_coins()[0]
            tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin, condition_dic=conditions)

            blocks = bt.get_consecutive_blocks(
                1,
                block_list_input=blocks,
                guarantee_transaction_block=True,
                transaction_data=tx,
                time_per_block=10,
            )
            ssi = b.constants.SUB_SLOT_ITERS_STARTING
            diff = b.constants.DIFFICULTY_STARTING
            pre_validation_results: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
                [blocks[-1]], {}, sub_slot_iters=ssi, difficulty=diff, prev_ses_block=None, validate_signatures=True
            )
            assert pre_validation_results is not None
            assert (await b.add_block(blocks[-1], pre_validation_results[0], None, sub_slot_iters=ssi))[0] == expected

            if expected == AddBlockResult.NEW_PEAK:
                # ensure coin was in fact spent
                c = await b.coin_store.get_coin_record(coin.name())
                assert c is not None and c.spent

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.AGG_SIG_ME,
            ConditionOpcode.AGG_SIG_UNSAFE,
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
        ],
    )
    @pytest.mark.parametrize("with_garbage", [True, False])
    async def test_aggsig_garbage(
        self,
        empty_blockchain: Blockchain,
        opcode: ConditionOpcode,
        with_garbage: bool,
        bt: BlockTools,
        consensus_mode: ConsensusMode,
    ) -> None:
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
            genesis_timestamp=uint64(10_000),
            time_per_block=10,
        )
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        await _validate_and_add_block(empty_blockchain, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx1 = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )
        coin1: Coin = tx1.additions()[0]
        secret_key = wt.get_private_key_for_puzzle_hash(coin1.puzzle_hash)
        synthetic_secret_key = calculate_synthetic_secret_key(secret_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        public_key = synthetic_secret_key.get_g1()

        args = [bytes(public_key), b"msg"] + ([b"garbage"] if with_garbage else [])
        conditions = {opcode: [ConditionWithArgs(opcode, args)]}

        tx2 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin1, condition_dic=conditions)
        assert coin1 in tx2.removals()

        bundles = SpendBundle.aggregate([tx1, tx2])
        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=bundles,
            time_per_block=10,
        )
        ssi = b.constants.SUB_SLOT_ITERS_STARTING
        diff = b.constants.DIFFICULTY_STARTING
        pre_validation_results: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
            [blocks[-1]], {}, sub_slot_iters=ssi, difficulty=diff, prev_ses_block=None, validate_signatures=False
        )
        # Ignore errors from pre-validation, we are testing block_body_validation
        repl_preval_results = replace(pre_validation_results[0], error=None, required_iters=uint64(1))
        res, error, state_change = await b.add_block(blocks[-1], repl_preval_results, None, sub_slot_iters=ssi)
        assert res == AddBlockResult.NEW_PEAK
        assert error is None
        assert state_change is not None and state_change.fork_height == uint32(2)

    @pytest.mark.anyio
    @pytest.mark.parametrize("with_garbage", [True, False])
    @pytest.mark.parametrize(
        "opcode,lock_value,expected",
        [
            # we don't allow any birth assertions, not
            # relative time locks on ephemeral coins. This test is only for
            # ephemeral coins, so these cases should always fail
            # MY BIRHT HEIGHT
            (co.ASSERT_MY_BIRTH_HEIGHT, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_HEIGHT, 0x100000000, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_HEIGHT, 2, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_HEIGHT, 3, rbr.INVALID_BLOCK),
            # MY BIRHT SECONDS
            (co.ASSERT_MY_BIRTH_SECONDS, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 0x10000000000000000, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 10029, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 10030, rbr.INVALID_BLOCK),
            (co.ASSERT_MY_BIRTH_SECONDS, 10031, rbr.INVALID_BLOCK),
            # SECONDS RELATIVE
            # genesis timestamp is 10000 and each block is 10 seconds
            (co.ASSERT_SECONDS_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_RELATIVE, 0, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_RELATIVE, 1, rbr.INVALID_BLOCK),
            # BEFORE SECONDS RELATIVE
            # relative conditions are not allowed on ephemeral spends
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 0, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 10, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_RELATIVE, 0x10000000000000000, rbr.INVALID_BLOCK),
            # HEIGHT RELATIVE
            (co.ASSERT_HEIGHT_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_HEIGHT_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_HEIGHT_RELATIVE, 0, rbr.INVALID_BLOCK),
            (co.ASSERT_HEIGHT_RELATIVE, 1, rbr.INVALID_BLOCK),
            # BEFORE HEIGHT RELATIVE
            # relative conditions are not allowed on ephemeral spends
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, -2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, -1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 0, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 1, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 0x100000000, rbr.INVALID_BLOCK),
            # HEIGHT ABSOLUTE
            (co.ASSERT_HEIGHT_ABSOLUTE, 2, rbr.NEW_PEAK),
            (co.ASSERT_HEIGHT_ABSOLUTE, 3, rbr.INVALID_BLOCK),
            (co.ASSERT_HEIGHT_ABSOLUTE, 4, rbr.INVALID_BLOCK),
            # BEFORE HEIGHT ABSOLUTE
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 2, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 3, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 4, rbr.NEW_PEAK),
            # SECONDS ABSOLUTE
            # genesis timestamp is 10000 and each block is 10 seconds
            (co.ASSERT_SECONDS_ABSOLUTE, 10020, rbr.NEW_PEAK),  # <- previous tx-block
            (co.ASSERT_SECONDS_ABSOLUTE, 10021, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10029, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10030, rbr.INVALID_BLOCK),  # <- current tx-block
            (co.ASSERT_SECONDS_ABSOLUTE, 10031, rbr.INVALID_BLOCK),
            (co.ASSERT_SECONDS_ABSOLUTE, 10032, rbr.INVALID_BLOCK),
            # BEFORE SECONDS ABSOLUTE
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10020, rbr.INVALID_BLOCK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10021, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10030, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10031, rbr.NEW_PEAK),
            (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10032, rbr.NEW_PEAK),
        ],
    )
    async def test_ephemeral_timelock(
        self, opcode: ConditionOpcode, lock_value: int, expected: AddBlockResult, with_garbage: bool, bt: BlockTools
    ) -> None:
        async with make_empty_blockchain(bt.constants) as b:
            blocks = bt.get_consecutive_blocks(
                3,
                guarantee_transaction_block=True,
                farmer_reward_puzzle_hash=bt.pool_ph,
                pool_reward_puzzle_hash=bt.pool_ph,
                genesis_timestamp=uint64(10_000),
                time_per_block=10,
            )
            await _validate_and_add_block(b, blocks[0])
            await _validate_and_add_block(b, blocks[1])
            await _validate_and_add_block(b, blocks[2])

            wt: WalletTool = bt.get_pool_wallet_tool()

            conditions = {
                opcode: [ConditionWithArgs(opcode, [int_to_bytes(lock_value)] + ([b"garbage"] if with_garbage else []))]
            }

            tx1 = wt.generate_signed_transaction(
                uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
            )
            coin1: Coin = tx1.additions()[0]
            tx2 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), coin1, condition_dic=conditions)
            assert coin1 in tx2.removals()
            coin2: Coin = tx2.additions()[0]

            bundles = SpendBundle.aggregate([tx1, tx2])
            blocks = bt.get_consecutive_blocks(
                1,
                block_list_input=blocks,
                guarantee_transaction_block=True,
                transaction_data=bundles,
                time_per_block=10,
            )
            ssi = b.constants.SUB_SLOT_ITERS_STARTING
            diff = b.constants.DIFFICULTY_STARTING
            pre_validation_results: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
                [blocks[-1]], {}, sub_slot_iters=ssi, difficulty=diff, prev_ses_block=None, validate_signatures=True
            )
            assert pre_validation_results is not None
            assert (await b.add_block(blocks[-1], pre_validation_results[0], None, sub_slot_iters=ssi))[0] == expected

            if expected == AddBlockResult.NEW_PEAK:
                # ensure coin1 was in fact spent
                c = await b.coin_store.get_coin_record(coin1.name())
                assert c is not None and c.spent
                # ensure coin2 was NOT spent
                c = await b.coin_store.get_coin_record(coin2.name())
                assert c is not None and not c.spent

    @pytest.mark.anyio
    async def test_not_tx_block_but_has_data(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 1
        blocks = bt.get_consecutive_blocks(1)
        while blocks[-1].foliage_transaction_block is not None:
            await _validate_and_add_block(empty_blockchain, blocks[-1])
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        original_block: FullBlock = blocks[-1]

        block = recursive_replace(original_block, "transactions_generator", SerializedProgram.to(None))
        await _validate_and_add_block(
            empty_blockchain, block, expected_error=Err.NOT_BLOCK_BUT_HAS_DATA, skip_prevalidation=True
        )
        h = std_hash(b"")
        i = uint64(1)
        block = recursive_replace(
            original_block,
            "transactions_info",
            TransactionsInfo(h, h, G2Element(), uint64(1), uint64(1), []),
        )
        await _validate_and_add_block(
            empty_blockchain, block, expected_error=Err.NOT_BLOCK_BUT_HAS_DATA, skip_prevalidation=True
        )

        block = recursive_replace(original_block, "transactions_generator_ref_list", [i])
        await _validate_and_add_block(
            empty_blockchain, block, expected_error=Err.NOT_BLOCK_BUT_HAS_DATA, skip_prevalidation=True
        )

    @pytest.mark.anyio
    async def test_tx_block_missing_data(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 2
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])
        block = recursive_replace(
            blocks[-1],
            "foliage_transaction_block",
            None,
        )
        await _validate_and_add_block_multi_error(
            b, block, [Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA, Err.INVALID_FOLIAGE_BLOCK_PRESENCE]
        )

        block = recursive_replace(
            blocks[-1],
            "transactions_info",
            None,
        )
        with pytest.raises(AssertionError):
            await _validate_and_add_block_multi_error(
                b, block, [Err.IS_TRANSACTION_BLOCK_BUT_NO_DATA, Err.INVALID_FOLIAGE_BLOCK_PRESENCE]
            )

    @pytest.mark.anyio
    async def test_invalid_transactions_info_hash(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 3
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])
        h = std_hash(b"")
        block = recursive_replace(
            blocks[-1],
            "foliage_transaction_block.transactions_info_hash",
            h,
        )
        block = recursive_replace(
            block, "foliage.foliage_transaction_block_hash", std_hash(block.foliage_transaction_block)
        )
        new_m = block.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block = recursive_replace(block, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block, expected_error=Err.INVALID_TRANSACTIONS_INFO_HASH)

    @pytest.mark.anyio
    async def test_invalid_transactions_block_hash(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 4
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])
        h = std_hash(b"")
        block = recursive_replace(blocks[-1], "foliage.foliage_transaction_block_hash", h)
        new_m = block.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block = recursive_replace(block, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block, expected_error=Err.INVALID_FOLIAGE_BLOCK_HASH)

    @pytest.mark.anyio
    async def test_invalid_reward_claims(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 5
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])
        block: FullBlock = blocks[-1]

        # Too few
        assert block.transactions_info is not None
        too_few_reward_claims = block.transactions_info.reward_claims_incorporated[:-1]
        block_2: FullBlock = recursive_replace(
            block, "transactions_info.reward_claims_incorporated", too_few_reward_claims
        )
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )

        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_REWARD_COINS, skip_prevalidation=True)

        # Too many
        h = std_hash(b"")
        too_many_reward_claims = block.transactions_info.reward_claims_incorporated + [
            Coin(h, h, too_few_reward_claims[0].amount)
        ]
        block_2 = recursive_replace(block, "transactions_info.reward_claims_incorporated", too_many_reward_claims)
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_REWARD_COINS, skip_prevalidation=True)

        # Duplicates
        duplicate_reward_claims = block.transactions_info.reward_claims_incorporated + [
            block.transactions_info.reward_claims_incorporated[-1]
        ]
        block_2 = recursive_replace(block, "transactions_info.reward_claims_incorporated", duplicate_reward_claims)
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_REWARD_COINS, skip_prevalidation=True)

    @pytest.mark.anyio
    async def test_invalid_transactions_generator_hash(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 7
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])

        # No tx should have all zeroes
        block: FullBlock = blocks[-1]
        block_2 = recursive_replace(block, "transactions_info.generator_root", bytes([1] * 32))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(
            b, block_2, expected_error=Err.INVALID_TRANSACTIONS_GENERATOR_HASH, skip_prevalidation=True
        )

        await _validate_and_add_block(b, blocks[1])
        blocks = bt.get_consecutive_blocks(
            2,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[2])
        await _validate_and_add_block(b, blocks[3])

        wt: WalletTool = bt.get_pool_wallet_tool()
        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )

        # Non empty generator hash must be correct
        block = blocks[-1]
        block_2 = recursive_replace(block, "transactions_info.generator_root", bytes([0] * 32))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)
        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_TRANSACTIONS_GENERATOR_HASH)

    @pytest.mark.anyio
    async def test_invalid_transactions_ref_list(
        self, empty_blockchain: Blockchain, bt: BlockTools, consensus_mode: ConsensusMode
    ) -> None:
        # No generator should have [1]s for the root
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])

        block: FullBlock = blocks[-1]
        block_2 = recursive_replace(block, "transactions_info.generator_refs_root", bytes([0] * 32))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(
            b, block_2, expected_error=Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, skip_prevalidation=True
        )

        # No generator should have no refs list
        block_2 = recursive_replace(block, "transactions_generator_ref_list", [uint32(0)])

        await _validate_and_add_block(
            b, block_2, expected_error=Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, skip_prevalidation=True
        )

        # Hash should be correct when there is a ref list
        await _validate_and_add_block(b, blocks[-1])
        wt: WalletTool = bt.get_pool_wallet_tool()
        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )
        blocks = bt.get_consecutive_blocks(5, block_list_input=blocks, guarantee_transaction_block=False)
        for block in blocks[-5:]:
            await _validate_and_add_block(b, block)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1])
        assert blocks[-1].transactions_generator is not None

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=tx,
            block_refs=[blocks[-1].height],
        )
        block = blocks[-1]
        # once the hard fork activated, we no longer use this form of block
        # compression anymore
        assert len(block.transactions_generator_ref_list) == 0

    @pytest.mark.anyio
    async def test_cost_exceeds_max(
        self, empty_blockchain: Blockchain, softfork_height: uint32, bt: BlockTools
    ) -> None:
        # 7
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        condition_dict: Dict[ConditionOpcode, List[ConditionWithArgs]] = {ConditionOpcode.CREATE_COIN: []}
        for i in range(7_000):
            output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt.pool_ph, int_to_bytes(i)])
            condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0], condition_dic=condition_dict
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )

        assert blocks[-1].transactions_generator is not None
        block_generator = BlockGenerator(blocks[-1].transactions_generator, [])
        npc_result = get_name_puzzle_conditions(
            block_generator,
            b.constants.MAX_BLOCK_COST_CLVM * 1000,
            mempool_mode=False,
            height=softfork_height,
            constants=bt.constants,
        )
        ssi = b.constants.SUB_SLOT_ITERS_STARTING
        diff = b.constants.DIFFICULTY_STARTING
        err = (
            await b.add_block(
                blocks[-1], PreValidationResult(None, uint64(1), npc_result, True, uint32(0)), None, sub_slot_iters=ssi
            )
        )[1]
        assert err in [Err.BLOCK_COST_EXCEEDS_MAX]
        results: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
            [blocks[-1]], {}, sub_slot_iters=ssi, difficulty=diff, prev_ses_block=None, validate_signatures=False
        )
        assert results is not None
        assert Err(results[0].error) == Err.BLOCK_COST_EXCEEDS_MAX

    @pytest.mark.anyio
    async def test_clvm_must_not_fail(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 8
        pass

    @pytest.mark.anyio
    async def test_invalid_cost_in_block(
        self, empty_blockchain: Blockchain, softfork_height: uint32, bt: BlockTools
    ) -> None:
        # 9
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]

        # zero
        block_2: FullBlock = recursive_replace(block, "transactions_info.cost", uint64(0))
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)
        assert block_2.transactions_generator is not None
        block_generator = BlockGenerator(block_2.transactions_generator, [])
        assert block.transactions_info is not None
        npc_result = get_name_puzzle_conditions(
            block_generator,
            min(b.constants.MAX_BLOCK_COST_CLVM * 1000, block.transactions_info.cost),
            mempool_mode=False,
            height=softfork_height,
            constants=bt.constants,
        )
        ssi = b.constants.SUB_SLOT_ITERS_STARTING
        _, err, _ = await b.add_block(
            block_2, PreValidationResult(None, uint64(1), npc_result, False, uint32(0)), None, sub_slot_iters=ssi
        )
        assert err == Err.INVALID_BLOCK_COST

        # too low
        block_2 = recursive_replace(block, "transactions_info.cost", uint64(1))
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)
        assert block_2.transactions_generator is not None
        block_generator = BlockGenerator(block_2.transactions_generator, [])
        assert block.transactions_info is not None
        npc_result = get_name_puzzle_conditions(
            block_generator,
            min(b.constants.MAX_BLOCK_COST_CLVM * 1000, block.transactions_info.cost),
            mempool_mode=False,
            height=softfork_height,
            constants=bt.constants,
        )
        _, err, _ = await b.add_block(
            block_2, PreValidationResult(None, uint64(1), npc_result, False, uint32(0)), None, sub_slot_iters=ssi
        )
        assert err == Err.INVALID_BLOCK_COST

        # too high
        block_2 = recursive_replace(block, "transactions_info.cost", uint64(1000000))
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        assert block_2.transactions_generator is not None
        block_generator = BlockGenerator(block_2.transactions_generator, [])
        max_cost = (
            min(b.constants.MAX_BLOCK_COST_CLVM * 1000, block.transactions_info.cost)
            if block.transactions_info is not None
            else b.constants.MAX_BLOCK_COST_CLVM * 1000
        )
        npc_result = get_name_puzzle_conditions(
            block_generator, max_cost, mempool_mode=False, height=softfork_height, constants=bt.constants
        )

        result, err, _ = await b.add_block(
            block_2, PreValidationResult(None, uint64(1), npc_result, False, uint32(0)), None, sub_slot_iters=ssi
        )
        assert err == Err.INVALID_BLOCK_COST

        # when the CLVM program exceeds cost during execution, it will fail with
        # a general runtime error. The previous test tests this.

    @pytest.mark.anyio
    async def test_max_coin_amount(self, db_version: int, bt: BlockTools) -> None:
        # 10
        # TODO: fix, this is not reaching validation. Because we can't create a block with such amounts due to uint64
        # limit in Coin
        pass
        #
        # with TempKeyring() as keychain:
        #     new_test_constants = bt.constants.replace(
        #         GENESIS_PRE_FARM_POOL_PUZZLE_HASH=bt.pool_ph,
        #         GENESIS_PRE_FARM_FARMER_PUZZLE_HASH=bt.pool_ph,
        #     )
        #     b, db_wrapper = await create_blockchain(new_test_constants, db_version)
        #     bt_2 = await create_block_tools_async(constants=new_test_constants, keychain=keychain)
        #     bt_2.constants = bt_2.constants.replace(
        #         GENESIS_PRE_FARM_POOL_PUZZLE_HASH=bt.pool_ph,
        #         GENESIS_PRE_FARM_FARMER_PUZZLE_HASH=bt.pool_ph,
        #     )
        #     blocks = bt_2.get_consecutive_blocks(
        #         3,
        #         guarantee_transaction_block=True,
        #         farmer_reward_puzzle_hash=bt.pool_ph,
        #         pool_reward_puzzle_hash=bt.pool_ph,
        #     )
        #     assert (await b.add_block(blocks[0]))[0] == AddBlockResult.NEW_PEAK
        #     assert (await b.add_block(blocks[1]))[0] == AddBlockResult.NEW_PEAK
        #     assert (await b.add_block(blocks[2]))[0] == AddBlockResult.NEW_PEAK

        #     wt: WalletTool = bt_2.get_pool_wallet_tool()

        #     condition_dict: Dict[ConditionOpcode, List[ConditionWithArgs]] = {ConditionOpcode.CREATE_COIN: []}
        #     output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt_2.pool_ph, int_to_bytes(2 ** 64)])
        #     condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        #     tx = wt.generate_signed_transaction_multiple_coins(
        #         uint64(10),
        #         wt.get_new_puzzlehash(),
        #         blocks[1].get_included_reward_coins(),
        #         condition_dic=condition_dict,
        #     )
        #     with pytest.raises(Exception):
        #         blocks = bt_2.get_consecutive_blocks(
        #             1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        #         )
        #     await db_wrapper.close()
        #     b.shut_down()

    @pytest.mark.anyio
    async def test_invalid_merkle_roots(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 11
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        await _validate_and_add_block(empty_blockchain, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]

        merkle_set = MerkleSet([])
        # additions
        block_2 = recursive_replace(block, "foliage_transaction_block.additions_root", merkle_set.get_root())
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(empty_blockchain, block_2, expected_error=Err.BAD_ADDITION_ROOT)

        # removals
        merkle_set = MerkleSet([std_hash(b"1")])
        block_2 = recursive_replace(block, "foliage_transaction_block.removals_root", merkle_set.get_root())
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(empty_blockchain, block_2, expected_error=Err.BAD_REMOVAL_ROOT)

    @pytest.mark.anyio
    async def test_invalid_filter(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 12
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]
        block_2 = recursive_replace(block, "foliage_transaction_block.filter_hash", std_hash(b"3"))
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_TRANSACTIONS_FILTER_HASH)

    @pytest.mark.anyio
    async def test_duplicate_outputs(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 13
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        condition_dict: Dict[ConditionOpcode, List[ConditionWithArgs]] = {ConditionOpcode.CREATE_COIN: []}
        for _ in range(2):
            output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt.pool_ph, int_to_bytes(1)])
            condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0], condition_dic=condition_dict
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1], expected_error=Err.DUPLICATE_OUTPUT)

    @pytest.mark.anyio
    async def test_duplicate_removals(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 14
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )
        tx_2 = wt.generate_signed_transaction(
            uint64(11), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )
        agg = SpendBundle.aggregate([tx, tx_2])

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=agg
        )
        await _validate_and_add_block(b, blocks[-1], expected_error=Err.DOUBLE_SPEND)

    @pytest.mark.anyio
    async def test_double_spent_in_coin_store(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 15
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1])

        tx_2 = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-2].get_included_reward_coins()[0]
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx_2
        )

        await _validate_and_add_block(b, blocks[-1], expected_error=Err.DOUBLE_SPEND)

    @pytest.mark.anyio
    async def test_double_spent_in_reorg(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 15
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1])

        new_coin: Coin = tx.additions()[0]
        tx_2 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), new_coin)
        # This is fine because coin exists
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx_2
        )
        await _validate_and_add_block(b, blocks[-1])
        blocks = bt.get_consecutive_blocks(5, block_list_input=blocks, guarantee_transaction_block=True)
        for block in blocks[-5:]:
            await _validate_and_add_block(b, block)

        blocks_reorg = bt.get_consecutive_blocks(2, block_list_input=blocks[:-7], guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks_reorg[-2], expected_result=AddBlockResult.ADDED_AS_ORPHAN)
        await _validate_and_add_block(b, blocks_reorg[-1], expected_result=AddBlockResult.ADDED_AS_ORPHAN)

        # Coin does not exist in reorg
        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg, guarantee_transaction_block=True, transaction_data=tx_2
        )

        await _validate_and_add_block(b, blocks_reorg[-1], expected_error=Err.UNKNOWN_UNSPENT)

        # Finally add the block to the fork (spending both in same bundle, this is ephemeral)
        agg = SpendBundle.aggregate([tx, tx_2])
        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg[:-1], guarantee_transaction_block=True, transaction_data=agg
        )
        await _validate_and_add_block(b, blocks_reorg[-1], expected_result=AddBlockResult.ADDED_AS_ORPHAN)

        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg, guarantee_transaction_block=True, transaction_data=tx_2
        )
        await _validate_and_add_block(b, blocks_reorg[-1], expected_error=Err.DOUBLE_SPEND_IN_FORK)

        rewards_ph = wt.get_new_puzzlehash()
        blocks_reorg = bt.get_consecutive_blocks(
            10,
            block_list_input=blocks_reorg[:-1],
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=rewards_ph,
        )
        for block in blocks_reorg[-10:]:
            await _validate_and_add_block_multi_result(
                b, block, expected_result=[AddBlockResult.ADDED_AS_ORPHAN, AddBlockResult.NEW_PEAK]
            )

        # ephemeral coin is spent
        first_coin = await b.coin_store.get_coin_record(new_coin.name())
        assert first_coin is not None and first_coin.spent
        second_coin = await b.coin_store.get_coin_record(tx_2.additions()[0].name())
        assert second_coin is not None and not second_coin.spent

        farmer_coin = create_farmer_coin(
            blocks_reorg[-1].height,
            rewards_ph,
            calculate_base_farmer_reward(blocks_reorg[-1].height),
            bt.constants.GENESIS_CHALLENGE,
        )
        tx_3 = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), farmer_coin)

        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg, guarantee_transaction_block=True, transaction_data=tx_3
        )
        await _validate_and_add_block(b, blocks_reorg[-1])

        farmer_coin_record = await b.coin_store.get_coin_record(farmer_coin.name())
        assert farmer_coin_record is not None and farmer_coin_record.spent

    @pytest.mark.anyio
    async def test_minting_coin(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 16 Minting coin check
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        spend = blocks[-1].get_included_reward_coins()[0]
        print("spend=", spend)
        # this create coin will spend all of the coin, so the 10 mojos below
        # will be "minted".
        output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt.pool_ph, int_to_bytes(spend.amount)])
        condition_dict = {ConditionOpcode.CREATE_COIN: [output]}

        tx = wt.generate_signed_transaction(uint64(10), wt.get_new_puzzlehash(), spend, condition_dic=condition_dict)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1], expected_error=Err.MINTING_COIN)
        # 17 is tested in mempool tests

    @pytest.mark.anyio
    async def test_max_coin_amount_fee(self) -> None:
        # 18 TODO: we can't create a block with such amounts due to uint64
        pass

    @pytest.mark.anyio
    async def test_invalid_fees_in_block(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 19
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]

        # wrong feees
        block_2: FullBlock = recursive_replace(block, "transactions_info.fees", uint64(1239))
        assert block_2.transactions_info is not None
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block is not None
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_BLOCK_FEE_AMOUNT)

    @pytest.mark.anyio
    async def test_invalid_agg_sig(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        # 22
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[-1].get_included_reward_coins()[0]
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )

        last_block = recursive_replace(blocks[-1], "transactions_info.aggregated_signature", G2Element.generator())
        assert last_block.transactions_info is not None
        last_block = recursive_replace(
            last_block, "foliage_transaction_block.transactions_info_hash", last_block.transactions_info.get_hash()
        )
        assert last_block.foliage_transaction_block is not None
        last_block = recursive_replace(
            last_block, "foliage.foliage_transaction_block_hash", last_block.foliage_transaction_block.get_hash()
        )
        new_m = last_block.foliage.foliage_transaction_block_hash
        assert new_m is not None
        new_fsb_sig = bt.get_plot_signature(new_m, last_block.reward_chain_block.proof_of_space.plot_public_key)
        last_block = recursive_replace(last_block, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        # Bad signature fails during add_block
        await _validate_and_add_block(b, last_block, expected_error=Err.BAD_AGGREGATE_SIGNATURE)
        # Also test the same case but when using BLSCache
        await _validate_and_add_block(b, last_block, expected_error=Err.BAD_AGGREGATE_SIGNATURE, use_bls_cache=True)

        # Bad signature also fails in prevalidation
        ssi = b.constants.SUB_SLOT_ITERS_STARTING
        diff = b.constants.DIFFICULTY_STARTING
        preval_results = await b.pre_validate_blocks_multiprocessing(
            [last_block], {}, sub_slot_iters=ssi, difficulty=diff, prev_ses_block=None, validate_signatures=True
        )
        assert preval_results is not None
        assert preval_results[0].error == Err.BAD_AGGREGATE_SIGNATURE.value


def maybe_header_hash(block: Optional[BlockRecord]) -> Optional[bytes32]:
    if block is None:
        return None
    return block.header_hash


class TestReorgs:
    @pytest.mark.anyio
    async def test_basic_reorg(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(15)

        for block in blocks:
            await _validate_and_add_block(b, block)
        peak = b.get_peak()
        assert peak is not None
        assert peak.height == 14

        blocks_reorg_chain = bt.get_consecutive_blocks(7, blocks[:10], seed=b"2")
        for reorg_block in blocks_reorg_chain:
            if reorg_block.height < 10:
                await _validate_and_add_block(b, reorg_block, expected_result=AddBlockResult.ALREADY_HAVE_BLOCK)
            elif reorg_block.height < 15:
                await _validate_and_add_block(b, reorg_block, expected_result=AddBlockResult.ADDED_AS_ORPHAN)
            elif reorg_block.height >= 15:
                await _validate_and_add_block(b, reorg_block)
        peak = b.get_peak()
        assert peak is not None
        assert peak.height == 16

    @pytest.mark.anyio
    async def test_get_tx_peak_reorg(
        self, empty_blockchain: Blockchain, bt: BlockTools, consensus_mode: ConsensusMode
    ) -> None:
        b = empty_blockchain

        if consensus_mode < ConsensusMode.HARD_FORK_2_0:
            reorg_point = 13
        else:
            reorg_point = 12
        blocks = bt.get_consecutive_blocks(reorg_point)

        last_tx_block: Optional[bytes32] = None
        for block in blocks:
            assert maybe_header_hash(b.get_tx_peak()) == last_tx_block
            await _validate_and_add_block(b, block)
            if block.is_transaction_block():
                last_tx_block = block.header_hash
        peak = b.get_peak()
        assert peak is not None
        assert peak.height == reorg_point - 1
        assert maybe_header_hash(b.get_tx_peak()) == last_tx_block

        reorg_last_tx_block: Optional[bytes32] = None

        blocks_reorg_chain = bt.get_consecutive_blocks(7, blocks[:10], seed=b"2")
        assert blocks_reorg_chain[reorg_point].is_transaction_block() is False
        for reorg_block in blocks_reorg_chain:
            if reorg_block.height < 10:
                await _validate_and_add_block(b, reorg_block, expected_result=AddBlockResult.ALREADY_HAVE_BLOCK)
            elif reorg_block.height < reorg_point:
                await _validate_and_add_block(b, reorg_block, expected_result=AddBlockResult.ADDED_AS_ORPHAN)
            elif reorg_block.height >= reorg_point:
                await _validate_and_add_block(b, reorg_block)

            if reorg_block.is_transaction_block():
                reorg_last_tx_block = reorg_block.header_hash
            if reorg_block.height >= reorg_point:
                last_tx_block = reorg_last_tx_block

            assert maybe_header_hash(b.get_tx_peak()) == last_tx_block

        peak = b.get_peak()
        assert peak is not None
        assert peak.height == 16

    @pytest.mark.anyio
    @pytest.mark.parametrize("light_blocks", [True, False])
    async def test_long_reorg(
        self,
        light_blocks: bool,
        empty_blockchain: Blockchain,
        default_10000_blocks: List[FullBlock],
        test_long_reorg_blocks: List[FullBlock],
        test_long_reorg_blocks_light: List[FullBlock],
    ) -> None:
        if light_blocks:
            reorg_blocks = test_long_reorg_blocks_light[:1650]
        else:
            reorg_blocks = test_long_reorg_blocks[:1200]

        # Reorg longer than a difficulty adjustment
        # Also tests higher weight chain but lower height
        b = empty_blockchain
        num_blocks_chain_1 = 1600
        num_blocks_chain_2_start = 500

        assert num_blocks_chain_1 < 10000
        blocks = default_10000_blocks[:num_blocks_chain_1]

        print(f"pre-validating {len(blocks)} blocks")
        ssi = b.constants.SUB_SLOT_ITERS_STARTING
        diff = b.constants.DIFFICULTY_STARTING
        pre_validation_results: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
            blocks, {}, sub_slot_iters=ssi, difficulty=diff, prev_ses_block=None, validate_signatures=False
        )
        for i, block in enumerate(blocks):
            if block.height != 0 and len(block.finished_sub_slots) > 0:
                if block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None:
                    ssi = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters
            assert pre_validation_results[i].error is None
            if (block.height % 100) == 0:
                print(f"main chain: {block.height:4} weight: {block.weight}")
            (result, err, _) = await b.add_block(block, pre_validation_results[i], None, sub_slot_iters=ssi)
            await check_block_store_invariant(b)
            assert err is None
            assert result == AddBlockResult.NEW_PEAK

        peak = b.get_peak()
        assert peak is not None
        chain_1_height = peak.height
        chain_1_weight = peak.weight
        assert chain_1_height == (num_blocks_chain_1 - 1)

        # The reorg blocks will have less time between them (timestamp) and therefore will make difficulty go up
        # This means that the weight will grow faster, and we can get a heavier chain with lower height

        # If these assert fail, you probably need to change the fixture in reorg_blocks to create the
        # right amount of blocks at the right time
        assert reorg_blocks[num_blocks_chain_2_start - 1] == default_10000_blocks[num_blocks_chain_2_start - 1]
        assert reorg_blocks[num_blocks_chain_2_start] != default_10000_blocks[num_blocks_chain_2_start]

        # one aspect of this test is to make sure we can reorg blocks that are
        # not in the cache. We need to explicitly prune the cache to get that
        # effect.
        b.clean_block_records()

        first_peak = b.get_peak()
        fork_info: Optional[ForkInfo] = None
        for reorg_block in reorg_blocks:
            if (reorg_block.height % 100) == 0:
                peak = b.get_peak()
                assert peak is not None
                print(
                    f"reorg chain: {reorg_block.height:4} "
                    f"weight: {reorg_block.weight:7} "
                    f"peak: {str(peak.header_hash)[:6]}"
                )

            if reorg_block.height < num_blocks_chain_2_start:
                await _validate_and_add_block(b, reorg_block, expected_result=AddBlockResult.ALREADY_HAVE_BLOCK)
            elif reorg_block.weight <= chain_1_weight:
                if fork_info is None:
                    fork_info = ForkInfo(reorg_block.height - 1, reorg_block.height - 1, reorg_block.prev_header_hash)
                await _validate_and_add_block(
                    b, reorg_block, expected_result=AddBlockResult.ADDED_AS_ORPHAN, fork_info=fork_info
                )
            elif reorg_block.weight > chain_1_weight:
                await _validate_and_add_block(
                    b, reorg_block, expected_result=AddBlockResult.NEW_PEAK, fork_info=fork_info
                )

        # if these asserts fires, there was no reorg
        peak = b.get_peak()
        assert peak is not None
        assert first_peak != peak
        assert peak is not None
        assert peak.weight > chain_1_weight
        second_peak = peak

        if light_blocks:
            assert peak.height > chain_1_height
        else:
            assert peak.height < chain_1_height

        chain_2_weight = peak.weight

        # now reorg back to the original chain
        # this exercises the case where we have some of the blocks in the DB already
        b.clean_block_records()

        if light_blocks:
            blocks = default_10000_blocks[num_blocks_chain_2_start - 100 : 1800]
        else:
            blocks = default_10000_blocks[num_blocks_chain_2_start - 100 : 2600]

        # the block validation requires previous block records to be in the
        # cache
        br = await b.get_block_record_from_db(blocks[0].prev_header_hash)
        for i in range(200):
            assert br is not None
            b.add_block_record(br)
            br = await b.get_block_record_from_db(br.prev_hash)
        assert br is not None
        b.add_block_record(br)

        # start the fork point a few blocks back, to test that the blockchain
        # can catch up
        fork_block = default_10000_blocks[num_blocks_chain_2_start - 200]
        fork_info = ForkInfo(fork_block.height, fork_block.height, fork_block.header_hash)
        await b.warmup(fork_block.height)
        for block in blocks:
            if (block.height % 128) == 0:
                peak = b.get_peak()
                assert peak is not None
                print(
                    f"original chain: {block.height:4} "
                    f"weight: {block.weight:7} "
                    f"peak: {str(peak.header_hash)[:6]}"
                )
            if block.height <= chain_1_height:
                expect = AddBlockResult.ALREADY_HAVE_BLOCK
            elif block.weight < chain_2_weight:
                expect = AddBlockResult.ADDED_AS_ORPHAN
            else:
                expect = AddBlockResult.NEW_PEAK
            await _validate_and_add_block(b, block, fork_info=fork_info, expected_result=expect)

        # if these asserts fires, there was no reorg back to the original chain
        peak = b.get_peak()
        assert peak is not None
        assert peak.header_hash != second_peak.header_hash
        assert peak.weight > chain_2_weight

    @pytest.mark.anyio
    async def test_long_compact_blockchain(
        self, empty_blockchain: Blockchain, default_2000_blocks_compact: List[FullBlock]
    ) -> None:
        b = empty_blockchain
        for block in default_2000_blocks_compact:
            await _validate_and_add_block(b, block, skip_prevalidation=True)
        peak = b.get_peak()
        assert peak is not None
        assert peak.height == len(default_2000_blocks_compact) - 1

    @pytest.mark.anyio
    async def test_reorg_from_genesis(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        b = empty_blockchain

        blocks = bt.get_consecutive_blocks(15)

        for block in blocks:
            await _validate_and_add_block(b, block)
        peak = b.get_peak()
        assert peak is not None
        assert peak.height == 14

        # Reorg to alternate chain that is 1 height longer
        blocks_reorg_chain = bt.get_consecutive_blocks(16, [], seed=b"2")
        for reorg_block in blocks_reorg_chain:
            if reorg_block.height < 15:
                await _validate_and_add_block_multi_result(
                    b,
                    reorg_block,
                    expected_result=[AddBlockResult.ADDED_AS_ORPHAN, AddBlockResult.ALREADY_HAVE_BLOCK],
                )
            elif reorg_block.height >= 15:
                await _validate_and_add_block(b, reorg_block)

        # Back to original chain
        blocks_reorg_chain_2 = bt.get_consecutive_blocks(3, blocks, seed=b"3")

        await _validate_and_add_block(b, blocks_reorg_chain_2[-3], expected_result=AddBlockResult.ADDED_AS_ORPHAN)
        await _validate_and_add_block(b, blocks_reorg_chain_2[-2])
        await _validate_and_add_block(b, blocks_reorg_chain_2[-1])

        peak = b.get_peak()
        assert peak is not None
        assert peak.height == 17

    @pytest.mark.anyio
    async def test_reorg_transaction(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        b = empty_blockchain
        wallet_a = WalletTool(b.constants)
        WALLET_A_PUZZLE_HASHES = [wallet_a.get_new_puzzlehash() for _ in range(5)]
        coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
        receiver_puzzlehash = WALLET_A_PUZZLE_HASHES[1]

        blocks = bt.get_consecutive_blocks(10, farmer_reward_puzzle_hash=coinbase_puzzlehash)
        blocks = bt.get_consecutive_blocks(
            2, blocks, farmer_reward_puzzle_hash=coinbase_puzzlehash, guarantee_transaction_block=True
        )

        spend_block = blocks[10]
        spend_coin = None
        for coin in spend_block.get_included_reward_coins():
            if coin.puzzle_hash == coinbase_puzzlehash:
                spend_coin = coin
        assert spend_coin is not None
        spend_bundle = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, spend_coin)

        blocks = bt.get_consecutive_blocks(
            2,
            blocks,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=spend_bundle,
            guarantee_transaction_block=True,
        )

        blocks_fork = bt.get_consecutive_blocks(
            1, blocks[:12], farmer_reward_puzzle_hash=coinbase_puzzlehash, seed=b"123", guarantee_transaction_block=True
        )
        blocks_fork = bt.get_consecutive_blocks(
            2,
            blocks_fork,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            transaction_data=spend_bundle,
            guarantee_transaction_block=True,
            seed=b"1245",
        )
        for block in blocks:
            await _validate_and_add_block(b, block)

        for block in blocks_fork:
            await _validate_and_add_block_no_error(b, block)

    @pytest.mark.anyio
    async def test_get_header_blocks_in_range_tx_filter(self, empty_blockchain: Blockchain, bt: BlockTools) -> None:
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            pool_reward_puzzle_hash=bt.pool_ph,
            farmer_reward_puzzle_hash=bt.pool_ph,
        )
        await _validate_and_add_block(b, blocks[0])
        await _validate_and_add_block(b, blocks[1])
        await _validate_and_add_block(b, blocks[2])
        wt: WalletTool = bt.get_pool_wallet_tool()
        tx = wt.generate_signed_transaction(
            uint64(10), wt.get_new_puzzlehash(), blocks[2].get_included_reward_coins()[0]
        )
        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=tx,
        )
        await _validate_and_add_block(b, blocks[-1])

        blocks_with_filter = await b.get_header_blocks_in_range(0, 10, tx_filter=True)
        blocks_without_filter = await b.get_header_blocks_in_range(0, 10, tx_filter=False)
        header_hash = blocks[-1].header_hash
        assert (
            blocks_with_filter[header_hash].transactions_filter
            != blocks_without_filter[header_hash].transactions_filter
        )
        assert blocks_with_filter[header_hash].header_hash == blocks_without_filter[header_hash].header_hash

    @pytest.mark.anyio
    async def test_get_blocks_at(self, empty_blockchain: Blockchain, default_1000_blocks: List[FullBlock]) -> None:
        b = empty_blockchain
        heights = []
        for block in default_1000_blocks[:200]:
            heights.append(block.height)
            await _validate_and_add_block(b, block)

        blocks = await b.get_block_records_at(heights, batch_size=2)
        assert blocks
        assert len(blocks) == 200
        assert blocks[-1].height == 199


@pytest.mark.anyio
async def test_reorg_new_ref(empty_blockchain: Blockchain, bt: BlockTools) -> None:
    b = empty_blockchain
    wallet_a = WalletTool(b.constants)
    WALLET_A_PUZZLE_HASHES = [wallet_a.get_new_puzzlehash() for _ in range(5)]
    coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
    receiver_puzzlehash = WALLET_A_PUZZLE_HASHES[1]

    blocks = bt.get_consecutive_blocks(
        5,
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        guarantee_transaction_block=True,
    )

    all_coins = []
    for spend_block in blocks[:5]:
        for coin in spend_block.get_included_reward_coins():
            if coin.puzzle_hash == coinbase_puzzlehash:
                all_coins.append(coin)
    spend_bundle_0 = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, all_coins.pop())
    blocks = bt.get_consecutive_blocks(
        15,
        block_list_input=blocks,
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        transaction_data=spend_bundle_0,
        guarantee_transaction_block=True,
    )

    for block in blocks:
        await _validate_and_add_block(b, block)
    peak = b.get_peak()
    assert peak is not None
    assert peak.height == 19

    print("first chain done")

    # Make sure a ref back into the reorg chain itself works as expected

    blocks_reorg_chain = bt.get_consecutive_blocks(
        1,
        blocks[:10],
        seed=b"2",
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
    )
    spend_bundle = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, all_coins.pop())

    blocks_reorg_chain = bt.get_consecutive_blocks(
        2,
        blocks_reorg_chain,
        seed=b"2",
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        transaction_data=spend_bundle,
        guarantee_transaction_block=True,
    )

    spend_bundle2 = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, all_coins.pop())
    blocks_reorg_chain = bt.get_consecutive_blocks(
        4, blocks_reorg_chain, seed=b"2", block_refs=[uint32(5), uint32(11)], transaction_data=spend_bundle2
    )
    blocks_reorg_chain = bt.get_consecutive_blocks(4, blocks_reorg_chain, seed=b"2")

    for i, block in enumerate(blocks_reorg_chain):
        fork_info: Optional[ForkInfo] = None
        if i < 10:
            expected = AddBlockResult.ALREADY_HAVE_BLOCK
        elif i < 19:
            expected = AddBlockResult.ADDED_AS_ORPHAN
        elif i == 19:
            # same height as peak decide by iterations
            peak = b.get_peak()
            assert peak is not None
            # same height as peak should be ADDED_AS_ORPHAN if  block.total_iters >= peak.total_iters
            assert block.total_iters < peak.total_iters
            expected = AddBlockResult.NEW_PEAK
        else:
            expected = AddBlockResult.NEW_PEAK
            if fork_info is None:
                fork_info = ForkInfo(blocks[1].height, blocks[1].height, blocks[1].header_hash)
        await _validate_and_add_block(b, block, expected_result=expected, fork_info=fork_info)
    peak = b.get_peak()
    assert peak is not None
    assert peak.height == 20


# this test doesn't reorg, but _reconsider_peak() is passed a stale
# "fork_height" to make it look like it's in a reorg, but all the same blocks
# are just added back.
@pytest.mark.anyio
async def test_reorg_stale_fork_height(empty_blockchain: Blockchain, bt: BlockTools) -> None:
    b = empty_blockchain
    wallet_a = WalletTool(b.constants)
    WALLET_A_PUZZLE_HASHES = [wallet_a.get_new_puzzlehash() for _ in range(5)]
    coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
    receiver_puzzlehash = WALLET_A_PUZZLE_HASHES[1]

    blocks = bt.get_consecutive_blocks(
        5,
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        guarantee_transaction_block=True,
    )

    all_coins = []
    for spend_block in blocks:
        for coin in spend_block.get_included_reward_coins():
            if coin.puzzle_hash == coinbase_puzzlehash:
                all_coins.append(coin)

    # Make sure a ref back into the reorg chain itself works as expected
    spend_bundle = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, all_coins.pop())

    # make sure we have a transaction block, with at least one transaction in it
    blocks = bt.get_consecutive_blocks(
        5,
        blocks,
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        transaction_data=spend_bundle,
        guarantee_transaction_block=True,
    )

    # this block (height 10) refers back to the generator in block 5
    spend_bundle2 = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, all_coins.pop())
    blocks = bt.get_consecutive_blocks(4, blocks, block_refs=[uint32(5)], transaction_data=spend_bundle2)

    for block in blocks[:5]:
        await _validate_and_add_block(b, block, expected_result=AddBlockResult.NEW_PEAK)

    # fake the fork_info to make every new block look like a reorg
    fork_info = ForkInfo(blocks[1].height, blocks[1].height, blocks[1].header_hash)
    for block in blocks[5:]:
        await _validate_and_add_block(b, block, expected_result=AddBlockResult.NEW_PEAK, fork_info=fork_info)
    peak = b.get_peak()
    assert peak is not None
    assert peak.height == 13


@pytest.mark.anyio
async def test_chain_failed_rollback(empty_blockchain: Blockchain, bt: BlockTools) -> None:
    b = empty_blockchain
    wallet_a = WalletTool(b.constants)
    WALLET_A_PUZZLE_HASHES = [wallet_a.get_new_puzzlehash() for _ in range(5)]
    coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
    receiver_puzzlehash = WALLET_A_PUZZLE_HASHES[1]

    blocks = bt.get_consecutive_blocks(
        20,
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
    )

    for block in blocks:
        await _validate_and_add_block(b, block)
    peak = b.get_peak()
    assert peak is not None
    assert peak.height == 19

    print("first chain done")

    # Make sure a ref back into the reorg chain itself works as expected

    all_coins = []
    for spend_block in blocks[:10]:
        for coin in spend_block.get_included_reward_coins():
            if coin.puzzle_hash == coinbase_puzzlehash:
                all_coins.append(coin)

    spend_bundle = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, all_coins.pop())

    blocks_reorg_chain = bt.get_consecutive_blocks(
        11,
        blocks[:10],
        seed=b"2",
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        transaction_data=spend_bundle,
        guarantee_transaction_block=True,
    )

    for block in blocks_reorg_chain[10:-1]:
        await _validate_and_add_block(b, block, expected_result=AddBlockResult.ADDED_AS_ORPHAN)

    # Incorrectly set the height as spent in DB to trigger an error
    print(f"{await b.coin_store.get_coin_record(spend_bundle.coin_spends[0].coin.name())}")
    print(spend_bundle.coin_spends[0].coin.name())
    # await b.coin_store._set_spent([spend_bundle.coin_spends[0].coin.name()], 8)
    await b.coin_store.rollback_to_block(2)
    print(f"{await b.coin_store.get_coin_record(spend_bundle.coin_spends[0].coin.name())}")

    with pytest.raises(ValueError, match="Invalid operation to set spent"):
        await _validate_and_add_block(b, blocks_reorg_chain[-1])

    peak = b.get_peak()
    assert peak is not None
    assert peak.height == 19


@pytest.mark.anyio
async def test_reorg_flip_flop(empty_blockchain: Blockchain, bt: BlockTools) -> None:
    b = empty_blockchain
    wallet_a = WalletTool(b.constants)
    WALLET_A_PUZZLE_HASHES = [wallet_a.get_new_puzzlehash() for _ in range(5)]
    coinbase_puzzlehash = WALLET_A_PUZZLE_HASHES[0]
    receiver_puzzlehash = WALLET_A_PUZZLE_HASHES[1]

    chain_a = bt.get_consecutive_blocks(
        10,
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        guarantee_transaction_block=True,
    )

    all_coins = []
    for spend_block in chain_a:
        for coin in spend_block.get_included_reward_coins():
            if coin.puzzle_hash == coinbase_puzzlehash:
                all_coins.append(coin)

    # this is a transaction block at height 10
    spend_bundle = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, all_coins.pop())
    chain_a = bt.get_consecutive_blocks(
        5,
        chain_a,
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        transaction_data=spend_bundle,
        guarantee_transaction_block=True,
    )

    spend_bundle = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, all_coins.pop())
    chain_a = bt.get_consecutive_blocks(
        5,
        chain_a,
        block_refs=[uint32(10)],
        transaction_data=spend_bundle,
        guarantee_transaction_block=True,
    )

    spend_bundle = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, all_coins.pop())
    chain_a = bt.get_consecutive_blocks(
        20,
        chain_a,
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        transaction_data=spend_bundle,
        guarantee_transaction_block=True,
    )

    # chain A is 40 blocks deep
    # chain B share the first 20 blocks with chain A

    # add 5 blocks on top of the first 20, to form chain B
    chain_b = bt.get_consecutive_blocks(
        5,
        chain_a[:20],
        seed=b"2",
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
    )
    spend_bundle = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, all_coins.pop())

    # this is a transaction block at height 15 (in Chain B)
    chain_b = bt.get_consecutive_blocks(
        5,
        chain_b,
        seed=b"2",
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        transaction_data=spend_bundle,
        guarantee_transaction_block=True,
    )

    spend_bundle = wallet_a.generate_signed_transaction(uint64(1_000), receiver_puzzlehash, all_coins.pop())
    chain_b = bt.get_consecutive_blocks(10, chain_b, seed=b"2", block_refs=[uint32(15)], transaction_data=spend_bundle)

    assert len(chain_a) == len(chain_b)

    counter = 0
    ssi = b.constants.SUB_SLOT_ITERS_STARTING
    diff = b.constants.DIFFICULTY_STARTING
    for b1, b2 in zip(chain_a, chain_b):
        # alternate the order we add blocks from the two chains, to ensure one
        # chain overtakes the other one in weight every other time
        if counter % 2 == 0:
            block1, block2 = b2, b1
        else:
            block1, block2 = b1, b2
        counter += 1

        preval: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
            [block1], {}, sub_slot_iters=ssi, difficulty=diff, prev_ses_block=None, validate_signatures=False
        )
        _, err, _ = await b.add_block(block1, preval[0], None, sub_slot_iters=ssi)
        assert err is None
        preval = await b.pre_validate_blocks_multiprocessing(
            [block2], {}, sub_slot_iters=ssi, difficulty=diff, prev_ses_block=None, validate_signatures=False
        )
        _, err, _ = await b.add_block(block2, preval[0], None, sub_slot_iters=ssi)
        assert err is None

    peak = b.get_peak()
    assert peak is not None
    assert peak.height == 39

    chain_b = bt.get_consecutive_blocks(
        10,
        chain_b,
        seed=b"2",
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
    )

    for block in chain_b[40:]:
        await _validate_and_add_block(b, block)


async def test_get_tx_peak(default_400_blocks: List[FullBlock], empty_blockchain: Blockchain) -> None:
    bc = empty_blockchain
    test_blocks = default_400_blocks[:100]
    ssi = empty_blockchain.constants.SUB_SLOT_ITERS_STARTING
    diff = empty_blockchain.constants.DIFFICULTY_STARTING
    res = await bc.pre_validate_blocks_multiprocessing(
        test_blocks, {}, sub_slot_iters=ssi, difficulty=diff, prev_ses_block=None, validate_signatures=False
    )

    last_tx_block_record = None
    for b, prevalidation_res in zip(test_blocks, res):
        assert bc.get_tx_peak() == last_tx_block_record
        _, err, _ = await bc.add_block(b, prevalidation_res, None, sub_slot_iters=ssi)
        assert err is None

        if b.is_transaction_block():
            assert prevalidation_res.required_iters is not None
            block_record = block_to_block_record(
                bc.constants,
                bc,
                prevalidation_res.required_iters,
                b,
                empty_blockchain.constants.SUB_SLOT_ITERS_STARTING,
            )
            last_tx_block_record = block_record

    assert bc.get_tx_peak() == last_tx_block_record


def to_bytes(gen: Optional[SerializedProgram]) -> bytes:
    assert gen is not None
    return bytes(gen)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="block heights for generators differ between test chains in different modes")
@pytest.mark.parametrize("clear_cache", [True, False])
async def test_lookup_block_generators(
    default_10000_blocks: List[FullBlock],
    test_long_reorg_blocks_light: List[FullBlock],
    bt: BlockTools,
    empty_blockchain: Blockchain,
    clear_cache: bool,
) -> None:
    b = empty_blockchain
    blocks_1 = default_10000_blocks
    blocks_2 = test_long_reorg_blocks_light

    # this test blockchain is expected to have block generators at these
    # heights:
    # 2, 3, 4, 5, 6, 7, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
    # 24, 25, 26, 28

    # default_10000_blocks and test_long_reorg_blocks_light diverge at height
    # 500. Add blocks from both past the fork to be able to test both

    # fork 1 is expected to have generators at these heights:
    # 503, 507, 511, 517, 524, 529, 532, 533, 534, 539, 542, 543, 546, 547

    # fork 2 is expected to have generators at these heights:
    # 507, 516, 527, 535, 539, 543, 547

    # start with adding some blocks to test lookups from the mainchain
    for block in blocks_2[:550]:
        await _validate_and_add_block(b, block, expected_result=AddBlockResult.NEW_PEAK)

    for block in blocks_1[500:550]:
        await _validate_and_add_block(b, block, expected_result=AddBlockResult.ADDED_AS_ORPHAN)

    # now we have a blockchain with two forks, the peak is at blocks_2[550] and
    # the leight weight peak is at blocks_1[550]
    # make sure we can lookup block generators from each fork

    peak_1 = blocks_1[550]
    peak_2 = blocks_2[550]

    # single generators, from the shared part of the chain
    for peak in [peak_1, peak_2]:
        if clear_cache:
            b.clean_block_records()
        generators = await b.lookup_block_generators(peak.prev_header_hash, {uint32(2)})
        assert generators == {
            uint32(2): to_bytes(blocks_1[2].transactions_generator),
        }

    # multiple generators from the shared part of the chain
    for peak in [peak_1, peak_2]:
        if clear_cache:
            b.clean_block_records()
        generators = await b.lookup_block_generators(peak.prev_header_hash, {uint32(2), uint32(10), uint32(26)})
        assert generators == {
            uint32(2): to_bytes(blocks_1[2].transactions_generator),
            uint32(10): to_bytes(blocks_1[10].transactions_generator),
            uint32(26): to_bytes(blocks_1[26].transactions_generator),
        }

    # lookups from the past the fork
    if clear_cache:
        b.clean_block_records()
    generators = await b.lookup_block_generators(peak_1.prev_header_hash, {uint32(503)})
    assert generators == {uint32(503): to_bytes(blocks_1[503].transactions_generator)}

    if clear_cache:
        b.clean_block_records()
    generators = await b.lookup_block_generators(peak_2.prev_header_hash, {uint32(516)})
    assert generators == {uint32(516): to_bytes(blocks_2[516].transactions_generator)}

    # make sure we don't cross the forks
    if clear_cache:
        b.clean_block_records()
    with pytest.raises(ValueError, match="Err.GENERATOR_REF_HAS_NO_GENERATOR"):
        await b.lookup_block_generators(peak_1.prev_header_hash, {uint32(516)})

    if clear_cache:
        b.clean_block_records()
    with pytest.raises(ValueError, match="Err.GENERATOR_REF_HAS_NO_GENERATOR"):
        await b.lookup_block_generators(peak_2.prev_header_hash, {uint32(503)})

    # make sure we fail when looking up a non-transaction block from the main
    # chain, regardless of which chain we start at
    if clear_cache:
        b.clean_block_records()
    with pytest.raises(ValueError, match="Err.GENERATOR_REF_HAS_NO_GENERATOR"):
        await b.lookup_block_generators(peak_1.prev_header_hash, {uint32(8)})

    if clear_cache:
        b.clean_block_records()
    with pytest.raises(ValueError, match="Err.GENERATOR_REF_HAS_NO_GENERATOR"):
        await b.lookup_block_generators(peak_2.prev_header_hash, {uint32(8)})

    # if we try to look up generators starting from a disconnected block, we
    # fail
    if clear_cache:
        b.clean_block_records()
    with pytest.raises(AssertionError):
        await b.lookup_block_generators(blocks_2[600].prev_header_hash, {uint32(3)})

    if clear_cache:
        b.clean_block_records()
    with pytest.raises(AssertionError):
        await b.lookup_block_generators(blocks_1[600].prev_header_hash, {uint32(3)})
