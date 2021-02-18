# flake8: noqa: F811, F401
import asyncio
import multiprocessing
import time
from dataclasses import replace
import logging
from secrets import token_bytes

import pytest
from blspy import AugSchemeMPL, G2Element

from src.consensus.blockchain import ReceiveBlockResult
from src.types.blockchain_format.classgroup import ClassgroupElement
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.blockchain_format.slots import InfusedChallengeChainSubSlot
from src.types.unfinished_block import UnfinishedBlock
from src.types.blockchain_format.vdf import VDFInfo, VDFProof
from src.util.block_tools import get_vdf_info_and_proof
from src.util.errors import Err
from src.util.hash import std_hash
from src.util.ints import uint64, uint8
from src.util.wallet_tools import WalletTool
from tests.recursive_replace import recursive_replace
from tests.setup_nodes import test_constants, bt
from tests.core.fixtures import empty_blockchain  # noqa: F401
from tests.core.fixtures import default_1000_blocks  # noqa: F401
from tests.core.fixtures import default_400_blocks  # noqa: F401
from tests.core.fixtures import default_10000_blocks  # noqa: F401

log = logging.getLogger(__name__)
bad_element = ClassgroupElement.from_bytes(b"\x00")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


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
    async def test_non_overflow_genesis(self, empty_blockchain):
        assert empty_blockchain.get_peak() is None
        genesis = bt.get_consecutive_blocks(1, force_overflow=False)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK
        assert empty_blockchain.get_peak().height == 0

    @pytest.mark.asyncio
    async def test_overflow_genesis(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(1, force_overflow=True)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_genesis_empty_slots(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(1, force_overflow=False, skip_slots=30)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_overflow_genesis_empty_slots(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(1, force_overflow=True, skip_slots=3)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_genesis_validate_1(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(1, force_overflow=False)[0]
        bad_prev = bytes([1] * 32)
        genesis = recursive_replace(genesis, "foliage.prev_block_hash", bad_prev)
        result, err, _ = await empty_blockchain.receive_block(genesis)
        assert err == Err.INVALID_PREV_BLOCK_HASH


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
                result, err, _ = await empty_blockchain.receive_block(block_bad)
                assert err == Err.INVALID_NEW_SUB_SLOT_ITERS
                new_finished_ss_2 = recursive_replace(
                    block.finished_sub_slots[0],
                    "challenge_chain.new_difficulty",
                    uint64(10000000),
                )
                block_bad_2 = recursive_replace(
                    block, "finished_sub_slots", [new_finished_ss_2] + block.finished_sub_slots[1:]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_2)
                assert err == Err.INVALID_NEW_DIFFICULTY

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
                block_bad_3 = recursive_replace(
                    block, "finished_sub_slots", [new_finished_ss_3] + block.finished_sub_slots[1:]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_3)
                assert err == Err.INVALID_SUB_EPOCH_SUMMARY

                # 3d
                new_finished_ss_4 = recursive_replace(
                    block.finished_sub_slots[0],
                    "challenge_chain.subepoch_summary_hash",
                    None,
                )
                new_finished_ss_4 = recursive_replace(
                    new_finished_ss_4,
                    "reward_chain.challenge_chain_sub_slot_hash",
                    new_finished_ss_4.challenge_chain.get_hash(),
                )
                block_bad_4 = recursive_replace(
                    block, "finished_sub_slots", [new_finished_ss_4] + block.finished_sub_slots[1:]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_4)
                assert err == Err.INVALID_SUB_EPOCH_SUMMARY or err == Err.INVALID_NEW_SUB_SLOT_ITERS

            result, err, _ = await empty_blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK
            log.info(
                f"Added block {block.height} total iters {block.total_iters} "
                f"new slot? {len(block.finished_sub_slots)}"
            )
        assert empty_blockchain.get_peak().height == len(blocks) - 1

    @pytest.mark.asyncio
    async def test_unfinished_blocks(self, empty_blockchain):
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(2)
        for block in blocks[:-1]:
            result, err, _ = await blockchain.receive_block(block)
            assert result == ReceiveBlockResult.NEW_PEAK
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
        )
        _, err = await blockchain.validate_unfinished_block(unf, False)
        assert err is None
        result, err, _ = await blockchain.receive_block(block)
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
        )
        _, err = await blockchain.validate_unfinished_block(unf, False)
        assert err is None

    @pytest.mark.asyncio
    async def test_empty_genesis(self, empty_blockchain):
        blockchain = empty_blockchain
        for block in bt.get_consecutive_blocks(2, skip_slots=3):
            result, err, _ = await blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_empty_slots_non_genesis(self, empty_blockchain):
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(10)
        for block in blocks:
            result, err, _ = await blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK

        blocks = bt.get_consecutive_blocks(10, skip_slots=2, block_list_input=blocks)
        for block in blocks[10:]:
            result, err, _ = await blockchain.receive_block(block)
            assert err is None
        assert blockchain.get_peak().height == 19

    @pytest.mark.asyncio
    async def test_one_sb_per_slot(self, empty_blockchain):
        blockchain = empty_blockchain
        num_blocks = 20
        blocks = []
        for i in range(num_blocks):
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1)
            result, err, _ = await blockchain.receive_block(blocks[-1])
            assert result == ReceiveBlockResult.NEW_PEAK
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_all_overflow(self, empty_blockchain):
        blockchain = empty_blockchain
        num_rounds = 5
        blocks = []
        num_blocks = 0
        for i in range(1, num_rounds):
            num_blocks += i
            blocks = bt.get_consecutive_blocks(i, block_list_input=blocks, skip_slots=1, force_overflow=True)
            for block in blocks[-i:]:
                result, err, _ = await blockchain.receive_block(block)
                assert result == ReceiveBlockResult.NEW_PEAK
                assert err is None
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_unf_block_overflow(self, empty_blockchain):
        blockchain = empty_blockchain

        blocks = []
        while True:
            # This creates an overflow block, then a normal block, and then an overflow in the next sub-slot
            # blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, force_overflow=True)
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, force_overflow=True)

            await blockchain.receive_block(blocks[-2])

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
                )
                _, error = await blockchain.validate_unfinished_block(unf, skip_overflow_ss_validation=True)
                assert error is None
                return

            await blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_one_sb_per_two_slots(self, empty_blockchain):
        blockchain = empty_blockchain
        num_blocks = 20
        blocks = []
        for i in range(num_blocks):  # Same thing, but 2 sub-slots per block
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=2)
            result, err, _ = await blockchain.receive_block(blocks[-1])
            assert result == ReceiveBlockResult.NEW_PEAK
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_one_sb_per_five_slots(self, empty_blockchain):
        blockchain = empty_blockchain
        num_blocks = 10
        blocks = []
        for i in range(num_blocks):  # Same thing, but 5 sub-slots per block
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=5)
            result, err, _ = await blockchain.receive_block(blocks[-1])
            assert result == ReceiveBlockResult.NEW_PEAK
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_basic_chain_overflow(self, empty_blockchain):
        blocks = bt.get_consecutive_blocks(5, force_overflow=True)
        for block in blocks:
            result, err, _ = await empty_blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK
        assert empty_blockchain.get_peak().height == len(blocks) - 1

    @pytest.mark.asyncio
    async def test_one_sb_per_two_slots_force_overflow(self, empty_blockchain):
        blockchain = empty_blockchain
        num_blocks = 10
        blocks = []
        for i in range(num_blocks):
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=2, force_overflow=True)
            result, err, _ = await blockchain.receive_block(blocks[-1])
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_invalid_prev(self, empty_blockchain):
        # 1
        blocks = bt.get_consecutive_blocks(2, force_overflow=False)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_1_bad = recursive_replace(blocks[-1], "foliage.prev_block_hash", bytes([0] * 32))

        result, err, _ = await empty_blockchain.receive_block(block_1_bad)
        assert result == ReceiveBlockResult.DISCONNECTED_BLOCK

    @pytest.mark.asyncio
    async def test_invalid_pospace(self, empty_blockchain):
        # 2
        blocks = bt.get_consecutive_blocks(2, force_overflow=False)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_1_bad = recursive_replace(blocks[-1], "reward_chain_block.proof_of_space.proof", bytes([0] * 32))

        result, err, _ = await empty_blockchain.receive_block(block_1_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert err == Err.INVALID_POSPACE

    @pytest.mark.asyncio
    async def test_invalid_sub_slot_challenge_hash_genesis(self, empty_blockchain):
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

        result, err, _ = await empty_blockchain.receive_block(block_0_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert err == Err.INVALID_PREV_CHALLENGE_SLOT_HASH

    @pytest.mark.asyncio
    async def test_invalid_sub_slot_challenge_hash_non_genesis(self, empty_blockchain):
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

        _, _, _ = await empty_blockchain.receive_block(blocks[0])
        result, err, _ = await empty_blockchain.receive_block(block_1_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert err == Err.INVALID_PREV_CHALLENGE_SLOT_HASH

    @pytest.mark.asyncio
    async def test_invalid_sub_slot_challenge_hash_empty_ss(self, empty_blockchain):
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

        _, _, _ = await empty_blockchain.receive_block(blocks[0])
        result, err, _ = await empty_blockchain.receive_block(block_1_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert err == Err.INVALID_PREV_CHALLENGE_SLOT_HASH

    @pytest.mark.asyncio
    async def test_genesis_no_icc(self, empty_blockchain):
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

        result, err, _ = await empty_blockchain.receive_block(block_0_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert err == Err.SHOULD_NOT_HAVE_ICC

    @pytest.mark.asyncio
    async def test_invalid_icc_sub_slot_vdf(self, empty_blockchain):
        blocks = bt.get_consecutive_blocks(10)
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
                result, err, _ = await empty_blockchain.receive_block(block_bad)
                assert err == Err.INVALID_ICC_EOS_VDF

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
                block_bad_2 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_2]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_2)
                assert err == Err.INVALID_ICC_EOS_VDF

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
                result, err, _ = await empty_blockchain.receive_block(block_bad_3)
                assert err == Err.INVALID_ICC_EOS_VDF

                # Bad proof
                new_finished_ss_5 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "proofs.infused_challenge_chain_slot_proof",
                    VDFProof(uint8(0), b"1239819023890"),
                )
                block_bad_5 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_5]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_5)
                assert err == Err.INVALID_ICC_EOS_VDF

            result, err, _ = await empty_blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_invalid_icc_into_cc(self, empty_blockchain):
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(1)
        assert (await blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
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
                result, err, _ = await blockchain.receive_block(block_bad)
                assert err == Err.INVALID_ICC_HASH_CC

                # 2i
                new_finished_ss_bad_rc = recursive_replace(
                    block.finished_sub_slots[-1],
                    "reward_chain",
                    replace(block.finished_sub_slots[-1].reward_chain, infused_challenge_chain_sub_slot_hash=None),
                )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_bad_rc]
                )
                result, err, _ = await blockchain.receive_block(block_bad)
                assert err == Err.INVALID_ICC_HASH_RC
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
                result, err, _ = await blockchain.receive_block(block_bad)
                assert err == Err.INVALID_ICC_HASH_CC

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
                result, err, _ = await blockchain.receive_block(block_bad)
                assert err == Err.INVALID_ICC_HASH_RC

            # Finally, add the block properly
            result, err, _ = await blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_empty_slot_no_ses(self, empty_blockchain):
        # 2l
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(1)
        assert (await blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=4)

        new_finished_ss = recursive_replace(
            blocks[-1].finished_sub_slots[-1],
            "challenge_chain",
            replace(blocks[-1].finished_sub_slots[-1].challenge_chain, subepoch_summary_hash=std_hash(b"0")),
        )
        block_bad = recursive_replace(
            blocks[-1], "finished_sub_slots", blocks[-1].finished_sub_slots[:-1] + [new_finished_ss]
        )
        result, err, _ = await blockchain.receive_block(block_bad)
        assert err == Err.INVALID_SUB_EPOCH_SUMMARY_HASH

    @pytest.mark.asyncio
    async def test_empty_sub_slots_epoch(self, empty_blockchain):
        # 2m
        # Tests adding an empty sub slot after the sub-epoch / epoch.
        # Also tests overflow block in epoch
        blocks_base = bt.get_consecutive_blocks(test_constants.EPOCH_BLOCKS)
        blocks_1 = bt.get_consecutive_blocks(1, block_list_input=blocks_base, force_overflow=True)
        blocks_2 = bt.get_consecutive_blocks(1, skip_slots=1, block_list_input=blocks_base, force_overflow=True)
        blocks_3 = bt.get_consecutive_blocks(1, skip_slots=2, block_list_input=blocks_base, force_overflow=True)
        blocks_4 = bt.get_consecutive_blocks(1, block_list_input=blocks_base)
        for block in blocks_base:
            result, err, _ = await empty_blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK
        for block in [blocks_1[-1], blocks_2[-1], blocks_3[-1], blocks_4[-1]]:
            result, err, _ = await empty_blockchain.receive_block(block)
            assert err is None

    @pytest.mark.asyncio
    async def test_wrong_cc_hash_rc(self, empty_blockchain):
        # 2o
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(1, skip_slots=1)
        blocks = bt.get_consecutive_blocks(1, skip_slots=1, block_list_input=blocks)
        assert (await blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        new_finished_ss = recursive_replace(
            blocks[-1].finished_sub_slots[-1],
            "reward_chain",
            replace(blocks[-1].finished_sub_slots[-1].reward_chain, challenge_chain_sub_slot_hash=bytes([3] * 32)),
        )
        block_1_bad = recursive_replace(
            blocks[-1], "finished_sub_slots", blocks[-1].finished_sub_slots[:-1] + [new_finished_ss]
        )

        result, err, _ = await blockchain.receive_block(block_1_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert err == Err.INVALID_CHALLENGE_SLOT_HASH_RC

    @pytest.mark.asyncio
    async def test_invalid_cc_sub_slot_vdf(self, empty_blockchain):
        # 2q
        blocks = bt.get_consecutive_blocks(10)
        for block in blocks:
            if len(block.finished_sub_slots):
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
                block_bad = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad)
                assert err == Err.INVALID_CC_EOS_VDF

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
                result, err, _ = await empty_blockchain.receive_block(block_bad_2)
                assert err == Err.INVALID_CC_EOS_VDF

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
                result, err, _ = await empty_blockchain.receive_block(block_bad_3)
                assert err == Err.INVALID_CC_EOS_VDF or err == Err.INVALID_PREV_CHALLENGE_SLOT_HASH

                # Bad proof
                new_finished_ss_5 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "proofs.challenge_chain_slot_proof",
                    VDFProof(uint8(0), b"1239819023890"),
                )
                block_bad_5 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_5]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_5)
                assert err == Err.INVALID_CC_EOS_VDF

            result, err, _ = await empty_blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_invalid_rc_sub_slot_vdf(self, empty_blockchain):
        # 2p
        blocks = bt.get_consecutive_blocks(10)
        for block in blocks:
            if len(block.finished_sub_slots):
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
                result, err, _ = await empty_blockchain.receive_block(block_bad)
                assert err == Err.INVALID_RC_EOS_VDF

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
                result, err, _ = await empty_blockchain.receive_block(block_bad_2)
                assert err == Err.INVALID_RC_EOS_VDF

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
                result, err, _ = await empty_blockchain.receive_block(block_bad_3)
                assert err == Err.INVALID_RC_EOS_VDF

                # Bad proof
                new_finished_ss_5 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "proofs.reward_chain_slot_proof",
                    VDFProof(uint8(0), b"1239819023890"),
                )
                block_bad_5 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_5]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_5)
                assert err == Err.INVALID_RC_EOS_VDF

            result, err, _ = await empty_blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_genesis_bad_deficit(self, empty_blockchain):
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
        result, err, _ = await empty_blockchain.receive_block(block_bad)
        assert err == Err.INVALID_DEFICIT

    @pytest.mark.asyncio
    async def test_reset_deficit(self, empty_blockchain):
        # 2s, 2t
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(2)
        await empty_blockchain.receive_block(blocks[0])
        await empty_blockchain.receive_block(blocks[1])
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
                result, err, _ = await empty_blockchain.receive_block(block_bad)
                assert err == Err.INVALID_DEFICIT or err == Err.INVALID_ICC_HASH_CC

            result, err, _ = await empty_blockchain.receive_block(blocks[-1])
            assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_genesis_has_ses(self, empty_blockchain):
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
        result, err, _ = await empty_blockchain.receive_block(block_bad)
        assert err == Err.INVALID_SUB_EPOCH_SUMMARY_HASH

    @pytest.mark.asyncio
    async def test_no_ses_if_no_se(self, empty_blockchain):
        # 3b
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if len(blocks[-1].finished_sub_slots) > 0:
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
                result, err, _ = await empty_blockchain.receive_block(block_bad)
                assert err == Err.INVALID_SUB_EPOCH_SUMMARY_HASH
                return
            await empty_blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_too_many_blocks(self, empty_blockchain):
        # 4: TODO
        pass

    @pytest.mark.asyncio
    async def test_bad_pos(self, empty_blockchain):
        # 5
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        block_bad = recursive_replace(blocks[-1], "reward_chain_block.proof_of_space.challenge", std_hash(b""))
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE

        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.proof_of_space.pool_contract_puzzle_hash", std_hash(b"")
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE

        block_bad = recursive_replace(blocks[-1], "reward_chain_block.proof_of_space.size", 62)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE

        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.proof_of_space.plot_public_key",
            AugSchemeMPL.key_gen(std_hash(b"1231n")).get_g1(),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.proof_of_space.size",
            32,
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.proof_of_space.proof",
            bytes([1] * int(blocks[-1].reward_chain_block.proof_of_space.size * 64 / 8)),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE

        # TODO: test not passing the plot filter

    @pytest.mark.asyncio
    async def test_bad_signage_point_index(self, empty_blockchain):
        # 6
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        with pytest.raises(ValueError):
            block_bad = recursive_replace(
                blocks[-1], "reward_chain_block.signage_point_index", test_constants.NUM_SPS_SUB_SLOT
            )
            assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_SP_INDEX
        with pytest.raises(ValueError):
            block_bad = recursive_replace(
                blocks[-1], "reward_chain_block.signage_point_index", test_constants.NUM_SPS_SUB_SLOT + 1
            )
            assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_SP_INDEX

    @pytest.mark.asyncio
    async def test_sp_0_no_sp(self, empty_blockchain):
        # 7
        blocks = []
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].reward_chain_block.signage_point_index == 0:
                case_1 = True
                block_bad = recursive_replace(blocks[-1], "reward_chain_block.signage_point_index", uint8(1))
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_SP_INDEX
            else:
                case_2 = True
                block_bad = recursive_replace(blocks[-1], "reward_chain_block.signage_point_index", uint8(0))
                error_code = (await empty_blockchain.receive_block(block_bad))[1]
                assert error_code == Err.INVALID_SP_INDEX or error_code == Err.INVALID_POSPACE
            assert (await empty_blockchain.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_epoch_overflows(self, empty_blockchain):
        # 9. TODO. This is hard to test because it requires modifying the block tools to make these special blocks
        pass

    @pytest.mark.asyncio
    async def test_bad_total_iters(self, empty_blockchain):
        # 10
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.total_iters", blocks[-1].reward_chain_block.total_iters + 1
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_TOTAL_ITERS

    @pytest.mark.asyncio
    async def test_bad_rc_sp_vdf(self, empty_blockchain):
        # 11
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].reward_chain_block.signage_point_index != 0:
                block_bad = recursive_replace(
                    blocks[-1], "reward_chain_block.reward_chain_sp_vdf.challenge", std_hash(b"1")
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_SP_VDF
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_block.reward_chain_sp_vdf.output",
                    bad_element,
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_SP_VDF
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_block.reward_chain_sp_vdf.number_of_iterations",
                    uint64(1111111111111),
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_SP_VDF
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_sp_proof",
                    VDFProof(uint8(0), std_hash(b"")),
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_SP_VDF
                return
            assert (await empty_blockchain.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_bad_rc_sp_sig(self, empty_blockchain):
        # 12
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad = recursive_replace(blocks[-1], "reward_chain_block.reward_chain_sp_signature", G2Element.generator())
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_SIGNATURE

    @pytest.mark.asyncio
    async def test_bad_cc_sp_vdf(self, empty_blockchain):
        # 13. Note: does not validate fully due to proof of space being validated first
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].reward_chain_block.signage_point_index != 0:
                block_bad = recursive_replace(
                    blocks[-1], "reward_chain_block.challenge_chain_sp_vdf.challenge", std_hash(b"1")
                )
                assert (await empty_blockchain.receive_block(block_bad))[0] == ReceiveBlockResult.INVALID_BLOCK
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_block.challenge_chain_sp_vdf.output",
                    bad_element,
                )
                assert (await empty_blockchain.receive_block(block_bad))[0] == ReceiveBlockResult.INVALID_BLOCK
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_block.challenge_chain_sp_vdf.number_of_iterations",
                    uint64(1111111111111),
                )
                assert (await empty_blockchain.receive_block(block_bad))[0] == ReceiveBlockResult.INVALID_BLOCK
                block_bad = recursive_replace(
                    blocks[-1],
                    "challenge_chain_sp_proof",
                    VDFProof(uint8(0), std_hash(b"")),
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_CC_SP_VDF
                return
            assert (await empty_blockchain.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_bad_cc_sp_sig(self, empty_blockchain):
        # 14
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.challenge_chain_sp_signature", G2Element.generator()
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_CC_SIGNATURE

    @pytest.mark.asyncio
    async def test_is_transaction_block(self, empty_blockchain):
        # 15: TODO
        pass

    @pytest.mark.asyncio
    async def test_bad_foliage_sb_sig(self, empty_blockchain):
        # 16
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad = recursive_replace(blocks[-1], "foliage.foliage_block_data_signature", G2Element.generator())
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PLOT_SIGNATURE

    @pytest.mark.asyncio
    async def test_bad_foliage_transaction_block_sig(self, empty_blockchain):
        # 17
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_transaction_block is not None:
                block_bad = recursive_replace(
                    blocks[-1], "foliage.foliage_transaction_block_signature", G2Element.generator()
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PLOT_SIGNATURE
                return
            assert (await empty_blockchain.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_unfinished_reward_chain_sb_hash(self, empty_blockchain):
        # 18
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage.foliage_block_data.unfinished_reward_block_hash", std_hash(b"2")
        )
        new_m = block_bad.foliage.foliage_block_data.get_hash()
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_URSB_HASH

    @pytest.mark.asyncio
    async def test_pool_target_height(self, empty_blockchain):
        # 19
        blocks = bt.get_consecutive_blocks(3)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await empty_blockchain.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(blocks[-1], "foliage.foliage_block_data.pool_target.max_height", 1)
        new_m = block_bad.foliage.foliage_block_data.get_hash()
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.OLD_POOL_TARGET

    @pytest.mark.asyncio
    async def test_pool_target_pre_farm(self, empty_blockchain):
        # 20a
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage.foliage_block_data.pool_target.puzzle_hash", std_hash(b"12")
        )
        new_m = block_bad.foliage.foliage_block_data.get_hash()
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage.foliage_block_data_signature", new_fsb_sig)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PREFARM

    @pytest.mark.asyncio
    async def test_pool_target_signature(self, empty_blockchain):
        # 20b
        blocks_initial = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks_initial[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await empty_blockchain.receive_block(blocks_initial[1]))[0] == ReceiveBlockResult.NEW_PEAK

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
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POOL_SIGNATURE
                return
            attempts += 1

    @pytest.mark.asyncio
    async def test_pool_target_contract(self, empty_blockchain):
        # 20c invalid pool target with contract
        blocks_initial = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks_initial[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await empty_blockchain.receive_block(blocks_initial[1]))[0] == ReceiveBlockResult.NEW_PEAK

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
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POOL_TARGET
                return
            attempts += 1

    @pytest.mark.asyncio
    async def test_foliage_data_presence(self, empty_blockchain):
        # 22
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
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
            err_code = (await empty_blockchain.receive_block(block_bad))[1]
            assert err_code == Err.INVALID_FOLIAGE_BLOCK_PRESENCE or err_code == Err.INVALID_IS_TRANSACTION_BLOCK
            await empty_blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_foliage_transaction_block_hash(self, empty_blockchain):
        # 23
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
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
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_FOLIAGE_BLOCK_HASH
                return
            await empty_blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_genesis_bad_prev_block(self, empty_blockchain):
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
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PREV_BLOCK_HASH

    @pytest.mark.asyncio
    async def test_bad_prev_block_non_genesis(self, empty_blockchain):
        # 24b
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
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
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PREV_BLOCK_HASH
                return
            await empty_blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_bad_filter_hash(self, empty_blockchain):
        # 25
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
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
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_TRANSACTIONS_FILTER_HASH
                return
            await empty_blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_bad_timestamp(self, empty_blockchain):
        # 26
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
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
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.TIMESTAMP_TOO_FAR_IN_PAST

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
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.TIMESTAMP_TOO_FAR_IN_FUTURE
                return
            await empty_blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_height(self, empty_blockchain):
        # 27
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.height", 2)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_HEIGHT

    @pytest.mark.asyncio
    async def test_height_genesis(self, empty_blockchain):
        # 27
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.height", 1)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PREV_BLOCK_HASH

    @pytest.mark.asyncio
    async def test_weight(self, empty_blockchain):
        # 28
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.weight", 22131)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_WEIGHT

    @pytest.mark.asyncio
    async def test_weight_genesis(self, empty_blockchain):
        # 28
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.weight", 0)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_WEIGHT

    @pytest.mark.asyncio
    async def test_bad_cc_ip_vdf(self, empty_blockchain):
        # 29
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block_bad = recursive_replace(blocks[-1], "reward_chain_block.challenge_chain_ip_vdf.challenge", std_hash(b"1"))
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_CC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.challenge_chain_ip_vdf.output",
            bad_element,
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_CC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.challenge_chain_ip_vdf.number_of_iterations",
            uint64(1111111111111),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_CC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "challenge_chain_ip_proof",
            VDFProof(uint8(0), std_hash(b"")),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_CC_IP_VDF

    @pytest.mark.asyncio
    async def test_bad_rc_ip_vdf(self, empty_blockchain):
        # 30
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block_bad = recursive_replace(blocks[-1], "reward_chain_block.reward_chain_ip_vdf.challenge", std_hash(b"1"))
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.reward_chain_ip_vdf.output",
            bad_element,
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.reward_chain_ip_vdf.number_of_iterations",
            uint64(1111111111111),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_ip_proof",
            VDFProof(uint8(0), std_hash(b"")),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_IP_VDF

    @pytest.mark.asyncio
    async def test_bad_icc_ip_vdf(self, empty_blockchain):
        # 31
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.infused_challenge_chain_ip_vdf.challenge", std_hash(b"1")
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_ICC_VDF
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_ICC_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.infused_challenge_chain_ip_vdf.output",
            bad_element,
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_ICC_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_block.infused_challenge_chain_ip_vdf.number_of_iterations",
            uint64(1111111111111),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_ICC_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "infused_challenge_chain_ip_proof",
            VDFProof(uint8(0), std_hash(b"")),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_ICC_VDF

    @pytest.mark.asyncio
    async def test_reward_block_hash(self, empty_blockchain):
        # 32
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(blocks[-1], "foliage.reward_block_hash", std_hash(b""))
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_REWARD_BLOCK_HASH

    @pytest.mark.asyncio
    async def test_reward_block_hash_2(self, empty_blockchain):
        # 33
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[0], "reward_chain_block.is_transaction_block", False)
        block_bad: FullBlock = recursive_replace(
            block_bad, "foliage.reward_block_hash", block_bad.reward_chain_block.get_hash()
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_FOLIAGE_BLOCK_PRESENCE
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        # Test one which should not be a tx block
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if not blocks[-1].is_transaction_block():
                block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_block.is_transaction_block", True)
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage.reward_block_hash", block_bad.reward_chain_block.get_hash()
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_FOLIAGE_BLOCK_PRESENCE
                return
            assert (await empty_blockchain.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK


class TestBodyValidation:
    @pytest.mark.asyncio
    async def test_not_block_but_has_data(self, empty_blockchain):
        # TODO
        pass


class TestReorgs:
    @pytest.mark.asyncio
    async def test_basic_reorg(self, empty_blockchain):
        b = empty_blockchain
        blocks = bt.get_consecutive_blocks(15)

        for block in blocks:
            assert (await b.receive_block(block))[0] == ReceiveBlockResult.NEW_PEAK
        assert b.get_peak().height == 14

        blocks_reorg_chain = bt.get_consecutive_blocks(7, blocks[:10], seed=b"2")
        for reorg_block in blocks_reorg_chain:
            result, error_code, fork_height = await b.receive_block(reorg_block)
            if reorg_block.height < 10:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height < 14:
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
            elif reorg_block.height >= 15:
                assert result == ReceiveBlockResult.NEW_PEAK
            assert error_code is None
        assert b.get_peak().height == 16

    @pytest.mark.asyncio
    async def test_long_reorg(self, empty_blockchain, default_10000_blocks):
        # Reorg longer than a difficulty adjustment
        # Also tests higher weight chain but lower height
        b = empty_blockchain
        num_blocks_chain_1 = 3 * test_constants.EPOCH_BLOCKS + test_constants.MAX_SUB_SLOT_BLOCKS + 10
        num_blocks_chain_2_start = test_constants.EPOCH_BLOCKS - 20
        num_blocks_chain_2 = 3 * test_constants.EPOCH_BLOCKS + test_constants.MAX_SUB_SLOT_BLOCKS + 8

        assert num_blocks_chain_1 < 10000
        blocks = default_10000_blocks[:num_blocks_chain_1]

        for block in blocks:
            assert (await b.receive_block(block))[0] == ReceiveBlockResult.NEW_PEAK
        chain_1_height = b.get_peak().height
        chain_1_weight = b.get_peak().weight
        assert chain_1_height == (num_blocks_chain_1 - 1)

        # These blocks will have less time between them (timestamp) and therefore will make difficulty go up
        # This means that the weight will grow faster, and we can get a heavier chain with lower height
        blocks_reorg_chain = bt.get_consecutive_blocks(
            num_blocks_chain_2 - num_blocks_chain_2_start,
            blocks[:num_blocks_chain_2_start],
            seed=b"2",
            time_per_block=8,
        )
        found_orphan = False
        for reorg_block in blocks_reorg_chain:
            result, error_code, fork_height = await b.receive_block(reorg_block)
            if reorg_block.height < num_blocks_chain_2_start:
                assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            if reorg_block.weight <= chain_1_weight:
                if result == ReceiveBlockResult.ADDED_AS_ORPHAN:
                    found_orphan = True
                assert error_code is None
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN or result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.weight > chain_1_weight:
                assert reorg_block.height < chain_1_height
                assert result == ReceiveBlockResult.NEW_PEAK
            assert error_code is None
        assert found_orphan

        assert b.get_peak().weight > chain_1_weight
        assert b.get_peak().height < chain_1_height

    @pytest.mark.asyncio
    async def test_reorg_from_genesis(self, empty_blockchain):
        b = empty_blockchain
        WALLET_A = WalletTool()
        WALLET_A_PUZZLE_HASHES = [WALLET_A.get_new_puzzlehash() for _ in range(5)]

        blocks = bt.get_consecutive_blocks(15)

        for block in blocks:
            assert (await b.receive_block(block))[0] == ReceiveBlockResult.NEW_PEAK
        assert b.get_peak().height == 14

        # Reorg to alternate chain that is 1 height longer
        found_orphan = False
        blocks_reorg_chain = bt.get_consecutive_blocks(16, [], seed=b"2")
        for reorg_block in blocks_reorg_chain:
            result, error_code, fork_height = await b.receive_block(reorg_block)
            if reorg_block.height < 14:
                if result == ReceiveBlockResult.ADDED_AS_ORPHAN:
                    found_orphan = True
                assert result == ReceiveBlockResult.ADDED_AS_ORPHAN or result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
            elif reorg_block.height >= 15:
                assert result == ReceiveBlockResult.NEW_PEAK
            assert error_code is None

        # Back to original chain
        blocks_reorg_chain_2 = bt.get_consecutive_blocks(3, blocks, seed=b"3")

        result, error_code, fork_height = await b.receive_block(blocks_reorg_chain_2[-3])
        assert result == ReceiveBlockResult.ADDED_AS_ORPHAN

        result, error_code, fork_height = await b.receive_block(blocks_reorg_chain_2[-2])
        assert result == ReceiveBlockResult.NEW_PEAK

        result, error_code, fork_height = await b.receive_block(blocks_reorg_chain_2[-1])
        assert result == ReceiveBlockResult.NEW_PEAK
        assert found_orphan
        assert b.get_peak().height == 17

    @pytest.mark.asyncio
    async def test_reorg_transaction(self, empty_blockchain):
        b = empty_blockchain
        wallet_a = WalletTool()
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
            result, error_code, _ = await b.receive_block(block)
            assert error_code is None and result == ReceiveBlockResult.NEW_PEAK

        for block in blocks_fork:
            result, error_code, _ = await b.receive_block(block)
            assert error_code is None


class TestPreValidation:
    @pytest.mark.asyncio
    async def test_pre_validation_fails_bad_blocks(self, empty_blockchain):
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        block_bad = recursive_replace(
            blocks[-1], "reward_chain_block.total_iters", blocks[-1].reward_chain_block.total_iters + 1
        )
        res = await empty_blockchain.pre_validate_blocks_multiprocessing([blocks[0], block_bad])
        assert res[0].error is None
        assert res[1].error is not None

    @pytest.mark.asyncio
    async def test_pre_validation(self, empty_blockchain, default_1000_blocks):
        blocks = default_1000_blocks[:100]
        start = time.time()
        n_at_a_time = min(multiprocessing.cpu_count(), 32)
        times_pv = []
        times_rb = []
        for i in range(0, len(blocks), n_at_a_time):
            end_i = min(i + n_at_a_time, len(blocks))
            blocks_to_validate = blocks[i:end_i]
            start_pv = time.time()
            res = await empty_blockchain.pre_validate_blocks_multiprocessing(blocks_to_validate)
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
