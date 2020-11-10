import random
from typing import Optional, Callable, Union, Dict, List

import blspy
from blspy import G2Element, G1Element
from chiabip158 import PyBIP158

from src.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from src.consensus.coinbase import create_pool_coin, create_farmer_coin
from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import calculate_sub_slot_iters
from src.full_node.mempool_check_conditions import get_name_puzzle_conditions
from src.full_node.sub_block_record import SubBlockRecord
from src.types.classgroup import ClassgroupElement
from src.types.coin import Coin, hash_coin_list
from src.types.foliage import FoliageSubBlock, FoliageBlock, TransactionsInfo, FoliageSubBlockData
from src.types.full_block import additions_for_npc
from src.types.pool_target import PoolTarget
from src.types.program import Program
from src.types.proof_of_space import ProofOfSpace
from src.types.reward_chain_sub_block import RewardChainSubBlockUnfinished, RewardChainSubBlock
from src.types.sized_bytes import bytes32
from src.types.unfinished_block import UnfinishedBlock
from src.types.vdf import VDFProof, VDFInfo
from src.util.hash import std_hash
from src.util.ints import uint128, uint64, uint32
from src.util.merkle_set import MerkleSet
from src.util.prev_block import get_prev_block
from src.util.vdf_prover import get_vdf_info_and_proof


def create_foliage(
    constants: ConsensusConstants,
    reward_sub_block: Union[RewardChainSubBlock, RewardChainSubBlockUnfinished],
    fees: uint64,
    aggsig: Optional[G2Element],
    transactions: Optional[Program],
    prev_sub_block: Optional[SubBlockRecord],
    prev_block: Optional[SubBlockRecord],
    sub_blocks: Dict[bytes32, SubBlockRecord],
    is_block: bool,
    timestamp: uint64,
    farmer_reward_puzzlehash: bytes32,
    pool_reward_puzzlehash: bytes32,
    get_plot_signature: Callable[[bytes32, G1Element], G2Element],
    get_pool_signature: Callable[[PoolTarget, G1Element], G2Element],
    seed: bytes32 = b"",
) -> (FoliageSubBlock, Optional[FoliageBlock], Optional[TransactionsInfo]):
    # Use the extension data to create different blocks based on header hash
    random.seed(seed)
    extension_data: bytes32 = random.randint(0, 100000000).to_bytes(32, "big")
    if prev_sub_block is None:
        height: uint32 = uint32(0)
    else:
        height = uint32(prev_sub_block.height + 1)
    cost: uint64 = uint64(0)

    # Create filter
    byte_array_tx: List[bytes32] = []
    tx_additions: List[Coin] = []
    tx_removals: List[bytes32] = []

    pool_target = PoolTarget(pool_reward_puzzlehash, uint32(height))
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

    if is_block:
        if aggsig is None:
            aggsig = G2Element.infinity()
        # TODO: prev generators root
        pool_coin = create_pool_coin(height, pool_reward_puzzlehash, calculate_pool_reward(height))
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
        additions: List[Coin] = reward_claims_incorporated
        npc_list = []
        if transactions is not None:
            error, npc_list, _ = get_name_puzzle_conditions(transactions)
            additions += additions_for_npc(npc_list)
        for coin in additions:
            tx_additions.append(coin)
            byte_array_tx.append(bytearray(coin.puzzle_hash))
        for npc in npc_list:
            tx_removals.append(npc.coin_name)
            byte_array_tx.append(bytearray(npc.coin_name))

        byte_array_tx.append(bytearray(farmer_reward_puzzlehash))
        byte_array_tx.append(bytearray(pool_reward_puzzlehash))
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

        generator_hash = transactions.get_tree_hash() if transactions is not None else bytes32([0] * 32)
        filter_hash: bytes32 = std_hash(encoded)

        transactions_info = TransactionsInfo(
            bytes([0] * 32), generator_hash, aggsig, fees, cost, reward_claims_incorporated
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

    return foliage_sub_block, foliage_block, transactions_info


def create_unfinished_block(
    constants: ConsensusConstants,
    sub_slot_start_total_iters: uint128,
    sp_iters: uint64,
    ip_iters: uint64,
    proof_of_space: ProofOfSpace,
    slot_cc_challenge: bytes32,
    farmer_reward_puzzle_hash: bytes32,
    pool_reward_puzzle_hash: bytes32,
    get_plot_signature: Callable[[bytes32, G1Element], G2Element],
    get_pool_signature: Callable[[PoolTarget, G1Element], G2Element],
    fees: uint64 = uint64(0),
    timestamp: Optional[uint64] = None,
    seed: bytes32 = b"",
    transactions: Optional[Program] = None,
    prev_sub_block: Optional[SubBlockRecord] = None,
    sub_blocks=None,
    finished_sub_slots=None,
    cc_sp_vdf: Optional[VDFInfo] = None,
    cc_sp_proof: Optional[VDFProof] = None,
    rc_sp_vdf: Optional[VDFInfo] = None,
    rc_sp_proof: Optional[VDFProof] = None,
) -> Optional[UnfinishedBlock]:
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
    if sp_iters != 0 and cc_sp_vdf is None:
        if is_genesis:
            cc_vdf_input = ClassgroupElement.get_default_element()
            if len(finished_sub_slots) == 0:
                cc_vdf_challenge = constants.FIRST_CC_CHALLENGE
                rc_vdf_challenge = constants.FIRST_RC_CHALLENGE
            else:
                cc_vdf_challenge = finished_sub_slots[-1].challenge_chain.get_hash()
                rc_vdf_challenge = finished_sub_slots[-1].reward_chain.get_hash()
            sp_vdf_iters = sp_iters
        elif new_sub_slot and not overflow:
            # Start from start of this slot. Case of no overflow slots. Also includes genesis block after
            # empty slot (but not overflowing)
            rc_vdf_challenge: bytes32 = finished_sub_slots[-1].reward_chain.get_hash()
            cc_vdf_challenge = finished_sub_slots[-1].challenge_chain.get_hash()
            sp_vdf_iters = sp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
        elif new_sub_slot and overflow and len(finished_sub_slots) > 1:
            # Start from start of prev slot. Rare case of empty prev slot.
            # Includes genesis block after 2 empty slots
            rc_vdf_challenge = finished_sub_slots[-2].reward_chain.get_hash()
            cc_vdf_challenge = finished_sub_slots[-2].challenge_chain.get_hash()
            sp_vdf_iters = sp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
        elif is_genesis:
            # Genesis block case, first challenge
            rc_vdf_challenge = constants.FIRST_RC_CHALLENGE
            cc_vdf_challenge = constants.FIRST_CC_CHALLENGE
            sp_vdf_iters = sp_iters
            cc_vdf_input = ClassgroupElement.get_default_element()
        else:
            if new_sub_slot and overflow:
                num_sub_slots_to_look_for = 1  # Starting at prev will skip 1 sub-slot
            elif not new_sub_slot and overflow:
                num_sub_slots_to_look_for = 2  # Starting at prev does not skip any sub slots
            elif not new_sub_slot and not overflow:
                num_sub_slots_to_look_for = 1  # Starting at prev does not skip any sub slots, but we should not go back
            else:
                assert False

            next_sb: SubBlockRecord = prev_sub_block
            curr: SubBlockRecord = next_sb
            # Finds a sub-block which is BEFORE our signage point, otherwise goes back to the end of sub-slot
            # Note that for overflow sub-blocks, we are looking at the end of the previous sub-slot
            while num_sub_slots_to_look_for > 0:
                next_sb = curr
                if curr.first_in_sub_slot:
                    num_sub_slots_to_look_for -= 1
                if curr.total_iters < total_iters_sp:
                    break
                if curr.height == 0:
                    break
                curr = sub_blocks[curr.prev_hash]

            if curr.total_iters < total_iters_sp:
                sp_vdf_iters = total_iters_sp - curr.total_iters
                cc_vdf_input = curr.challenge_vdf_output
                rc_vdf_challenge = curr.reward_infusion_new_challenge
            else:
                sp_vdf_iters = sp_iters
                cc_vdf_input = ClassgroupElement.get_default_element()
                rc_vdf_challenge = next_sb.finished_reward_slot_hashes[-1]

            while not curr.first_in_sub_slot:
                curr = sub_blocks[curr.prev_hash]
            cc_vdf_challenge = curr.finished_challenge_slot_hashes[-1]

        cc_sp_vdf, cc_sp_proof = get_vdf_info_and_proof(
            constants,
            cc_vdf_input,
            cc_vdf_challenge,
            sp_vdf_iters,
        )
        rc_sp_vdf, rc_sp_proof = get_vdf_info_and_proof(
            constants,
            ClassgroupElement.get_default_element(),
            rc_vdf_challenge,
            sp_vdf_iters,
        )

        cc_sp_hash = cc_sp_vdf.output.get_hash()
        rc_sp_hash = rc_sp_vdf.output.get_hash()
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

    cc_sp_signature: Optional[G2Element] = get_plot_signature(cc_sp_hash, proof_of_space.plot_public_key)
    rc_sp_signature: Optional[G2Element] = get_plot_signature(rc_sp_hash, proof_of_space.plot_public_key)
    assert cc_sp_signature is not None
    assert rc_sp_signature is not None
    assert blspy.AugSchemeMPL.verify(proof_of_space.plot_public_key, cc_sp_hash, cc_sp_signature)

    # Checks sp filter
    plot_id = proof_of_space.get_plot_id()
    if not ProofOfSpace.can_create_proof(
        constants, plot_id, proof_of_space.challenge_hash, cc_sp_hash, cc_sp_signature
    ):
        return None
    total_iters = uint128(sub_slot_start_total_iters + ip_iters + (prev_sub_slot_iters if overflow else 0))

    rc_sub_block = RewardChainSubBlockUnfinished(
        total_iters,
        proof_of_space,
        cc_sp_vdf,
        cc_sp_signature,
        rc_sp_vdf,
        rc_sp_signature,
    )

    foliage_sub_block, foliage_block, transactions_info = create_foliage(
        constants,
        rc_sub_block,
        fees,
        None,
        None,
        prev_sub_block,
        prev_block,
        sub_blocks,
        is_block,
        timestamp,
        farmer_reward_puzzle_hash,
        pool_reward_puzzle_hash,
        get_plot_signature,
        get_pool_signature,
        seed,
    )

    return UnfinishedBlock(
        [],
        rc_sub_block,
        cc_sp_proof,
        rc_sp_proof,
        foliage_sub_block,
        foliage_block,
        transactions_info,
        transactions,
    )
