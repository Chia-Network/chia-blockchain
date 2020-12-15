import random
from dataclasses import replace
from typing import Optional, Callable, Dict, List, Tuple

import blspy
from blspy import G2Element, G1Element
from chiabip158 import PyBIP158

from src.consensus.block_rewards import (
    calculate_pool_reward,
    calculate_base_farmer_reward,
)
from src.consensus.coinbase import create_pool_coin, create_farmer_coin
from src.consensus.constants import ConsensusConstants
from src.full_node.bundle_tools import best_solution_program
from src.consensus.cost_calculator import calculate_cost_of_program
from src.full_node.mempool_check_conditions import get_name_puzzle_conditions
from src.full_node.signage_point import SignagePoint
from src.consensus.sub_block_record import SubBlockRecord
from src.types.coin import Coin, hash_coin_list
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.foliage import (
    FoliageSubBlock,
    FoliageBlock,
    TransactionsInfo,
    FoliageSubBlockData,
)
from src.types.full_block import additions_for_npc, FullBlock
from src.types.pool_target import PoolTarget
from src.types.program import Program
from src.types.proof_of_space import ProofOfSpace
from src.types.reward_chain_sub_block import (
    RewardChainSubBlockUnfinished,
    RewardChainSubBlock,
)
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.types.unfinished_block import UnfinishedBlock
from src.types.vdf import VDFInfo, VDFProof
from src.util.hash import std_hash
from src.util.ints import uint128, uint64, uint32, uint8
from src.util.merkle_set import MerkleSet
from src.util.prev_block import get_prev_block
from tests.recursive_replace import recursive_replace


def create_foliage(
    constants: ConsensusConstants,
    reward_sub_block: RewardChainSubBlockUnfinished,
    spend_bundle: Optional[SpendBundle],
    prev_sub_block: Optional[SubBlockRecord],
    sub_blocks: Dict[bytes32, SubBlockRecord],
    total_iters_sp: uint128,
    timestamp: uint64,
    farmer_reward_puzzlehash: bytes32,
    pool_target: PoolTarget,
    get_plot_signature: Callable[[bytes32, G1Element], G2Element],
    get_pool_signature: Callable[[PoolTarget, G1Element], G2Element],
    seed: bytes32 = b"",
) -> Tuple[FoliageSubBlock, Optional[FoliageBlock], Optional[TransactionsInfo], Optional[Program]]:
    """
    Creates a foliage for a given reward chain sub block. This may or may not be a block. In the case of a block,
    the return values are not None. This is called at the signage point, so some of this information may be
    tweaked at the infusion point.

    Args:
        constants: consensus constants being used for this chain
        reward_sub_block: the reward sub block to look at, potentially at the signage point
        spend_bundle: the spend bundle including all transactions
        prev_sub_block: the previous sub-block at the signage point
        sub_blocks: dict from header hash to sub-blocks, of all ancestor sub-blocks
        total_iters_sp: total iters at the signage point
        timestamp: timestamp to put into the foliage block
        farmer_reward_puzzlehash: where to pay out farming reward
        pool_target: where to pay out pool reward
        get_plot_signature: retrieve the signature corresponding to the plot public key
        get_pool_signature: retrieve the signature corresponding to the pool public key
        seed: seed to randomize block

    """

    if prev_sub_block is not None:
        res = get_prev_block(prev_sub_block, sub_blocks, total_iters_sp)
        is_block: bool = res[0]
        prev_block: Optional[SubBlockRecord] = res[1]
    else:
        # Genesis is a block
        prev_block = None
        is_block = True

    random.seed(seed)
    # Use the extension data to create different blocks based on header hash
    extension_data: bytes32 = random.randint(0, 100000000).to_bytes(32, "big")
    if prev_sub_block is None:
        sub_block_height: uint32 = uint32(0)
    else:
        sub_block_height = uint32(prev_sub_block.sub_block_height + 1)

    if prev_block is None:
        sub_height: uint32 = uint32(0)
        height: uint32 = uint32(0)
    else:
        sub_height = uint32(prev_block.sub_block_height + 1)
        prev_is_block = prev_block.is_block
        if prev_is_block:
            height = uint32(prev_block.height + 1)
        else:
            height = uint32(prev_block.height)

    # Create filter
    byte_array_tx: List[bytes32] = []
    tx_additions: List[Coin] = []
    tx_removals: List[bytes32] = []

    pool_target_signature: Optional[G2Element] = get_pool_signature(
        pool_target, reward_sub_block.proof_of_space.pool_public_key
    )
    assert pool_target_signature is not None

    foliage_sub_block_data = FoliageSubBlockData(
        reward_sub_block.get_hash(),
        pool_target,
        pool_target_signature,
        farmer_reward_puzzlehash,
        extension_data,
    )

    foliage_sub_block_signature: G2Element = get_plot_signature(
        foliage_sub_block_data.get_hash(),
        reward_sub_block.proof_of_space.plot_public_key,
    )

    prev_sub_block_hash: bytes32 = constants.GENESIS_PREV_HASH
    if sub_block_height != 0:
        assert prev_sub_block is not None
        prev_sub_block_hash = prev_sub_block.header_hash

    solution_program: Optional[Program] = None
    if is_block:
        spend_bundle_fees: int = 0
        aggregate_sig: G2Element = G2Element.infinity()
        cost = uint64(0)

        if spend_bundle is not None:
            solution_program = best_solution_program(spend_bundle)
            spend_bundle_fees = spend_bundle.fees()
            aggregate_sig = spend_bundle.aggregated_signature

        # Calculate the cost of transactions
        if solution_program is not None:
            _, _, cost = calculate_cost_of_program(solution_program, constants.CLVM_COST_RATIO_CONSTANT)
        # TODO: prev generators root
        reward_claims_incorporated = []
        if sub_height > 0:
            assert prev_block is not None
            assert prev_sub_block is not None
            curr: SubBlockRecord = prev_sub_block
            while not curr.is_block:
                curr = sub_blocks[curr.prev_hash]

            assert curr.fees is not None
            pool_coin = create_pool_coin(
                curr.sub_block_height,
                curr.pool_puzzle_hash,
                calculate_pool_reward(curr.height),
            )

            farmer_coin = create_farmer_coin(
                curr.sub_block_height,
                curr.farmer_puzzle_hash,
                uint64(calculate_base_farmer_reward(curr.height) + curr.fees),
            )
            assert curr.header_hash == prev_block.header_hash
            reward_claims_incorporated += [pool_coin, farmer_coin]

            if curr.sub_block_height > 0:
                curr = sub_blocks[curr.prev_hash]
                # Prev block is not genesis
                while not curr.is_block:
                    pool_coin = create_pool_coin(
                        curr.sub_block_height,
                        curr.pool_puzzle_hash,
                        calculate_pool_reward(curr.height),
                    )
                    farmer_coin = create_farmer_coin(
                        curr.sub_block_height,
                        curr.farmer_puzzle_hash,
                        calculate_base_farmer_reward(curr.height),
                    )
                    reward_claims_incorporated += [pool_coin, farmer_coin]
                    curr = sub_blocks[curr.prev_hash]
        additions: List[Coin] = reward_claims_incorporated.copy()
        npc_list = []
        if solution_program is not None:
            error, npc_list, _ = get_name_puzzle_conditions(solution_program, False)
            additions += additions_for_npc(npc_list)
        for coin in additions:
            tx_additions.append(coin)
            byte_array_tx.append(bytearray(coin.puzzle_hash))
        for npc in npc_list:
            tx_removals.append(npc.coin_name)
            byte_array_tx.append(bytearray(npc.coin_name))

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

        generator_hash = solution_program.get_tree_hash() if solution_program is not None else bytes32([0] * 32)
        filter_hash: bytes32 = std_hash(encoded)

        transactions_info: Optional[TransactionsInfo] = TransactionsInfo(
            bytes([0] * 32),
            generator_hash,
            aggregate_sig,
            uint64(spend_bundle_fees),
            cost,
            reward_claims_incorporated,
        )
        if prev_block is None:
            prev_block_hash: bytes32 = constants.GENESIS_PREV_HASH
        else:
            prev_block_hash = prev_block.header_hash

        assert transactions_info is not None
        foliage_block: Optional[FoliageBlock] = FoliageBlock(
            prev_block_hash,
            timestamp,
            filter_hash,
            additions_root,
            removals_root,
            transactions_info.get_hash(),
            height,
        )
        assert foliage_block is not None
        foliage_block_hash: Optional[bytes32] = foliage_block.get_hash()
        foliage_block_signature: Optional[G2Element] = get_plot_signature(
            foliage_block_hash, reward_sub_block.proof_of_space.plot_public_key
        )
        assert foliage_block_signature is not None
    else:
        foliage_block_hash = None
        foliage_block_signature = None
        foliage_block = None
        transactions_info = None
    assert (foliage_block_hash is None) == (foliage_block_signature is None)

    foliage_sub_block = FoliageSubBlock(
        prev_sub_block_hash,
        reward_sub_block.get_hash(),
        foliage_sub_block_data,
        foliage_sub_block_signature,
        foliage_block_hash,
        foliage_block_signature,
    )

    return foliage_sub_block, foliage_block, transactions_info, solution_program


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
    get_pool_signature: Callable[[PoolTarget, G1Element], G2Element],
    signage_point: SignagePoint,
    timestamp: uint64,
    seed: bytes32 = b"",
    spend_bundle: Optional[SpendBundle] = None,
    prev_sub_block: Optional[SubBlockRecord] = None,
    sub_blocks: Dict[bytes32, SubBlockRecord] = {},
    finished_sub_slots_input: List[EndOfSubSlotBundle] = None,
) -> UnfinishedBlock:
    """
    Creates a new unfinished block using all the information available at the signage point. This will have to be
    modified using information from the infusion point.

    Args:
        constants: consensus constants being used for this chain
        sub_slot_start_total_iters: the starting sub-slot iters at the signage point sub-slot
        sub_slot_iters: sub-slot-iters at the infusion point epoch
        signage_point_index: signage point index of the sub-block to create
        sp_iters: sp_iters of the sub-block to create
        ip_iters: ip_iters of the sub-block to create
        proof_of_space: proof of space of the sub-block to create
        slot_cc_challenge: challenge hash at the sp sub-slot
        farmer_reward_puzzle_hash: where to pay out farmer rewards
        pool_target: where to pay out pool rewards
        get_plot_signature: function that returns signature corresponding to plot public key
        get_pool_signature: function that returns signature corresponding to pool public key
        signage_point: signage point information (VDFs)
        timestamp: timestamp to add to the foliage block, if created
        seed: seed to randomize chain
        spend_bundle: transactions to add to the foliage block, if created
        prev_sub_block: previous sub-block (already in chain) from the signage point
        sub_blocks: dictionary from header hash to SBR of all included SBR
        finished_sub_slots_input: finished_sub_slots at the signage point

    Returns:

    """
    if finished_sub_slots_input is None:
        finished_sub_slots: List[EndOfSubSlotBundle] = []
    else:
        finished_sub_slots = finished_sub_slots_input.copy()
    overflow: bool = sp_iters > ip_iters
    total_iters_sp: uint128 = uint128(sub_slot_start_total_iters + sp_iters)
    is_genesis: bool = prev_sub_block is None

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
                rc_sp_hash = constants.FIRST_RC_CHALLENGE
            else:
                assert prev_sub_block is not None
                assert sub_blocks is not None
                curr = prev_sub_block
                while not curr.first_in_sub_slot:
                    curr = sub_blocks[curr.prev_hash]
                assert curr.finished_reward_slot_hashes is not None
                rc_sp_hash = curr.finished_reward_slot_hashes[-1]
        signage_point = SignagePoint(None, None, None, None)

    cc_sp_signature: Optional[G2Element] = get_plot_signature(cc_sp_hash, proof_of_space.plot_public_key)
    rc_sp_signature: Optional[G2Element] = get_plot_signature(rc_sp_hash, proof_of_space.plot_public_key)
    assert cc_sp_signature is not None
    assert rc_sp_signature is not None
    assert blspy.AugSchemeMPL.verify(proof_of_space.plot_public_key, cc_sp_hash, cc_sp_signature)

    total_iters = uint128(sub_slot_start_total_iters + ip_iters + (sub_slot_iters if overflow else 0))

    rc_sub_block = RewardChainSubBlockUnfinished(
        total_iters,
        signage_point_index,
        slot_cc_challenge,
        proof_of_space,
        signage_point.cc_vdf,
        cc_sp_signature,
        signage_point.rc_vdf,
        rc_sp_signature,
    )

    (foliage_sub_block, foliage_block, transactions_info, solution_program,) = create_foliage(
        constants,
        rc_sub_block,
        spend_bundle,
        prev_sub_block,
        sub_blocks,
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
        rc_sub_block,
        signage_point.cc_proof,
        signage_point.rc_proof,
        foliage_sub_block,
        foliage_block,
        transactions_info,
        solution_program,
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
    prev_sub_block: Optional[SubBlockRecord],
    sub_blocks: Dict[bytes32, SubBlockRecord],
    total_iters_sp: uint128,
    difficulty: uint64,
) -> FullBlock:
    """
    Converts an unfinished sub block to a finished sub block. Includes all the infusion point VDFs as well as tweaking
    other properties (height, weight, sub-slots, etc)

    Args:
        unfinished_block: the unfinished sub-block to finish
        cc_ip_vdf: the challenge chain vdf info at the infusion point
        cc_ip_proof: the challenge chain proof
        rc_ip_vdf: the reward chain vdf info at the infusion point
        rc_ip_proof: the reward chain proof
        icc_ip_vdf: the infused challenge chain vdf info at the infusion point
        icc_ip_proof: the infused challenge chain proof
        finished_sub_slots: finished sub slots from the prev sub block to the infusion point
        prev_sub_block: prev sub block from the infusion point
        sub_blocks: dictionary from header hash to SBR of all included SBR
        total_iters_sp: total iters at the signage point
        difficulty: difficulty at the infusion point

    """
    # Replace things that need to be replaced, since foliage blocks did not necessarily have the latest information
    if prev_sub_block is None:
        is_block = True
        new_weight = uint128(difficulty)
        new_sub_height = uint32(0)
        new_foliage_sub_block = unfinished_block.foliage_sub_block
        new_foliage_block = unfinished_block.foliage_block
        new_tx_info = unfinished_block.transactions_info
        new_generator = unfinished_block.transactions_generator
    else:
        is_block, _ = get_prev_block(prev_sub_block, sub_blocks, total_iters_sp)
        new_weight = uint128(prev_sub_block.weight + difficulty)
        new_sub_height = uint32(prev_sub_block.sub_block_height + 1)
        if is_block:
            new_fbh = unfinished_block.foliage_sub_block.foliage_block_hash
            new_fbs = unfinished_block.foliage_sub_block.foliage_block_signature
            new_foliage_block = unfinished_block.foliage_block
            new_tx_info = unfinished_block.transactions_info
            new_generator = unfinished_block.transactions_generator
        else:
            new_fbh = None
            new_fbs = None
            new_foliage_block = None
            new_tx_info = None
            new_generator = None
        assert (new_fbh is None) == (new_fbs is None)
        new_foliage_sub_block = replace(
            unfinished_block.foliage_sub_block,
            prev_sub_block_hash=prev_sub_block.header_hash,
            foliage_block_hash=new_fbh,
            foliage_block_signature=new_fbs,
        )
    ret = FullBlock(
        finished_sub_slots,
        RewardChainSubBlock(
            new_weight,
            new_sub_height,
            unfinished_block.reward_chain_sub_block.total_iters,
            unfinished_block.reward_chain_sub_block.signage_point_index,
            unfinished_block.reward_chain_sub_block.pos_ss_cc_challenge_hash,
            unfinished_block.reward_chain_sub_block.proof_of_space,
            unfinished_block.reward_chain_sub_block.challenge_chain_sp_vdf,
            unfinished_block.reward_chain_sub_block.challenge_chain_sp_signature,
            cc_ip_vdf,
            unfinished_block.reward_chain_sub_block.reward_chain_sp_vdf,
            unfinished_block.reward_chain_sub_block.reward_chain_sp_signature,
            rc_ip_vdf,
            icc_ip_vdf,
            is_block,
        ),
        unfinished_block.challenge_chain_sp_proof,
        cc_ip_proof,
        unfinished_block.reward_chain_sp_proof,
        rc_ip_proof,
        icc_ip_proof,
        new_foliage_sub_block,
        new_foliage_block,
        new_tx_info,
        new_generator,
    )
    return recursive_replace(
        ret,
        "foliage_sub_block.reward_block_hash",
        ret.reward_chain_sub_block.get_hash(),
    )
