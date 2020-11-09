from typing import Dict, Optional

from src.consensus.constants import ConsensusConstants
from src.full_node.sub_block_record import SubBlockRecord
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.util.ints import uint32, uint64, uint8


def make_sub_epoch_summary(
    constants: ConsensusConstants,
    sub_blocks: Dict[bytes32, SubBlockRecord],
    blocks_included_height: uint32,
    prev_sb: SubBlockRecord,
    new_difficulty: Optional[uint64],
    new_ips: Optional[uint64],
) -> SubEpochSummary:
    """
    Creates a sub-epoch-summary object, assuming that the first sub-block in the new sub-epoch is at height
    "blocks_included_height". Prev_sb is the last sub block in the previous sub-epoch. On a new epoch,
    new_difficulty and new_ips are also added.
    """
    assert prev_sb.height == blocks_included_height - 1
    if blocks_included_height // constants.SUB_EPOCH_SUB_BLOCKS == 1:
        ses = SubEpochSummary(constants.GENESIS_SES_HASH, constants.FIRST_RC_CHALLENGE, uint8(0), None, None)
    else:
        curr = prev_sb
        while curr.sub_epoch_summary_included is None:
            curr = sub_blocks[curr.prev_hash]
        assert curr.sub_epoch_summary_included is not None
        prev_ses = curr.sub_epoch_summary_included.get_hash()
        ses = SubEpochSummary(
            prev_ses,
            curr.finished_reward_slot_hashes[-1],
            curr.height % constants.SUB_EPOCH_SUB_BLOCKS,
            new_difficulty,
            new_ips,
        )
    assert ses is not None
    return ses
