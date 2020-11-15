from typing import Dict, Optional, List

from Crypto.Random import random
from blspy import G2Element
from src.full_node.full_block_to_sub_block_record import full_block_to_sub_block_record

from src.consensus.constants import ConsensusConstants
from src.types.sub_epoch_summary import SubEpochSummary


from src.types.proof_of_space import ProofOfSpace
from src.types.vdf import VDFProof


from src.full_node.sub_block_record import SubBlockRecord


from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.weight_proof import WeightProof, SubEpochData, SubepochChallengeSegment
from src.util.ints import uint32, uint64, uint8


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


def make_sub_epoch_segments(block: HeaderBlock, sub_epoch_n: uint32) -> SubepochChallengeSegment:
    slot_vdf: Optional[VDFProof] = None
    proof_of_space: Optional[ProofOfSpace] = None
    signage_point_vdf: Optional[VDFProof] = None
    signage_point_sig: Optional[G2Element] = None
    infusion_point_vdf: Optional[VDFProof] = None
    slot_end_vdf: Optional[VDFProof] = None

    proofs = block.finished_sub_slots[-1].proofs
    if proofs.infused_challenge_chain_slot_proof is None:
        # Proof of space
        proof_of_space: Optional[ProofOfSpace] = HeaderBlock.reward_chain_sub_block.proof_of_space  # if infused
        # VDF to signage point
        signage_point_vdf: Optional[VDFProof] = block.reward_chain_sp_proof  # if infused
        # Signature of signage point
        signage_point_sig: Optional[G2Element] = block.reward_chain_sub_block.challenge_chain_sp_signature  # if infused
        # VDF to infusion point
        infusion_point_vdf: Optional[VDFProof] = block.challenge_chain_ip_proof  # if infused
        # VDF from infusion point to end of subslot
        slot_end_vdf: Optional[VDFProof] = proofs.challenge_chain_slot_proof  # if infused
        # VDF from beginning to end of subslot
    else:
        slot_vdf = proofs.infused_challenge_chain_slot_proof

    return SubepochChallengeSegment(
        sub_epoch_n,
        proof_of_space,
        signage_point_vdf,
        signage_point_sig,
        infusion_point_vdf,
        slot_end_vdf,
        slot_vdf,
    )


# todo finish (almog)
def get_epoch_block_num() -> uint32:
    # todo
    return uint32(0)


def choose_sub_epoch(sub_epoch_blocks_N: uint32, total_number_of_blocks: uint64) -> bool:
    #   sample with chance sub_epoch_blocks_N / total_number_of_blocks X sub_epoch_blocks_N
    # todo
    return True


def prepere_sub_epoch_segments(
    block_header: SubBlockRecord, sub_epoch_blocks_n: uint32
) -> List[SubepochChallengeSegment]:
    #     for each challenge_block ?
    #       sub_epoch_segments.append(make_sub_epoch_segments(block, sub_epoch_n))
    # todo
    return None


def make_weight_proof(
    recent_blocks_n: uint32,
    tip: bytes32,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    total_number_of_blocks: uint64,
) -> WeightProof:
    """
    Creates a weight proof object
    """
    sub_epoch_data: List[SubEpochData] = []
    sub_epoch_segments: List[SubepochChallengeSegment] = []
    proof_blocks: List[HeaderBlock] = []
    curr: SubBlockRecord = sub_blocks[tip]
    sub_epoch_n = 0
    while not total_number_of_blocks == 0:
        # next sub block
        curr = sub_blocks[curr.prev_header_hash]
        # for each sub-epoch
        if curr.sub_epoch_summary_included is not None:
            sub_epoch_data.append(make_sub_epoch_data(curr.sub_epoch_summary_included))
            # get sub_epoch_blocks_n in sub_epoch
            sub_epoch_blocks_n = get_epoch_block_num()
            #   sample sub epoch
            if choose_sub_epoch(sub_epoch_blocks_n, total_number_of_blocks):
                prepere_sub_epoch_segments(curr, sub_epoch_blocks_n)
            sub_epoch_n += 1
        total_number_of_blocks -= 1

        if recent_blocks_n > 0:
            # add to needed reward chain recent blocks
            proof_blocks.append(curr.get_header())
            recent_blocks_n -= 1

    return WeightProof(sub_epoch_data, sub_epoch_segments, proof_blocks)
