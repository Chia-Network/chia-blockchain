import random
from dataclasses import replace
from typing import Optional, Callable, Union, Dict, List

import blspy
from blspy import G2Element, G1Element
from chiabip158 import PyBIP158

from src.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from src.consensus.coinbase import create_pool_coin, create_farmer_coin
from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import calculate_sub_slot_iters
from src.full_node.bundle_tools import best_solution_program
from src.full_node.cost_calculator import calculate_cost_of_program
from src.full_node.mempool_check_conditions import get_name_puzzle_conditions
from src.full_node.signage_point import SignagePoint
from src.full_node.sub_block_record import SubBlockRecord
from src.types.coin import Coin, hash_coin_list
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.foliage import FoliageSubBlock, FoliageBlock, TransactionsInfo, FoliageSubBlockData
from src.types.full_block import additions_for_npc, FullBlock
from src.types.pool_target import PoolTarget
from src.types.program import Program
from src.types.proof_of_space import ProofOfSpace
from src.types.reward_chain_sub_block import RewardChainSubBlockUnfinished, RewardChainSubBlock
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
    reward_sub_block: Union[RewardChainSubBlock, RewardChainSubBlockUnfinished],
    spend_bundle: Optional[SpendBundle],
    prev_sub_block: Optional[SubBlockRecord],
    prev_block: Optional[SubBlockRecord],
    sub_blocks: Dict[bytes32, SubBlockRecord],
    is_block: bool,
    timestamp: uint64,
    farmer_reward_puzzlehash: bytes32,
    pool_target: PoolTarget,
    get_plot_signature: Callable[[bytes32, G1Element], G2Element],
    get_pool_signature: Callable[[PoolTarget, G1Element], G2Element],
    seed: bytes32 = b"",
) -> (FoliageSubBlock, Optional[FoliageBlock], Optional[TransactionsInfo], Optional[Program]):
    # Use the extension data to create different blocks based on header hash
    random.seed(seed)
    extension_data: bytes32 = random.randint(0, 100000000).to_bytes(32, "big")
    if prev_sub_block is None:
        height: uint32 = uint32(0)
    else:
        height = uint32(prev_sub_block.height + 1)

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
        foliage_sub_block_data.get_hash(), reward_sub_block.proof_of_space.plot_public_key
    )

    prev_sub_block_hash: bytes32 = constants.GENESIS_PREV_HASH
    if height != 0:
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
        pool_coin = create_pool_coin(height, pool_target.puzzle_hash, calculate_pool_reward(height))
        farmer_coin = create_farmer_coin(
            uint32(height), farmer_reward_puzzlehash, calculate_base_farmer_reward(uint32(height))
        )
        reward_claims_incorporated = [pool_coin, farmer_coin]
        if height > 0:
            curr: SubBlockRecord = prev_sub_block
            while not curr.is_block:
                pool_coin = create_pool_coin(curr.height, curr.pool_puzzle_hash, calculate_pool_reward(curr.height))
                farmer_coin = create_farmer_coin(
                    curr.height, curr.farmer_puzzle_hash, calculate_base_farmer_reward(curr.height)
                )
                reward_claims_incorporated += [pool_coin, farmer_coin]
                curr = sub_blocks[curr.prev_hash]
        additions: List[Coin] = reward_claims_incorporated.copy()
        npc_list = []
        if solution_program is not None:
            error, npc_list, _ = get_name_puzzle_conditions(solution_program)
            additions += additions_for_npc(npc_list)
        for coin in additions:
            tx_additions.append(coin)
            byte_array_tx.append(bytearray(coin.puzzle_hash))
        for npc in npc_list:
            tx_removals.append(npc.coin_name)
            byte_array_tx.append(bytearray(npc.coin_name))

        byte_array_tx.append(bytearray(farmer_reward_puzzlehash))
        byte_array_tx.append(bytearray(pool_target.puzzle_hash))
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

        transactions_info = TransactionsInfo(
            bytes([0] * 32), generator_hash, aggregate_sig, uint64(spend_bundle_fees), cost, reward_claims_incorporated
        )
        if prev_block is None:
            prev_block_hash: bytes32 = constants.GENESIS_PREV_HASH
        else:
            prev_block_hash = prev_block.header_hash

        foliage_block = FoliageBlock(
            prev_block_hash,
            timestamp,
            filter_hash,
            additions_root,
            removals_root,
            transactions_info.get_hash(),
        )
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
    timestamp: Optional[uint64] = None,
    seed: bytes32 = b"",
    spend_bundle: Optional[SpendBundle] = None,
    prev_sub_block: Optional[SubBlockRecord] = None,
    sub_blocks=None,
    finished_sub_slots=None,
) -> UnfinishedBlock:
    overflow = sp_iters > ip_iters
    total_iters_sp = sub_slot_start_total_iters + sp_iters
    prev_block: Optional[SubBlockRecord] = None  # Set this if we are a block
    is_genesis = False
    if prev_sub_block is not None:
        curr = prev_sub_block
        is_block, prev_block = get_prev_block(curr, prev_block, sub_blocks, total_iters_sp)
        prev_sub_slot_iters: uint64 = calculate_sub_slot_iters(constants, prev_sub_block.ips)
    else:
        # Genesis is a block
        is_genesis = True
        is_block = True
        prev_sub_slot_iters = calculate_sub_slot_iters(constants, constants.IPS_STARTING)

    new_sub_slot: bool = len(finished_sub_slots) > 0

    cc_sp_hash: Optional[bytes32] = slot_cc_challenge

    # Only enters this if statement if we are in testing mode (making VDF proofs here)
    if signage_point.cc_vdf is not None:
        cc_sp_hash = signage_point.cc_vdf.output.get_hash()
        rc_sp_hash = signage_point.rc_vdf.output.get_hash()
    else:
        if new_sub_slot:
            rc_sp_hash = finished_sub_slots[-1].reward_chain.get_hash()
        else:
            if is_genesis:
                rc_sp_hash = constants.FIRST_RC_CHALLENGE
            else:
                curr = prev_sub_block
                while not curr.first_in_sub_slot:
                    curr = sub_blocks[curr.prev_hash]
                rc_sp_hash = curr.finished_reward_slot_hashes[-1]
        signage_point = SignagePoint(None, None, None, None)

    cc_sp_signature: Optional[G2Element] = get_plot_signature(cc_sp_hash, proof_of_space.plot_public_key)
    rc_sp_signature: Optional[G2Element] = get_plot_signature(rc_sp_hash, proof_of_space.plot_public_key)
    assert cc_sp_signature is not None
    assert rc_sp_signature is not None
    assert blspy.AugSchemeMPL.verify(proof_of_space.plot_public_key, cc_sp_hash, cc_sp_signature)

    # print(
    #     f"Calculating iters.. sssti {sub_slot_start_total_iters} ip iters {ip_iters} overflow {overflow} {prev_sub_slot_iters}"
    # )
    total_iters = uint128(sub_slot_start_total_iters + ip_iters + (prev_sub_slot_iters if overflow else 0))

    rc_sub_block = RewardChainSubBlockUnfinished(
        total_iters,
        signage_point_index,
        proof_of_space,
        signage_point.cc_vdf,
        cc_sp_signature,
        signage_point.rc_vdf,
        rc_sp_signature,
    )

    foliage_sub_block, foliage_block, transactions_info, solution_program = create_foliage(
        constants,
        rc_sub_block,
        spend_bundle,
        prev_sub_block,
        prev_block,
        sub_blocks,
        is_block,
        timestamp,
        farmer_reward_puzzle_hash,
        pool_target,
        get_plot_signature,
        get_pool_signature,
        seed,
    )

    return UnfinishedBlock(
        [],
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
    difficulty: uint64,
) -> FullBlock:
    # Replace things that need to be replaced, since foliage blocks did not necessarily have the latest information
    if prev_sub_block is None:
        new_weight = uint128(difficulty)
        new_height = uint32(0)
        new_foliage_sub_block = unfinished_block.foliage_sub_block
    else:
        new_weight = uint128(prev_sub_block.weight + difficulty)
        new_height = uint32(prev_sub_block.height + 1)
        new_foliage_sub_block = replace(
            unfinished_block.foliage_sub_block, prev_sub_block_hash=prev_sub_block.header_hash
        )
    ret = FullBlock(
        finished_sub_slots,
        RewardChainSubBlock(
            new_weight,
            new_height,
            unfinished_block.reward_chain_sub_block.total_iters,
            unfinished_block.reward_chain_sub_block.signage_point_index,
            unfinished_block.reward_chain_sub_block.proof_of_space,
            unfinished_block.reward_chain_sub_block.challenge_chain_sp_vdf,
            unfinished_block.reward_chain_sub_block.challenge_chain_sp_signature,
            cc_ip_vdf,
            unfinished_block.reward_chain_sub_block.reward_chain_sp_vdf,
            unfinished_block.reward_chain_sub_block.reward_chain_sp_signature,
            rc_ip_vdf,
            icc_ip_vdf,
            unfinished_block.foliage_block is not None,
        ),
        unfinished_block.challenge_chain_sp_proof,
        cc_ip_proof,
        unfinished_block.reward_chain_sp_proof,
        rc_ip_proof,
        icc_ip_proof,
        new_foliage_sub_block,
        unfinished_block.foliage_block,
        unfinished_block.transactions_info,
        unfinished_block.transactions_generator,
    )
    return recursive_replace(ret, "foliage_sub_block.reward_block_hash", ret.reward_chain_sub_block.get_hash())
