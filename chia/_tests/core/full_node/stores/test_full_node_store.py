from __future__ import annotations

import logging
import random
from typing import AsyncIterator, Dict, List, Optional, Tuple

import pytest

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block, _validate_and_add_block_no_error
from chia._tests.util.blockchain import create_blockchain
from chia._tests.util.blockchain_mock import BlockchainMock
from chia.consensus.blockchain import AddBlockResult, Blockchain
from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.find_fork_point import find_fork_point_in_chain
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.consensus.pot_iterations import is_overflow_block
from chia.full_node.full_node_store import FullNodeStore, UnfinishedBlockEntry, find_best_block
from chia.full_node.signage_point import SignagePoint
from chia.protocols import timelord_protocol
from chia.protocols.timelord_protocol import NewInfusionPointVDF
from chia.simulator.block_tools import BlockTools, create_block_tools_async, get_signage_point, make_unfinished_block
from chia.simulator.keyring import TempKeyring
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64, uint128
from chia.util.recursive_replace import recursive_replace

log = logging.getLogger(__name__)


@pytest.fixture(scope="function")
async def custom_block_tools(blockchain_constants: ConsensusConstants) -> AsyncIterator[BlockTools]:
    with TempKeyring() as keychain:
        patched_constants = blockchain_constants.replace(
            DISCRIMINANT_SIZE_BITS=uint16(32),
            SUB_SLOT_ITERS_STARTING=uint64(2**12),
        )
        yield await create_block_tools_async(constants=patched_constants, keychain=keychain)


@pytest.fixture(scope="function")
async def empty_blockchain(db_version: int, blockchain_constants: ConsensusConstants) -> AsyncIterator[Blockchain]:
    patched_constants = blockchain_constants.replace(
        DISCRIMINANT_SIZE_BITS=uint16(32),
        SUB_SLOT_ITERS_STARTING=uint64(2**12),
    )
    async with create_blockchain(patched_constants, db_version) as (bc1, db_wrapper):
        yield bc1


@pytest.fixture(scope="function")
async def empty_blockchain_with_original_constants(
    db_version: int, blockchain_constants: ConsensusConstants
) -> AsyncIterator[Blockchain]:
    async with create_blockchain(blockchain_constants, db_version) as (bc1, db_wrapper):
        yield bc1


@pytest.mark.anyio
@pytest.mark.parametrize("num_duplicates", [0, 1, 3, 10])
@pytest.mark.parametrize("include_none", [True, False])
async def test_unfinished_block_rank(
    empty_blockchain: Blockchain,
    custom_block_tools: BlockTools,
    seeded_random: random.Random,
    num_duplicates: int,
    include_none: bool,
) -> None:
    blocks = custom_block_tools.get_consecutive_blocks(
        1,
        guarantee_transaction_block=True,
    )

    assert blocks[-1].is_transaction_block()
    store = FullNodeStore(custom_block_tools.constants)
    unf: UnfinishedBlock = make_unfinished_block(blocks[-1], custom_block_tools.constants)

    # create variants of the unfinished block, where all we do is to change
    # the foliage_transaction_block_hash. As if they all had different foliage,
    # but the same reward block hash (i.e. the same proof-of-space)
    unfinished: List[UnfinishedBlock] = [
        recursive_replace(unf, "foliage.foliage_transaction_block_hash", bytes32([idx + 4] * 32))
        for idx in range(num_duplicates)
    ]

    if include_none:
        unfinished.append(recursive_replace(unf, "foliage.foliage_transaction_block_hash", None))

    # shuffle them to ensure the order we add them to the store isn't relevant
    seeded_random.shuffle(unfinished)
    for new_unf in unfinished:
        store.add_unfinished_block(
            uint32(2), new_unf, PreValidationResult(None, uint64(123532), None, False, uint32(0))
        )

    # now ask for "the" unfinished block given the proof-of-space.
    # the FullNodeStore should return the one with the lowest foliage tx block
    # hash. We prefer a block with foliage over one without (i.e. where foliage
    # is None)
    if num_duplicates == 0 and not include_none:
        assert store.get_unfinished_block(unf.partial_hash) is None
    else:
        best_unf = store.get_unfinished_block(unf.partial_hash)
        assert best_unf is not None
        if num_duplicates == 0:
            # if a block without foliage is our only option, that's what we get
            assert best_unf.foliage.foliage_transaction_block_hash is None
        else:
            assert best_unf.foliage.foliage_transaction_block_hash == bytes32([4] * 32)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.parametrize(
    "blocks,expected",
    [
        ([(None, True), (1, True), (2, True), (3, True)], 1),
        ([(None, True), (1, False), (2, True), (3, True)], 2),
        ([(None, True), (1, False), (2, False), (3, True)], 3),
        ([(None, True)], None),
        ([], None),
        ([(4, True), (5, True), (3, True)], 3),
        ([(4, True)], 4),
        ([(4, False)], None),
    ],
)
async def test_find_best_block(
    seeded_random: random.Random,
    blocks: List[Tuple[Optional[int], bool]],
    expected: Optional[int],
    default_400_blocks: List[FullBlock],
    bt: BlockTools,
) -> None:
    result: Dict[Optional[bytes32], UnfinishedBlockEntry] = {}
    i = 0
    for b, with_unf in blocks:
        unf: Optional[UnfinishedBlock]
        if with_unf:
            unf = make_unfinished_block(default_400_blocks[i], bt.constants)
            i += 1
        else:
            unf = None
        if b is None:
            result[b] = UnfinishedBlockEntry(unf, None, uint32(123))
        else:
            result[bytes32(b.to_bytes(1, "big") * 32)] = UnfinishedBlockEntry(unf, None, uint32(123))

    foliage_hash, block = find_best_block(result)
    if expected is None:
        assert foliage_hash is None
    else:
        assert foliage_hash == bytes32(expected.to_bytes(1, "big") * 32)


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
@pytest.mark.parametrize("normalized_to_identity", [False, True])
async def test_basic_store(
    empty_blockchain: Blockchain,
    custom_block_tools: BlockTools,
    normalized_to_identity: bool,
    seeded_random: random.Random,
) -> None:
    blockchain = empty_blockchain
    blocks = custom_block_tools.get_consecutive_blocks(
        10,
        seed=b"1234",
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
    )

    store = FullNodeStore(empty_blockchain.constants)

    unfinished_blocks = []
    for block in blocks:
        unfinished_blocks.append(
            UnfinishedBlock(
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
        )

    # Add/get candidate block
    assert store.get_candidate_block(unfinished_blocks[0].get_hash()) is None
    for height, unf_block in enumerate(unfinished_blocks):
        store.add_candidate_block(unf_block.get_hash(), uint32(height), unf_block)

    candidate = store.get_candidate_block(unfinished_blocks[4].get_hash())
    assert candidate is not None
    assert candidate[1] == unfinished_blocks[4]
    store.clear_candidate_blocks_below(uint32(8))
    assert store.get_candidate_block(unfinished_blocks[5].get_hash()) is None
    assert store.get_candidate_block(unfinished_blocks[8].get_hash()) is not None

    # Test seen unfinished blocks
    h_hash_1 = bytes32.random(seeded_random)
    assert not store.seen_unfinished_block(h_hash_1)
    assert store.seen_unfinished_block(h_hash_1)
    # this will crowd out h_hash_1
    for _ in range(store.max_seen_unfinished_blocks):
        store.seen_unfinished_block(bytes32.random(seeded_random))
    assert not store.seen_unfinished_block(h_hash_1)

    # Add/get unfinished block
    for height, unf_block in enumerate(unfinished_blocks):
        assert store.get_unfinished_block(unf_block.partial_hash) is None
        assert store.get_unfinished_block2(unf_block.partial_hash, None) == (None, 0, False)
        store.add_unfinished_block(
            uint32(height), unf_block, PreValidationResult(None, uint64(123532), None, False, uint32(0))
        )
        assert store.get_unfinished_block(unf_block.partial_hash) == unf_block
        assert store.get_unfinished_block2(
            unf_block.partial_hash, unf_block.foliage.foliage_transaction_block_hash
        ) == (unf_block, 1, False)

        foliage_hash = unf_block.foliage.foliage_transaction_block_hash
        dummy_hash = bytes32.fromhex("abababababababababababababababababababababababababababababababab")
        assert store.get_unfinished_block2(unf_block.partial_hash, dummy_hash) == (
            None,
            1,
            foliage_hash is not None and dummy_hash > foliage_hash,
        )

        # only transaction blocks have PreValidationResults
        # so get_unfinished_block_result requires the foliage hash
        if unf_block.foliage.foliage_transaction_block_hash is not None:
            entry = store.get_unfinished_block_result(
                unf_block.partial_hash, unf_block.foliage.foliage_transaction_block_hash
            )
            assert entry is not None
            ublock = entry.result
            assert ublock is not None and ublock.required_iters == uint64(123532)
            entry = store.get_unfinished_block_result(
                unf_block.partial_hash, unf_block.foliage.foliage_transaction_block_hash
            )
            assert entry is not None
            ublock = entry.result

            assert ublock is not None and ublock.required_iters == uint64(123532)

        store.remove_unfinished_block(unf_block.partial_hash)
        assert store.get_unfinished_block(unf_block.partial_hash) is None
        assert store.get_unfinished_block2(
            unf_block.partial_hash, unf_block.foliage.foliage_transaction_block_hash
        ) == (None, 0, False)

    # Multiple unfinished blocks with colliding partial hashes
    unf1 = unfinished_blocks[0]
    unf2 = unf1.replace(foliage=unfinished_blocks[1].foliage)
    unf3 = unf1.replace(foliage=unfinished_blocks[2].foliage)
    unf4 = unf1.replace(foliage=unfinished_blocks[3].foliage)

    # we have none of these blocks in the store
    for unf_block in [unf1, unf2, unf3, unf4]:
        assert store.get_unfinished_block(unf_block.partial_hash) is None
        assert store.get_unfinished_block2(unf_block.partial_hash, None) == (None, 0, False)

    height = uint32(1)
    # all blocks without a foliage all collapse down into being the same
    assert unf1.foliage.foliage_transaction_block_hash is not None
    assert unf2.foliage.foliage_transaction_block_hash is None
    assert unf3.foliage.foliage_transaction_block_hash is None
    assert unf4.foliage.foliage_transaction_block_hash is None
    for val, unf_block in enumerate([unf1, unf2, unf3, unf4]):
        store.add_unfinished_block(
            uint32(height), unf_block, PreValidationResult(None, uint64(val), None, False, uint32(0))
        )

    # when not specifying a foliage hash, you get the "best" one
    # best is defined as the lowest foliage hash
    assert store.get_unfinished_block(unf1.partial_hash) == unf1
    assert store.get_unfinished_block2(unf1.partial_hash, unf1.foliage.foliage_transaction_block_hash) == (
        unf1,
        2,
        False,
    )
    # unf4 overwrote unf2 and unf3 (that's why there are only 2 blocks stored).
    # however, there's no way to explicitly request the block with None foliage
    # since when specifying None, you always get the first one. unf1 in this
    # case
    assert store.get_unfinished_block2(unf2.partial_hash, unf2.foliage.foliage_transaction_block_hash) == (
        unf1,
        2,
        False,
    )
    assert store.get_unfinished_block2(unf3.partial_hash, unf3.foliage.foliage_transaction_block_hash) == (
        unf1,
        2,
        False,
    )
    assert store.get_unfinished_block2(unf4.partial_hash, unf4.foliage.foliage_transaction_block_hash) == (
        unf1,
        2,
        False,
    )
    assert store.get_unfinished_block2(unf4.partial_hash, None) == (unf1, 2, False)

    entry = store.get_unfinished_block_result(unf1.partial_hash, unf1.foliage.foliage_transaction_block_hash)
    assert entry is not None
    ublock = entry.result
    assert ublock is not None and ublock.required_iters == uint64(0)
    entry = store.get_unfinished_block_result(unf1.partial_hash, unf1.foliage.foliage_transaction_block_hash)
    assert entry is not None
    ublock = entry.result
    assert ublock is not None and ublock.required_iters == uint64(0)
    # still, when not specifying a foliage hash, you just get the first ublock
    entry = store.get_unfinished_block_result(unf1.partial_hash, unf1.foliage.foliage_transaction_block_hash)
    assert entry is not None
    ublock = entry.result
    assert ublock is not None and ublock.required_iters == uint64(0)

    # negative test cases
    assert store.get_unfinished_block_result(bytes32([1] * 32), bytes32([2] * 32)) is None

    blocks = custom_block_tools.get_consecutive_blocks(
        1,
        skip_slots=5,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
    )
    sub_slots = blocks[0].finished_sub_slots
    assert len(sub_slots) == 5

    assert (
        store.get_finished_sub_slots(
            BlockchainMock({}),
            None,
            sub_slots[0].challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
        )
        == []
    )
    # Test adding non-connecting sub-slots genesis
    assert store.get_sub_slot(empty_blockchain.constants.GENESIS_CHALLENGE) is None
    assert store.get_sub_slot(sub_slots[0].challenge_chain.get_hash()) is None
    assert store.get_sub_slot(sub_slots[1].challenge_chain.get_hash()) is None
    next_sub_slot_iters = custom_block_tools.constants.SUB_SLOT_ITERS_STARTING
    next_difficulty = custom_block_tools.constants.DIFFICULTY_STARTING
    assert (
        store.new_finished_sub_slot(sub_slots[1], blockchain, None, next_sub_slot_iters, next_difficulty, None) is None
    )
    assert (
        store.new_finished_sub_slot(sub_slots[2], blockchain, None, next_sub_slot_iters, next_difficulty, None) is None
    )

    # Test adding sub-slots after genesis
    assert (
        store.new_finished_sub_slot(sub_slots[0], blockchain, None, next_sub_slot_iters, next_difficulty, None)
        is not None
    )
    sub_slot = store.get_sub_slot(sub_slots[0].challenge_chain.get_hash())
    assert sub_slot is not None
    assert sub_slot[0] == sub_slots[0]
    assert store.get_sub_slot(sub_slots[1].challenge_chain.get_hash()) is None
    assert (
        store.new_finished_sub_slot(sub_slots[1], blockchain, None, next_sub_slot_iters, next_difficulty, None)
        is not None
    )
    for i in range(len(sub_slots)):
        assert (
            store.new_finished_sub_slot(sub_slots[i], blockchain, None, next_sub_slot_iters, next_difficulty, None)
            is not None
        )
        slot_i = store.get_sub_slot(sub_slots[i].challenge_chain.get_hash())
        assert slot_i is not None
        assert slot_i[0] == sub_slots[i]

    assert store.get_finished_sub_slots(BlockchainMock({}), None, sub_slots[-1].challenge_chain.get_hash()) == sub_slots
    assert store.get_finished_sub_slots(BlockchainMock({}), None, std_hash(b"not a valid hash")) is None

    assert (
        store.get_finished_sub_slots(BlockchainMock({}), None, sub_slots[-2].challenge_chain.get_hash())
        == sub_slots[:-1]
    )

    # Test adding genesis peak
    await _validate_and_add_block(blockchain, blocks[0])
    peak = blockchain.get_peak()
    assert peak is not None
    peak_full_block = await blockchain.get_full_peak()
    assert peak_full_block is not None
    next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
        blockchain.constants, False, peak, blockchain
    )

    if peak.overflow:
        store.new_peak(
            peak,
            peak_full_block,
            sub_slots[-2],
            sub_slots[-1],
            None,
            blockchain,
            next_sub_slot_iters,
            next_difficulty,
        )
    else:
        store.new_peak(
            peak, peak_full_block, None, sub_slots[-1], None, blockchain, next_sub_slot_iters, next_difficulty
        )

    assert store.get_sub_slot(sub_slots[0].challenge_chain.get_hash()) is None
    assert store.get_sub_slot(sub_slots[1].challenge_chain.get_hash()) is None
    assert store.get_sub_slot(sub_slots[2].challenge_chain.get_hash()) is None
    if peak.overflow:
        slot_3 = store.get_sub_slot(sub_slots[3].challenge_chain.get_hash())
        assert slot_3 is not None
        assert slot_3[0] == sub_slots[3]
    else:
        assert store.get_sub_slot(sub_slots[3].challenge_chain.get_hash()) is None

    slot_4 = store.get_sub_slot(sub_slots[4].challenge_chain.get_hash())
    assert slot_4 is not None
    assert slot_4[0] == sub_slots[4]

    assert (
        store.get_finished_sub_slots(
            blockchain,
            peak,
            sub_slots[-1].challenge_chain.get_hash(),
        )
        == []
    )

    # Test adding non genesis peak directly
    blocks = custom_block_tools.get_consecutive_blocks(
        2,
        skip_slots=2,
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
    )
    blocks = custom_block_tools.get_consecutive_blocks(
        3,
        block_list_input=blocks,
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
    )

    for block in blocks:
        await _validate_and_add_block_no_error(blockchain, block)
        sb = blockchain.block_record(block.header_hash)
        next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
            blockchain.constants, False, sb, blockchain
        )
        result = await blockchain.get_sp_and_ip_sub_slots(block.header_hash)
        assert result is not None
        sp_sub_slot, ip_sub_slot = result
        res = store.new_peak(
            sb, block, sp_sub_slot, ip_sub_slot, None, blockchain, next_sub_slot_iters, next_difficulty
        )
        assert res.added_eos is None

    # Add reorg blocks
    blocks_reorg = custom_block_tools.get_consecutive_blocks(
        20,
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
    )
    for block in blocks_reorg:
        peak = blockchain.get_peak()
        assert peak is not None

        await _validate_and_add_block_no_error(blockchain, block)

        peak_here = blockchain.get_peak()
        assert peak_here is not None
        if peak_here.header_hash == block.header_hash:
            sb = blockchain.block_record(block.header_hash)
            fork = await find_fork_point_in_chain(blockchain, peak, blockchain.block_record(sb.header_hash))
            if fork > 0:
                fork_block = blockchain.height_to_block_record(uint32(fork))
            else:
                fork_block = None
            result = await blockchain.get_sp_and_ip_sub_slots(block.header_hash)
            assert result is not None
            sp_sub_slot, ip_sub_slot = result
            next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
                blockchain.constants, False, sb, blockchain
            )
            res = store.new_peak(
                sb, block, sp_sub_slot, ip_sub_slot, fork_block, blockchain, next_sub_slot_iters, next_difficulty
            )
            assert res.added_eos is None

    # Add slots to the end
    blocks_2 = custom_block_tools.get_consecutive_blocks(
        1,
        block_list_input=blocks_reorg,
        skip_slots=2,
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
    )
    peak = blockchain.get_peak()
    for slot in blocks_2[-1].finished_sub_slots:
        next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
            blockchain.constants, True, peak, blockchain
        )

        store.new_finished_sub_slot(
            slot,
            blockchain,
            blockchain.get_peak(),
            next_sub_slot_iters,
            next_difficulty,
            await blockchain.get_full_peak(),
        )

    assert store.get_sub_slot(sub_slots[3].challenge_chain.get_hash()) is None
    assert store.get_sub_slot(sub_slots[4].challenge_chain.get_hash()) is None

    # Test adding signage point
    peak = blockchain.get_peak()
    assert peak is not None
    ss_start_iters = peak.ip_sub_slot_total_iters(custom_block_tools.constants)
    for i in range(
        1, custom_block_tools.constants.NUM_SPS_SUB_SLOT - custom_block_tools.constants.NUM_SP_INTERVALS_EXTRA
    ):
        sp = get_signage_point(
            custom_block_tools.constants,
            blockchain,
            peak,
            ss_start_iters,
            uint8(i),
            [],
            peak.sub_slot_iters,
        )
        assert store.new_signage_point(uint8(i), blockchain, peak, peak.sub_slot_iters, sp)

    blocks = blocks_reorg
    while True:
        blocks = custom_block_tools.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )
        await _validate_and_add_block(blockchain, blocks[-1])
        peak_here = blockchain.get_peak()
        assert peak_here is not None
        if peak_here.header_hash == blocks[-1].header_hash:
            sb = blockchain.block_record(blocks[-1].header_hash)
            fork = await find_fork_point_in_chain(blockchain, peak, blockchain.block_record(sb.header_hash))
            if fork > 0:
                fork_block = blockchain.height_to_block_record(uint32(fork))
            else:
                fork_block = None
            result = await blockchain.get_sp_and_ip_sub_slots(blocks[-1].header_hash)
            assert result is not None
            sp_sub_slot, ip_sub_slot = result

            next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
                blockchain.constants, False, sb, blockchain
            )
            res = store.new_peak(
                sb,
                blocks[-1],
                sp_sub_slot,
                ip_sub_slot,
                fork_block,
                blockchain,
                next_sub_slot_iters,
                next_difficulty,
            )
            assert res.added_eos is None
            if sb.overflow and sp_sub_slot is not None:
                assert sp_sub_slot != ip_sub_slot
                break

    peak = blockchain.get_peak()
    assert peak is not None
    assert peak.overflow
    # Overflow peak should result in 2 finished sub slots
    assert len(store.finished_sub_slots) == 2

    # Add slots to the end, except for the last one, which we will use to test invalid SP
    blocks_2 = custom_block_tools.get_consecutive_blocks(
        1,
        block_list_input=blocks,
        skip_slots=3,
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
    )
    for slot in blocks_2[-1].finished_sub_slots[:-1]:
        next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
            blockchain.constants, True, peak, blockchain
        )

        store.new_finished_sub_slot(
            slot,
            blockchain,
            blockchain.get_peak(),
            next_sub_slot_iters,
            next_difficulty,
            await blockchain.get_full_peak(),
        )
    finished_sub_slots = blocks_2[-1].finished_sub_slots
    assert len(store.finished_sub_slots) == 4

    # Test adding signage points for overflow blocks (sp_sub_slot)
    ss_start_iters = peak.sp_sub_slot_total_iters(custom_block_tools.constants)
    # for i in range(peak.signage_point_index, custom_block_tools.constants.NUM_SPS_SUB_SLOT):
    #     if i < peak.signage_point_index:
    #         continue
    #     latest = peak
    #     while latest.total_iters > peak.sp_total_iters(custom_block_tools.constants):
    #         latest = blockchain.blocks[latest.prev_hash]
    #     sp = get_signage_point(
    #         custom_block_tools.constants,
    #         blockchain.blocks,
    #         latest,
    #         ss_start_iters,
    #         uint8(i),
    #         [],
    #         peak.sub_slot_iters,
    #     )
    #     assert store.new_signage_point(i, blockchain.blocks, peak, peak.sub_slot_iters, sp)

    # Test adding signage points for overflow blocks (ip_sub_slot)
    for i in range(
        1, custom_block_tools.constants.NUM_SPS_SUB_SLOT - custom_block_tools.constants.NUM_SP_INTERVALS_EXTRA
    ):
        sp = get_signage_point(
            custom_block_tools.constants,
            blockchain,
            peak,
            peak.ip_sub_slot_total_iters(custom_block_tools.constants),
            uint8(i),
            [],
            peak.sub_slot_iters,
        )
        assert store.new_signage_point(uint8(i), blockchain, peak, peak.sub_slot_iters, sp)

    # Test adding future signage point, a few slots forward (good)
    saved_sp_hash = None
    for slot_offset in range(1, len(finished_sub_slots)):
        for i in range(
            1,
            custom_block_tools.constants.NUM_SPS_SUB_SLOT - custom_block_tools.constants.NUM_SP_INTERVALS_EXTRA,
        ):
            sp = get_signage_point(
                custom_block_tools.constants,
                blockchain,
                peak,
                uint128(peak.ip_sub_slot_total_iters(custom_block_tools.constants) + slot_offset * peak.sub_slot_iters),
                uint8(i),
                finished_sub_slots[:slot_offset],
                peak.sub_slot_iters,
            )
            assert sp.cc_vdf is not None
            saved_sp_hash = sp.cc_vdf.output.get_hash()
            assert store.new_signage_point(uint8(i), blockchain, peak, peak.sub_slot_iters, sp)

    # Test adding future signage point (bad)
    for i in range(
        1, custom_block_tools.constants.NUM_SPS_SUB_SLOT - custom_block_tools.constants.NUM_SP_INTERVALS_EXTRA
    ):
        sp = get_signage_point(
            custom_block_tools.constants,
            blockchain,
            peak,
            uint128(
                peak.ip_sub_slot_total_iters(custom_block_tools.constants)
                + len(finished_sub_slots) * peak.sub_slot_iters
            ),
            uint8(i),
            finished_sub_slots[: len(finished_sub_slots)],
            peak.sub_slot_iters,
        )
        assert not store.new_signage_point(uint8(i), blockchain, peak, peak.sub_slot_iters, sp)

    # Test adding past signage point
    sp = SignagePoint(
        blocks[1].reward_chain_block.challenge_chain_sp_vdf,
        blocks[1].challenge_chain_sp_proof,
        blocks[1].reward_chain_block.reward_chain_sp_vdf,
        blocks[1].reward_chain_sp_proof,
    )
    assert not store.new_signage_point(
        blocks[1].reward_chain_block.signage_point_index,
        blockchain,
        peak,
        uint64(blockchain.block_record(blocks[1].header_hash).sp_sub_slot_total_iters(custom_block_tools.constants)),
        sp,
    )

    # Get signage point by index
    assert (
        store.get_signage_point_by_index(
            finished_sub_slots[0].challenge_chain.get_hash(),
            uint8(4),
            finished_sub_slots[0].reward_chain.get_hash(),
        )
        is not None
    )

    assert (
        store.get_signage_point_by_index(finished_sub_slots[0].challenge_chain.get_hash(), uint8(4), std_hash(b"1"))
        is None
    )

    # Get signage point by hash
    assert saved_sp_hash is not None
    assert store.get_signage_point(saved_sp_hash) is not None
    assert store.get_signage_point(std_hash(b"2")) is None

    # Test adding signage points before genesis
    store.initialize_genesis_sub_slot()
    assert len(store.finished_sub_slots) == 1
    for i in range(
        1, custom_block_tools.constants.NUM_SPS_SUB_SLOT - custom_block_tools.constants.NUM_SP_INTERVALS_EXTRA
    ):
        sp = get_signage_point(
            custom_block_tools.constants,
            BlockchainMock({}, {}),
            None,
            uint128(0),
            uint8(i),
            [],
            peak.sub_slot_iters,
        )
        assert store.new_signage_point(uint8(i), blockchain, None, peak.sub_slot_iters, sp)

    blocks_3 = custom_block_tools.get_consecutive_blocks(
        1,
        skip_slots=2,
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
    )
    peak = blockchain.get_peak()
    assert peak is not None
    for slot in blocks_3[-1].finished_sub_slots:
        next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
            blockchain.constants, True, peak, blockchain
        )

        store.new_finished_sub_slot(slot, blockchain, None, next_sub_slot_iters, next_difficulty, None)
    assert len(store.finished_sub_slots) == 3
    finished_sub_slots = blocks_3[-1].finished_sub_slots

    for slot_offset in range(1, len(finished_sub_slots) + 1):
        for i in range(
            1,
            custom_block_tools.constants.NUM_SPS_SUB_SLOT - custom_block_tools.constants.NUM_SP_INTERVALS_EXTRA,
        ):
            sp = get_signage_point(
                custom_block_tools.constants,
                BlockchainMock({}, {}),
                None,
                uint128(slot_offset * peak.sub_slot_iters),
                uint8(i),
                finished_sub_slots[:slot_offset],
                peak.sub_slot_iters,
            )
            assert store.new_signage_point(uint8(i), blockchain, None, peak.sub_slot_iters, sp)

    # Test adding signage points after genesis
    blocks_4 = custom_block_tools.get_consecutive_blocks(
        1,
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
    )
    blocks_5 = custom_block_tools.get_consecutive_blocks(
        1,
        block_list_input=blocks_4,
        skip_slots=1,
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
    )

    # If this is not the case, fix test to find a block that is
    assert (
        blocks_4[-1].reward_chain_block.signage_point_index
        < custom_block_tools.constants.NUM_SPS_SUB_SLOT - custom_block_tools.constants.NUM_SP_INTERVALS_EXTRA
    )
    await _validate_and_add_block(blockchain, blocks_4[-1], expected_result=AddBlockResult.ADDED_AS_ORPHAN)

    sb = blockchain.block_record(blocks_4[-1].header_hash)
    next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
        blockchain.constants, False, sb, blockchain
    )

    store.new_peak(sb, blocks_4[-1], None, None, None, blockchain, next_sub_slot_iters, next_difficulty)
    for i in range(
        sb.signage_point_index + custom_block_tools.constants.NUM_SP_INTERVALS_EXTRA,
        custom_block_tools.constants.NUM_SPS_SUB_SLOT,
    ):
        if is_overflow_block(custom_block_tools.constants, uint8(i)):
            finished_sub_slots = blocks_5[-1].finished_sub_slots
        else:
            finished_sub_slots = []

        sp = get_signage_point(
            custom_block_tools.constants,
            blockchain,
            sb,
            uint128(0),
            uint8(i),
            finished_sub_slots,
            peak.sub_slot_iters,
        )
        assert store.new_signage_point(uint8(i), empty_blockchain, sb, peak.sub_slot_iters, sp)

    # Test future EOS cache
    store.initialize_genesis_sub_slot()
    blocks = custom_block_tools.get_consecutive_blocks(
        1,
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
    )
    await _validate_and_add_block_no_error(blockchain, blocks[-1])
    while True:
        blocks = custom_block_tools.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )
        await _validate_and_add_block_no_error(blockchain, blocks[-1])
        sb = blockchain.block_record(blocks[-1].header_hash)
        if sb.first_in_sub_slot:
            break
    assert len(blocks) >= 2
    dependant_sub_slots = blocks[-1].finished_sub_slots
    peak = blockchain.get_peak()
    assert peak is not None
    peak_full_block = await blockchain.get_full_peak()
    for block in blocks[:-2]:
        sb = blockchain.block_record(block.header_hash)
        result = await blockchain.get_sp_and_ip_sub_slots(block.header_hash)
        assert result is not None
        sp_sub_slot, ip_sub_slot = result
        peak = sb
        peak_full_block = block
        next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
            blockchain.constants, False, peak, blockchain
        )

        res = store.new_peak(
            sb, block, sp_sub_slot, ip_sub_slot, None, blockchain, next_sub_slot_iters, next_difficulty
        )
        assert res.added_eos is None

    next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
        blockchain.constants, True, peak, blockchain
    )

    assert (
        store.new_finished_sub_slot(
            dependant_sub_slots[0], blockchain, peak, next_sub_slot_iters, next_difficulty, peak_full_block
        )
        is None
    )
    block = blocks[-2]
    sb = blockchain.block_record(block.header_hash)
    result = await blockchain.get_sp_and_ip_sub_slots(block.header_hash)
    assert result is not None
    sp_sub_slot, ip_sub_slot = result
    next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
        blockchain.constants, False, sb, blockchain
    )

    res = store.new_peak(sb, block, sp_sub_slot, ip_sub_slot, None, blockchain, next_sub_slot_iters, next_difficulty)
    assert res.added_eos == dependant_sub_slots[0]
    assert res.new_signage_points == []
    assert res.new_infusion_points == []

    # Test future IP cache
    store.initialize_genesis_sub_slot()
    blocks = custom_block_tools.get_consecutive_blocks(
        60,
        normalized_to_identity_cc_ip=normalized_to_identity,
        normalized_to_identity_cc_sp=normalized_to_identity,
        normalized_to_identity_cc_eos=normalized_to_identity,
        normalized_to_identity_icc_eos=normalized_to_identity,
    )

    for block in blocks[:5]:
        await _validate_and_add_block_no_error(blockchain, block)
        sb = blockchain.block_record(block.header_hash)
        result = await blockchain.get_sp_and_ip_sub_slots(block.header_hash)
        assert result is not None
        sp_sub_slot, ip_sub_slot = result
        next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
            blockchain.constants, False, sb, blockchain
        )

        res = store.new_peak(
            sb, block, sp_sub_slot, ip_sub_slot, None, blockchain, next_sub_slot_iters, next_difficulty
        )
        assert res.added_eos is None

    case_0, case_1 = False, False
    for i in range(5, len(blocks) - 1):
        prev_block = blocks[i]
        block = blocks[i + 1]
        new_ip = NewInfusionPointVDF(
            block.reward_chain_block.get_unfinished().get_hash(),
            block.reward_chain_block.challenge_chain_ip_vdf,
            block.challenge_chain_ip_proof,
            block.reward_chain_block.reward_chain_ip_vdf,
            block.reward_chain_ip_proof,
            block.reward_chain_block.infused_challenge_chain_ip_vdf,
            block.infused_challenge_chain_ip_proof,
        )
        store.add_to_future_ip(new_ip)

        await _validate_and_add_block_no_error(blockchain, prev_block)
        result = await blockchain.get_sp_and_ip_sub_slots(prev_block.header_hash)
        assert result is not None
        sp_sub_slot, ip_sub_slot = result
        sb = blockchain.block_record(prev_block.header_hash)
        next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
            blockchain.constants, False, sb, blockchain
        )

        res = store.new_peak(
            sb, prev_block, sp_sub_slot, ip_sub_slot, None, blockchain, next_sub_slot_iters, next_difficulty
        )
        if len(block.finished_sub_slots) == 0:
            case_0 = True
            assert res.new_infusion_points == [new_ip]
        else:
            case_1 = True
            assert res.new_infusion_points == []
            found_ips: List[timelord_protocol.NewInfusionPointVDF] = []
            peak = blockchain.get_peak()

            for ss in block.finished_sub_slots:
                next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
                    blockchain.constants, True, peak, blockchain
                )

                ipvdf = store.new_finished_sub_slot(
                    ss, blockchain, sb, next_sub_slot_iters, next_difficulty, prev_block
                )
                assert ipvdf is not None
                found_ips += ipvdf
            assert found_ips == [new_ip]

    # If flaky, increase the number of blocks created
    assert case_0 and case_1

    # Try to get two blocks in the same slot, such that we have
    # SP, B2 SP .... SP B1
    #     i2 .........  i1
    # Then do a reorg up to B2, removing all signage points after B2, but not before
    log.warning(f"Adding blocks up to {blocks[-1]}")
    for block in blocks:
        await _validate_and_add_block_no_error(blockchain, block)

    log.warning("Starting loop")
    while True:
        log.warning("Looping")
        blocks = custom_block_tools.get_consecutive_blocks(1, block_list_input=blocks, skip_slots=1)
        await _validate_and_add_block_no_error(blockchain, blocks[-1])
        peak = blockchain.get_peak()
        assert peak is not None
        result = await blockchain.get_sp_and_ip_sub_slots(peak.header_hash)
        assert result is not None
        sp_sub_slot, ip_sub_slot = result
        next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
            blockchain.constants, False, peak, blockchain
        )

        store.new_peak(
            peak, blocks[-1], sp_sub_slot, ip_sub_slot, None, blockchain, next_sub_slot_iters, next_difficulty
        )

        blocks = custom_block_tools.get_consecutive_blocks(2, block_list_input=blocks, guarantee_transaction_block=True)

        i3 = blocks[-3].reward_chain_block.signage_point_index
        i2 = blocks[-2].reward_chain_block.signage_point_index
        i1 = blocks[-1].reward_chain_block.signage_point_index
        if (
            len(blocks[-2].finished_sub_slots) == len(blocks[-1].finished_sub_slots) == 0
            and not is_overflow_block(custom_block_tools.constants, signage_point_index=i2)
            and not is_overflow_block(custom_block_tools.constants, signage_point_index=i1)
            and i2 > i3 + 3
            and i1 > (i2 + 3)
        ):
            # We hit all the conditions that we want
            all_sps: List[Optional[SignagePoint]] = [None] * custom_block_tools.constants.NUM_SPS_SUB_SLOT

            def assert_sp_none(sp_index: int, is_none: bool) -> None:
                sp_to_check: Optional[SignagePoint] = all_sps[sp_index]
                assert sp_to_check is not None
                assert sp_to_check.cc_vdf is not None
                fetched = store.get_signage_point(sp_to_check.cc_vdf.output.get_hash())
                assert (fetched is None) == is_none
                if fetched is not None:
                    assert fetched == sp_to_check

            for i in range(i3 + 1, custom_block_tools.constants.NUM_SPS_SUB_SLOT - 3):
                finished_sub_slots = []
                sp = get_signage_point(
                    custom_block_tools.constants,
                    blockchain,
                    peak,
                    uint128(peak.ip_sub_slot_total_iters(custom_block_tools.constants)),
                    uint8(i),
                    finished_sub_slots,
                    peak.sub_slot_iters,
                )
                all_sps[i] = sp
                assert store.new_signage_point(uint8(i), blockchain, peak, peak.sub_slot_iters, sp)

            # Adding a new peak clears all SPs after that peak
            await _validate_and_add_block_no_error(blockchain, blocks[-2])
            peak = blockchain.get_peak()
            assert peak is not None
            result = await blockchain.get_sp_and_ip_sub_slots(peak.header_hash)
            assert result is not None
            sp_sub_slot, ip_sub_slot = result
            next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
                blockchain.constants, False, peak, blockchain
            )

            store.new_peak(
                peak, blocks[-2], sp_sub_slot, ip_sub_slot, None, blockchain, next_sub_slot_iters, next_difficulty
            )

            assert_sp_none(i2, False)
            assert_sp_none(i2 + 1, False)
            assert_sp_none(i1, True)
            assert_sp_none(i1 + 1, True)
            # We load into `all_sps` only up to `NUM_SPS_SUB_SLOT - 3`, so make sure we're not out of range
            if i1 + 4 < custom_block_tools.constants.NUM_SPS_SUB_SLOT - 3:
                assert_sp_none(i1 + 4, True)

            for i in range(i2, custom_block_tools.constants.NUM_SPS_SUB_SLOT):
                if is_overflow_block(custom_block_tools.constants, uint8(i)):
                    blocks_alt = custom_block_tools.get_consecutive_blocks(
                        1, block_list_input=blocks[:-1], skip_slots=1
                    )
                    finished_sub_slots = blocks_alt[-1].finished_sub_slots
                else:
                    finished_sub_slots = []
                sp = get_signage_point(
                    custom_block_tools.constants,
                    blockchain,
                    peak,
                    uint128(peak.ip_sub_slot_total_iters(custom_block_tools.constants)),
                    uint8(i),
                    finished_sub_slots,
                    peak.sub_slot_iters,
                )
                all_sps[i] = sp
                assert store.new_signage_point(uint8(i), blockchain, peak, peak.sub_slot_iters, sp)

            assert_sp_none(i2, False)
            assert_sp_none(i2 + 1, False)
            assert_sp_none(i1, False)
            assert_sp_none(i1 + 1, False)
            assert_sp_none(i1 + 4, False)

            await _validate_and_add_block_no_error(blockchain, blocks[-1])
            peak = blockchain.get_peak()
            assert peak is not None
            result = await blockchain.get_sp_and_ip_sub_slots(peak.header_hash)
            assert result is not None
            sp_sub_slot, ip_sub_slot = result
            next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
                blockchain.constants, False, peak, blockchain
            )

            # Do a reorg, which should remove everything after B2
            store.new_peak(
                peak,
                blocks[-1],
                sp_sub_slot,
                ip_sub_slot,
                (await blockchain.get_block_records_at([blocks[-2].height]))[0],
                blockchain,
                next_sub_slot_iters,
                next_difficulty,
            )

            assert_sp_none(i2, False)
            assert_sp_none(i2 + 1, False)
            assert_sp_none(i1, True)
            assert_sp_none(i1 + 1, True)
            assert_sp_none(i1 + 4, True)
            break
        else:
            for block in blocks[-2:]:
                await _validate_and_add_block_no_error(blockchain, block)


@pytest.mark.limit_consensus_modes(reason="save time")
@pytest.mark.anyio
async def test_long_chain_slots(
    empty_blockchain_with_original_constants: Blockchain,
    default_1000_blocks: List[FullBlock],
) -> None:
    blockchain = empty_blockchain_with_original_constants
    store = FullNodeStore(blockchain.constants)
    peak = None
    peak_full_block = None
    for block in default_1000_blocks:
        next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
            blockchain.constants, True, peak, blockchain
        )

        for sub_slot in block.finished_sub_slots:
            assert (
                store.new_finished_sub_slot(
                    sub_slot, blockchain, peak, next_sub_slot_iters, next_difficulty, peak_full_block
                )
                is not None
            )
        await _validate_and_add_block(blockchain, block)
        peak = blockchain.get_peak()
        assert peak is not None
        peak_full_block = await blockchain.get_full_peak()
        assert peak_full_block is not None
        result = await blockchain.get_sp_and_ip_sub_slots(peak.header_hash)
        assert result is not None
        sp_sub_slot, ip_sub_slot = result
        store.new_peak(
            peak, peak_full_block, sp_sub_slot, ip_sub_slot, None, blockchain, next_sub_slot_iters, next_difficulty
        )


@pytest.mark.anyio
async def test_mark_requesting(
    seeded_random: random.Random,
) -> None:
    store = FullNodeStore(DEFAULT_CONSTANTS)
    a = bytes32.random(seeded_random)
    b = bytes32.random(seeded_random)
    c = bytes32.random(seeded_random)

    assert store.is_requesting_unfinished_block(a, a) == (False, 0)
    assert store.is_requesting_unfinished_block(a, b) == (False, 0)
    assert store.is_requesting_unfinished_block(a, c) == (False, 0)
    assert store.is_requesting_unfinished_block(b, b) == (False, 0)
    assert store.is_requesting_unfinished_block(c, c) == (False, 0)

    store.mark_requesting_unfinished_block(a, b)
    assert store.is_requesting_unfinished_block(a, b) == (True, 1)
    assert store.is_requesting_unfinished_block(a, c) == (False, 1)
    assert store.is_requesting_unfinished_block(a, a) == (False, 1)
    assert store.is_requesting_unfinished_block(b, c) == (False, 0)
    assert store.is_requesting_unfinished_block(b, b) == (False, 0)

    store.mark_requesting_unfinished_block(a, c)
    assert store.is_requesting_unfinished_block(a, b) == (True, 2)
    assert store.is_requesting_unfinished_block(a, c) == (True, 2)
    assert store.is_requesting_unfinished_block(a, a) == (False, 2)
    assert store.is_requesting_unfinished_block(b, c) == (False, 0)
    assert store.is_requesting_unfinished_block(b, b) == (False, 0)

    # this is a no-op
    store.remove_requesting_unfinished_block(a, a)
    store.remove_requesting_unfinished_block(c, a)

    assert store.is_requesting_unfinished_block(a, b) == (True, 2)
    assert store.is_requesting_unfinished_block(a, c) == (True, 2)
    assert store.is_requesting_unfinished_block(a, a) == (False, 2)
    assert store.is_requesting_unfinished_block(b, c) == (False, 0)
    assert store.is_requesting_unfinished_block(b, b) == (False, 0)

    store.remove_requesting_unfinished_block(a, b)

    assert store.is_requesting_unfinished_block(a, b) == (False, 1)
    assert store.is_requesting_unfinished_block(a, c) == (True, 1)
    assert store.is_requesting_unfinished_block(a, a) == (False, 1)
    assert store.is_requesting_unfinished_block(b, c) == (False, 0)
    assert store.is_requesting_unfinished_block(b, b) == (False, 0)

    store.remove_requesting_unfinished_block(a, c)

    assert store.is_requesting_unfinished_block(a, b) == (False, 0)
    assert store.is_requesting_unfinished_block(a, c) == (False, 0)
    assert store.is_requesting_unfinished_block(a, a) == (False, 0)
    assert store.is_requesting_unfinished_block(b, c) == (False, 0)
    assert store.is_requesting_unfinished_block(b, b) == (False, 0)

    assert len(store._unfinished_blocks) == 0
