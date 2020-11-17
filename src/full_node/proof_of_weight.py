import random
from typing import Dict, Optional, List

from src.types.reward_chain_sub_block import RewardChainSubBlock
from src.consensus.constants import ConsensusConstants
from src.full_node.sub_block_record import SubBlockRecord
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.vdf import VDFProof
from src.types.weight_proof import WeightProof, SubEpochData, SubepochChallengeSegment
from src.util.hash import std_hash
from src.util.ints import uint32, uint64, uint8


def full_block_to_header(block: FullBlock) -> HeaderBlock:
    return HeaderBlock(
        block.finished_sub_slots,
        block.reward_chain_sub_block,
        block.challenge_chain_sp_proof,
        block.challenge_chain_ip_proof,
        block.reward_chain_sp_proof,
        block.reward_chain_ip_proof,
        block.infused_challenge_chain_ip_proof,
        block.foliage_sub_block,
        block.foliage_block,
        b"",  # No filter
    )


def combine_proofs(proofs: List[VDFProof]) -> VDFProof:
    # todo
    return VDFProof(witness_type=uint8(0), witness=b"")


def make_sub_epoch_data(
    sub_epoch_summary: SubEpochSummary,
) -> SubEpochData:
    reward_chain_hash: bytes32 = sub_epoch_summary.reward_chain_hash
    #  Number of subblocks overflow in previous slot
    previous_sub_epoch_overflows: uint8 = sub_epoch_summary.num_sub_blocks_overflow  # total in sub epoch - expected
    #  New work difficulty and iterations per subslot
    sub_slot_iters: Optional[uint64] = sub_epoch_summary.new_ips
    new_difficulty: Optional[uint64] = sub_epoch_summary.new_difficulty
    return SubEpochData(reward_chain_hash, previous_sub_epoch_overflows, sub_slot_iters, new_difficulty)


def get_sub_epoch_block_num(block: SubBlockRecord, sub_blocks: Dict[bytes32, SubBlockRecord]) -> uint32:
    """
    returns the number of blocks in a sub epoch ending with
    """
    curr = block
    count: uint32 = uint32(0)
    while not curr.sub_epoch_summary_included:
        # todo skip overflows from last sub epoch
        curr = sub_blocks[curr.prev_hash]
        count += 1

    count += 1
    return count


def choose_sub_epoch(sub_epoch_blocks_N: uint32, rng: random.Random, total_number_of_blocks: uint64) -> bool:
    prob = sub_epoch_blocks_N / total_number_of_blocks
    for i in range(sub_epoch_blocks_N):
        if rng.random() < prob:
            return True
    return False


# returns a challenge chain vdf from slot start to signage point
def get_cc_combined_signage_vdf(block: HeaderBlock, header_cache: Dict[bytes32, SubBlockRecord]) -> VDFProof:
    # combine cc vdfs of all reward blocks from the start of the slot
    # blocks  = get all reward blocks from the start of the slot to sp
    proofs: List[VDFProof] = []
    curr = block

    # get all cc_vdfs from start of sub slot until challenge block
    while not len(curr.finished_sub_slots) > 0:
        proofs.append(curr.challenge_chain_sp_proof)
        proofs.append(curr.challenge_chain_ip_proof)
        # prev
        curr = header_cache[curr.prev_hash]

    # handle empty sub_slots
    for sub_slot in curr.finished_sub_slots:
        proofs.append(sub_slot.proofs.challenge_chain_slot_proof)

    return combine_proofs(proofs)


# returns a challenge chain vdf from infusion point to end of slot
def get_cc_combined_ip_to_slot_end_vdf(
    constants: ConsensusConstants,
    block: HeaderBlock,
    height_to_hash: Dict[uint32, bytes32],
    header_cache: Dict[bytes32, SubBlockRecord],
) -> VDFProof:
    # combine cc vdfs of all reward blocks from block to the end of the slot
    # blocks = reward blocks from block to the end of the slot
    proofs: List[VDFProof] = []
    curr = block
    # get all cc vdfs from ip to end of  slot

    while not curr.deficit < constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:

        for sub_slot in curr.finished_sub_slots:
            proofs.append(sub_slot.proofs.infused_challenge_chain_slot_proof)

        proofs.append(curr.challenge_chain_sp_proof)
        proofs.append(curr.challenge_chain_ip_proof)
        # next
        curr = header_cache[height_to_hash[curr.height + 1]]

    return combine_proofs(proofs)


# returns an infused challenge chain vdf for the challenge slot
def get_icc_combined_slot_vdf(
    constants: ConsensusConstants,
    block: HeaderBlock,
    height_to_hash: Dict[uint32, bytes32],
    header_cache: Dict[bytes32, SubBlockRecord],
) -> VDFProof:
    # combine icc vdfs of all reward blocks from block to the end of the slot
    # blocks = reward blocks from block to the end of the slot
    proofs: List[VDFProof] = []
    curr = block
    while not curr.deficit < constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
        proofs.append(curr.infused_challenge_chain_ip_proof)
        curr = header_cache[height_to_hash[curr.height + 1]]
    return combine_proofs(proofs)


def handle_challenge_segment(
    constants: ConsensusConstants,
    block: HeaderBlock,
    sub_epoch_n: uint32,
    height_to_hash: Dict[uint32, bytes32],
    sub_blocks: Dict[bytes32, SubBlockRecord],
) -> SubepochChallengeSegment:

    # Proof of space
    proof_of_space = block.reward_chain_sub_block.proof_of_space  # if infused
    # Signature of signage point
    cc_signage_point_sig = block.reward_chain_sub_block.challenge_chain_sp_signature  # if infused)

    # VDF from slot start to signage point
    # needs all reward blocks from sub slot start to sp
    cc_signage_point_vdf = get_cc_combined_signage_vdf(block, sub_blocks)  # if infused

    # VDF from signage to infusion point
    infusion_point_vdf = block.challenge_chain_ip_proof  # if infused

    # VDF from infusion point to end of slot
    # needs all reward blocks from sp to end of sub slot
    slot_end_vdf = get_cc_combined_ip_to_slot_end_vdf(constants, block, height_to_hash, sub_blocks)  # if infused

    # VDF from beginning to end of slot
    icc_challenge_slot_vdf = get_icc_combined_slot_vdf(constants, block, height_to_hash, sub_blocks)

    return SubepochChallengeSegment(
        sub_epoch_n,
        proof_of_space,
        cc_signage_point_sig,
        cc_signage_point_vdf,
        infusion_point_vdf,
        icc_challenge_slot_vdf,
        slot_end_vdf,
        block.reward_chain_sub_block.reward_chain_ip_vdf,
    )


def create_sub_epoch_segments(
    constants: ConsensusConstants,
    block: SubBlockRecord,
    sub_epoch_blocks_n: uint32,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    sub_epoch_n: uint32,
    header_cache: Dict[bytes32, HeaderBlock],
    height_to_hash: Dict[uint32, bytes32],
) -> List[SubepochChallengeSegment]:
    """
    received the last block in sub epoch and creates List[SubepochChallengeSegment] for that sub_epoch
    """

    segments: List[SubepochChallengeSegment] = []
    curr = block

    count = sub_epoch_blocks_n
    while not count == 0:
        curr = sub_blocks[curr.prev_hash]
        if not curr.is_challenge_sub_block(constants):
            continue

        header_block = header_cache[curr.header_hash]
        segment = handle_challenge_segment(
            constants,
            header_block,
            sub_epoch_n,
            height_to_hash,
            sub_blocks,
        )
        segments.append(segment)
        count -= 1

    return segments


def make_weight_proof(
    constants: ConsensusConstants,
    recent_blocks_n: uint32,
    tip: bytes32,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    total_number_of_blocks: uint64,
    header_cache: Dict[bytes32, HeaderBlock],
    height_to_hash: Dict[uint32, bytes32],
) -> WeightProof:
    """
    Creates a weight proof object
    """
    sub_epoch_data: List[SubEpochData] = []
    sub_epoch_segments: List[SubepochChallengeSegment] = []
    proof_blocks: List[RewardChainSubBlock] = []
    curr: SubBlockRecord = sub_blocks[tip]
    sub_epoch_n = uint32(0)
    rng: random.Random = random.Random(tip)
    while not total_number_of_blocks == 0:
        # next sub block
        curr = sub_blocks[curr.prev_header_hash]
        header_block = header_cache[curr.header_hash]
        # for each sub-epoch
        if curr.sub_epoch_summary_included is not None:
            sub_epoch_data.append(make_sub_epoch_data(curr.sub_epoch_summary_included))
            # get sub_epoch_blocks_n in sub_epoch
            sub_epoch_blocks_n = get_sub_epoch_block_num(constants, curr, sub_blocks)
            #   sample sub epoch
            if choose_sub_epoch(sub_epoch_blocks_n, rng, total_number_of_blocks):
                sub_epoch_segments = create_sub_epoch_segments(
                    constants, curr, sub_epoch_blocks_n, sub_blocks, sub_epoch_n, header_cache, height_to_hash
                )
            sub_epoch_n += 1

        if recent_blocks_n > 0:
            # add to needed reward chain recent blocks
            proof_blocks.append(header_block.reward_chain_sub_block)
            recent_blocks_n -= 1

        total_number_of_blocks -= 1

    return WeightProof(sub_epoch_data, sub_epoch_segments, proof_blocks)


def validate_weight_proof(weight_proof: WeightProof, fork_point_weight: uint64) -> bool:

    # sub epoch summaries validate hashes
    ses_hash = std_hash(weight_proof.sub_epoch_data[0])
    for sub_epoch_data in weight_proof.sub_epoch_data[:1]:
        if sub_epoch_data.prev_ses != ses_hash:
            return False
        ses_hash = std_hash(sub_epoch_data)

    # Calculate weight make sure equals to weight of peak
    weight_to_prove = uint64(0)
    for sub_epoch_data in weight_proof.sub_epoch_data:
        weight_to_prove += sub_epoch_data.new_difficulty

    peak = weight_proof.recent_reward_chain[-1].weight
    if peak != weight_to_prove + fork_point_weight:
        return False

    # samples
    #   validate first sub slot -> validate all the sub slots in the way -> validate challenge chain end of slot

    return False
