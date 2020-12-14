import asyncio
from dataclasses import replace
import pytest
from blspy import AugSchemeMPL, G2Element
from pytest import raises

from src.consensus.blockchain import ReceiveBlockResult
from src.types.classgroup import ClassgroupElement
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.slots import InfusedChallengeChainSubSlot
from src.types.vdf import VDFInfo, VDFProof
from src.util.block_tools import get_vdf_info_and_proof
from src.util.errors import Err
from src.util.hash import std_hash
from src.util.ints import uint64, uint8, int512
from tests.recursive_replace import recursive_replace
from tests.setup_nodes import test_constants, bt
from tests.full_node.fixtures import empty_blockchain
from tests.full_node.fixtures import default_1000_blocks


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestGenesisBlock:
    @pytest.mark.asyncio
    async def test_block_tools_proofs(self):
        vdf, proof = get_vdf_info_and_proof(
            test_constants, ClassgroupElement.get_default_element(), test_constants.FIRST_CC_CHALLENGE, uint64(231)
        )
        if proof.is_valid(test_constants, vdf) is False:
            raise Exception("invalid proof")

    @pytest.mark.asyncio
    async def test_non_overflow_genesis(self, empty_blockchain):
        assert empty_blockchain.get_peak() is None
        genesis = bt.get_consecutive_blocks(1, force_overflow=False)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK
        assert empty_blockchain.get_peak().height == 0

    @pytest.mark.asyncio
    async def test_overflow_genesis(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(1, force_overflow=True)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_genesis_empty_slots(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(1, force_overflow=False, skip_slots=3)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_overflow_genesis_empty_slots(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(1, force_overflow=True, skip_slots=3)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_genesis_validate_1(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(1, force_overflow=False)[0]
        bad_prev = bytes([1] * 32)
        genesis = recursive_replace(genesis, "foliage_sub_block.prev_sub_block_hash", bad_prev)
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
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
            print(
                f"Added block {block.height} total iters {block.total_iters} new slot? {len(block.finished_sub_slots)}"
            )
        assert empty_blockchain.get_peak().height == len(blocks) - 1

    @pytest.mark.asyncio
    async def test_empty_genesis(self, empty_blockchain):
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(2, skip_slots=3)
        for block in blocks:
            result, err, _ = await blockchain.receive_block(block)
            assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_empty_slots_non_genesis(self, empty_blockchain):
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(10)
        for block in blocks:
            print(block.reward_chain_sub_block.challenge_chain_ip_vdf)
            print(block.challenge_chain_ip_proof)
            result, err, _ = await blockchain.receive_block(block)
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
    async def test_one_sb_per_two_slots(self, empty_blockchain):
        blockchain = empty_blockchain
        num_blocks = 20
        blocks = []
        for i in range(num_blocks):  # Same thing, but 2 sub-slots per sub-block
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=2)
            result, err, _ = await blockchain.receive_block(blocks[-1])
            assert result == ReceiveBlockResult.NEW_PEAK
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_one_sb_per_five_slots(self, empty_blockchain):
        blockchain = empty_blockchain
        num_blocks = 10
        blocks = []
        for i in range(num_blocks):  # Same thing, but 5 sub-slots per sub-block
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
            print(f"added {block.height} {block.total_iters}")
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
        block_1_bad = recursive_replace(blocks[-1], "foliage_sub_block.prev_sub_block_hash", bytes([0] * 32))
        print(block_1_bad)

        result, err, _ = await empty_blockchain.receive_block(block_1_bad)
        assert result == ReceiveBlockResult.DISCONNECTED_BLOCK

    @pytest.mark.asyncio
    async def test_invalid_pospace(self, empty_blockchain):
        # 2
        blocks = bt.get_consecutive_blocks(2, force_overflow=False)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_1_bad = recursive_replace(blocks[-1], "reward_chain_sub_block.proof_of_space.proof", bytes([0] * 32))

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
        print(blocks)
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
                    ClassgroupElement.get_default_element(),
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
                            challenge_hash=bytes([0] * 32),
                        )
                    ),
                )
                block_bad_3 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_3]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_3)
                assert err == Err.INVALID_ICC_EOS_VDF

                # Bad input
                new_finished_ss_4 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "infused_challenge_chain",
                    InfusedChallengeChainSubSlot(
                        replace(
                            block.finished_sub_slots[
                                -1
                            ].infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf,
                            input=ClassgroupElement(int512(3), int512(5)),
                        )
                    ),
                )
                block_bad_4 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_4]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_4)
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

            else:
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
                if (
                    block.finished_sub_slots[-1].reward_chain.deficit
                    == test_constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
                ):
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
                print(len(block.finished_sub_slots))
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
        blocks_base = bt.get_consecutive_blocks(test_constants.EPOCH_SUB_BLOCKS)
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
                block_bad_3 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_3]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_3)
                assert err == Err.INVALID_CC_EOS_VDF

                # Bad input
                new_finished_ss_4 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "challenge_chain",
                    recursive_replace(
                        block.finished_sub_slots[-1].challenge_chain,
                        "challenge_chain_end_of_slot_vdf.input",
                        ClassgroupElement(int512(5), int512(1)),
                    ),
                )
                block_bad_4 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_4]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_4)
                assert err == Err.INVALID_CC_EOS_VDF

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

            else:
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
                        "reward_chain_end_of_slot_vdf.number_of_iterations",
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
                        "reward_chain_end_of_slot_vdf.output",
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

                # Bad input
                new_finished_ss_4 = recursive_replace(
                    block.finished_sub_slots[-1],
                    "reward_chain",
                    recursive_replace(
                        block.finished_sub_slots[-1].reward_chain,
                        "end_of_slot_vdf.input",
                        ClassgroupElement(int512(5), int512(1)),
                    ),
                )
                block_bad_4 = recursive_replace(
                    block, "finished_sub_slots", block.finished_sub_slots[:-1] + [new_finished_ss_4]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_4)
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

            else:
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
                test_constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1,
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
                if blockchain.sub_blocks[blocks[-2].header_hash].deficit == 0:
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
    async def test_too_many_sub_blocks(self, empty_blockchain):
        # 4: TODO
        pass

    @pytest.mark.asyncio
    async def test_bad_pos(self, empty_blockchain):
        # 4
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        block_bad = recursive_replace(blocks[-1], "reward_chain_sub_block.proof_of_space.challenge", std_hash(b""))
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE

        block_bad = recursive_replace(
            blocks[-1], "reward_chain_sub_block.proof_of_space.pool_contract_puzzle_hash", std_hash(b"")
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE

        block_bad = recursive_replace(blocks[-1], "reward_chain_sub_block.proof_of_space.pool_public_key", None)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE

        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.proof_of_space.plot_public_key",
            AugSchemeMPL.key_gen(std_hash(b"1231n")).get_g1(),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.proof_of_space.size",
            32,
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.proof_of_space.proof",
            bytes([1] * int(blocks[-1].reward_chain_sub_block.proof_of_space.size * 64 / 8)),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POSPACE

        # TODO: test not passing the plot filter

    @pytest.mark.asyncio
    async def test_bad_signage_point_index(self, empty_blockchain):
        # 5
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        with raises(ValueError):
            block_bad = recursive_replace(
                blocks[-1], "reward_chain_sub_block.signage_point_index", test_constants.NUM_SPS_SUB_SLOT
            )
            assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_SP_INDEX
        with raises(ValueError):
            block_bad = recursive_replace(
                blocks[-1], "reward_chain_sub_block.signage_point_index", test_constants.NUM_SPS_SUB_SLOT + 1
            )
            assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_SP_INDEX

    @pytest.mark.asyncio
    async def test_sp_0_no_sp(self, empty_blockchain):
        # 7
        blocks = []
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].reward_chain_sub_block.signage_point_index == 0:
                case_1 = True
                block_bad = recursive_replace(blocks[-1], "reward_chain_sub_block.signage_point_index", uint8(1))
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_SP_INDEX
            else:
                case_2 = True
                block_bad = recursive_replace(blocks[-1], "reward_chain_sub_block.signage_point_index", uint8(0))
                error_code = (await empty_blockchain.receive_block(block_bad))[1]
                assert error_code == Err.INVALID_SP_INDEX or error_code == Err.INVALID_POSPACE
            assert (await empty_blockchain.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_epoch_overflows(self, empty_blockchain):
        # 9. TODO. This is hard to test because it requires modifying the block tools to make these special blocks
        pass

    @pytest.mark.asyncio
    async def test_bad_total_iters(self, empty_blockchain):
        # 8
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        block_bad = recursive_replace(
            blocks[-1], "reward_chain_sub_block.total_iters", blocks[-1].reward_chain_sub_block.total_iters + 1
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_TOTAL_ITERS

    @pytest.mark.asyncio
    async def test_bad_rc_sp_vdf(self, empty_blockchain):
        # 9
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].reward_chain_sub_block.signage_point_index != 0:
                block_bad = recursive_replace(
                    blocks[-1], "reward_chain_sub_block.reward_chain_sp_vdf.challenge", std_hash(b"1")
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_SP_VDF
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_sub_block.reward_chain_sp_vdf.input",
                    ClassgroupElement(int512(10), int512(2)),
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_SP_VDF
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_sub_block.reward_chain_sp_vdf.output",
                    ClassgroupElement(int512(10), int512(2)),
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_SP_VDF
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_sub_block.reward_chain_sp_vdf.number_of_iterations",
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
        # 10
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_sub_block.reward_chain_sp_signature", G2Element.generator()
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_SIGNATURE

    @pytest.mark.asyncio
    async def test_bad_cc_sp_vdf(self, empty_blockchain):
        # 11. Note: does not validate fully due to proof of space being validated first
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].reward_chain_sub_block.signage_point_index != 0:
                block_bad = recursive_replace(
                    blocks[-1], "reward_chain_sub_block.challenge_chain_sp_vdf.challenge", std_hash(b"1")
                )
                assert (await empty_blockchain.receive_block(block_bad))[0] == ReceiveBlockResult.INVALID_BLOCK
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_sub_block.challenge_chain_sp_vdf.input",
                    ClassgroupElement(int512(10), int512(2)),
                )
                assert (await empty_blockchain.receive_block(block_bad))[0] == ReceiveBlockResult.INVALID_BLOCK
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_sub_block.challenge_chain_sp_vdf.output",
                    ClassgroupElement(int512(10), int512(2)),
                )
                assert (await empty_blockchain.receive_block(block_bad))[0] == ReceiveBlockResult.INVALID_BLOCK
                block_bad = recursive_replace(
                    blocks[-1],
                    "reward_chain_sub_block.challenge_chain_sp_vdf.number_of_iterations",
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
        # 12
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_sub_block.challenge_chain_sp_signature", G2Element.generator()
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_CC_SIGNATURE

    @pytest.mark.asyncio
    async def test_is_block(self, empty_blockchain):
        # 15: TODO
        pass

    @pytest.mark.asyncio
    async def test_bad_foliage_sb_sig(self, empty_blockchain):
        # 14
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad = recursive_replace(
            blocks[-1], "foliage_sub_block.foliage_sub_block_signature", G2Element.generator()
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PLOT_SIGNATURE

    @pytest.mark.asyncio
    async def test_bad_foliage_block_sig(self, empty_blockchain):
        # 15
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_block is not None:
                block_bad = recursive_replace(
                    blocks[-1], "foliage_sub_block.foliage_block_signature", G2Element.generator()
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PLOT_SIGNATURE
                return
            assert (await empty_blockchain.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_unfinished_reward_chain_sb_hash(self, empty_blockchain):
        # 16
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage_sub_block.foliage_sub_block_data.unfinished_reward_block_hash", std_hash(b"2")
        )
        new_m = block_bad.foliage_sub_block.foliage_sub_block_data.get_hash()
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_sub_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage_sub_block.foliage_sub_block_signature", new_fsb_sig)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_URSB_HASH

    @pytest.mark.asyncio
    async def test_pool_target_height(self, empty_blockchain):
        # 17
        blocks = bt.get_consecutive_blocks(3)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await empty_blockchain.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage_sub_block.foliage_sub_block_data.pool_target.max_height", 1
        )
        new_m = block_bad.foliage_sub_block.foliage_sub_block_data.get_hash()
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_sub_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage_sub_block.foliage_sub_block_signature", new_fsb_sig)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.OLD_POOL_TARGET

    @pytest.mark.asyncio
    async def test_pool_target_signature(self, empty_blockchain):
        # 18
        blocks = bt.get_consecutive_blocks(3)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await empty_blockchain.receive_block(blocks[1]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage_sub_block.foliage_sub_block_data.pool_signature", G2Element.generator()
        )
        new_m = block_bad.foliage_sub_block.foliage_sub_block_data.get_hash()
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_sub_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage_sub_block.foliage_sub_block_signature", new_fsb_sig)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_POOL_SIGNATURE

    @pytest.mark.asyncio
    async def test_foliage_data_presence(self, empty_blockchain):
        # 20
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_block is not None:
                case_1 = True
                block_bad: FullBlock = recursive_replace(blocks[-1], "foliage_sub_block.foliage_block_hash", None)
            else:
                case_2 = True
                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage_sub_block.foliage_block_hash", std_hash(b"")
                )
            err_code = (await empty_blockchain.receive_block(block_bad))[1]
            assert err_code == Err.INVALID_FOLIAGE_BLOCK_PRESENCE or err_code == Err.INVALID_IS_BLOCK
            await empty_blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_foliage_block_hash(self, empty_blockchain):
        # 21
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_block is not None:
                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage_sub_block.foliage_block_hash", std_hash(b"2")
                )

                new_m = block_bad.foliage_sub_block.foliage_block_hash
                new_fbh_sig = bt.get_plot_signature(
                    new_m, blocks[-1].reward_chain_sub_block.proof_of_space.plot_public_key
                )
                block_bad = recursive_replace(block_bad, "foliage_sub_block.foliage_block_signature", new_fbh_sig)
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_FOLIAGE_BLOCK_HASH
                return
            await empty_blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_genesis_bad_prev_block(self, empty_blockchain):
        # 22a
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[-1], "foliage_block.prev_block_hash", std_hash(b"2"))
        block_bad: FullBlock = recursive_replace(
            block_bad, "foliage_sub_block.foliage_block_hash", block_bad.foliage_block.get_hash()
        )
        new_m = block_bad.foliage_sub_block.foliage_block_hash
        new_fbh_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_sub_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage_sub_block.foliage_block_signature", new_fbh_sig)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PREV_BLOCK_HASH

    @pytest.mark.asyncio
    async def test_bad_prev_block_non_genesis(self, empty_blockchain):
        # 22b
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_block is not None:
                block_bad: FullBlock = recursive_replace(blocks[-1], "foliage_block.prev_block_hash", std_hash(b"2"))
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage_sub_block.foliage_block_hash", block_bad.foliage_block.get_hash()
                )
                new_m = block_bad.foliage_sub_block.foliage_block_hash
                new_fbh_sig = bt.get_plot_signature(
                    new_m, blocks[-1].reward_chain_sub_block.proof_of_space.plot_public_key
                )
                block_bad = recursive_replace(block_bad, "foliage_sub_block.foliage_block_signature", new_fbh_sig)
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PREV_BLOCK_HASH
                return
            await empty_blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_bad_filter_hash(self, empty_blockchain):
        # 23
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_block is not None:
                block_bad: FullBlock = recursive_replace(blocks[-1], "foliage_block.filter_hash", std_hash(b"2"))
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage_sub_block.foliage_block_hash", block_bad.foliage_block.get_hash()
                )
                new_m = block_bad.foliage_sub_block.foliage_block_hash
                new_fbh_sig = bt.get_plot_signature(
                    new_m, blocks[-1].reward_chain_sub_block.proof_of_space.plot_public_key
                )
                block_bad = recursive_replace(block_bad, "foliage_sub_block.foliage_block_signature", new_fbh_sig)
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_TRANSACTIONS_FILTER_HASH
                return
            await empty_blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_bad_timestamp(self, empty_blockchain):
        # 24
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if blocks[-1].foliage_block is not None:
                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage_block.timestamp", blocks[0].foliage_block.timestamp - 10
                )
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage_sub_block.foliage_block_hash", block_bad.foliage_block.get_hash()
                )
                new_m = block_bad.foliage_sub_block.foliage_block_hash
                new_fbh_sig = bt.get_plot_signature(
                    new_m, blocks[-1].reward_chain_sub_block.proof_of_space.plot_public_key
                )
                block_bad = recursive_replace(block_bad, "foliage_sub_block.foliage_block_signature", new_fbh_sig)
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.TIMESTAMP_TOO_FAR_IN_PAST

                block_bad: FullBlock = recursive_replace(
                    blocks[-1], "foliage_block.timestamp", blocks[0].foliage_block.timestamp + 10000000
                )
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage_sub_block.foliage_block_hash", block_bad.foliage_block.get_hash()
                )
                new_m = block_bad.foliage_sub_block.foliage_block_hash
                new_fbh_sig = bt.get_plot_signature(
                    new_m, blocks[-1].reward_chain_sub_block.proof_of_space.plot_public_key
                )
                block_bad = recursive_replace(block_bad, "foliage_sub_block.foliage_block_signature", new_fbh_sig)
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.TIMESTAMP_TOO_FAR_IN_FUTURE
                return
            await empty_blockchain.receive_block(blocks[-1])

    @pytest.mark.asyncio
    async def test_sub_block_height(self, empty_blockchain):
        # 25
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_sub_block.sub_block_height", 2)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_HEIGHT

    @pytest.mark.asyncio
    async def test_sub_block_height_genesis(self, empty_blockchain):
        # 25
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_sub_block.sub_block_height", 1)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PREV_BLOCK_HASH

    @pytest.mark.asyncio
    async def test_weight(self, empty_blockchain):
        # 26
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_sub_block.weight", 22131)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_WEIGHT

    @pytest.mark.asyncio
    async def test_weight_genesis(self, empty_blockchain):
        # 26
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_sub_block.weight", 0)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_WEIGHT

    @pytest.mark.asyncio
    async def test_bad_cc_ip_vdf(self, empty_blockchain):
        # 27
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_sub_block.challenge_chain_ip_vdf.challenge", std_hash(b"1")
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_CC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.challenge_chain_ip_vdf.input",
            ClassgroupElement(int512(10), int512(2)),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_CC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.challenge_chain_ip_vdf.output",
            ClassgroupElement(int512(10), int512(2)),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_CC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.challenge_chain_ip_vdf.number_of_iterations",
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
        # 28
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_sub_block.reward_chain_ip_vdf.challenge", std_hash(b"1")
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.reward_chain_ip_vdf.input",
            ClassgroupElement(int512(10), int512(2)),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.reward_chain_ip_vdf.output",
            ClassgroupElement(int512(10), int512(2)),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_IP_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.reward_chain_ip_vdf.number_of_iterations",
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
        # 29
        blocks = bt.get_consecutive_blocks(1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_sub_block.infused_challenge_chain_ip_vdf.challenge", std_hash(b"1")
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_ICC_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.infused_challenge_chain_ip_vdf.input",
            ClassgroupElement(int512(10), int512(2)),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_ICC_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.infused_challenge_chain_ip_vdf.output",
            ClassgroupElement(int512(10), int512(2)),
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_ICC_VDF
        block_bad = recursive_replace(
            blocks[-1],
            "reward_chain_sub_block.infused_challenge_chain_ip_vdf.number_of_iterations",
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
        # 30
        blocks = bt.get_consecutive_blocks(2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(blocks[-1], "foliage_sub_block.reward_block_hash", std_hash(b""))
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_REWARD_BLOCK_HASH

    @pytest.mark.asyncio
    async def test_reward_block_hash(self, empty_blockchain):
        # 31
        blocks = bt.get_consecutive_blocks(1)
        block_bad: FullBlock = recursive_replace(blocks[0], "reward_chain_sub_block.is_block", False)
        block_bad: FullBlock = recursive_replace(
            block_bad, "foliage_sub_block.reward_block_hash", block_bad.reward_chain_sub_block.get_hash()
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_FOLIAGE_BLOCK_PRESENCE
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        # Test one which should not be a block
        while True:
            blocks = bt.get_consecutive_blocks(1, block_list_input=blocks)
            if not blocks[-1].is_block():
                block_bad: FullBlock = recursive_replace(blocks[-1], "reward_chain_sub_block.is_block", True)
                block_bad: FullBlock = recursive_replace(
                    block_bad, "foliage_sub_block.reward_block_hash", block_bad.reward_chain_sub_block.get_hash()
                )
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_FOLIAGE_BLOCK_PRESENCE
                return
            assert (await empty_blockchain.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK


class TestBodyValidation:
    @pytest.mark.asyncio
    async def test_not_block_but_has_data(self, empty_blockchain):
        # 1
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
    async def test_long_reorg(self, empty_blockchain):
        # Reorg longer than a difficulty adjustment
        # Also tests higher weight chain but lower height
        b = empty_blockchain
        num_blocks_chain_1 = 3 * test_constants.EPOCH_SUB_BLOCKS + test_constants.MAX_SUB_SLOT_SUB_BLOCKS + 10
        num_blocks_chain_2_start = test_constants.EPOCH_SUB_BLOCKS - 20
        num_blocks_chain_2 = 3 * test_constants.EPOCH_SUB_BLOCKS + test_constants.MAX_SUB_SLOT_SUB_BLOCKS + 8

        blocks = bt.get_consecutive_blocks(num_blocks_chain_1)

        for block in blocks:
            assert (await b.receive_block(block))[0] == ReceiveBlockResult.NEW_PEAK
        chain_1_height = b.get_peak().height
        chain_1_weight = b.get_peak().weight
        assert chain_1_height == (num_blocks_chain_1 - 1)

        # These blocks will have less time between them (timestamp) and therefore will make difficulty go up
        # This means that the weight will grow faster, and we can get a heavier chain with lower height
        blocks_reorg_chain = bt.get_consecutive_blocks(
            test_constants,
            num_blocks_chain_2 - num_blocks_chain_2_start,
            blocks[:num_blocks_chain_2_start],
            seed=b"2",
            time_per_sub_block=8,
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
        blocks = bt.get_consecutive_blocks(15)

        for block in blocks:
            assert (await b.receive_block(block))[0] == ReceiveBlockResult.NEW_PEAK
        assert b.get_peak().height == 14

        # Reorg to alternate chain that is 1 height longer
        found_orphan = False
        blocks_reorg_chain = bt.get_consecutive_blocks(16, [], seed=b"2")
        for reorg_block in blocks_reorg_chain:
            result, error_code, fork_height = await b.receive_block(reorg_block)
            print(reorg_block.height, result)
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
