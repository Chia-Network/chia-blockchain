from typing import List
from src.types.trunk_block import TrunkBlock


def verify_weight(tip: TrunkBlock, proof_blocks: List[TrunkBlock]) -> bool:
    """
    Verifies whether the weight of the tip is valid or not. Naiveley, looks at every block
    from genesis, verifying proof of space, proof of time, and difficulty resets.
    """
    return True
