from typing import Dict, Optional, Union

from src.consensus.pot_iterations import calculate_min_iters_from_iterations
from src.types.full_block import FullBlock
from src.types.header import Header
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.util.significant_bits import (
    count_significant_bits,
    truncate_to_significant_bits,
)


def get_next_difficulty(
    constants: Dict,
    headers: Dict[bytes32, Header],
    height_to_hash: Dict[uint32, bytes32],
    block: Header,
) -> uint64:
    """
    Returns the difficulty of the next block that extends onto block.
    Used to calculate the number of iterations. When changing this, also change the implementation
    in wallet_state_manager.py.
    """

    next_height: uint32 = uint32(block.height + 1)
    if next_height < constants["DIFFICULTY_EPOCH"]:
        # We are in the first epoch
        return uint64(constants["DIFFICULTY_STARTING"])

    # Epochs are diffined as intervals of DIFFICULTY_EPOCH blocks, inclusive and indexed at 0.
    # For example, [0-2047], [2048-4095], etc. The difficulty changes DIFFICULTY_DELAY into the
    # epoch, as opposed to the first block (as in Bitcoin).
    elif next_height % constants["DIFFICULTY_EPOCH"] != constants["DIFFICULTY_DELAY"]:
        # Not at a point where difficulty would change
        prev_block: Header = headers[block.prev_header_hash]
        return uint64(block.weight - prev_block.weight)

    #       old diff                  curr diff       new diff
    # ----------|-----|----------------------|-----|-----...
    #           h1    h2                     h3   i-1
    # Height1 is the last block 2 epochs ago, so we can include the time to mine 1st block in previous epoch
    height1 = uint32(
        next_height - constants["DIFFICULTY_EPOCH"] - constants["DIFFICULTY_DELAY"] - 1
    )
    # Height2 is the DIFFICULTY DELAYth block in the previous epoch
    height2 = uint32(next_height - constants["DIFFICULTY_EPOCH"] - 1)
    # Height3 is the last block in the previous epoch
    height3 = uint32(next_height - constants["DIFFICULTY_DELAY"] - 1)

    # h1 to h2 timestamps are mined on previous difficulty, while  and h2 to h3 timestamps are mined on the
    # current difficulty

    block1, block2, block3 = None, None, None

    # We need to backtrack until we merge with the LCA chain, so we can use the height_to_hash dict.
    # This is important if we are on a fork, or beyond the LCA.
    curr: Optional[Header] = block
    assert curr is not None
    while (
        curr.height not in height_to_hash
        or height_to_hash[curr.height] != curr.header_hash
    ):
        if curr.height == height1:
            block1 = curr
        elif curr.height == height2:
            block2 = curr
        elif curr.height == height3:
            block3 = curr
        curr = headers.get(curr.prev_header_hash, None)
        assert curr is not None

    # Once we are before the fork point (and before the LCA), we can use the height_to_hash map
    if not block1 and height1 >= 0:
        # height1 could be -1, for the first difficulty calculation
        block1 = headers[height_to_hash[height1]]
    if not block2:
        block2 = headers[height_to_hash[height2]]
    if not block3:
        block3 = headers[height_to_hash[height3]]
    assert block2 is not None and block3 is not None

    # Current difficulty parameter (diff of block h = i - 1)
    Tc = get_next_difficulty(
        constants, headers, height_to_hash, headers[block.prev_header_hash]
    )

    # Previous difficulty parameter (diff of block h = i - 2048 - 1)
    Tp = get_next_difficulty(
        constants, headers, height_to_hash, headers[block2.prev_header_hash]
    )
    if block1:
        timestamp1 = block1.data.timestamp  # i - 512 - 1
    else:
        # In the case of height == -1, there is no timestamp here, so assume the genesis block
        # took constants["BLOCK_TIME_TARGET"] seconds to mine.
        genesis = headers[height_to_hash[uint32(0)]]
        timestamp1 = genesis.data.timestamp - constants["BLOCK_TIME_TARGET"]
    timestamp2 = block2.data.timestamp  # i - 2048 + 512 - 1
    timestamp3 = block3.data.timestamp  # i - 512 - 1

    # Numerator fits in 128 bits, so big int is not necessary
    # We multiply by the denominators here, so we only have one fraction in the end (avoiding floating point)
    term1 = (
        constants["DIFFICULTY_DELAY"]
        * Tp
        * (timestamp3 - timestamp2)
        * constants["BLOCK_TIME_TARGET"]
    )
    term2 = (
        (constants["DIFFICULTY_WARP_FACTOR"] - 1)
        * (constants["DIFFICULTY_EPOCH"] - constants["DIFFICULTY_DELAY"])
        * Tc
        * (timestamp2 - timestamp1)
        * constants["BLOCK_TIME_TARGET"]
    )

    # Round down after the division
    new_difficulty_precise: uint64 = uint64(
        (term1 + term2)
        // (
            constants["DIFFICULTY_WARP_FACTOR"]
            * (timestamp3 - timestamp2)
            * (timestamp2 - timestamp1)
        )
    )
    # Take only DIFFICULTY_SIGNIFICANT_BITS significant bits
    new_difficulty = uint64(
        truncate_to_significant_bits(
            new_difficulty_precise, constants["SIGNIFICANT_BITS"]
        )
    )
    assert count_significant_bits(new_difficulty) <= constants["SIGNIFICANT_BITS"]

    # Only change by a max factor, to prevent attacks, as in greenpaper, and must be at least 1
    max_diff = uint64(
        truncate_to_significant_bits(
            constants["DIFFICULTY_FACTOR"] * Tc, constants["SIGNIFICANT_BITS"],
        )
    )
    min_diff = uint64(
        truncate_to_significant_bits(
            Tc // constants["DIFFICULTY_FACTOR"], constants["SIGNIFICANT_BITS"],
        )
    )
    if new_difficulty >= Tc:
        return min(new_difficulty, max_diff)
    else:
        return max([uint64(1), new_difficulty, min_diff])


def get_next_min_iters(
    constants: Dict,
    headers: Dict[bytes32, Header],
    height_to_hash: Dict[uint32, bytes32],
    block: Union[FullBlock, HeaderBlock],
) -> uint64:
    """
    Returns the VDF speed in iterations per seconds, to be used for the next block. This depends on
    the number of iterations of the last epoch, and changes at the same block as the difficulty.
    """
    next_height: uint32 = uint32(block.height + 1)
    if next_height < constants["DIFFICULTY_EPOCH"]:
        # First epoch has a hardcoded vdf speed
        return constants["MIN_ITERS_STARTING"]

    prev_block_header: Header = headers[block.prev_header_hash]

    proof_of_space = block.proof_of_space
    difficulty = get_next_difficulty(
        constants, headers, height_to_hash, prev_block_header
    )
    iterations = uint64(
        block.header.data.total_iters - prev_block_header.data.total_iters
    )
    prev_min_iters = calculate_min_iters_from_iterations(
        proof_of_space, difficulty, iterations
    )

    if next_height % constants["DIFFICULTY_EPOCH"] != constants["DIFFICULTY_DELAY"]:
        # Not at a point where ips would change, so return the previous ips
        # TODO: cache this for efficiency
        return prev_min_iters

    # min iters (along with difficulty) will change in this block, so we need to calculate the new one.
    # The calculation is (iters_2 - iters_1) // epoch size
    # 1 and 2 correspond to height_1 and height_2, being the last block of the second to last, and last
    # block of the last epochs. Basically, it's total iterations per block on average.

    # Height1 is the last block 2 epochs ago, so we can include the iterations taken for mining first block in epoch
    height1 = uint32(
        next_height - constants["DIFFICULTY_EPOCH"] - constants["DIFFICULTY_DELAY"] - 1
    )
    # Height2 is the last block in the previous epoch
    height2 = uint32(next_height - constants["DIFFICULTY_DELAY"] - 1)

    block1: Optional[Header] = None
    block2: Optional[Header] = None

    # We need to backtrack until we merge with the LCA chain, so we can use the height_to_hash dict.
    # This is important if we are on a fork, or beyond the LCA.
    curr: Optional[Header] = block.header
    assert curr is not None
    while (
        curr.height not in height_to_hash
        or height_to_hash[curr.height] != curr.header_hash
    ):
        if curr.height == height1:
            block1 = curr
        elif curr.height == height2:
            block2 = curr
        curr = headers.get(curr.prev_header_hash, None)
        assert curr is not None

    # Once we are before the fork point (and before the LCA), we can use the height_to_hash map
    if block1 is None and height1 >= 0:
        # height1 could be -1, for the first difficulty calculation
        block1 = headers.get(height_to_hash[height1], None)
    if block2 is None:
        block2 = headers.get(height_to_hash[height2], None)
    assert block2 is not None

    if block1 is not None:
        iters1 = block1.data.total_iters
    else:
        # In the case of height == -1, iters = 0
        iters1 = uint64(0)

    iters2 = block2.data.total_iters

    min_iters_precise = uint64(
        (iters2 - iters1)
        // (constants["DIFFICULTY_EPOCH"] * constants["MIN_ITERS_PROPORTION"])
    )
    min_iters = uint64(
        truncate_to_significant_bits(min_iters_precise, constants["SIGNIFICANT_BITS"])
    )
    assert count_significant_bits(min_iters) <= constants["SIGNIFICANT_BITS"]
    return min_iters
