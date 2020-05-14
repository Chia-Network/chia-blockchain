import logging
import time
from typing import Dict, List, Optional, Tuple
import blspy

from src.consensus.block_rewards import calculate_block_reward
from src.consensus.pot_iterations import calculate_iterations_quality
from src.full_node.difficulty_adjustment import get_next_difficulty, get_next_min_iters
from src.types.challenge import Challenge
from src.types.header import Header
from src.types.header_block import HeaderBlock
from src.types.full_block import FullBlock
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.errors import Err
from src.util.hash import std_hash
from src.util.ints import uint32, uint64
from src.util.significant_bits import count_significant_bits

log = logging.getLogger(__name__)


async def validate_unfinished_block_header(
    constants: Dict,
    headers: Dict[bytes32, Header],
    height_to_hash: Dict[uint32, bytes32],
    block_header: Header,
    proof_of_space: ProofOfSpace,
    prev_header_block: Optional[HeaderBlock],
    pre_validated: bool = False,
    pos_quality_string: bytes32 = None,
) -> Tuple[Optional[Err], Optional[uint64]]:
    """
    Block validation algorithm. Returns the number of VDF iterations that this block's
    proof of time must have, if the candidate block is fully valid (except for proof of
    time). The same as validate_block, but without proof of time and challenge validation.
    If the block is invalid, an error code is returned.

    Does NOT validate transactions and fees.
    """
    if not pre_validated:
        # 1. The hash of the proof of space must match header_data.proof_of_space_hash
        if proof_of_space.get_hash() != block_header.data.proof_of_space_hash:
            return (Err.INVALID_POSPACE_HASH, None)

        # 2. The coinbase signature must be valid, according the the pool public key
        pair = block_header.data.coinbase_signature.PkMessagePair(
            proof_of_space.pool_pubkey, block_header.data.coinbase.name(),
        )

        if not block_header.data.coinbase_signature.validate([pair]):
            return (Err.INVALID_COINBASE_SIGNATURE, None)

        # 3. Check harvester signature of header data is valid based on harvester key
        if not block_header.harvester_signature.verify(
            [blspy.Util.hash256(block_header.data.get_hash())],
            [proof_of_space.plot_pubkey],
        ):
            return (Err.INVALID_HARVESTER_SIGNATURE, None)

    # 4. If not genesis, the previous block must exist
    if prev_header_block is not None and block_header.prev_header_hash not in headers:
        return (Err.DOES_NOT_EXTEND, None)

    # 5. If not genesis, the timestamp must be >= the average timestamp of last 11 blocks
    # and less than 2 hours in the future (if block height < 11, average all previous blocks).
    # Average is the sum, int diveded by the number of timestamps
    if prev_header_block is not None:
        last_timestamps: List[uint64] = []
        curr = prev_header_block.header
        while len(last_timestamps) < constants["NUMBER_OF_TIMESTAMPS"]:
            last_timestamps.append(curr.data.timestamp)
            fetched = headers.get(curr.prev_header_hash, None)
            if not fetched:
                break
            curr = fetched
        if len(last_timestamps) != constants["NUMBER_OF_TIMESTAMPS"]:
            # For blocks 1 to 10, average timestamps of all previous blocks
            assert curr.height == 0
        prev_time: uint64 = uint64(int(sum(last_timestamps) // len(last_timestamps)))
        if block_header.data.timestamp < prev_time:
            return (Err.TIMESTAMP_TOO_FAR_IN_PAST, None)
        if block_header.data.timestamp > time.time() + constants["MAX_FUTURE_TIME"]:
            return (Err.TIMESTAMP_TOO_FAR_IN_FUTURE, None)

    # 7. Extension data must be valid, if any is present

    # Compute challenge of parent
    challenge_hash: bytes32
    if prev_header_block is not None:
        challenge: Challenge = prev_header_block.challenge
        challenge_hash = challenge.get_hash()
        # 8. Check challenge hash of prev is the same as in pos
        if challenge_hash != proof_of_space.challenge_hash:
            return (Err.INVALID_POSPACE_CHALLENGE, None)

    # 10. The proof of space must be valid on the challenge
    if pos_quality_string is None:
        pos_quality_string = proof_of_space.verify_and_get_quality_string()
        if not pos_quality_string:
            return (Err.INVALID_POSPACE, None)

    if prev_header_block is not None:
        # 11. If not genesis, the height on the previous block must be one less than on this block
        if block_header.height != prev_header_block.height + 1:
            return (Err.INVALID_HEIGHT, None)
    else:
        # 12. If genesis, the height must be 0
        if block_header.height != 0:
            return (Err.INVALID_HEIGHT, None)

    # 13. The coinbase reward must match the block schedule
    coinbase_reward = calculate_block_reward(block_header.height)
    if coinbase_reward != block_header.data.coinbase.amount:
        return (Err.INVALID_COINBASE_AMOUNT, None)

    # 13b. The coinbase parent id must be the height
    if block_header.data.coinbase.parent_coin_info != block_header.height.to_bytes(
        32, "big"
    ):
        return (Err.INVALID_COINBASE_PARENT, None)

    # 13c. The fees coin parent id must be hash(hash(height))
    if block_header.data.fees_coin.parent_coin_info != std_hash(
        std_hash(uint32(block_header.height))
    ):
        return (Err.INVALID_FEES_COIN_PARENT, None)

    difficulty: uint64
    if prev_header_block is not None:
        difficulty = get_next_difficulty(
            constants, headers, height_to_hash, prev_header_block.header
        )
        min_iters = get_next_min_iters(
            constants, headers, height_to_hash, prev_header_block
        )
    else:
        difficulty = uint64(constants["DIFFICULTY_STARTING"])
        min_iters = uint64(constants["MIN_ITERS_STARTING"])

    number_of_iters: uint64 = calculate_iterations_quality(
        pos_quality_string, proof_of_space.size, difficulty, min_iters,
    )

    assert count_significant_bits(difficulty) <= constants["SIGNIFICANT_BITS"]
    assert count_significant_bits(min_iters) <= constants["SIGNIFICANT_BITS"]

    if prev_header_block is not None:
        # 17. If not genesis, the total weight must be the parent weight + difficulty
        if block_header.weight != prev_header_block.weight + difficulty:
            return (Err.INVALID_WEIGHT, None)

        # 18. If not genesis, the total iters must be parent iters + number_iters
        if (
            block_header.data.total_iters
            != prev_header_block.header.data.total_iters + number_of_iters
        ):
            return (Err.INVALID_TOTAL_ITERS, None)
    else:
        # 19. If genesis, the total weight must be starting difficulty
        if block_header.weight != difficulty:
            return (Err.INVALID_WEIGHT, None)

        # 20. If genesis, the total iters must be number iters
        if block_header.data.total_iters != number_of_iters:
            return (Err.INVALID_TOTAL_ITERS, None)

    return (None, number_of_iters)


async def validate_finished_block_header(
    constants: Dict,
    headers: Dict[bytes32, Header],
    height_to_hash: Dict[uint32, bytes32],
    block: HeaderBlock,
    prev_header_block: Optional[HeaderBlock],
    genesis: bool,
    pre_validated: bool = False,
    pos_quality_string: bytes32 = None,
) -> Optional[Err]:
    """
    Block validation algorithm. Returns None iff the candidate block is valid,
    and extends something in the blockchain.

    Does NOT validate transactions and fees.
    """
    if not genesis:
        if prev_header_block is None:
            return Err.DOES_NOT_EXTEND
    else:
        assert prev_header_block is None

    # 0. Validate unfinished block (check the rest of the conditions)
    err, number_of_iters = await validate_unfinished_block_header(
        constants,
        headers,
        height_to_hash,
        block.header,
        block.proof_of_space,
        prev_header_block,
        pre_validated,
        pos_quality_string,
    )
    if err is not None:
        return err

    assert number_of_iters is not None

    if block.proof_of_time is None:
        return Err.BLOCK_IS_NOT_FINISHED

    # 1. The number of iterations (based on quality, pos, difficulty, ips) must be the same as in the PoT
    if number_of_iters != block.proof_of_time.number_of_iterations:
        return Err.INVALID_NUM_ITERATIONS

    # 2. the PoT must be valid, on a discriminant of size 1024, and the challenge_hash
    if not pre_validated:
        if not block.proof_of_time.is_valid(constants["DISCRIMINANT_SIZE_BITS"]):
            return Err.INVALID_POT
    # 3. If not genesis, the challenge_hash in the proof of time must match the challenge on the previous block
    if not genesis:
        assert prev_header_block is not None
        prev_challenge: Optional[Challenge] = prev_header_block.challenge
        assert prev_challenge is not None

        if block.proof_of_time.challenge_hash != prev_challenge.get_hash():
            return Err.INVALID_POT_CHALLENGE
    else:
        # 9. If genesis, the challenge hash in the proof of time must be the same as in the proof of space
        assert block.proof_of_time is not None
        challenge_hash = block.proof_of_time.challenge_hash

        if challenge_hash != block.proof_of_space.challenge_hash:
            return Err.INVALID_POSPACE_CHALLENGE

    return None


def pre_validate_finished_block_header(constants: Dict, data: bytes):
    """
    Validates all parts of block that don't need to be serially checked
    """
    block = FullBlock.from_bytes(data)

    if not block.proof_of_time:
        return False, None

    # 4. Check PoT
    if not block.proof_of_time.is_valid(constants["DISCRIMINANT_SIZE_BITS"]):
        return False, None

    # 9. Check harvester signature of header data is valid based on harvester key
    if not block.header.harvester_signature.verify(
        [blspy.Util.hash256(block.header.data.get_hash())],
        [block.proof_of_space.plot_pubkey],
    ):
        return False, None

    # 10. Check proof of space based on challenge
    pos_quality_string = block.proof_of_space.verify_and_get_quality_string()

    if not pos_quality_string:
        return False, None

    return True, bytes(pos_quality_string)
