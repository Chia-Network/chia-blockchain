import asyncio
from dataclasses import replace
from pathlib import Path

import aiosqlite
import pytest
from blspy import PrivateKey, AugSchemeMPL, G2Element
from pytest import raises

from src.full_node.block_store import BlockStore
from src.consensus.blockchain import Blockchain, ReceiveBlockResult
from src.full_node.coin_store import CoinStore
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


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="function")
async def empty_blockchain():
    """
    Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
    """
    db_path = Path("blockchain_test.db")
    if db_path.exists():
        db_path.unlink()
    connection = await aiosqlite.connect(db_path)
    coin_store = await CoinStore.create(connection)
    store = await BlockStore.create(connection)
    bc1 = await Blockchain.create(coin_store, store, test_constants)
    assert bc1.get_peak() is None

    yield bc1

    await connection.close()
    bc1.shut_down()


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
        genesis = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK
        assert empty_blockchain.get_peak().height == 0

    @pytest.mark.asyncio
    async def test_overflow_genesis(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(test_constants, 1, force_overflow=True)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_genesis_empty_slots(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False, skip_slots=3)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_overflow_genesis_empty_slots(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(test_constants, 1, force_overflow=True, skip_slots=3)[0]
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err is None
        assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_genesis_validate_1(self, empty_blockchain):
        genesis = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False)[0]
        bad_prev = bytes([1] * 32)
        genesis = recursive_replace(genesis, "foliage_sub_block.prev_sub_block_hash", bad_prev)
        result, err, _ = await empty_blockchain.receive_block(genesis, False)
        assert err == Err.INVALID_PREV_BLOCK_HASH


class TestAddingMoreBlocks:
    @pytest.mark.asyncio
    async def test_long_chain(self, empty_blockchain):
        blocks = bt.get_consecutive_blocks(test_constants, 200)
        for block in blocks:
            if (
                len(block.finished_sub_slots) > 0
                and block.finished_sub_slots[0].challenge_chain.subepoch_summary_hash is not None
            ):
                # Sub/Epoch. Try using a bad ips and difficulty to test 2m and 2n
                new_finished_ss = recursive_replace(
                    block.finished_sub_slots[0],
                    "challenge_chain.new_ips",
                    uint64(10000000),
                )
                block_bad = recursive_replace(
                    block, "finished_sub_slots", [new_finished_ss] + block.finished_sub_slots[1:]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad)
                assert err == Err.INVALID_NEW_IPS
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
                new_finished_ss_3 = recursive_replace(
                    block.finished_sub_slots[0],
                    "challenge_chain.subepoch_summary_hash",
                    bytes([0] * 32),
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
                block_bad_4 = recursive_replace(
                    block, "finished_sub_slots", [new_finished_ss_4] + block.finished_sub_slots[1:]
                )
                result, err, _ = await empty_blockchain.receive_block(block_bad_4)
                assert err == Err.INVALID_SUB_EPOCH_SUMMARY

            result, err, _ = await empty_blockchain.receive_block(block)
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK
            print(
                f"Added block {block.height} total iters {block.total_iters} new slot? {len(block.finished_sub_slots)}"
            )
        assert empty_blockchain.get_peak().height == len(blocks) - 1

    @pytest.mark.asyncio
    async def test_multiple_times(self, empty_blockchain):
        blockchain = empty_blockchain
        # Calls block tools twice
        blocks = bt.get_consecutive_blocks(test_constants, 5)
        for block in blocks:
            result, err, _ = await blockchain.receive_block(block)
            assert result == ReceiveBlockResult.NEW_PEAK

        blocks = bt.get_consecutive_blocks(test_constants, 5, block_list=blocks)
        assert len(blocks) == 10
        for block in blocks[5:]:
            result, err, _ = await blockchain.receive_block(block)
            assert result == ReceiveBlockResult.NEW_PEAK
        assert blockchain.get_peak().height == 9

    @pytest.mark.asyncio
    async def test_empty_genesis(self, empty_blockchain):
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(test_constants, 10, skip_slots=3)
        for block in blocks:
            result, err, _ = await blockchain.receive_block(block)
            assert result == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_empty_slots_non_genesis(self, empty_blockchain):
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(test_constants, 10)
        for block in blocks:
            result, err, _ = await blockchain.receive_block(block)
            assert result == ReceiveBlockResult.NEW_PEAK

        blocks = bt.get_consecutive_blocks(test_constants, 10, skip_slots=5, block_list=blocks)
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
            blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks, skip_slots=1)
            result, err, _ = await blockchain.receive_block(blocks[-1])
            assert result == ReceiveBlockResult.NEW_PEAK
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_one_sb_per_two_slots(self, empty_blockchain):
        blockchain = empty_blockchain
        num_blocks = 20
        blocks = []
        for i in range(num_blocks):  # Same thing, but 2 sub-slots per sub-block
            blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks, skip_slots=2)
            result, err, _ = await blockchain.receive_block(blocks[-1])
            assert result == ReceiveBlockResult.NEW_PEAK
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_one_sb_per_five_slots(self, empty_blockchain):
        blockchain = empty_blockchain
        num_blocks = 10
        blocks = []
        for i in range(num_blocks):  # Same thing, but 5 sub-slots per sub-block
            blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks, skip_slots=5)
            result, err, _ = await blockchain.receive_block(blocks[-1])
            assert result == ReceiveBlockResult.NEW_PEAK
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_basic_chain_overflow(self, empty_blockchain):
        blocks = bt.get_consecutive_blocks(test_constants, 5, force_overflow=True)
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
            blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks, skip_slots=2, force_overflow=True)
            result, err, _ = await blockchain.receive_block(blocks[-1])
            assert err is None
            assert result == ReceiveBlockResult.NEW_PEAK
        assert blockchain.get_peak().height == num_blocks - 1

    @pytest.mark.asyncio
    async def test_invalid_prev(self, empty_blockchain):
        # 1
        blocks = bt.get_consecutive_blocks(test_constants, 2, force_overflow=False)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_1_bad = recursive_replace(blocks[-1], "foliage_sub_block.prev_sub_block_hash", bytes([0] * 32))
        print(block_1_bad)

        result, err, _ = await empty_blockchain.receive_block(block_1_bad)
        assert result == ReceiveBlockResult.DISCONNECTED_BLOCK

    @pytest.mark.asyncio
    async def test_invalid_pospace(self, empty_blockchain):
        # 2
        blocks = bt.get_consecutive_blocks(test_constants, 2, force_overflow=False)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_1_bad = recursive_replace(blocks[-1], "reward_chain_sub_block.proof_of_space.proof", bytes([0] * 32))

        result, err, _ = await empty_blockchain.receive_block(block_1_bad)
        assert result == ReceiveBlockResult.INVALID_BLOCK
        assert err == Err.INVALID_POSPACE

    @pytest.mark.asyncio
    async def test_invalid_sub_slot_challenge_hash_genesis(self, empty_blockchain):
        # 2a
        blocks = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False, skip_slots=1)
        new_finished_ss = recursive_replace(
            blocks[0].finished_sub_slots[0],
            "challenge_chain.challenge_chain_end_of_slot_vdf.challenge_hash",
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
        blocks = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False, skip_slots=0)
        blocks = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False, skip_slots=1, block_list=blocks)
        print(blocks)
        new_finished_ss = recursive_replace(
            blocks[1].finished_sub_slots[0],
            "challenge_chain.challenge_chain_end_of_slot_vdf.challenge_hash",
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
        blocks = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False, skip_slots=0)
        blocks = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False, skip_slots=2, block_list=blocks)
        new_finished_ss = recursive_replace(
            blocks[1].finished_sub_slots[-1],
            "challenge_chain.challenge_chain_end_of_slot_vdf.challenge_hash",
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
        blocks = bt.get_consecutive_blocks(test_constants, 1, force_overflow=False, skip_slots=1)
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
        blocks = bt.get_consecutive_blocks(test_constants, 10)
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
        blocks = bt.get_consecutive_blocks(test_constants, 1)
        assert (await blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks, skip_slots=1)
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
        blocks = bt.get_consecutive_blocks(test_constants, 1)
        assert (await blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks, skip_slots=4)

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
    async def test_wrong_cc_hash_rc(self, empty_blockchain):
        # 2o
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(test_constants, 1, skip_slots=1)
        blocks = bt.get_consecutive_blocks(test_constants, 1, skip_slots=1, block_list=blocks)
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
        blocks = bt.get_consecutive_blocks(test_constants, 10)
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
                        "challenge_chain_end_of_slot_vdf.challenge_hash",
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
        blocks = bt.get_consecutive_blocks(test_constants, 10)
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
                        "end_of_slot_vdf.challenge_hash",
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
        block = bt.get_consecutive_blocks(test_constants, 1, skip_slots=2)[0]
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
        blocks = bt.get_consecutive_blocks(test_constants, 2)
        await empty_blockchain.receive_block(blocks[0])
        await empty_blockchain.receive_block(blocks[1])
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks, skip_slots=1)
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
        block = bt.get_consecutive_blocks(test_constants, 1, skip_slots=1)[0]
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
        blocks = bt.get_consecutive_blocks(test_constants, 1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        while True:
            blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks)
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
    async def test_bad_pos(self, empty_blockchain):
        # 4
        blocks = bt.get_consecutive_blocks(test_constants, 2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        block_bad = recursive_replace(blocks[-1], "reward_chain_sub_block.proof_of_space.challenge_hash", std_hash(b""))
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
        blocks = bt.get_consecutive_blocks(test_constants, 2)
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
        # 6
        blocks = []
        case_1, case_2 = False, False
        while not case_1 or not case_2:
            blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks)
            if blocks[-1].reward_chain_sub_block.signage_point_index == 0:
                case_1 = True
                block_bad = recursive_replace(blocks[-1], "reward_chain_sub_block.signage_point_index", uint8(1))
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_SP_INDEX
            else:
                case_2 = True
                block_bad = recursive_replace(blocks[-1], "reward_chain_sub_block.signage_point_index", uint8(0))
                assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_SP_INDEX
            assert (await empty_blockchain.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK

    @pytest.mark.asyncio
    async def test_epoch_overflows(self, empty_blockchain):
        # 7. TODO. This is hard to test because it requires modifying the block tools to make these special blocks
        pass

    @pytest.mark.asyncio
    async def test_bad_total_iters(self, empty_blockchain):
        # 8
        blocks = bt.get_consecutive_blocks(test_constants, 2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        block_bad = recursive_replace(
            blocks[-1], "reward_chain_sub_block.total_iters", blocks[-1].reward_chain_sub_block.total_iters + 1
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_TOTAL_ITERS

    @pytest.mark.asyncio
    async def test_bad_rc_sp_vdf(self, empty_blockchain):
        # 9
        blocks = bt.get_consecutive_blocks(test_constants, 1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        while True:
            blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks)
            if blocks[-1].reward_chain_sub_block.signage_point_index != 0:
                block_bad = recursive_replace(
                    blocks[-1], "reward_chain_sub_block.reward_chain_sp_vdf.challenge_hash", std_hash(b"1")
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
        blocks = bt.get_consecutive_blocks(test_constants, 2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_sub_block.reward_chain_sp_signature", G2Element.generator()
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_RC_SIGNATURE

    @pytest.mark.asyncio
    async def test_bad_cc_sp_vdf(self, empty_blockchain):
        # 11. Note: does not validate fully due to proof of space being validated first
        blocks = bt.get_consecutive_blocks(test_constants, 1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        while True:
            blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks)
            if blocks[-1].reward_chain_sub_block.signage_point_index != 0:
                block_bad = recursive_replace(
                    blocks[-1], "reward_chain_sub_block.challenge_chain_sp_vdf.challenge_hash", std_hash(b"1")
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
        blocks = bt.get_consecutive_blocks(test_constants, 2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad = recursive_replace(
            blocks[-1], "reward_chain_sub_block.challenge_chain_sp_signature", G2Element.generator()
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_CC_SIGNATURE

    @pytest.mark.asyncio
    async def test_is_block(self, empty_blockchain):
        # 13: TODO
        pass

    @pytest.mark.asyncio
    async def test_bad_foliage_sb_sig(self, empty_blockchain):
        # 14
        blocks = bt.get_consecutive_blocks(test_constants, 2)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        block_bad = recursive_replace(
            blocks[-1], "foliage_sub_block.foliage_sub_block_signature", G2Element.generator()
        )
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.INVALID_PLOT_SIGNATURE

    @pytest.mark.asyncio
    async def test_bad_foliage_block_sig(self, empty_blockchain):
        # 15
        blocks = bt.get_consecutive_blocks(test_constants, 1)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK

        while True:
            blocks = bt.get_consecutive_blocks(test_constants, 1, block_list=blocks)
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
        blocks = bt.get_consecutive_blocks(test_constants, 2)
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
        blocks = bt.get_consecutive_blocks(test_constants, 3)
        assert (await empty_blockchain.receive_block(blocks[0]))[0] == ReceiveBlockResult.NEW_PEAK
        assert (await empty_blockchain.receive_block(blocks[0]))[1] == ReceiveBlockResult.NEW_PEAK
        block_bad: FullBlock = recursive_replace(
            blocks[-1], "foliage_sub_block.foliage_sub_block_data.pool_target.max_height", 1
        )
        new_m = block_bad.foliage_sub_block.foliage_sub_block_data.get_hash()
        new_fsb_sig = bt.get_plot_signature(new_m, blocks[-1].reward_chain_sub_block.proof_of_space.plot_public_key)
        block_bad = recursive_replace(block_bad, "foliage_sub_block.foliage_sub_block_signature", new_fsb_sig)
        assert (await empty_blockchain.receive_block(block_bad))[1] == Err.OLD_POOL_TARGET


#
# # class TestBlockValidation:
#     @pytest.fixture(scope="module")
#     async def initial_blockchain(self):
#         """
#         Provides a list of 10 valid blocks, as well as a blockchain with 9 blocks added to it.
#         """
#         blocks = bt.get_consecutive_blocks(test_constants, 10, [], 10)
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         store = await BlockStore.create(connection)
#         coin_store = await CoinStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#         for i in range(1, 9):
#             result, removed, error_code = await b.receive_block(blocks[i])
#             assert result == ReceiveBlockResult.NEW_TIP
#         yield (blocks, b)
#
#         await connection.close()
#
#     @pytest.mark.asyncio
#     async def test_prev_pointer(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 HeaderData(
#                     blocks[9].header.data.height,
#                     bytes([1] * 32),
#                     blocks[9].header.data.timestamp,
#                     blocks[9].header.data.filter_hash,
#                     blocks[9].header.data.proof_of_space_hash,
#                     blocks[9].header.data.weight,
#                     blocks[9].header.data.total_iters,
#                     blocks[9].header.data.additions_root,
#                     blocks[9].header.data.removals_root,
#                     blocks[9].header.data.farmer_rewards_puzzle_hash,
#                     blocks[9].header.data.total_transaction_fees,
#                     blocks[9].header.data.pool_target,
#                     blocks[9].header.data.aggregated_signature,
#                     blocks[9].header.data.cost,
#                     blocks[9].header.data.extension_data,
#                     blocks[9].header.data.generator_hash,
#                 ),
#                 blocks[9].header.plot_signature,
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert (result) == ReceiveBlockResult.DISCONNECTED_BLOCK
#         assert error_code is None
#
#     @pytest.mark.asyncio
#     async def test_prev_block(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         block_bad = blocks[10]
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert (result) == ReceiveBlockResult.DISCONNECTED_BLOCK
#         assert error_code is None
#
#     @pytest.mark.asyncio
#     async def test_timestamp(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         # Time too far in the past
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp - 1000,
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert (result) == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.TIMESTAMP_TOO_FAR_IN_PAST
#
#         # Time too far in the future
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             uint64(int(time.time() + 3600 * 3)),
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert (result) == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.TIMESTAMP_TOO_FAR_IN_FUTURE
#
#     @pytest.mark.asyncio
#     async def test_generator_hash(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             bytes([1] * 32),
#         )
#
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_TRANSACTIONS_GENERATOR_HASH
#
#     @pytest.mark.asyncio
#     async def test_plot_signature(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         # Time too far in the past
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 blocks[9].header.data,
#                 AugSchemeMPL.sign(AugSchemeMPL.key_gen(bytes([5] * 32)), token_bytes(32)),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_PLOT_SIGNATURE
#
#     @pytest.mark.asyncio
#     async def test_invalid_pos(self, initial_blockchain):
#         blocks, b = initial_blockchain
#
#         bad_pos_proof = bytearray([i for i in blocks[9].proof_of_space.proof])
#         bad_pos_proof[0] = uint8((bad_pos_proof[0] + 1) % 256)
#         bad_pos = ProofOfSpace(
#             blocks[9].proof_of_space.challenge_hash,
#             blocks[9].proof_of_space.pool_public_key,
#             blocks[9].proof_of_space.plot_public_key,
#             blocks[9].proof_of_space.size,
#             bytes(bad_pos_proof),
#         )
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             bad_pos.get_hash(),
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         # Proof of space invalid
#         block_bad = FullBlock(
#             bad_pos,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_POSPACE
#
#     @pytest.mark.asyncio
#     async def test_invalid_pos_hash(self, initial_blockchain):
#         blocks, b = initial_blockchain
#
#         bad_pos_proof = bytearray([i for i in blocks[9].proof_of_space.proof])
#         bad_pos_proof[0] = uint8((bad_pos_proof[0] + 1) % 256)
#         bad_pos = ProofOfSpace(
#             blocks[9].proof_of_space.challenge_hash,
#             blocks[9].proof_of_space.pool_public_key,
#             blocks[9].proof_of_space.plot_public_key,
#             blocks[9].proof_of_space.size,
#             bytes(bad_pos_proof),
#         )
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             bad_pos.get_hash(),
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         # Proof of space has invalid
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_POSPACE_HASH
#
#     @pytest.mark.asyncio
#     async def test_invalid_filter_hash(self, initial_blockchain):
#         blocks, b = initial_blockchain
#
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             bytes32(bytes([3] * 32)),
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_TRANSACTIONS_FILTER_HASH
#
#     @pytest.mark.asyncio
#     async def test_invalid_max_height(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         print(blocks[9].header)
#         pool_target = PoolTarget(blocks[9].header.data.pool_target.puzzle_hash, uint32(8))
#         agg_sig = bt.get_pool_key_signature(pool_target, blocks[9].proof_of_space.pool_public_key)
#         assert agg_sig is not None
#
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             pool_target,
#             agg_sig,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_POOL_TARGET
#
#     @pytest.mark.asyncio
#     async def test_invalid_pool_sig(self, initial_blockchain):
#         blocks, b = initial_blockchain
#         pool_target = PoolTarget(blocks[9].header.data.pool_target.puzzle_hash, uint32(10))
#         agg_sig = bt.get_pool_key_signature(pool_target, blocks[9].proof_of_space.pool_public_key)
#         assert agg_sig is not None
#
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees,
#             blocks[9].header.data.pool_target,
#             agg_sig,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.BAD_AGGREGATE_SIGNATURE
#
#     @pytest.mark.asyncio
#     async def test_invalid_fees_amount(self, initial_blockchain):
#         blocks, b = initial_blockchain
#
#         new_header_data = HeaderData(
#             blocks[9].header.data.height,
#             blocks[9].header.data.prev_header_hash,
#             blocks[9].header.data.timestamp,
#             blocks[9].header.data.filter_hash,
#             blocks[9].header.data.proof_of_space_hash,
#             blocks[9].header.data.weight,
#             blocks[9].header.data.total_iters,
#             blocks[9].header.data.additions_root,
#             blocks[9].header.data.removals_root,
#             blocks[9].header.data.farmer_rewards_puzzle_hash,
#             blocks[9].header.data.total_transaction_fees + 1,
#             blocks[9].header.data.pool_target,
#             blocks[9].header.data.aggregated_signature,
#             blocks[9].header.data.cost,
#             blocks[9].header.data.extension_data,
#             blocks[9].header.data.generator_hash,
#         )
#
#         # Coinbase amount invalid
#         block_bad = FullBlock(
#             blocks[9].proof_of_space,
#             blocks[9].proof_of_time,
#             Header(
#                 new_header_data,
#                 bt.get_plot_signature(new_header_data, blocks[9].proof_of_space.plot_public_key),
#             ),
#             blocks[9].transactions_generator,
#             blocks[9].transactions_filter,
#         )
#         result, removed, error_code = await b.receive_block(block_bad)
#         assert result == ReceiveBlockResult.INVALID_BLOCK
#         assert error_code == Err.INVALID_BLOCK_FEE_AMOUNT
#
#     @pytest.mark.asyncio
#     async def test_difficulty_change(self):
#         num_blocks = 10
#         # Make it much faster than target time, 1 second instead of 10 seconds, so difficulty goes up
#         blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 1)
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#         for i in range(1, num_blocks):
#             result, removed, error_code = await b.receive_block(blocks[i])
#             assert result == ReceiveBlockResult.NEW_TIP
#             assert error_code is None
#
#         diff_6 = b.get_next_difficulty(blocks[5].header)
#         diff_7 = b.get_next_difficulty(blocks[6].header)
#         diff_8 = b.get_next_difficulty(blocks[7].header)
#         # diff_9 = b.get_next_difficulty(blocks[8].header)
#
#         assert diff_6 == diff_7
#         assert diff_8 > diff_7
#         assert (diff_8 / diff_7) <= test_constants.DIFFICULTY_FACTOR
#         assert (b.get_next_min_iters(blocks[1])) == test_constants.MIN_ITERS_STARTING
#         assert (b.get_next_min_iters(blocks[6])) == (b.get_next_min_iters(blocks[5]))
#         assert (b.get_next_min_iters(blocks[7])) > (b.get_next_min_iters(blocks[6]))
#         assert (b.get_next_min_iters(blocks[8])) == (b.get_next_min_iters(blocks[7]))
#
#         await connection.close()
#         b.shut_down()
#
#
# class TestReorgs:
#     @pytest.mark.asyncio
#     async def test_basic_reorg(self):
#         blocks = bt.get_consecutive_blocks(test_constants, 15, [], 9)
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#
#         for i in range(1, len(blocks)):
#             await b.receive_block(blocks[i])
#         assert b.get_current_tips()[0].height == 15
#
#         blocks_reorg_chain = bt.get_consecutive_blocks(test_constants, 7, blocks[:10], 9, b"2")
#         for i in range(1, len(blocks_reorg_chain)):
#             reorg_block = blocks_reorg_chain[i]
#             result, removed, error_code = await b.receive_block(reorg_block)
#             if reorg_block.height < 10:
#                 assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
#             elif reorg_block.height < 14:
#                 assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
#             elif reorg_block.height >= 15:
#                 assert result == ReceiveBlockResult.NEW_TIP
#             assert error_code is None
#         assert b.get_current_tips()[0].height == 16
#
#         await connection.close()
#         b.shut_down()
#
#     @pytest.mark.asyncio
#     async def test_reorg_from_genesis(self):
#         blocks = bt.get_consecutive_blocks(test_constants, 20, [], 9, b"0")
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#         for i in range(1, len(blocks)):
#             await b.receive_block(blocks[i])
#         assert b.get_current_tips()[0].height == 20
#
#         # Reorg from genesis
#         blocks_reorg_chain = bt.get_consecutive_blocks(test_constants, 21, [blocks[0]], 9, b"3")
#         for i in range(1, len(blocks_reorg_chain)):
#             reorg_block = blocks_reorg_chain[i]
#             result, removed, error_code = await b.receive_block(reorg_block)
#             if reorg_block.height == 0:
#                 assert result == ReceiveBlockResult.ALREADY_HAVE_BLOCK
#             elif reorg_block.height < 19:
#                 assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
#             else:
#                 assert result == ReceiveBlockResult.NEW_TIP
#         assert b.get_current_tips()[0].height == 21
#
#         # Reorg back to original branch
#         blocks_reorg_chain_2 = bt.get_consecutive_blocks(test_constants, 3, blocks[:-1], 9, b"4")
#         result, _, error_code = await b.receive_block(blocks_reorg_chain_2[20])
#         assert result == ReceiveBlockResult.ADDED_AS_ORPHAN
#
#         result, _, error_code = await b.receive_block(blocks_reorg_chain_2[21])
#         assert result == ReceiveBlockResult.NEW_TIP
#
#         result, _, error_code = await b.receive_block(blocks_reorg_chain_2[22])
#         assert result == ReceiveBlockResult.NEW_TIP
#
#         await connection.close()
#         b.shut_down()
#
#     @pytest.mark.asyncio
#     async def test_lca(self):
#         blocks = bt.get_consecutive_blocks(test_constants, 5, [], 9, b"0")
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#         for i in range(1, len(blocks)):
#             await b.receive_block(blocks[i])
#
#         assert b.lca_block.header_hash == blocks[3].header_hash
#         block_5_2 = bt.get_consecutive_blocks(test_constants, 1, blocks[:5], 9, b"1")
#         block_5_3 = bt.get_consecutive_blocks(test_constants, 1, blocks[:5], 9, b"2")
#
#         await b.receive_block(block_5_2[5])
#         assert b.lca_block.header_hash == blocks[4].header_hash
#         await b.receive_block(block_5_3[5])
#         assert b.lca_block.header_hash == blocks[4].header_hash
#
#         reorg = bt.get_consecutive_blocks(test_constants, 6, [], 9, b"3")
#         for i in range(1, len(reorg)):
#             await b.receive_block(reorg[i])
#         assert b.lca_block.header_hash == blocks[0].header_hash
#
#         await connection.close()
#         b.shut_down()
#
#     @pytest.mark.asyncio
#     async def test_find_fork_point(self):
#         blocks = bt.get_consecutive_blocks(test_constants, 10, [], 9, b"7")
#         blocks_2 = bt.get_consecutive_blocks(test_constants, 6, blocks[:5], 9, b"8")
#         blocks_3 = bt.get_consecutive_blocks(test_constants, 8, blocks[:3], 9, b"9")
#
#         blocks_reorg = bt.get_consecutive_blocks(test_constants, 3, blocks[:9], 9, b"9")
#
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#         for i in range(1, len(blocks)):
#             await b.receive_block(blocks[i])
#
#         for i in range(1, len(blocks_2)):
#             await b.receive_block(blocks_2[i])
#
#         assert find_fork_point_in_chain(b.headers, blocks[10].header, blocks_2[10].header) == 4
#
#         for i in range(1, len(blocks_3)):
#             await b.receive_block(blocks_3[i])
#
#         assert find_fork_point_in_chain(b.headers, blocks[10].header, blocks_3[10].header) == 2
#
#         assert b.lca_block.data == blocks[2].header.data
#
#         for i in range(1, len(blocks_reorg)):
#             await b.receive_block(blocks_reorg[i])
#
#         assert find_fork_point_in_chain(b.headers, blocks[10].header, blocks_reorg[10].header) == 8
#         assert find_fork_point_in_chain(b.headers, blocks_2[10].header, blocks_reorg[10].header) == 4
#         assert b.lca_block.data == blocks[4].header.data
#         await connection.close()
#         b.shut_down()
#
#     @pytest.mark.asyncio
#     async def test_get_header_hashes(self):
#         blocks = bt.get_consecutive_blocks(test_constants, 5, [], 9, b"0")
#         db_path = Path("blockchain_test.db")
#         if db_path.exists():
#             db_path.unlink()
#         connection = await aiosqlite.connect(db_path)
#         coin_store = await CoinStore.create(connection)
#         store = await BlockStore.create(connection)
#         b: Blockchain = await Blockchain.create(coin_store, store, test_constants)
#
#         for i in range(1, len(blocks)):
#             await b.receive_block(blocks[i])
#         header_hashes = b.get_header_hashes(blocks[-1].header_hash)
#         assert len(header_hashes) == 6
#         assert header_hashes == [block.header_hash for block in blocks]
#
#         await connection.close()
#         b.shut_down()
