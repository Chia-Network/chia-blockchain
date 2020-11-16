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


def create_sub_epoch_segment(block: HeaderBlock, sub_epoch_n: uint32) -> SubepochChallengeSegment:

    sub_slot = block.finished_sub_slots[-1]
    # Proof of space
    proof_of_space = block.reward_chain_sub_block.proof_of_space  # if infused
    # Signature of signage point
    cc_signage_point_sig = block.reward_chain_sub_block.challenge_chain_sp_signature  # if infused)

    # VDF to signage point
    # todo this should be the combined challenge_chain_sp_proofs
    cc_signage_point_vdf = block.challenge_chain_sp_proof  # if infused

    # VDF to infusion point
    # todo this should be the combined challenge_chain_ip_proofs
    infusion_point_vdf = block.challenge_chain_ip_proof  # if infused

    # VDF from infusion point to end of subslot
    slot_end_vdf = sub_slot.proofs.challenge_chain_slot_proof  # if infused

    # VDF from beginning to end of subslot
    vdfs: List[VDFProof] = []
    for sub_slot in block.finished_sub_slots[1:]:
        vdfs.append(sub_slot.proofs.infused_challenge_chain_slot_proof)

    return SubepochChallengeSegment(
        sub_epoch_n,
        proof_of_space,
        cc_signage_point_vdf,
        cc_signage_point_sig,
        infusion_point_vdf,
        slot_end_vdf,
        combine_proofs(vdfs),
    )


def get_sub_epoch_block_num(
    constants: ConsensusConstants, block: SubBlockRecord, sub_blocks: Dict[bytes32, SubBlockRecord]
) -> uint32:
    """
    returns the number of blocks in a sub epoch
    ending with" "block""
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


def create_sub_epoch_segments(
    constants: ConsensusConstants,
    block: SubBlockRecord,
    sub_epoch_blocks_n: uint32,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    sub_epoch_n: uint32,
    header_cache: Dict[bytes32, HeaderBlock],
) -> List[SubepochChallengeSegment]:
    """
    received the last block in sub epoch and creates List[SubepochChallengeSegment] for that sub_epoch
    """

    segments: List[SubepochChallengeSegment] = []
    curr = block

    count = sub_epoch_blocks_n
    while not count == 0:
        curr = sub_blocks[curr.prev_hash]
        header_block = header_cache[curr.header_hash]
        # todo skip overflows from last sub epoch

        if not curr.is_challenge_sub_block(constants):
            continue
        else:
            segment = create_sub_epoch_segment(header_block, sub_epoch_n)
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
                create_sub_epoch_segments(constants, curr, sub_epoch_blocks_n, sub_blocks, sub_epoch_n, header_cache)
            sub_epoch_n += 1

        if recent_blocks_n > 0:
            # add to needed reward chain recent blocks
            proof_blocks.append(header_block.reward_chain_sub_block)
            recent_blocks_n -= 1

        total_number_of_blocks -= 1

    return WeightProof(sub_epoch_data, sub_epoch_segments, proof_blocks)


def validate_weight_proof(proof: WeightProof) -> bool:
    # todo
    # sub epoch summaries
    #   validate hashes
    # Calculate weight make sure equals to peak
    #
    # samples
    #   validate first sub slot -> validate all the sub slots in the way -> validate challenge chain end of slot

    return False
