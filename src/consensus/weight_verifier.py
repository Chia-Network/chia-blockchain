from typing import List

from src.types.header_block import HeaderBlock
from src.blockchain import Blockchain
from src.consensus.pot_iterations import calculate_iterations_quality
from src.util.ints import uint64


def verify_weight(
    blockchain: Blockchain,
    tip: HeaderBlock,
    proof_blocks: List[HeaderBlock],
    fork_point: HeaderBlock,
) -> bool:
    """
    Verifies whether the weight of the tip is valid or not.
    Naively, looks at every block from genesis, verifying proof of space,
    proof of time, and difficulty resets.
    """

    prev_block: HeaderBlock = fork_point
    next_difficulty: uint64 = blockchain.get_next_difficulty(fork_point.header_hash)
    next_ips: uint64 = blockchain.get_next_ips(fork_point.header_hash)
    beanstalk: List[HeaderBlock] = []  # Valid potential chain

    for expected_height, header_block in enumerate(proof_blocks, fork_point.height + 1):
        assert prev_block.challenge is not None

        # Check height, weight, pos hash
        if (
            header_block.height != expected_height
            or header_block.weight - prev_block.weight != next_difficulty
            or prev_block.challenge.get_hash()
            != header_block.proof_of_space.challenge_hash
        ):
            return False

        pos_quality = header_block.proof_of_space.verify_and_get_quality()
        if pos_quality is None:
            return False

        num_iters: uint64 = calculate_iterations_quality(
            pos_quality,
            header_block.proof_of_space.size,
            next_difficulty,
            next_ips,
            blockchain.constants["MIN_BLOCK_TIME"],
        )

        # Check vdf iters, valid pot, pot challenge hash
        if (
            header_block.proof_of_time is None
            or num_iters != header_block.proof_of_time.number_of_iterations
            or not header_block.proof_of_time.is_valid(
                blockchain.constants["DISCRIMINANT_SIZE_BITS"]
            )
            or header_block.challenge is None
            or header_block.proof_of_time.challenge_hash
            != prev_block.challenge.get_hash()
            or header_block.challenge.total_iters
            != prev_block.challenge.total_iters + num_iters
        ):
            return False

        # Prepare prev_block, next_difficulty, next_ips for next iteration
        beanstalk.append(header_block)
        next_difficulty = blockchain.get_next_difficulty(
            header_block.header_hash, header_block.height, beanstalk
        )
        next_ips = blockchain.get_next_ips(
            header_block.header_hash, header_block.height, beanstalk
        )
        prev_block = header_block

    return True
