from __future__ import annotations

import logging
import multiprocessing
import time
from dataclasses import replace
from secrets import token_bytes
from typing import List

import pytest
from blspy import AugSchemeMPL, G2Element
from clvm.casts import int_to_bytes

from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_rewards import calculate_base_farmer_reward
from chia.consensus.blockchain import ReceiveBlockResult
from chia.consensus.coinbase import create_farmer_coin
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.consensus.pot_iterations import is_overflow_block
from chia.full_node.bundle_tools import detect_potential_template_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.simulator.block_tools import create_block_tools_async, test_constants
from chia.simulator.keyring import TempKeyring
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.foliage import TransactionsInfo
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import InfusedChallengeChainSubSlot
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.errors import Err
from chia.util.generator_tools import get_block_header
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64
from chia.util.merkle_set import MerkleSet
from chia.util.recursive_replace import recursive_replace
from chia.util.vdf_prover import get_vdf_info_and_proof
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
)
from tests.blockchain.blockchain_test_utils import (
    _validate_and_add_block,
    _validate_and_add_block_multi_error,
    _validate_and_add_block_multi_result,
    _validate_and_add_block_no_error,
)
from tests.util.blockchain import create_blockchain

log = logging.getLogger(__name__)
bad_element = ClassgroupElement.from_bytes(b"\x00")


class TestGenesisBlock:
    @pytest.mark.asyncio
    async def test_block_tools_proofs_400(self, default_400_blocks):
        vdf, proof = get_vdf_info_and_proof(
            test_constants, ClassgroupElement.get_default_element(), test_constants.GENESIS_CHALLENGE, uint64(231)
        )
        if proof.is_valid(test_constants, ClassgroupElement.get_default_element(), vdf) is False:
            raise Exception("invalid proof")

    @pytest.mark.asyncio
    async def test_block_tools_proofs_1000(self, default_1000_blocks):
        vdf, proof = get_vdf_info_and_proof(
            test_constants, ClassgroupElement.get_default_element(), test_constants.GENESIS_CHALLENGE, uint64(231)
        )
        if proof.is_valid(test_constants, ClassgroupElement.get_default_element(), vdf) is False:
            raise Exception("invalid proof")

    @pytest.mark.asyncio
    async def test_block_tools_proofs(self):
        vdf, proof = get_vdf_info_and_proof(
            test_constants, ClassgroupElement.get_default_element(), test_constants.GENESIS_CHALLENGE, uint64(231)
        )
        if proof.is_valid(test_constants, ClassgroupElement.get_default_element(), vdf) is False:
            raise Exception("invalid proof")

    @pytest.mark.asyncio
    async def test_non_overflow_genesis(self, empty_blockchain, bt):
        assert empty_blockchain.get_peak() is None
        genesis = bt.get_consecutive_blocks(1, force_overflow=False)[0]
        await _validate_and_add_block(empty_blockchain, genesis)
        assert empty_blockchain.get_peak().height == 0

    @pytest.mark.asyncio
    async def test_overflow_genesis(self, empty_blockchain, bt):
        genesis = bt.get_consecutive_blocks(1, force_overflow=True)[0]
        await _validate_and_add_block(empty_blockchain, genesis)

    @pytest.mark.asyncio
    async def test_genesis_empty_slots(self, empty_blockchain, bt):
        genesis = bt.get_consecutive_blocks(1, force_overflow=False, skip_slots=30)[0]
        await _validate_and_add_block(empty_blockchain, genesis)

    @pytest.mark.asyncio
    async def test_overflow_genesis_empty_slots(self, empty_blockchain, bt):
        genesis = bt.get_consecutive_blocks(1, force_overflow=True, skip_slots=3)[0]
        await _validate_and_add_block(empty_blockchain, genesis)

    @pytest.mark.asyncio
    async def test_genesis_validate_1(self, empty_blockchain, bt):
        genesis = bt.get_consecutive_blocks(1, force_overflow=False)[0]
        bad_prev = bytes([1] * 32)
        genesis = recursive_replace(genesis, "foliage.prev_block_hash", bad_prev)
        await _validate_and_add_block(empty_blockchain, genesis, expected_error=Err.INVALID_PREV_BLOCK_HASH)


class TestBlockHeaderValidation:
    @pytest.mark.asyncio
    async def test_long_chain(self, empty_blockchain, default_1000_blocks):
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
                    uint64(10000000),
                )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", [new_finished_ss] + block.finished_sub_slots[1:]
                )
                header_block_bad = get_block_header(block_bad, [], [])
                _, error = validate_finished_header_block(
                    empty_blockchain.constants,
                    empty_blockchain,
                    header_block_bad,
                    False,
                    block.finished_sub_slots[0].challenge_chain.new_difficulty,
                    block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters,
                )
                assert error.code == Err.INVALID_NEW_SUB_SLOT_ITERS

                # Also fails calling the outer methods, but potentially with a different error
                await _validate_and_add_block(
                    empty_blockchain, block_bad, expected_result=ReceiveBlockResult.INVALID_BLOCK
                )

                new_finished_ss_2 = recursive_replace(
                    block.finished_sub_slots[0],
                    "challenge_chain.new_difficulty",
                    uint64(10000000),
                )
                block_bad_2 = recursive_replace(
                    block, "finished_sub_slots", [new_finished_ss_2] + block.finished_sub_slots[1:]
                )

                header_block_bad_2 = get_block_header(block_bad_2, [], [])
                _, error = validate_finished_header_block(
                    empty_blockchain.constants,
                    empty_blockchain,
                    header_block_bad_2,
                    False,
                    block.finished_sub_slots[0].challenge_chain.new_difficulty,
                    block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters,
                )
                assert error.code == Err.INVALID_NEW_DIFFICULTY

                # Also fails calling the outer methods, but potentially with a different error
                await _validate_and_add_block(
                    empty_blockchain, block_bad_2, expected_result=ReceiveBlockResult.INVALID_BLOCK
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
                block_bad_3 = recursive_replace(
                    block, "finished_sub_slots", [new_finished_ss_3] + block.finished_sub_slots[1:]
                )

                header_block_bad_3 = get_block_header(block_bad_3, [], [])
                _, error = validate_finished_header_block(
                    empty_blockchain.constants,
                    empty_blockchain,
                    header_block_bad_3,
                    False,
                    block.finished_sub_slots[0].challenge_chain.new_difficulty,
                    block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters,
                )
                assert error.code == Err.INVALID_SUB_EPOCH_SUMMARY

                # Also fails calling the outer methods, but potentially with a different error
                await _validate_and_add_block(
                    empty_blockchain, block_bad_3, expected_result=ReceiveBlockResult.INVALID_BLOCK
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
                block_bad_4 = recursive_replace(
                    block, "finished_sub_slots", [new_finished_ss_4] + block.finished_sub_slots[1:]
                )

                header_block_bad_4 = get_block_header(block_bad_4, [], [])
                _, error = validate_finished_header_block(
                    empty_blockchain.constants,
                    empty_blockchain,
                    header_block_bad_4,
                    False,
                    block.finished_sub_slots[0].challenge_chain.new_difficulty,
                    block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters,
                )
                assert error.code == Err.INVALID_SUB_EPOCH_SUMMARY

                # Also fails calling the outer methods, but potentially with a different error
                await _validate_and_add_block(
                    empty_blockchain, block_bad_4, expected_result=ReceiveBlockResult.INVALID_BLOCK
                )
            await _validate_and_add_block(empty_blockchain, block)
            log.info(
                f"Added block {block.height} total iters {block.total_iters} "
                f"new slot? {len(block.finished_sub_slots)}"
            )
        assert empty_blockchain.get_peak().height == len(blocks) - 1

    @pytest.mark.asyncio
    async def test_unfinished_blocks(self, empty_blockchain, softfork_height, bt):
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
        if unf.transactions_generator is not None:
            block_generator: BlockGenerator = await blockchain.get_block_generator(unf)
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
        if unf.transactions_generator is not None:
            block_generator: BlockGenerator = await blockchain.get_block_generator(unf)
            block_bytes = bytes(unf)
            npc_result = await blockchain.run_generator(block_bytes, block_generator, height=softfork_height)
        validate_res = await blockchain.validate_unfinished_block(unf, npc_result, False)
        assert validate_res.error is None

    @pytest.mark.asyncio
    async def test_empty_genesis(self, empty_blockchain, bt):
        for block in bt.get_consecutive_blocks(2, skip_slots=3):
            await _validate_and_add_block(empty_blockchain, block)

    @pytest.mark.asyncio
    async def test_empty_slots_non_genesis(self, empty_blockchain, bt):
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(10)
        for block in blocks:
            await _validate_and_add_block(empty_blockchain, block)

        blocks = bt.get_consecutive_blocks(10, skip_slots=2, block_list_input=blocks)
        for block in blocks[10:]:
            await _validate_and_add_block(empty_blockchain, block)
        assert blockchain.get_peak().height == 19

    @pytest.mark.asyncio
    async def test_one_sb_per_slot(self, empty_blockchain, bt):
        blockchain = empty_blockchain
        num_blocks = 20
        blocks = []
        for i in range(num_blocks):
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1)
            await _validate_and_add_block(empty_blockchain, blocks[-1])
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_all_overflow(self, empty_blockchain, bt):
        blockchain = empty_blockchain
        num_rounds = 5
        blocks = []
        num_blocks = 0
        for i in range(1, num_rounds):
            num_blocks += i
            blocks = bt.get_consecutive_blocks(i, block_list_input=blocks, skip_slots=1, force_overflow=True)
            for block in blocks[-i:]:
                await _validate_and_add_block(empty_blockchain, block)
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_unf_block_overflow(self, empty_blockchain, softfork_height, bt):
        blockchain = empty_blockchain

        blocks = []
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
                if block.transactions_generator is not None:
                    block_generator: BlockGenerator = await blockchain.get_block_generator(unf)
                    block_bytes = bytes(unf)
                    npc_result = await blockchain.run_generator(block_bytes, block_generator, height=softfork_height)
                validate_res = await blockchain.validate_unfinished_block(
                    unf, npc_result, skip_overflow_ss_validation=True
                )
                assert validate_res.error is None
                return None

            await _validate_and_add_block(blockchain, blocks[-1])

    @pytest.mark.asyncio
    async def test_one_sb_per_two_slots(self, empty_blockchain, bt):
        blockchain = empty_blockchain
        num_blocks = 20
        blocks = []
        for i in range(num_blocks):  # Same thing, but 2 sub-slots per block
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=2)
            await _validate_and_add_block(blockchain, blocks[-1])
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_one_sb_per_five_slots(self, empty_blockchain, bt):
        blockchain = empty_blockchain
        num_blocks = 10
        blocks = []
        for i in range(num_blocks):  # Same thing, but 5 sub-slots per block
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=5)
            await _validate_and_add_block(blockchain, blocks[-1])
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_basic_chain_overflow(self, empty_blockchain, bt):
        blocks = bt.get_consecutive_blocks(5, force_overflow=True)
        for block in blocks:
            await _validate_and_add_block(empty_blockchain, block)
        assert empty_blockchain.get_peak().height == len(blocks) - 1

    @pytest.mark.asyncio
    async def test_one_sb_per_two_slots_force_overflow(self, empty_blockchain, bt):
        blockchain = empty_blockchain
        num_blocks = 10
        blocks = []
        for i in range(num_blocks):
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=2, force_overflow=True)
            await _validate_and_add_block(blockchain, blocks[-1])
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_invalid_prev(self, empty_blockchain, bt):
        # 1
        blocks = bt.get_consecutive_blocks(2, force_overflow=False)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_1_bad = recursive_replace(blocks[-1], "foliage.prev_block_hash", bytes([0] * 32))

        await _validate_and_add_block(empty_blockchain, block_1_bad, expected_error=Err.INVALID_PREV_BLOCK_HASH)

    @pytest.mark.asyncio
    async def test_invalid_pospace(self, empty_blockchain, bt):
        # 2
        blocks = bt.get_consecutive_blocks(2, force_overflow=False)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_1_bad = recursive_replace(blocks[-1], "reward_chain_block.proof_of_space.proof", bytes([0] * 32))

        await _validate_and_add_block(empty_blockchain, block_1_bad, expected_error=Err.INVALID_POSPACE)

    @pytest.mark.asyncio
    async def test_invalid_sub_slot_challenge_hash_genesis(self, empty_blockchain, bt):
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

        assert error.code == Err.INVALID_PREV_CHALLENGE_SLOT_HASH
        await _validate_and_add_block(empty_blockchain, block_0_bad, expected_result=ReceiveBlockResult.INVALID_BLOCK)

    @pytest.mark.asyncio
    async def test_invalid_sub_slot_challenge_hash_non_genesis(self, empty_blockchain, bt):
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
        _, error = validate_finished_header_block(
            empty_blockchain.constants,
            empty_blockchain,
            header_block_bad,
            False,
            blocks[1].finished_sub_slots[0].challenge_chain.new_difficulty,
            blocks[1].finished_sub_slots[0].challenge_chain.new_sub_slot_iters,
        )
        assert error.code == Err.INVALID_PREV_CHALLENGE_SLOT_HASH
        await _validate_and_add_block(empty_blockchain, block_1_bad, expected_result=ReceiveBlockResult.INVALID_BLOCK)

    @pytest.mark.asyncio
    async def test_invalid_sub_slot_challenge_hash_empty_ss(self, empty_blockchain, bt):
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
        _, error = validate_finished_header_block(
            empty_blockchain.constants,
            empty_blockchain,
            header_block_bad,
            False,
            blocks[1].finished_sub_slots[0].challenge_chain.new_difficulty,
            blocks[1].finished_sub_slots[0].challenge_chain.new_sub_slot_iters,
        )
        assert error.code == Err.INVALID_PREV_CHALLENGE_SLOT_HASH
        await _validate_and_add_block(empty_blockchain, block_1_bad, expected_result=ReceiveBlockResult.INVALID_BLOCK)

    @pytest.mark.asyncio
    async def test_genesis_no_icc(self, empty_blockchain, bt):
        # 2d
        blocks = bt.get_consecutive_blocks(1, force_overflow=False, skip_slots=1)
        new_finished_ss = recursive_replace(
            blocks[0].finished_sub_slots[0],
            "infused_challenge_chain",
            InfusedChallengeChainSubSlot(
                VDFInfo(
                    bytes([0] * 32),
                    uint64(1200),
                    ClassgroupElement.get_default_element(),
                )
            ),
        )
        block_0_bad = recursive_replace(
            blocks[0], "finished_sub_slots", [new_finished_ss] + blocks[0].finished_sub_slots[1:]
        )
        await _validate_and_add_block(empty_blockchain, block_0_bad, expected_error=Err.SHOULD_NOT_HAVE_ICC)

    async def do_test_invalid_icc_sub_slot_vdf(self, keychain, db_version):
        bt_high_iters = await create_block_tools_async(
            constants=test_constants.replace(SUB_SLOT_ITERS_STARTING=(2**12), DIFFICULTY_STARTING=(2**14)),
            keychain=keychain,
        )
        bc1, db_wrapper, db_path = await create_blockchain(bt_high_iters.constants, db_version)
        blocks = bt_high_iters.get_consecutive_blocks(10)
        for block in blocks:
            if len(block.finished_sub_slots) > 0 and block.finished_sub_slots[-1].infused_challenge_chain is not None:
                # Bad iters
                new_finished_ss = recursive_replace(
                    block.finished_sub_slots[-1],
                    "infused_challenge_chain",
                    InfusedChallengeChainSubSlot(
                        replace(
                            block.finished_sub_slots[
                                -1
                            ].infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf,
                            number_of_iterations=10000000,
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
                        replace(
                            block.finished_sub_slots[
                                -1
                            ].infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf,
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
                        replace(
                            block.finished_sub_slots[
                                -1
                            ].infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf,
                            challenge=bytes([0] * 32),
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

        await db_wrapper.close()
        bc1.shut_down()
        db_path.unlink()

    @pytest.mark.asyncio
    async def test_invalid_icc_sub_slot_vdf(self, db_version):
        with TempKeyring() as keychain:
            await self.do_test_invalid_icc_sub_slot_vdf(keychain, db_version)

    @pytest.mark.asyncio
    async def test_invalid_icc_into_cc(self, empty_blockchain, bt):
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(blockchain, blocks[0])
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1)
            block = blocks[-1]
            if len(block.finished_sub_slots) > 0 and block.finished_sub_slots[-1].infused_challenge_chain is not None:
                if block.finished_sub_slots[-1].reward_chain.deficit == test_constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                    # 2g
                    case_1 = True
                    new_finished_ss = recursive_replace(
                        block.finished_sub_slots[-1],
                        "challenge_chain",
                        replace(
                            block.finished_sub_slots[-1].challenge_chain,
                            infused_challenge_chain_sub_slot_hash=bytes([1] * 32),
                        ),
                    )
                else:
                    # 2h
                    case_2 = True
                    new_finished_ss = recursive_replace(
                        block.finished_sub_slots[-1],
                        "challenge_chain",
                        replace(
                            block.finished_sub_slots[-1].challenge_chain,
                            infused_challenge_chain_sub_slot_hash=block.finished_sub_slots[
                                -1
                            ].infused_challenge_chain.get_hash(),
                        ),
                    )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss]
                )

                header_block_bad = get_block_header(block_bad, [], [])
                _, error = validate_finished_header_block(
                    empty_blockchain.constants,
                    empty_blockchain,
                    header_block_bad,
                    False,
                    block.finished_sub_slots[0].challenge_chain.new_difficulty,
                    block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters,
                )
                assert error.code == Err.INVALID_ICC_HASH_CC
                await _validate_and_add_block(blockchain, block_bad, expected_result=ReceiveBlockResult.INVALID_BLOCK)

                # 2i
                new_finished_ss_bad_rc = recursive_replace(
                    block.finished_sub_slots[-1],
                    "reward_chain",
                    replace(block.finished_sub_slots[-1].reward_chain, infused_challenge_chain_sub_slot_hash=None),
                )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_bad_rc]
                )
                await _validate_and_add_block(blockchain, block_bad, expected_error=Err.INVALID_ICC_HASH_RC)
            elif len(block.finished_sub_slots) > 0 and block.finished_sub_slots[-1].infused_challenge_chain is None:
                # 2j
                new_finished_ss_bad_cc = recursive_replace(
                    block.finished_sub_slots[-1],
                    "challenge_chain",
                    replace(
                        block.finished_sub_slots[-1].challenge_chain,
                        infused_challenge_chain_sub_slot_hash=bytes([1] * 32),
                    ),
                )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_bad_cc]
                )
                await _validate_and_add_block(blockchain, block_bad, expected_error=Err.INVALID_ICC_HASH_CC)

                # 2k
                new_finished_ss_bad_rc = recursive_replace(
                    block.finished_sub_slots[-1],
                    "reward_chain",
                    replace(
                        block.finished_sub_slots[-1].reward_chain, infused_challenge_chain_sub_slot_hash=bytes([1] * 32)
                    ),
                )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_bad_rc]
                )
                await _validate_and_add_block(blockchain, block_bad, expected_error=Err.INVALID_ICC_HASH_RC)

            # Finally, add the block properly
            await _validate_and_add_block(blockchain, block)

    @pytest.mark.asyncio
    async def test_empty_slot_no_ses(self, empty_blockchain, bt):
        # 2l
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(blockchain, blocks[0])
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=4)

        new_finished_ss = recursive_replace(
            blocks[-1].finished_sub_slots[-1],
            "challenge_chain",
            replace(blocks[-1].finished_sub_slots[-1].challenge_chain, subepoch_summary_hash=std_hash(b"0")),
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
        assert error.code == Err.INVALID_SUB_EPOCH_SUMMARY_HASH
        await _validate_and_add_block(blockchain, block_bad, expected_result=ReceiveBlockResult.INVALID_BLOCK)

    @pytest.mark.asyncio
    async def test_empty_sub_slots_epoch(self, empty_blockchain, default_400_blocks, bt):
        # 2m
        # Tests adding an empty sub slot after the sub-epoch / epoch.
        # Also tests overflow block in epoch
        blocks_base = default_400_blocks[: test_constants.EPOCH_BLOCKS]
        assert len(blocks_base) == test_constants.EPOCH_BLOCKS
        blocks_1 = bt.get_consecutive_blocks(1, block_list_input=blocks_base, force_overflow=True)
        blocks_2 = bt.get_consecutive_blocks(1, skip_slots=3, block_list_input=blocks_base, force_overflow=True)
        for block in blocks_base:
            await _validate_and_add_block(empty_blockchain, block, skip_prevalidation=True)
        await _validate_and_add_block(
            empty_blockchain, blocks_1[-1], expected_result=ReceiveBlockResult.NEW_PEAK, skip_prevalidation=True
        )
        await _validate_and_add_block(
            empty_blockchain, blocks_2[-1], expected_result=ReceiveBlockResult.ADDED_AS_ORPHAN, skip_prevalidation=True
        )

    @pytest.mark.asyncio
    async def test_wrong_cc_hash_rc(self, empty_blockchain, bt):
        # 2o
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(1, skip_slots=1)
        blocks = bt.get_consecutive_blocks(1, skip_slots=1, block_list_input=blocks)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        new_finished_ss = recursive_replace(
            blocks[-1].finished_sub_slots[-1],
            "reward_chain",
            replace(blocks[-1].finished_sub_slots[-1].reward_chain, challenge_chain_sub_slot_hash=bytes([3] * 32)),
        )
        block_1_bad = recursive_replace(
            blocks[-1], "finished_sub_slots", blocks[-1].finished_sub_slots[:-1] + [new_finished_ss]
        )

        await _validate_and_add_block(blockchain, block_1_bad, expected_error=Err.INVALID_CHALLENGE_SLOT_HASH_RC)

    @pytest.mark.asyncio
    async def test_invalid_cc_sub_slot_vdf(self, empty_blockchain, bt):
        # 2q
        blocks: List[FullBlock] = []
        found_overflow_slot: bool = False

        while not found_overflow_slot:
            blocks = bt.get_consecutive_blocks(1, blocks)
            block = blocks[-1]
            if (
                len(block.finished_sub_slots)
                and is_overflow_block(test_constants, block.reward_chain_block.signage_point_index)
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

    @pytest.mark.asyncio
    async def test_invalid_rc_sub_slot_vdf(self, empty_blockchain, bt):
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
                        bytes([1] * 32),
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

    @pytest.mark.asyncio
    async def test_genesis_bad_deficit(self, empty_blockchain, bt):
        # 2r
        block = bt.get_consecutive_blocks(1, skip_slots=2)[0]
        new_finished_ss = recursive_replace(
            block.finished_sub_slots[-1],
            "reward_chain",
            recursive_replace(
                block.finished_sub_slots[-1].reward_chain,
                "deficit",
                test_constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1,
            ),
        )
        block_bad = recursive_replace(block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss])
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_DEFICIT)

    @pytest.mark.asyncio
    async def test_reset_deficit(self, empty_blockchain, bt):
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

    @pytest.mark.asyncio
    async def test_genesis_has_ses(self, empty_blockchain, bt):
        # 3a
        block = bt.get_consecutive_blocks(1, skip_slots=1)[0]
        new_finished_ss = recursive_replace(
            block.finished_sub_slots[0],
            "challenge_chain",
            recursive_replace(
                block.finished_sub_slots[0].challenge_chain,
                "subepoch_summary_hash",
                bytes([0] * 32),
            ),
        )

        new_finished_ss = recursive_replace(
            new_finished_ss,
            "reward_chain",
            replace(
                new_finished_ss.reward_chain, challenge_chain_sub_slot_hash=new_finished_ss.challenge_chain.get_hash()
            ),
        )
        block_bad = recursive_replace(block, "finished_sub_slots", [new_finished_ss] + block.finished_sub_slots[1:])
        with pytest.raises(AssertionError):
            # Fails pre validation
            await _validate_and_add_block(
                empty_blockchain, block_bad, expected_error=Err.INVALID_SUB_EPOCH_SUMMARY_HASH
            )

    @pytest.mark.asyncio
    async def test_no_ses_if_no_se(self, empty_blockchain, bt):
        # 3b
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if len(blocks[-1].finished_sub_slots) > 0 and is_overflow_block(
                test_constants, blocks[-1].reward_chain_block.signage_point_index
            ):
                new_finished_ss: EndOfSubSlotBundle = recursive_replace(
                    blocks[-1].finished_sub_slots[0],
                    "challenge_chain",
                    recursive_replace(
                        blocks[-1].finished_sub_slots[0].challenge_chain,
                        "subepoch_summary_hash",
                        bytes([0] * 32),
                    ),
                )

                new_finished_ss = recursive_replace(
                    new_finished_ss,
                    "reward_chain",
                    replace(
                        new_finished_ss.reward_chain,
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

    @pytest.mark.asyncio
    async def test_too_many_blocks(self, empty_blockchain):
        # 4: TODO
        pass

    @pytest.mark.asyncio
    async def test_bad_pos(self, empty_blockchain, bt):
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

    @pytest.mark.asyncio
    async def test_bad_signage_point_index(self, empty_blockchain, bt):
        # 6
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        with pytest.raises(ValueError):
            block_bad = recursive_replace(
                blocks[-1], "reward_chain_block.signage_point_index", test_constants.NUM_SPS_SUB_SLOT
            )
            await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_SP_INDEX)
        with pytest.raises(ValueError):
            block_bad = recursive_replace(
                blocks[-1], "reward_chain_block.signage_point_index", test_constants.NUM_SPS_SUB_SLOT + 1
            )
            await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_SP_INDEX)

    @pytest.mark.asyncio
    async def test_sp_0_no_sp(self, empty_blockchain, bt):
        # 7
        blocks = []
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].reward_chain_block.signage_point_index == 0:
                case_1 = True
                block_bad = recursive_replace(blocks[-1], "reward_chain_block.signage_point_index", uint8(1))
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_SP_INDEX)

            elif not is_overflow_block(test_constants, blocks[-1].reward_chain_block.signage_point_index):
                case_2 = True
                block_bad = recursive_replace(blocks[-1], "reward_chain_block.signage_point_index", uint8(0))
                await _validate_and_add_block_multi_error(
                    empty_blockchain, block_bad, [Err.INVALID_SP_INDEX, Err.INVALID_POSPACE]
                )
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.asyncio
    async def test_epoch_overflows(self, empty_blockchain):
        # 9. TODO. This is hard to test because it requires modifying the block tools to make these special blocks
        pass

    @pytest.mark.asyncio
    async def test_bad_total_iters(self, empty_blockchain, bt):
        # 10
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.total_iters", blocks[-1].reward_chain_block.total_iters + 1
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_TOTAL_ITERS)

    @pytest.mark.asyncio
    async def test_bad_rc_sp_vdf(self, empty_blockchain, bt):
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

    @pytest.mark.asyncio
    async def test_bad_rc_sp_sig(self, empty_blockchain, bt):
        # 12
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad = recursive_replace(blocks[-1], "reward_chain_block.reward_chain_sp_signature", G2Element.generator())
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_RC_SIGNATURE)

    @pytest.mark.asyncio
    async def test_bad_cc_sp_vdf(self, empty_blockchain, bt):
        # 13. Note: does not validate fully due to proof of space being validated first

        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].reward_chain_block.signage_point_index != 0:
                block_bad = recursive_replace(
                    blocks[-1], "reward_chain_block.challenge_chain_sp_vdf.challenge", std_hash(b"1")
                )
                await _validate_and_add_block(
                    empty_blockchain, block_bad, expected_result=ReceiveBlockResult.INVALID_BLOCK
                )
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_block.challenge_chain_sp_vdf.output",
                    bad_element,
                )
                await _validate_and_add_block(
                    empty_blockchain, block_bad, expected_result=ReceiveBlockResult.INVALID_BLOCK
                )
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_block.challenge_chain_sp_vdf.number_of_iterations",
                    uint64(1111111111111),
                )
                await _validate_and_add_block(
                    empty_blockchain, block_bad, expected_result=ReceiveBlockResult.INVALID_BLOCK
                )
                block_bad = recursive_replace(
                    blocks[-1],
                    "challenge_chain_sp_proof",
                    VDFProof(uint8(0), std_hash(b""), False),
                )
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_CC_SP_VDF)
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.asyncio
    async def test_bad_cc_sp_sig(self, empty_blockchain, bt):
        # 14
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.challenge_chain_sp_signature", G2Element.generator()
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_CC_SIGNATURE)

    @pytest.mark.asyncio
    async def test_is_transaction_block(self, empty_blockchain):
        # 15: TODO
        pass

    @pytest.mark.asyncio
    async def test_bad_foliage_sb_sig(self, empty_blockchain, bt):
        # 16
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad = recursive_replace(blocks[-1], "foliage.foliage_block_data_signature", G2Element.generator())
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_PLOT_SIGNATURE)

    @pytest.mark.asyncio
    async def test_bad_foliage_transaction_block_sig(self, empty_blockchain, bt):
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

    @pytest.mark.asyncio
    async def test_unfinished_reward_chain_sb_hash(self, empty_blockchain, bt):
        # 18
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage.foliage_block_data.unfinished_reward_block_hash", std_hash(b"2")
        )
        new_m = block_bad.foliage.foliage_block_data.get_hash()
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_URSB_HASH)

    @pytest.mark.asyncio
    async def test_pool_target_height(self, empty_blockchain, bt):
        # 19
        blocks = bt.get_consecutive_blocks(3)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        block_bad: FullBlock = recursive_replace(blocks[-1], "foliage.foliage_block_data.pool_target.max_height", 1)
        new_m = block_bad.foliage.foliage_block_data.get_hash()
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.OLD_POOL_TARGET)

    @pytest.mark.asyncio
    async def test_pool_target_pre_farm(self, empty_blockchain, bt):
        # 20a
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage.foliage_block_data.pool_target.puzzle_hash", std_hash(b"12")
        )
        new_m = block_bad.foliage.foliage_block_data.get_hash()
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_PREFARM)

    @pytest.mark.asyncio
    async def test_pool_target_signature(self, empty_blockchain, bt):
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
                new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_POOL_SIGNATURE)
                return None
            attempts += 1

    @pytest.mark.asyncio
    async def test_pool_target_contract(self, empty_blockchain, bt):
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
                    blocks[-1], "foliage.foliage_block_data.pool_target.puzzle_hash", bytes32(token_bytes(32))
                )
                new_m = block_bad.foliage.foliage_block_data.get_hash()
                new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_POOL_TARGET)
                return None
            attempts += 1

    @pytest.mark.asyncio
    async def test_foliage_data_presence(self, empty_blockchain, bt):
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
                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage.foliage_transaction_block_hash", std_hash(b"")
                )
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

    @pytest.mark.asyncio
    async def test_foliage_transaction_block_hash(self, empty_blockchain, bt):
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
                new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                await _validate_and_add_block(
                    empty_blockchain, block_bad, expected_error=Err.INVALID_FOLIAGE_BLOCK_HASH
                )
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.asyncio
    async def test_genesis_bad_prev_block(self, empty_blockchain, bt):
        # 24a
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage_transaction_block.prev_transaction_block_hash", std_hash(b"2")
        )
        block_bad: FullBlock = recursive_replace(
            block_bad, "foliage.foliage_transaction_block_hash", block_bad.foliage_transaction_block.get_hash()
        )
        new_m = block_bad.foliage.foliage_transaction_block_hash
        new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_PREV_BLOCK_HASH)

    @pytest.mark.asyncio
    async def test_bad_prev_block_non_genesis(self, empty_blockchain, bt):
        # 24b
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_transaction_block is not None:
                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage_transaction_block.prev_transaction_block_hash", std_hash(b"2")
                )
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage.foliage_transaction_block_hash", block_bad.foliage_transaction_block.get_hash()
                )
                new_m = block_bad.foliage.foliage_transaction_block_hash
                new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_PREV_BLOCK_HASH)
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.asyncio
    async def test_bad_filter_hash(self, empty_blockchain, bt):
        # 25
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_transaction_block is not None:
                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage_transaction_block.filter_hash", std_hash(b"2")
                )
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage.foliage_transaction_block_hash", block_bad.foliage_transaction_block.get_hash()
                )
                new_m = block_bad.foliage.foliage_transaction_block_hash
                new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                await _validate_and_add_block(
                    empty_blockchain, block_bad, expected_error=Err.INVALID_TRANSACTIONS_FILTER_HASH
                )
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.asyncio
    async def test_bad_timestamp(self, empty_blockchain, bt):
        # 26
        blocks = bt.get_consecutive_blocks(1)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_transaction_block is not None:
                block_bad: FullBlock = recursive_replace(
                    blocks[-1],
                    "foliage_transaction_block.timestamp",
                    blocks[0].foliage_transaction_block.timestamp - 10,
                )
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage.foliage_transaction_block_hash", block_bad.foliage_transaction_block.get_hash()
                )
                new_m = block_bad.foliage.foliage_transaction_block_hash
                new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.TIMESTAMP_TOO_FAR_IN_PAST)

                block_bad: FullBlock = recursive_replace(
                    blocks[-1],
                    "foliage_transaction_block.timestamp",
                    blocks[0].foliage_transaction_block.timestamp,
                )
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage.foliage_transaction_block_hash", block_bad.foliage_transaction_block.get_hash()
                )
                new_m = block_bad.foliage.foliage_transaction_block_hash
                new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.TIMESTAMP_TOO_FAR_IN_PAST)

                block_bad: FullBlock = recursive_replace(
                    blocks[-1],
                    "foliage_transaction_block.timestamp",
                    blocks[0].foliage_transaction_block.timestamp + 10000000,
                )
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage.foliage_transaction_block_hash", block_bad.foliage_transaction_block.get_hash()
                )
                new_m = block_bad.foliage.foliage_transaction_block_hash
                new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
                block_bad = recursive_replace(block_bad, "foliage.foliage_transaction_block_signature", new_fbh_sig)
                await _validate_and_add_block(
                    empty_blockchain, block_bad, expected_error=Err.TIMESTAMP_TOO_FAR_IN_FUTURE
                )
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])

    @pytest.mark.asyncio
    async def test_height(self, empty_blockchain, bt):
        # 27
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.height", 2)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_HEIGHT)

    @pytest.mark.asyncio
    async def test_height_genesis(self, empty_blockchain, bt):
        # 27
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.height", 1)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_PREV_BLOCK_HASH)

    @pytest.mark.asyncio
    async def test_weight(self, empty_blockchain, bt):
        # 28
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.weight", 22131)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_WEIGHT)

    @pytest.mark.asyncio
    async def test_weight_genesis(self, empty_blockchain, bt):
        # 28
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.weight", 0)
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_WEIGHT)

    @pytest.mark.asyncio
    async def test_bad_cc_ip_vdf(self, empty_blockchain, bt):
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

    @pytest.mark.asyncio
    async def test_bad_rc_ip_vdf(self, empty_blockchain, bt):
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

    @pytest.mark.asyncio
    async def test_bad_icc_ip_vdf(self, empty_blockchain, bt):
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

    @pytest.mark.asyncio
    async def test_reward_block_hash(self, empty_blockchain, bt):
        # 32
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])
        block_bad: FullBlock = recursive_replace(blocks[-1], "foliage.reward_block_hash", std_hash(b""))
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_REWARD_BLOCK_HASH)

    @pytest.mark.asyncio
    async def test_reward_block_hash_2(self, empty_blockchain, bt):
        # 33
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[0], "reward_chain_block.is_transaction_block", False)
        block_bad: FullBlock = recursive_replace(
            block_bad, "foliage.reward_block_hash", block_bad.reward_chain_block.get_hash()
        )
        await _validate_and_add_block(empty_blockchain, block_bad, expected_error=Err.INVALID_FOLIAGE_BLOCK_PRESENCE)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        # Test one which should not be a tx block
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if not blocks[-1].is_transaction_block():
                block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.is_transaction_block", True)
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage.reward_block_hash", block_bad.reward_chain_block.get_hash()
                )
                await _validate_and_add_block(
                    empty_blockchain, block_bad, expected_error=Err.INVALID_FOLIAGE_BLOCK_PRESENCE
                )
                return None
            await _validate_and_add_block(empty_blockchain, blocks[-1])


class TestPreValidation:
    @pytest.mark.asyncio
    async def test_pre_validation_fails_bad_blocks(self, empty_blockchain, bt):
        blocks = bt.get_consecutive_blocks(2)
        await _validate_and_add_block(empty_blockchain, blocks[0])

        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.total_iters", blocks[-1].reward_chain_block.total_iters + 1
        )
        res = await empty_blockchain.pre_validate_blocks_multiprocessing(
            [blocks[0], block_bad], {}, validate_signatures=True
        )
        assert res[0].error is None
        assert res[1].error is not None

    @pytest.mark.asyncio
    async def test_pre_validation(self, empty_blockchain, default_1000_blocks, bt):
        blocks = default_1000_blocks[:100]
        start = time.time()
        n_at_a_time = min(multiprocessing.cpu_count(), 32)
        times_pv = []
        times_rb = []
        for i in range(0, len(blocks), n_at_a_time):
            end_i = min(i + n_at_a_time, len(blocks))
            blocks_to_validate = blocks[i:end_i]
            start_pv = time.time()
            res = await empty_blockchain.pre_validate_blocks_multiprocessing(
                blocks_to_validate, {}, validate_signatures=True
            )
            end_pv = time.time()
            times_pv.append(end_pv - start_pv)
            assert res is not None
            for n in range(end_i - i):
                assert res[n] is not None
                assert res[n].error is None
                block = blocks_to_validate[n]
                start_rb = time.time()
                result, err, _ = await empty_blockchain.receive_block(block, res[n])
                end_rb = time.time()
                times_rb.append(end_rb - start_rb)
                assert err is None
                assert result == ReceiveBlockResult.NEW_PEAK
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

    @pytest.mark.asyncio
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
    async def test_conditions(self, empty_blockchain, opcode, with_garbage, bt):
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
            genesis_timestamp=10000,
            time_per_block=10,
        )
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        await _validate_and_add_block(empty_blockchain, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx1: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
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

        conditions = {opcode: [ConditionWithArgs(opcode, args + ([b"garbage"] if with_garbage else []))]}

        tx2: SpendBundle = wt.generate_signed_transaction(10, wt.get_new_puzzlehash(), coin1, condition_dic=conditions)
        assert coin1 in tx2.removals()

        bundles = SpendBundle.aggregate([tx1, tx2])
        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=bundles,
            time_per_block=10,
        )

        pre_validation_results: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
            [blocks[-1]], {}, validate_signatures=False
        )
        # Ignore errors from pre-validation, we are testing block_body_validation
        repl_preval_results = replace(pre_validation_results[0], error=None, required_iters=uint64(1))
        code, err, state_change = await b.receive_block(blocks[-1], repl_preval_results)
        assert code == ReceiveBlockResult.NEW_PEAK
        assert err is None
        assert state_change.fork_height == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("opcode", [ConditionOpcode.AGG_SIG_ME, ConditionOpcode.AGG_SIG_UNSAFE])
    @pytest.mark.parametrize(
        "with_garbage,expected",
        [
            (True, (ReceiveBlockResult.INVALID_BLOCK, Err.INVALID_CONDITION, None)),
            (False, (ReceiveBlockResult.NEW_PEAK, None, 2)),
        ],
    )
    async def test_aggsig_garbage(self, empty_blockchain, opcode, with_garbage, expected, bt):
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
            genesis_timestamp=10000,
            time_per_block=10,
        )
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        await _validate_and_add_block(empty_blockchain, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        tx1: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
        coin1: Coin = tx1.additions()[0]
        secret_key = wt.get_private_key_for_puzzle_hash(coin1.puzzle_hash)
        synthetic_secret_key = calculate_synthetic_secret_key(secret_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        public_key = synthetic_secret_key.get_g1()

        args = [public_key, b"msg"] + ([b"garbage"] if with_garbage else [])
        conditions = {opcode: [ConditionWithArgs(opcode, args)]}

        tx2: SpendBundle = wt.generate_signed_transaction(10, wt.get_new_puzzlehash(), coin1, condition_dic=conditions)
        assert coin1 in tx2.removals()

        bundles = SpendBundle.aggregate([tx1, tx2])
        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=bundles,
            time_per_block=10,
        )

        pre_validation_results: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
            [blocks[-1]], {}, validate_signatures=False
        )
        # Ignore errors from pre-validation, we are testing block_body_validation
        repl_preval_results = replace(pre_validation_results[0], error=None, required_iters=uint64(1))
        res, error, state_change = await b.receive_block(blocks[-1], repl_preval_results)
        assert (res, error, state_change.fork_height if state_change else None) == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "opcode,lock_value,expected,with_garbage",
        [
            (ConditionOpcode.ASSERT_SECONDS_RELATIVE, -2, ReceiveBlockResult.NEW_PEAK, False),
            (ConditionOpcode.ASSERT_SECONDS_RELATIVE, -1, ReceiveBlockResult.NEW_PEAK, False),
            (ConditionOpcode.ASSERT_SECONDS_RELATIVE, 0, ReceiveBlockResult.NEW_PEAK, False),
            (ConditionOpcode.ASSERT_SECONDS_RELATIVE, 1, ReceiveBlockResult.INVALID_BLOCK, False),
            (ConditionOpcode.ASSERT_HEIGHT_RELATIVE, -2, ReceiveBlockResult.NEW_PEAK, False),
            (ConditionOpcode.ASSERT_HEIGHT_RELATIVE, -1, ReceiveBlockResult.NEW_PEAK, False),
            (ConditionOpcode.ASSERT_HEIGHT_RELATIVE, 0, ReceiveBlockResult.INVALID_BLOCK, False),
            (ConditionOpcode.ASSERT_HEIGHT_RELATIVE, 1, ReceiveBlockResult.INVALID_BLOCK, False),
            (ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, 2, ReceiveBlockResult.NEW_PEAK, False),
            (ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, 3, ReceiveBlockResult.INVALID_BLOCK, False),
            (ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, 4, ReceiveBlockResult.INVALID_BLOCK, False),
            # genesis timestamp is 10000 and each block is 10 seconds
            (ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, 10029, ReceiveBlockResult.NEW_PEAK, False),
            (ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, 10030, ReceiveBlockResult.NEW_PEAK, False),
            (ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, 10031, ReceiveBlockResult.INVALID_BLOCK, False),
            (ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, 10032, ReceiveBlockResult.INVALID_BLOCK, False),
            # additional garbage at the end of parameters
            (ConditionOpcode.ASSERT_SECONDS_RELATIVE, 0, ReceiveBlockResult.NEW_PEAK, True),
            (ConditionOpcode.ASSERT_HEIGHT_RELATIVE, -1, ReceiveBlockResult.NEW_PEAK, True),
            (ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, 2, ReceiveBlockResult.NEW_PEAK, True),
            (ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, 10029, ReceiveBlockResult.NEW_PEAK, True),
        ],
    )
    async def test_ephemeral_timelock(self, empty_blockchain, opcode, lock_value, expected, with_garbage, bt):
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            3,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=bt.pool_ph,
            pool_reward_puzzle_hash=bt.pool_ph,
            genesis_timestamp=10000,
            time_per_block=10,
        )
        await _validate_and_add_block(empty_blockchain, blocks[0])
        await _validate_and_add_block(empty_blockchain, blocks[1])
        await _validate_and_add_block(empty_blockchain, blocks[2])

        wt: WalletTool = bt.get_pool_wallet_tool()

        conditions = {
            opcode: [ConditionWithArgs(opcode, [int_to_bytes(lock_value)] + ([b"garbage"] if with_garbage else []))]
        }

        tx1: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
        coin1: Coin = tx1.additions()[0]
        tx2: SpendBundle = wt.generate_signed_transaction(10, wt.get_new_puzzlehash(), coin1, condition_dic=conditions)
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

        pre_validation_results: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
            [blocks[-1]], {}, validate_signatures=True
        )
        assert pre_validation_results is not None
        assert (await b.receive_block(blocks[-1], pre_validation_results[0]))[0] == expected

        if expected == ReceiveBlockResult.NEW_PEAK:
            # ensure coin1 was in fact spent
            c = await b.coin_store.get_coin_record(coin1.name())
            assert c is not None and c.spent
            # ensure coin2 was NOT spent
            c = await b.coin_store.get_coin_record(coin2.name())
            assert c is not None and not c.spent

    @pytest.mark.asyncio
    async def test_not_tx_block_but_has_data(self, empty_blockchain, bt):
        # 1
        blocks = bt.get_consecutive_blocks(1)
        while blocks[-1].foliage_transaction_block is not None:
            await _validate_and_add_block(empty_blockchain, blocks[-1])
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        original_block: FullBlock = blocks[-1]

        block = recursive_replace(original_block, "transactions_generator", SerializedProgram())
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

    @pytest.mark.asyncio
    async def test_tx_block_missing_data(self, empty_blockchain, bt):
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

    @pytest.mark.asyncio
    async def test_invalid_transactions_info_hash(self, empty_blockchain, bt):
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
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block = recursive_replace(block, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block, expected_error=Err.INVALID_TRANSACTIONS_INFO_HASH)

    @pytest.mark.asyncio
    async def test_invalid_transactions_block_hash(self, empty_blockchain, bt):
        # 4
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])
        h = std_hash(b"")
        block = recursive_replace(blocks[-1], "foliage.foliage_transaction_block_hash", h)
        new_m = block.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block = recursive_replace(block, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block, expected_error=Err.INVALID_FOLIAGE_BLOCK_HASH)

    @pytest.mark.asyncio
    async def test_invalid_reward_claims(self, empty_blockchain, bt):
        # 5
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks[0])
        block: FullBlock = blocks[-1]

        # Too few
        assert block.transactions_info
        too_few_reward_claims = block.transactions_info.reward_claims_incorporated[:-1]
        block_2: FullBlock = recursive_replace(
            block, "transactions_info.reward_claims_incorporated", too_few_reward_claims
        )
        assert block_2.transactions_info
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )

        assert block_2.foliage_transaction_block
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_REWARD_COINS, skip_prevalidation=True)

        # Too many
        h = std_hash(b"")
        too_many_reward_claims = block.transactions_info.reward_claims_incorporated + [
            Coin(h, h, too_few_reward_claims[0].amount)
        ]
        block_2 = recursive_replace(block, "transactions_info.reward_claims_incorporated", too_many_reward_claims)
        assert block_2.transactions_info
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_REWARD_COINS, skip_prevalidation=True)

        # Duplicates
        duplicate_reward_claims = block.transactions_info.reward_claims_incorporated + [
            block.transactions_info.reward_claims_incorporated[-1]
        ]
        block_2 = recursive_replace(block, "transactions_info.reward_claims_incorporated", duplicate_reward_claims)
        assert block_2.transactions_info
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_REWARD_COINS, skip_prevalidation=True)

    @pytest.mark.asyncio
    async def test_invalid_transactions_generator_hash(self, empty_blockchain, bt):
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
        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
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
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)
        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_TRANSACTIONS_GENERATOR_HASH)

    @pytest.mark.asyncio
    async def test_invalid_transactions_ref_list(self, empty_blockchain, bt):
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
        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
        blocks = bt.get_consecutive_blocks(5, block_list_input=blocks, guarantee_transaction_block=False)
        for block in blocks[-5:]:
            await _validate_and_add_block(b, block)

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1])
        generator_arg = detect_potential_template_generator(blocks[-1].height, blocks[-1].transactions_generator)
        assert generator_arg is not None

        blocks = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            transaction_data=tx,
            previous_generator=generator_arg,
        )
        block = blocks[-1]
        assert len(block.transactions_generator_ref_list) > 0

        block_2 = recursive_replace(block, "transactions_info.generator_refs_root", bytes([1] * 32))
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(
            b, block_2, expected_error=Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT, skip_prevalidation=True
        )

        # Too many heights
        block_2 = recursive_replace(block, "transactions_generator_ref_list", [block.height - 2, block.height - 1])
        # Fails preval
        await _validate_and_add_block(b, block_2, expected_error=Err.FAILED_GETTING_GENERATOR_MULTIPROCESSING)
        # Fails receive_block
        await _validate_and_add_block_multi_error(
            b,
            block_2,
            [Err.GENERATOR_REF_HAS_NO_GENERATOR, Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT],
            skip_prevalidation=True,
        )

        # Not tx block
        for h in range(0, block.height - 1):
            block_2 = recursive_replace(block, "transactions_generator_ref_list", [h])
            await _validate_and_add_block(b, block_2, expected_error=Err.FAILED_GETTING_GENERATOR_MULTIPROCESSING)
            await _validate_and_add_block_multi_error(
                b,
                block_2,
                [Err.GENERATOR_REF_HAS_NO_GENERATOR, Err.INVALID_TRANSACTIONS_GENERATOR_REFS_ROOT],
                skip_prevalidation=True,
            )

    @pytest.mark.asyncio
    async def test_cost_exceeds_max(self, empty_blockchain, softfork_height, bt):
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

        condition_dict = {ConditionOpcode.CREATE_COIN: []}
        for i in range(7000):
            output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt.pool_ph, int_to_bytes(i)])
            condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0], condition_dic=condition_dict
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )

        block_generator: BlockGenerator = BlockGenerator(blocks[-1].transactions_generator, [], [])
        npc_result = get_name_puzzle_conditions(
            block_generator,
            b.constants.MAX_BLOCK_COST_CLVM * 1000,
            cost_per_byte=b.constants.COST_PER_BYTE,
            mempool_mode=False,
            height=softfork_height,
        )
        err = (await b.receive_block(blocks[-1], PreValidationResult(None, uint64(1), npc_result, True)))[1]
        assert err in [Err.BLOCK_COST_EXCEEDS_MAX]

        results: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
            [blocks[-1]], {}, validate_signatures=False
        )
        assert results is not None
        assert Err(results[0].error) == Err.BLOCK_COST_EXCEEDS_MAX

    @pytest.mark.asyncio
    async def test_clvm_must_not_fail(self, empty_blockchain, bt):
        # 8
        pass

    @pytest.mark.asyncio
    async def test_invalid_cost_in_block(self, empty_blockchain, softfork_height, bt):
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

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]

        # zero
        block_2: FullBlock = recursive_replace(block, "transactions_info.cost", uint64(0))
        assert block_2.transactions_info
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        block_generator: BlockGenerator = BlockGenerator(block_2.transactions_generator, [], [])
        npc_result = get_name_puzzle_conditions(
            block_generator,
            min(b.constants.MAX_BLOCK_COST_CLVM * 1000, block.transactions_info.cost),
            cost_per_byte=b.constants.COST_PER_BYTE,
            mempool_mode=False,
            height=softfork_height,
        )
        result, err, _ = await b.receive_block(block_2, PreValidationResult(None, uint64(1), npc_result, False))
        assert err == Err.INVALID_BLOCK_COST

        # too low
        block_2: FullBlock = recursive_replace(block, "transactions_info.cost", uint64(1))
        assert block_2.transactions_info
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        block_generator: BlockGenerator = BlockGenerator(block_2.transactions_generator, [], [])
        npc_result = get_name_puzzle_conditions(
            block_generator,
            min(b.constants.MAX_BLOCK_COST_CLVM * 1000, block.transactions_info.cost),
            cost_per_byte=b.constants.COST_PER_BYTE,
            mempool_mode=False,
            height=softfork_height,
        )
        result, err, _ = await b.receive_block(block_2, PreValidationResult(None, uint64(1), npc_result, False))
        assert err == Err.INVALID_BLOCK_COST

        # too high
        block_2: FullBlock = recursive_replace(block, "transactions_info.cost", uint64(1000000))
        assert block_2.transactions_info
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        block_generator: BlockGenerator = BlockGenerator(block_2.transactions_generator, [], [])
        npc_result = get_name_puzzle_conditions(
            block_generator,
            min(b.constants.MAX_BLOCK_COST_CLVM * 1000, block.transactions_info.cost),
            cost_per_byte=b.constants.COST_PER_BYTE,
            mempool_mode=False,
            height=softfork_height,
        )

        result, err, _ = await b.receive_block(block_2, PreValidationResult(None, uint64(1), npc_result, False))
        assert err == Err.INVALID_BLOCK_COST

        # when the CLVM program exceeds cost during execution, it will fail with
        # a general runtime error. The previous test tests this.

    @pytest.mark.asyncio
    async def test_max_coin_amount(self, db_version, bt):
        # 10
        # TODO: fix, this is not reaching validation. Because we can't create a block with such amounts due to uint64
        # limit in Coin
        pass
        #
        # with TempKeyring() as keychain:
        #     new_test_constants = test_constants.replace(
        #         **{"GENESIS_PRE_FARM_POOL_PUZZLE_HASH": bt.pool_ph, "GENESIS_PRE_FARM_FARMER_PUZZLE_HASH": bt.pool_ph}
        #     )
        #     b, db_wrapper, db_path = await create_blockchain(new_test_constants, db_version)
        #     bt_2 = await create_block_tools_async(constants=new_test_constants, keychain=keychain)
        #     bt_2.constants = bt_2.constants.replace(
        #         **{"GENESIS_PRE_FARM_POOL_PUZZLE_HASH": bt.pool_ph, "GENESIS_PRE_FARM_FARMER_PUZZLE_HASH": bt.pool_ph}
        #     )
        #     blocks = bt_2.get_consecutive_blocks(
        #         3,
        #         guarantee_transaction_block=True,
        #         farmer_reward_puzzle_hash=bt.pool_ph,
        #         pool_reward_puzzle_hash=bt.pool_ph,
        #     )
        #     assert (await b.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        #     assert (await b.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        #     assert (await b.receive_block(blocks[2]))[0] == ReceiveBlockResult.NEW_PEAK

        #     wt: WalletTool = bt_2.get_pool_wallet_tool()

        #     condition_dict = {ConditionOpcode.CREATE_COIN: []}
        #     output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt_2.pool_ph, int_to_bytes(2 ** 64)])
        #     condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        #     tx: SpendBundle = wt.generate_signed_transaction_multiple_coins(
        #         10,
        #         wt.get_new_puzzlehash(),
        #         list(blocks[1].get_included_reward_coins()),
        #         condition_dic=condition_dict,
        #     )
        #     try:
        #         blocks = bt_2.get_consecutive_blocks(
        #             1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        #         )
        #         assert False
        #     except Exception as e:
        #         pass
        #     await db_wrapper.close()
        #     b.shut_down()
        #     db_path.unlink()

    @pytest.mark.asyncio
    async def test_invalid_merkle_roots(self, empty_blockchain, bt):
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

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]

        merkle_set = MerkleSet()
        # additions
        block_2 = recursive_replace(block, "foliage_transaction_block.additions_root", merkle_set.get_root())
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(empty_blockchain, block_2, expected_error=Err.BAD_ADDITION_ROOT)

        # removals
        merkle_set.add_already_hashed(std_hash(b"1"))
        block_2 = recursive_replace(block, "foliage_transaction_block.removals_root", merkle_set.get_root())
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(empty_blockchain, block_2, expected_error=Err.BAD_REMOVAL_ROOT)

    @pytest.mark.asyncio
    async def test_invalid_filter(self, empty_blockchain, bt):
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

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
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
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_TRANSACTIONS_FILTER_HASH)

    @pytest.mark.asyncio
    async def test_duplicate_outputs(self, empty_blockchain, bt):
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

        condition_dict = {ConditionOpcode.CREATE_COIN: []}
        for i in range(2):
            output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt.pool_ph, int_to_bytes(1)])
            condition_dict[ConditionOpcode.CREATE_COIN].append(output)

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0], condition_dic=condition_dict
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1], expected_error=Err.DUPLICATE_OUTPUT)

    @pytest.mark.asyncio
    async def test_duplicate_removals(self, empty_blockchain, bt):
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

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
        tx_2: SpendBundle = wt.generate_signed_transaction(
            11, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
        agg = SpendBundle.aggregate([tx, tx_2])

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=agg
        )
        await _validate_and_add_block(b, blocks[-1], expected_error=Err.DOUBLE_SPEND)

    @pytest.mark.asyncio
    async def test_double_spent_in_coin_store(self, empty_blockchain, bt):
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

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1])

        tx_2: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-2].get_included_reward_coins())[0]
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx_2
        )

        await _validate_and_add_block(b, blocks[-1], expected_error=Err.DOUBLE_SPEND)

    @pytest.mark.asyncio
    async def test_double_spent_in_reorg(self, empty_blockchain, bt):
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

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1])

        new_coin: Coin = tx.additions()[0]
        tx_2: SpendBundle = wt.generate_signed_transaction(10, wt.get_new_puzzlehash(), new_coin)
        # This is fine because coin exists
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx_2
        )
        await _validate_and_add_block(b, blocks[-1])
        blocks = bt.get_consecutive_blocks(5, block_list_input=blocks, guarantee_transaction_block=True)
        for block in blocks[-5:]:
            await _validate_and_add_block(b, block)

        blocks_reorg = bt.get_consecutive_blocks(2, block_list_input=blocks[:-7], guarantee_transaction_block=True)
        await _validate_and_add_block(b, blocks_reorg[-2], expected_result=ReceiveBlockResult.ADDED_AS_ORPHAN)
        await _validate_and_add_block(b, blocks_reorg[-1], expected_result=ReceiveBlockResult.ADDED_AS_ORPHAN)

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
        await _validate_and_add_block(b, blocks_reorg[-1], expected_result=ReceiveBlockResult.ADDED_AS_ORPHAN)

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
                b, block, expected_result=[ReceiveBlockResult.ADDED_AS_ORPHAN, ReceiveBlockResult.NEW_PEAK]
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
        tx_3: SpendBundle = wt.generate_signed_transaction(10, wt.get_new_puzzlehash(), farmer_coin)

        blocks_reorg = bt.get_consecutive_blocks(
            1, block_list_input=blocks_reorg, guarantee_transaction_block=True, transaction_data=tx_3
        )
        await _validate_and_add_block(b, blocks_reorg[-1])

        farmer_coin = await b.coin_store.get_coin_record(farmer_coin.name())
        assert first_coin is not None and farmer_coin.spent

    @pytest.mark.asyncio
    async def test_minting_coin(self, empty_blockchain, bt):
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

        spend = list(blocks[-1].get_included_reward_coins())[0]
        print("spend=", spend)
        # this create coin will spend all of the coin, so the 10 mojos below
        # will be "minted".
        output = ConditionWithArgs(ConditionOpcode.CREATE_COIN, [bt.pool_ph, int_to_bytes(spend.amount)])
        condition_dict = {ConditionOpcode.CREATE_COIN: [output]}

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), spend, condition_dic=condition_dict
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        await _validate_and_add_block(b, blocks[-1], expected_error=Err.MINTING_COIN)
        # 17 is tested in mempool tests

    @pytest.mark.asyncio
    async def test_max_coin_amount_fee(self):
        # 18 TODO: we can't create a block with such amounts due to uint64
        pass

    @pytest.mark.asyncio
    async def test_invalid_fees_in_block(self, empty_blockchain, bt):
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

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )
        block: FullBlock = blocks[-1]

        # wrong feees
        block_2: FullBlock = recursive_replace(block, "transactions_info.fees", uint64(1239))
        assert block_2.transactions_info
        block_2 = recursive_replace(
            block_2, "foliage_transaction_block.transactions_info_hash", block_2.transactions_info.get_hash()
        )
        assert block_2.foliage_transaction_block
        block_2 = recursive_replace(
            block_2, "foliage.foliage_transaction_block_hash", block_2.foliage_transaction_block.get_hash()
        )
        new_m = block_2.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, block.reward_chain_block.proof_of_space.plot_public_key)
        block_2 = recursive_replace(block_2, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        await _validate_and_add_block(b, block_2, expected_error=Err.INVALID_BLOCK_FEE_AMOUNT)

    @pytest.mark.asyncio
    async def test_invalid_agg_sig(self, empty_blockchain, bt):
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

        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[-1].get_included_reward_coins())[0]
        )
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=tx
        )

        last_block = recursive_replace(blocks[-1], "transactions_info.aggregated_signature", G2Element.generator())
        assert last_block.transactions_info
        last_block = recursive_replace(
            last_block, "foliage_transaction_block.transactions_info_hash", last_block.transactions_info.get_hash()
        )
        assert last_block.foliage_transaction_block
        last_block = recursive_replace(
            last_block, "foliage.foliage_transaction_block_hash", last_block.foliage_transaction_block.get_hash()
        )
        new_m = last_block.foliage.foliage_transaction_block_hash
        new_fsb_sig = bt.get_plot_signature(new_m, last_block.reward_chain_block.proof_of_space.plot_public_key)
        last_block = recursive_replace(last_block, "foliage.foliage_transaction_block_signature", new_fsb_sig)

        # Bad signature fails during receive_block
        await _validate_and_add_block(b, last_block, expected_error=Err.BAD_AGGREGATE_SIGNATURE)

        # Bad signature also fails in prevalidation
        preval_results = await b.pre_validate_blocks_multiprocessing([last_block], {}, validate_signatures=True)
        assert preval_results is not None
        assert preval_results[0].error == Err.BAD_AGGREGATE_SIGNATURE.value


class TestReorgs:
    @pytest.mark.asyncio
    async def test_basic_reorg(self, empty_blockchain, bt):
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(15)

        for block in blocks:
            await _validate_and_add_block(b, block)
        assert b.get_peak().height == 14

        blocks_reorg_chain = bt.get_consecutive_blocks(7, blocks[:10], seed=b"2")
        for reorg_block in blocks_reorg_chain:
            if reorg_block.height < 10:
                await _validate_and_add_block(b, reorg_block, expected_result=ReceiveBlockResult.ALREADY_HAVE_BLOCK)
            elif reorg_block.height < 15:
                await _validate_and_add_block(b, reorg_block, expected_result=ReceiveBlockResult.ADDED_AS_ORPHAN)
            elif reorg_block.height >= 15:
                await _validate_and_add_block(b, reorg_block)
        assert b.get_peak().height == 16

    @pytest.mark.asyncio
    async def test_long_reorg(self, empty_blockchain, default_1500_blocks, test_long_reorg_blocks, bt):
        # Reorg longer than a difficulty adjustment
        # Also tests higher weight chain but lower height
        b = empty_blockchain
        num_blocks_chain_1 = 3 * test_constants.EPOCH_BLOCKS + test_constants.MAX_SUB_SLOT_BLOCKS + 10
        num_blocks_chain_2_start = test_constants.EPOCH_BLOCKS - 20

        assert num_blocks_chain_1 < 10000
        blocks = default_1500_blocks[:num_blocks_chain_1]

        for block in blocks:
            await _validate_and_add_block(b, block, skip_prevalidation=True)
        chain_1_height = b.get_peak().height
        chain_1_weight = b.get_peak().weight
        assert chain_1_height == (num_blocks_chain_1 - 1)

        # The reorg blocks will have less time between them (timestamp) and therefore will make difficulty go up
        # This means that the weight will grow faster, and we can get a heavier chain with lower height

        # If these assert fail, you probably need to change the fixture in test_long_reorg_blocks to create the
        # right amount of blocks at the right time
        assert test_long_reorg_blocks[num_blocks_chain_2_start - 1] == default_1500_blocks[num_blocks_chain_2_start - 1]
        assert test_long_reorg_blocks[num_blocks_chain_2_start] != default_1500_blocks[num_blocks_chain_2_start]

        for reorg_block in test_long_reorg_blocks:
            if reorg_block.height < num_blocks_chain_2_start:
                await _validate_and_add_block(
                    b, reorg_block, expected_result=ReceiveBlockResult.ALREADY_HAVE_BLOCK, skip_prevalidation=True
                )
            elif reorg_block.weight <= chain_1_weight:
                await _validate_and_add_block_multi_result(
                    b,
                    reorg_block,
                    [ReceiveBlockResult.ADDED_AS_ORPHAN, ReceiveBlockResult.ALREADY_HAVE_BLOCK],
                    skip_prevalidation=True,
                )
            elif reorg_block.weight > chain_1_weight:
                assert reorg_block.height < chain_1_height
                await _validate_and_add_block(b, reorg_block, skip_prevalidation=True)

        assert b.get_peak().weight > chain_1_weight
        assert b.get_peak().height < chain_1_height

    @pytest.mark.asyncio
    async def test_long_compact_blockchain(self, empty_blockchain, default_2000_blocks_compact):
        b = empty_blockchain
        for block in default_2000_blocks_compact:
            await _validate_and_add_block(b, block, skip_prevalidation=True)
        assert b.get_peak().height == len(default_2000_blocks_compact) - 1

    @pytest.mark.asyncio
    async def test_reorg_from_genesis(self, empty_blockchain, bt):
        b = empty_blockchain

        blocks = bt.get_consecutive_blocks(15)

        for block in blocks:
            await _validate_and_add_block(b, block)
        assert b.get_peak().height == 14

        # Reorg to alternate chain that is 1 height longer
        blocks_reorg_chain = bt.get_consecutive_blocks(16, [], seed=b"2")
        for reorg_block in blocks_reorg_chain:
            if reorg_block.height < 15:
                await _validate_and_add_block_multi_result(
                    b,
                    reorg_block,
                    expected_result=[ReceiveBlockResult.ADDED_AS_ORPHAN, ReceiveBlockResult.ALREADY_HAVE_BLOCK],
                )
            elif reorg_block.height >= 15:
                await _validate_and_add_block(b, reorg_block)

        # Back to original chain
        blocks_reorg_chain_2 = bt.get_consecutive_blocks(3, blocks, seed=b"3")

        await _validate_and_add_block(b, blocks_reorg_chain_2[-3], expected_result=ReceiveBlockResult.ADDED_AS_ORPHAN)
        await _validate_and_add_block(b, blocks_reorg_chain_2[-2])
        await _validate_and_add_block(b, blocks_reorg_chain_2[-1])

        assert b.get_peak().height == 17

    @pytest.mark.asyncio
    async def test_reorg_transaction(self, empty_blockchain, bt):
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
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                spend_coin = coin
        spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, spend_coin)

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

    @pytest.mark.asyncio
    async def test_get_header_blocks_in_range_tx_filter(self, empty_blockchain, bt):
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
        tx: SpendBundle = wt.generate_signed_transaction(
            10, wt.get_new_puzzlehash(), list(blocks[2].get_included_reward_coins())[0]
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

    @pytest.mark.asyncio
    async def test_get_blocks_at(self, empty_blockchain, default_1000_blocks):
        b = empty_blockchain
        heights = []
        for block in default_1000_blocks[:200]:
            heights.append(block.height)
            await _validate_and_add_block(b, block)

        blocks = await b.get_block_records_at(heights, batch_size=2)
        assert blocks
        assert len(blocks) == 200
        assert blocks[-1].height == 199


@pytest.mark.asyncio
async def test_reorg_new_ref(empty_blockchain, bt):
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
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                all_coins.append(coin)
    spend_bundle_0 = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, all_coins.pop())
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
    assert b.get_peak().height == 19

    print("first chain done")

    # Make sure a ref back into the reorg chain itself works as expected

    blocks_reorg_chain = bt.get_consecutive_blocks(
        1,
        blocks[:10],
        seed=b"2",
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
    )
    spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, all_coins.pop())

    blocks_reorg_chain = bt.get_consecutive_blocks(
        2,
        blocks_reorg_chain,
        seed=b"2",
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        transaction_data=spend_bundle,
        guarantee_transaction_block=True,
    )

    spend_bundle2 = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, all_coins.pop())
    blocks_reorg_chain = bt.get_consecutive_blocks(
        4, blocks_reorg_chain, seed=b"2", previous_generator=[uint32(5), uint32(11)], transaction_data=spend_bundle2
    )
    blocks_reorg_chain = bt.get_consecutive_blocks(4, blocks_reorg_chain, seed=b"2")

    for i, block in enumerate(blocks_reorg_chain):
        fork_point_with_peak = None
        if i < 10:
            expected = ReceiveBlockResult.ALREADY_HAVE_BLOCK
        elif i < 20:
            expected = ReceiveBlockResult.ADDED_AS_ORPHAN
        else:
            expected = ReceiveBlockResult.NEW_PEAK
            fork_point_with_peak = uint32(1)
        await _validate_and_add_block(b, block, expected_result=expected, fork_point_with_peak=fork_point_with_peak)
    assert b.get_peak().height == 20


# this test doesn't reorg, but _reconsider_peak() is passed a stale
# "fork_height" to make it look like it's in a reorg, but all the same blocks
# are just added back.
@pytest.mark.asyncio
async def test_reorg_stale_fork_height(empty_blockchain, bt):
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
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                all_coins.append(coin)

    # Make sure a ref back into the reorg chain itself works as expected
    spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, all_coins.pop())

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
    spend_bundle2 = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, all_coins.pop())
    blocks = bt.get_consecutive_blocks(4, blocks, previous_generator=[uint32(5)], transaction_data=spend_bundle2)

    for block in blocks[:5]:
        await _validate_and_add_block(b, block, expected_result=ReceiveBlockResult.NEW_PEAK)

    # fake the fork_height to make every new block look like a reorg
    for block in blocks[5:]:
        await _validate_and_add_block(b, block, expected_result=ReceiveBlockResult.NEW_PEAK, fork_point_with_peak=2)
    assert b.get_peak().height == 13


@pytest.mark.asyncio
async def test_chain_failed_rollback(empty_blockchain, bt):
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
    assert b.get_peak().height == 19

    print("first chain done")

    # Make sure a ref back into the reorg chain itself works as expected

    all_coins = []
    for spend_block in blocks[:10]:
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                all_coins.append(coin)

    spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, all_coins.pop())

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
        await _validate_and_add_block(b, block, expected_result=ReceiveBlockResult.ADDED_AS_ORPHAN)

    # Incorrectly set the height as spent in DB to trigger an error
    print(f"{await b.coin_store.get_coin_record(spend_bundle.coin_spends[0].coin.name())}")
    print(spend_bundle.coin_spends[0].coin.name())
    # await b.coin_store._set_spent([spend_bundle.coin_spends[0].coin.name()], 8)
    await b.coin_store.rollback_to_block(2)
    print(f"{await b.coin_store.get_coin_record(spend_bundle.coin_spends[0].coin.name())}")

    with pytest.raises(ValueError):
        await _validate_and_add_block(b, blocks_reorg_chain[-1])

    assert b.get_peak().height == 19


@pytest.mark.asyncio
async def test_reorg_flip_flop(empty_blockchain, bt):
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
        for coin in list(spend_block.get_included_reward_coins()):
            if coin.puzzle_hash == coinbase_puzzlehash:
                all_coins.append(coin)

    # this is a transaction block at height 10
    spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, all_coins.pop())
    chain_a = bt.get_consecutive_blocks(
        5,
        chain_a,
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
        transaction_data=spend_bundle,
        guarantee_transaction_block=True,
    )

    spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, all_coins.pop())
    chain_a = bt.get_consecutive_blocks(
        5,
        chain_a,
        previous_generator=[uint32(10)],
        transaction_data=spend_bundle,
        guarantee_transaction_block=True,
    )

    spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, all_coins.pop())
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
    spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, all_coins.pop())

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

    spend_bundle = wallet_a.generate_signed_transaction(1000, receiver_puzzlehash, all_coins.pop())
    chain_b = bt.get_consecutive_blocks(
        10, chain_b, seed=b"2", previous_generator=[uint32(15)], transaction_data=spend_bundle
    )

    assert len(chain_a) == len(chain_b)

    counter = 0
    for b1, b2 in zip(chain_a, chain_b):

        # alternate the order we add blocks from the two chains, to ensure one
        # chain overtakes the other one in weight every other time
        if counter % 2 == 0:
            block1, block2 = b2, b1
        else:
            block1, block2 = b1, b2
        counter += 1

        fork_height = 2 if counter > 3 else None

        preval: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
            [block1], {}, validate_signatures=False
        )
        result, err, _ = await b.receive_block(block1, preval[0], fork_point_with_peak=fork_height)
        assert not err
        preval: List[PreValidationResult] = await b.pre_validate_blocks_multiprocessing(
            [block2], {}, validate_signatures=False
        )
        result, err, _ = await b.receive_block(block2, preval[0], fork_point_with_peak=fork_height)
        assert not err

    assert b.get_peak().height == 39

    chain_b = bt.get_consecutive_blocks(
        10,
        chain_b,
        seed=b"2",
        farmer_reward_puzzle_hash=coinbase_puzzlehash,
        pool_reward_puzzle_hash=receiver_puzzlehash,
    )

    for block in chain_b[40:]:
        await _validate_and_add_block(b, block)
