from typing import Dict, List

from src.types.header_block import HeaderBlock
from src.blockchain import Blockchain
from src.types.sized_bytes import bytes32


def verify_weight(
    blockchain: Blockchain,
    tip: HeaderBlock,
    proof_blocks: List[HeaderBlock],
    fork_point: HeaderBlock,
) -> bool:
    """
    Verifies whether the weight of the tip is valid or not. Naively, looks at every block
    from genesis, verifying proof of space, proof of time, and difficulty resets.
    """

    cur_weight = fork_point.weight
    next_difficulty = blockchain.get_next_difficulty(fork_point.header_hash)
    beanstalk: Dict[bytes32, HeaderBlock] = {}  # Valid potential chain

    for expected_height, block in enumerate(proof_blocks, fork_point.height + 1):
        if (
            block.height != expected_height
            or block.weight - cur_weight != next_difficulty
            or block.proof_of_space.verify_and_get_quality() is None
        ):
            return False

        beanstalk[block.header_hash] = block
        next_difficulty = blockchain.get_next_difficulty(block.header_hash, beanstalk)
        cur_weight = block.weight

    return True
