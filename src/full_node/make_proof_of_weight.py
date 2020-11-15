from typing import Dict, Optional, List

from blspy import G2Element

from src.consensus.constants import ConsensusConstants
from src.full_node.block_store import BlockStore
from src.full_node.sub_block_record import SubBlockRecord
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.proof_of_space import ProofOfSpace
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


def choose_sub_epoch(sub_epoch_blocks_N: uint32, total_number_of_blocks: uint64) -> bool:
    # todo
    return True


async def get_header_block(header_hash: bytes32, block_store: BlockStore) -> HeaderBlock:
    # todo avoid this db call, add needed fields to sub_blocks / build header cache
    block = await block_store.get_full_block(header_hash)
    assert block is not None
    return full_block_to_header(block)


def create_sub_epoch_segments(
    constants: ConsensusConstants,
    block: SubBlockRecord,
    sub_epoch_blocks_n: uint32,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    sub_epoch_n: uint32,
    block_store: BlockStore,
) -> List[SubepochChallengeSegment]:
    """
    received the last block in sub epoch and creates List[SubepochChallengeSegment] for that sub_epoch
    """

    segments: List[SubepochChallengeSegment] = []
    curr = block

    count = sub_epoch_blocks_n
    while not count == 0:
        curr = sub_blocks[curr.prev_hash]

        # todo skip overflows from last sub epoch

        if not curr.is_challenge_sub_block(constants):
            continue

        header_block = await get_header_block(curr, block_store)
        proof_of_space: Optional[ProofOfSpace] = None
        signage_point_vdf: Optional[VDFProof] = None
        signage_point_sig: Optional[G2Element] = None
        infusion_point_vdf: Optional[VDFProof] = None
        infusion_to_slot_end_vdf: Optional[VDFProof] = None
        slot_vdf: Optional[VDFProof] = None

        if curr.deficit == constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1:
            proof_of_space = header_block.reward_chain_sub_block.proof_of_space
            signage_point_vdf = header_block.challenge_chain_sp_proof
            signage_point_sig = header_block.reward_chain_sub_block.challenge_chain_sp_signature
            infusion_point_vdf = header_block.challenge_chain_ip_proof
            infusion_to_slot_end_vdf = header_block.finished_sub_slots[-1].proofs.infused_challenge_chain_slot_proof
        else:
            slot_vdf = header_block.finished_sub_slots[-1].proofs.challenge_chain_slot_proof
        segment = SubepochChallengeSegment(
            sub_epoch_n,
            proof_of_space,
            signage_point_vdf,
            signage_point_sig,
            infusion_point_vdf,
            infusion_to_slot_end_vdf,
            slot_vdf,
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
    block_store: BlockStore,
) -> WeightProof:
    """
    Creates a weight proof object
    """
    sub_epoch_data: List[SubEpochData] = []
    sub_epoch_segments: List[SubepochChallengeSegment] = []
    proof_blocks: List[HeaderBlock] = []
    curr: SubBlockRecord = sub_blocks[tip]
    sub_epoch_n = uint32(0)
    while not total_number_of_blocks == 0:
        # next sub block
        curr = sub_blocks[curr.prev_header_hash]
        # for each sub-epoch
        if curr.sub_epoch_summary_included is not None:
            sub_epoch_data.append(make_sub_epoch_data(curr.sub_epoch_summary_included))
            # get sub_epoch_blocks_n in sub_epoch
            sub_epoch_blocks_n = get_sub_epoch_block_num(constants, curr, sub_blocks)
            #   sample sub epoch
            if choose_sub_epoch(sub_epoch_blocks_n, total_number_of_blocks):
                create_sub_epoch_segments(constants, curr, sub_epoch_blocks_n, sub_blocks, sub_epoch_n, block_store)
            sub_epoch_n += 1

        if recent_blocks_n > 0:
            # add to needed reward chain recent blocks
            full_block = await block_store.get_full_block(curr.prev_hash)
            proof_blocks.append(full_block_to_header(full_block))
            recent_blocks_n -= 1

        total_number_of_blocks -= 1

    return WeightProof(sub_epoch_data, sub_epoch_segments, proof_blocks)


def validate_weight_proof(proof: WeightProof) -> bool:
    # todo
    return False
