import logging
import random
from dataclasses import replace
from typing import Callable, Dict, List, Optional, Tuple

import blspy
from blspy import G1Element, G2Element
from chiabip158 import PyBIP158

from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult, calculate_cost_of_program
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.full_node.signage_point import SignagePoint
from chia.types.blockchain_format.coin import Coin, hash_coin_list
from chia.types.blockchain_format.foliage import Foliage, FoliageBlockData, FoliageTransactionBlock, TransactionsInfo
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock, RewardChainBlockUnfinished
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.merkle_set import MerkleSet
from chia.util.prev_transaction_block import get_prev_transaction_block
from chia.util.recursive_replace import recursive_replace

log = logging.getLogger(__name__)


def create_foliage(
    constants: ConsensusConstants,
    reward_block_unfinished: RewardChainBlockUnfinished,
    block_generator: Optional[BlockGenerator],
    aggregate_sig: G2Element,
    additions: List[Coin],
    removals: List[Coin],
    prev_block: Optional[BlockRecord],
    blocks: BlockchainInterface,
    total_iters_sp: uint128,
    timestamp: uint64,
    farmer_reward_puzzlehash: bytes32,
    pool_target: PoolTarget,
    get_plot_signature: Callable[[bytes32, G1Element], G2Element],
    get_pool_signature: Callable[[PoolTarget, Optional[G1Element]], Optional[G2Element]],
    seed: bytes32 = b"",
) -> Tuple[Foliage, Optional[FoliageTransactionBlock], Optional[TransactionsInfo]]:
    """
    Creates a foliage for a given reward chain block. This may or may not be a tx block. In the case of a tx block,
    the return values are not None. This is called at the signage point, so some of this information may be
    tweaked at the infusion point.

    Args:
        constants: consensus constants being used for this chain
        reward_block_unfinished: the reward block to look at, potentially at the signage point
        block_generator: transactions to add to the foliage block, if created
        aggregate_sig: aggregate of all transctions (or infinity element)
        prev_block: the previous block at the signage point
        blocks: dict from header hash to blocks, of all ancestor blocks
        total_iters_sp: total iters at the signage point
        timestamp: timestamp to put into the foliage block
        farmer_reward_puzzlehash: where to pay out farming reward
        pool_target: where to pay out pool reward
        get_plot_signature: retrieve the signature corresponding to the plot public key
        get_pool_signature: retrieve the signature corresponding to the pool public key
        seed: seed to randomize block

    """

    if prev_block is not None:
        res = get_prev_transaction_block(prev_block, blocks, total_iters_sp)
        is_transaction_block: bool = res[0]
        prev_transaction_block: Optional[BlockRecord] = res[1]
    else:
        # Genesis is a transaction block
        prev_transaction_block = None
        is_transaction_block = True

    random.seed(seed)
    # Use the extension data to create different blocks based on header hash
    extension_data: bytes32 = random.randint(0, 100000000).to_bytes(32, "big")
    if prev_block is None:
        height: uint32 = uint32(0)
    else:
        height = uint32(prev_block.height + 1)

    # Create filter
    byte_array_tx: List[bytes32] = []
    tx_additions: List[Coin] = []
    tx_removals: List[bytes32] = []

    pool_target_signature: Optional[G2Element] = get_pool_signature(
        pool_target, reward_block_unfinished.proof_of_space.pool_public_key
    )

    foliage_data = FoliageBlockData(
        reward_block_unfinished.get_hash(),
        pool_target,
        pool_target_signature,
        farmer_reward_puzzlehash,
        extension_data,
    )

    foliage_block_data_signature: G2Element = get_plot_signature(
        foliage_data.get_hash(),
        reward_block_unfinished.proof_of_space.plot_public_key,
    )

    prev_block_hash: bytes32 = constants.GENESIS_CHALLENGE
    if height != 0:
        assert prev_block is not None
        prev_block_hash = prev_block.header_hash

    generator_block_heights_list: List[uint32] = []

    if is_transaction_block:
        cost = uint64(0)

        # Calculate the cost of transactions
        if block_generator is not None:
            generator_block_heights_list = block_generator.block_height_list()
            result: NPCResult = get_name_puzzle_conditions(
                block_generator,
                constants.MAX_BLOCK_COST_CLVM,
                cost_per_byte=constants.COST_PER_BYTE,
                safe_mode=True,
            )
            cost = calculate_cost_of_program(block_generator.program, result, constants.COST_PER_BYTE)

            removal_amount = 0
            addition_amount = 0
            for coin in removals:
                removal_amount += coin.amount
            for coin in additions:
                addition_amount += coin.amount
            spend_bundle_fees = removal_amount - addition_amount
        else:
            spend_bundle_fees = 0

        reward_claims_incorporated = []
        if height > 0:
            assert prev_transaction_block is not None
            assert prev_block is not None
            curr: BlockRecord = prev_block
            while not curr.is_transaction_block:
                curr = blocks.block_record(curr.prev_hash)

            assert curr.fees is not None
            pool_coin = create_pool_coin(
                curr.height, curr.pool_puzzle_hash, calculate_pool_reward(curr.height), constants.GENESIS_CHALLENGE
            )

            farmer_coin = create_farmer_coin(
                curr.height,
                curr.farmer_puzzle_hash,
                uint64(calculate_base_farmer_reward(curr.height) + curr.fees),
                constants.GENESIS_CHALLENGE,
            )
            assert curr.header_hash == prev_transaction_block.header_hash
            reward_claims_incorporated += [pool_coin, farmer_coin]

            if curr.height > 0:
                curr = blocks.block_record(curr.prev_hash)
                # Prev block is not genesis
                while not curr.is_transaction_block:
                    pool_coin = create_pool_coin(
                        curr.height,
                        curr.pool_puzzle_hash,
                        calculate_pool_reward(curr.height),
                        constants.GENESIS_CHALLENGE,
                    )
                    farmer_coin = create_farmer_coin(
                        curr.height,
                        curr.farmer_puzzle_hash,
                        calculate_base_farmer_reward(curr.height),
                        constants.GENESIS_CHALLENGE,
                    )
                    reward_claims_incorporated += [pool_coin, farmer_coin]
                    curr = blocks.block_record(curr.prev_hash)
        additions.extend(reward_claims_incorporated.copy())
        for coin in additions:
            tx_additions.append(coin)
            byte_array_tx.append(bytearray(coin.puzzle_hash))
        for coin in removals:
            tx_removals.append(coin.name())
            byte_array_tx.append(bytearray(coin.name()))

        bip158: PyBIP158 = PyBIP158(byte_array_tx)
        encoded = bytes(bip158.GetEncoded())

        removal_merkle_set = MerkleSet()
        addition_merkle_set = MerkleSet()

        # Create removal Merkle set
        for coin_name in tx_removals:
            removal_merkle_set.add_already_hashed(coin_name)

        # Create addition Merkle set
        puzzlehash_coin_map: Dict[bytes32, List[Coin]] = {}

        for coin in tx_additions:
            if coin.puzzle_hash in puzzlehash_coin_map:
                puzzlehash_coin_map[coin.puzzle_hash].append(coin)
            else:
                puzzlehash_coin_map[coin.puzzle_hash] = [coin]

        # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
        for puzzle, coins in puzzlehash_coin_map.items():
            addition_merkle_set.add_already_hashed(puzzle)
            addition_merkle_set.add_already_hashed(hash_coin_list(coins))

        additions_root = addition_merkle_set.get_root()
        removals_root = removal_merkle_set.get_root()

        generator_hash = bytes32([0] * 32)
        if block_generator is not None:
            generator_hash = std_hash(block_generator.program)

        generator_refs_hash = bytes32([1] * 32)
        if generator_block_heights_list not in (None, []):
            generator_ref_list_bytes = b"".join([bytes(i) for i in generator_block_heights_list])
            generator_refs_hash = std_hash(generator_ref_list_bytes)

        filter_hash: bytes32 = std_hash(encoded)

        transactions_info: Optional[TransactionsInfo] = TransactionsInfo(
            generator_hash,
            generator_refs_hash,
            aggregate_sig,
            uint64(spend_bundle_fees),
            cost,
            reward_claims_incorporated,
        )
        if prev_transaction_block is None:
            prev_transaction_block_hash: bytes32 = constants.GENESIS_CHALLENGE
        else:
            prev_transaction_block_hash = prev_transaction_block.header_hash

        assert transactions_info is not None
        foliage_transaction_block: Optional[FoliageTransactionBlock] = FoliageTransactionBlock(
            prev_transaction_block_hash,
            timestamp,
            filter_hash,
            additions_root,
            removals_root,
            transactions_info.get_hash(),
        )
        assert foliage_transaction_block is not None

        foliage_transaction_block_hash: Optional[bytes32] = foliage_transaction_block.get_hash()
        foliage_transaction_block_signature: Optional[G2Element] = get_plot_signature(
            foliage_transaction_block_hash, reward_block_unfinished.proof_of_space.plot_public_key
        )
        assert foliage_transaction_block_signature is not None
    else:
        foliage_transaction_block_hash = None
        foliage_transaction_block_signature = None
        foliage_transaction_block = None
        transactions_info = None
    assert (foliage_transaction_block_hash is None) == (foliage_transaction_block_signature is None)

    foliage = Foliage(
        prev_block_hash,
        reward_block_unfinished.get_hash(),
        foliage_data,
        foliage_block_data_signature,
        foliage_transaction_block_hash,
        foliage_transaction_block_signature,
    )

    return foliage, foliage_transaction_block, transactions_info


def create_unfinished_block(
    constants: ConsensusConstants,
    sub_slot_start_total_iters: uint128,
    sub_slot_iters: uint64,
    signage_point_index: uint8,
    sp_iters: uint64,
    ip_iters: uint64,
    proof_of_space: ProofOfSpace,
    slot_cc_challenge: bytes32,
    farmer_reward_puzzle_hash: bytes32,
    pool_target: PoolTarget,
    get_plot_signature: Callable[[bytes32, G1Element], G2Element],
    get_pool_signature: Callable[[PoolTarget, Optional[G1Element]], Optional[G2Element]],
    signage_point: SignagePoint,
    timestamp: uint64,
    blocks: BlockchainInterface,
    seed: bytes32 = b"",
    block_generator: Optional[BlockGenerator] = None,
    aggregate_sig: G2Element = G2Element(),
    additions: Optional[List[Coin]] = None,
    removals: Optional[List[Coin]] = None,
    prev_block: Optional[BlockRecord] = None,
    finished_sub_slots_input: List[EndOfSubSlotBundle] = None,
) -> UnfinishedBlock:
    """
    Creates a new unfinished block using all the information available at the signage point. This will have to be
    modified using information from the infusion point.

    Args:
        constants: consensus constants being used for this chain
        sub_slot_start_total_iters: the starting sub-slot iters at the signage point sub-slot
        sub_slot_iters: sub-slot-iters at the infusion point epoch
        signage_point_index: signage point index of the block to create
        sp_iters: sp_iters of the block to create
        ip_iters: ip_iters of the block to create
        proof_of_space: proof of space of the block to create
        slot_cc_challenge: challenge hash at the sp sub-slot
        farmer_reward_puzzle_hash: where to pay out farmer rewards
        pool_target: where to pay out pool rewards
        get_plot_signature: function that returns signature corresponding to plot public key
        get_pool_signature: function that returns signature corresponding to pool public key
        signage_point: signage point information (VDFs)
        timestamp: timestamp to add to the foliage block, if created
        seed: seed to randomize chain
        block_generator: transactions to add to the foliage block, if created
        aggregate_sig: aggregate of all transctions (or infinity element)
        additions: Coins added in spend_bundle
        removals: Coins removed in spend_bundle
        prev_block: previous block (already in chain) from the signage point
        blocks: dictionary from header hash to SBR of all included SBR
        finished_sub_slots_input: finished_sub_slots at the signage point

    Returns:

    """
    if finished_sub_slots_input is None:
        finished_sub_slots: List[EndOfSubSlotBundle] = []
    else:
        finished_sub_slots = finished_sub_slots_input.copy()
    overflow: bool = sp_iters > ip_iters
    total_iters_sp: uint128 = uint128(sub_slot_start_total_iters + sp_iters)
    is_genesis: bool = prev_block is None

    new_sub_slot: bool = len(finished_sub_slots) > 0

    cc_sp_hash: Optional[bytes32] = slot_cc_challenge

    # Only enters this if statement if we are in testing mode (making VDF proofs here)
    if signage_point.cc_vdf is not None:
        assert signage_point.rc_vdf is not None
        cc_sp_hash = signage_point.cc_vdf.output.get_hash()
        rc_sp_hash = signage_point.rc_vdf.output.get_hash()
    else:
        if new_sub_slot:
            rc_sp_hash = finished_sub_slots[-1].reward_chain.get_hash()
        else:
            if is_genesis:
                rc_sp_hash = constants.GENESIS_CHALLENGE
            else:
                assert prev_block is not None
                assert blocks is not None
                curr = prev_block
                while not curr.first_in_sub_slot:
                    curr = blocks.block_record(curr.prev_hash)
                assert curr.finished_reward_slot_hashes is not None
                rc_sp_hash = curr.finished_reward_slot_hashes[-1]
        signage_point = SignagePoint(None, None, None, None)

    cc_sp_signature: Optional[G2Element] = get_plot_signature(cc_sp_hash, proof_of_space.plot_public_key)
    rc_sp_signature: Optional[G2Element] = get_plot_signature(rc_sp_hash, proof_of_space.plot_public_key)
    assert cc_sp_signature is not None
    assert rc_sp_signature is not None
    assert blspy.AugSchemeMPL.verify(proof_of_space.plot_public_key, cc_sp_hash, cc_sp_signature)

    total_iters = uint128(sub_slot_start_total_iters + ip_iters + (sub_slot_iters if overflow else 0))

    rc_block = RewardChainBlockUnfinished(
        total_iters,
        signage_point_index,
        slot_cc_challenge,
        proof_of_space,
        signage_point.cc_vdf,
        cc_sp_signature,
        signage_point.rc_vdf,
        rc_sp_signature,
    )
    if additions is None:
        additions = []
    if removals is None:
        removals = []
    (foliage, foliage_transaction_block, transactions_info,) = create_foliage(
        constants,
        rc_block,
        block_generator,
        aggregate_sig,
        additions,
        removals,
        prev_block,
        blocks,
        total_iters_sp,
        timestamp,
        farmer_reward_puzzle_hash,
        pool_target,
        get_plot_signature,
        get_pool_signature,
        seed,
    )
    return UnfinishedBlock(
        finished_sub_slots,
        rc_block,
        signage_point.cc_proof,
        signage_point.rc_proof,
        foliage,
        foliage_transaction_block,
        transactions_info,
        block_generator.program if block_generator else None,
        block_generator.block_height_list() if block_generator else [],
    )


def unfinished_block_to_full_block(
    unfinished_block: UnfinishedBlock,
    cc_ip_vdf: VDFInfo,
    cc_ip_proof: VDFProof,
    rc_ip_vdf: VDFInfo,
    rc_ip_proof: VDFProof,
    icc_ip_vdf: Optional[VDFInfo],
    icc_ip_proof: Optional[VDFProof],
    finished_sub_slots: List[EndOfSubSlotBundle],
    prev_block: Optional[BlockRecord],
    blocks: BlockchainInterface,
    total_iters_sp: uint128,
    difficulty: uint64,
) -> FullBlock:
    """
    Converts an unfinished block to a finished block. Includes all the infusion point VDFs as well as tweaking
    other properties (height, weight, sub-slots, etc)

    Args:
        unfinished_block: the unfinished block to finish
        cc_ip_vdf: the challenge chain vdf info at the infusion point
        cc_ip_proof: the challenge chain proof
        rc_ip_vdf: the reward chain vdf info at the infusion point
        rc_ip_proof: the reward chain proof
        icc_ip_vdf: the infused challenge chain vdf info at the infusion point
        icc_ip_proof: the infused challenge chain proof
        finished_sub_slots: finished sub slots from the prev block to the infusion point
        prev_block: prev block from the infusion point
        blocks: dictionary from header hash to SBR of all included SBR
        total_iters_sp: total iters at the signage point
        difficulty: difficulty at the infusion point

    """
    # Replace things that need to be replaced, since foliage blocks did not necessarily have the latest information
    if prev_block is None:
        is_transaction_block = True
        new_weight = uint128(difficulty)
        new_height = uint32(0)
        new_foliage = unfinished_block.foliage
        new_foliage_transaction_block = unfinished_block.foliage_transaction_block
        new_tx_info = unfinished_block.transactions_info
        new_generator = unfinished_block.transactions_generator
        new_generator_ref_list = unfinished_block.transactions_generator_ref_list
    else:
        is_transaction_block, _ = get_prev_transaction_block(prev_block, blocks, total_iters_sp)
        new_weight = uint128(prev_block.weight + difficulty)
        new_height = uint32(prev_block.height + 1)
        if is_transaction_block:
            new_fbh = unfinished_block.foliage.foliage_transaction_block_hash
            new_fbs = unfinished_block.foliage.foliage_transaction_block_signature
            new_foliage_transaction_block = unfinished_block.foliage_transaction_block
            new_tx_info = unfinished_block.transactions_info
            new_generator = unfinished_block.transactions_generator
            new_generator_ref_list = unfinished_block.transactions_generator_ref_list
        else:
            new_fbh = None
            new_fbs = None
            new_foliage_transaction_block = None
            new_tx_info = None
            new_generator = None
            new_generator_ref_list = []
        assert (new_fbh is None) == (new_fbs is None)
        new_foliage = replace(
            unfinished_block.foliage,
            prev_block_hash=prev_block.header_hash,
            foliage_transaction_block_hash=new_fbh,
            foliage_transaction_block_signature=new_fbs,
        )
    ret = FullBlock(
        finished_sub_slots,
        RewardChainBlock(
            new_weight,
            new_height,
            unfinished_block.reward_chain_block.total_iters,
            unfinished_block.reward_chain_block.signage_point_index,
            unfinished_block.reward_chain_block.pos_ss_cc_challenge_hash,
            unfinished_block.reward_chain_block.proof_of_space,
            unfinished_block.reward_chain_block.challenge_chain_sp_vdf,
            unfinished_block.reward_chain_block.challenge_chain_sp_signature,
            cc_ip_vdf,
            unfinished_block.reward_chain_block.reward_chain_sp_vdf,
            unfinished_block.reward_chain_block.reward_chain_sp_signature,
            rc_ip_vdf,
            icc_ip_vdf,
            is_transaction_block,
        ),
        unfinished_block.challenge_chain_sp_proof,
        cc_ip_proof,
        unfinished_block.reward_chain_sp_proof,
        rc_ip_proof,
        icc_ip_proof,
        new_foliage,
        new_foliage_transaction_block,
        new_tx_info,
        new_generator,
        new_generator_ref_list,
    )
    return recursive_replace(
        ret,
        "foliage.reward_block_hash",
        ret.reward_chain_block.get_hash(),
    )
