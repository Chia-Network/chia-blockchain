from typing import List

from src.types.header_block import HeaderBlock


def verify_weight(tip: HeaderBlock, proof_blocks: List[HeaderBlock]) -> bool:
    """
    Verifies whether the weight of the tip is valid or not. Naively, looks at every block
    from genesis, verifying proof of space, proof of time, and difficulty resets.
    # TODO: implement
    """
    for height, block in enumerate(proof_blocks):
        if not block.height == height:
            return False

    return True
