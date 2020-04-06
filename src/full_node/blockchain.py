import collections
import logging
import multiprocessing
import time
from enum import Enum
from typing import Dict, List, Optional, Tuple, Set
import asyncio
import concurrent
import blspy

from src.consensus.block_rewards import calculate_block_reward, calculate_base_fee
from src.consensus.constants import constants as consensus_constants
from src.consensus.pot_iterations import (
    calculate_min_iters_from_iterations,
    calculate_iterations_quality,
)
from src.full_node.store import FullNodeStore

from src.types.full_block import FullBlock, additions_for_npc
from src.types.coin import Coin, hash_coin_list
from src.types.coin_record import CoinRecord
from src.types.header_block import HeaderBlock
from src.types.header import Header
from src.types.sized_bytes import bytes32
from src.full_node.coin_store import CoinStore
from src.util.errors import Err, ConsensusError
from src.util.cost_calculator import calculate_cost_of_program
from src.util.merkle_set import MerkleSet
from src.util.blockchain_check_conditions import blockchain_check_conditions_dict
from src.util.condition_tools import hash_key_pairs_for_conditions_dict
from src.util.ints import uint32, uint64
from src.types.challenge import Challenge
from src.util.hash import std_hash
from src.util.significant_bits import (
    truncate_to_significant_bits,
    count_significant_bits,
)

log = logging.getLogger(__name__)


class ReceiveBlockResult(Enum):
    """
    When Blockchain.receive_block(b) is called, one of these results is returned,
    showing whether the block was added to the chain (extending a head or not),
    and if not, why it was not added.
    """

    ADDED_TO_HEAD = 1  # Added to one of the heads, this block is now a new head
    ADDED_AS_ORPHAN = 2  # Added as an orphan/stale block (block that is not a head or ancestor of a head)
    INVALID_BLOCK = 3  # Block was not added because it was invalid
    ALREADY_HAVE_BLOCK = 4  # Block is already present in this blockchain
    DISCONNECTED_BLOCK = (
        5  # Block's parent (previous pointer) is not in this blockchain
    )


class Blockchain:
    # Allow passing in custom overrides for any consesus parameters
    constants: Dict
    # Tips of the blockchain
    tips: List[Header]
    # Least common ancestor of tips
    lca_block: Header
    # Defines the path from genesis to the lca
    height_to_hash: Dict[uint32, bytes32]
    # All headers (but not orphans) from genesis to the tip are guaranteed to be in headers
    headers: Dict[bytes32, Header]
    # Process pool to verify blocks
    pool: concurrent.futures.ProcessPoolExecutor
    # Genesis block
    genesis: FullBlock
    # Unspent Store
    unspent_store: CoinStore
    # Store
    store: FullNodeStore
    # Coinbase freeze period
    coinbase_freeze: uint32

    @staticmethod
    async def create(
        unspent_store: CoinStore, store: FullNodeStore, override_constants: Dict = {},
    ):
        """
        Initializes a blockchain with the header blocks from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = Blockchain()
        self.constants = consensus_constants.copy()
        for key, value in override_constants.items():
            self.constants[key] = value
        self.tips = []
        self.height_to_hash = {}
        self.headers = {}

        self.unspent_store = unspent_store
        self.store = store

        self.genesis = FullBlock.from_bytes(self.constants["GENESIS_BLOCK"])
        self.coinbase_freeze = self.constants["COINBASE_FREEZE_PERIOD"]
        result, removed, error_code = await self.receive_block(self.genesis)
        if result != ReceiveBlockResult.ADDED_TO_HEAD:
            if error_code is not None:
                raise ConsensusError(error_code)
            else:
                raise RuntimeError(f"Invalid genesis block {self.genesis}")

        headers_input: Dict[str, Header] = await self._load_headers_from_store()

        assert self.lca_block is not None
        if len(headers_input) > 0:
            self.headers = headers_input
            for _, header in self.headers.items():
                self.height_to_hash[header.height] = header.header_hash
                await self._reconsider_heads(header, False)
            assert (
                self.headers[self.height_to_hash[uint32(0)]].get_hash()
                == self.genesis.header_hash
            )
        if len(headers_input) > 1:
            assert (
                self.headers[self.height_to_hash[uint32(1)]].prev_header_hash
                == self.genesis.header_hash
            )
        return self

    async def _load_headers_from_store(self) -> Dict[str, Header]:
        """
        Loads headers from disk, into a list of Headers, that can be used
        to initialize the Blockchain class.
        """
        seen_blocks: Dict[str, Header] = {}
        tips: List[Header] = []
        for header in await self.store.get_headers():
            if not tips or header.weight > tips[0].weight:
                tips = [header]
            seen_blocks[header.header_hash] = header

        headers = {}
        if len(tips) > 0:
            curr: Header = tips[0]
            reverse_blocks: List[Header] = [curr]
            while curr.height > 0:
                curr = seen_blocks[curr.prev_header_hash]
                reverse_blocks.append(curr)

            for block in reversed(reverse_blocks):
                headers[block.header_hash] = block
        return headers

    def get_current_tips(self) -> List[Header]:
        """
        Return the heads.
        """
        return self.tips[:]

    async def get_full_tips(self) -> List[FullBlock]:
        """ Return list of FullBlocks that are tips"""
        result: List[FullBlock] = []
        for tip in self.tips:
            block = await self.store.get_block(tip.header_hash)
            if not block:
                continue
            result.append(block)
        return result

    def is_child_of_head(self, block: FullBlock) -> bool:
        """
        True iff the block is the direct ancestor of a head.
        """
        for head in self.tips:
            if block.prev_header_hash == head.header_hash:
                return True
        return False

    def contains_block(self, header_hash: bytes32) -> bool:
        return header_hash in self.headers

    def get_challenge(self, block: FullBlock) -> Optional[Challenge]:
        if block.proof_of_time is None:
            return None
        if block.header_hash not in self.headers:
            return None

        prev_challenge_hash = block.proof_of_space.challenge_hash

        new_difficulty: Optional[uint64]
        if (block.height + 1) % self.constants["DIFFICULTY_EPOCH"] == self.constants[
            "DIFFICULTY_DELAY"
        ]:
            new_difficulty = self.get_next_difficulty(block.header_hash)
        else:
            new_difficulty = None
        return Challenge(
            prev_challenge_hash,
            std_hash(
                block.proof_of_space.get_hash() + block.proof_of_time.output.get_hash()
            ),
            new_difficulty,
        )

    def get_header_block(self, block: FullBlock) -> Optional[HeaderBlock]:
        challenge: Optional[Challenge] = self.get_challenge(block)
        if not challenge or not block.proof_of_time:
            return None
        return HeaderBlock(
            block.proof_of_space, block.proof_of_time, challenge, block.header
        )

    def get_header_hashes(self, tip_header_hash: bytes32) -> List[bytes32]:
        if tip_header_hash not in self.headers:
            raise ValueError("Invalid tip requested")

        curr = self.headers[tip_header_hash]
        ret_hashes = [tip_header_hash]
        while curr.height != 0:
            curr = self.headers[curr.prev_header_hash]
            ret_hashes.append(curr.header_hash)
        return list(reversed(ret_hashes))

    def find_fork_point_alternate_chain(self, alternate_chain: List[bytes32]) -> uint32:
        """
        Takes in an alternate blockchain (headers), and compares it to self. Returns the last header
        where both blockchains are equal.
        """
        lca: Header = self.lca_block

        if lca.height >= len(alternate_chain) - 1:
            raise ValueError("Alternate chain is shorter")
        low: uint32 = uint32(0)
        high = lca.height
        while low + 1 < high:
            mid = (low + high) // 2
            if self.height_to_hash[uint32(mid)] != alternate_chain[mid]:
                high = mid
            else:
                low = mid
        if low == high and low == 0:
            assert self.height_to_hash[uint32(0)] == alternate_chain[0]
            return uint32(0)
        assert low + 1 == high
        if self.height_to_hash[uint32(low)] == alternate_chain[low]:
            if self.height_to_hash[uint32(high)] == alternate_chain[high]:
                return high
            else:
                return low
        elif low > 0:
            assert self.height_to_hash[uint32(low - 1)] == alternate_chain[low - 1]
            return uint32(low - 1)
        else:
            raise ValueError("Invalid genesis block")

    def get_next_difficulty(self, header_hash: bytes32) -> uint64:
        """
        Returns the difficulty of the next block that extends onto header_hash.
        Used to calculate the number of iterations. When changing this, also change the implementation
        in wallet_state_manager.py.
        """
        block: Header = self.headers[header_hash]

        next_height: uint32 = uint32(block.height + 1)
        if next_height < self.constants["DIFFICULTY_EPOCH"]:
            # We are in the first epoch
            return uint64(self.constants["DIFFICULTY_STARTING"])

        # Epochs are diffined as intervals of DIFFICULTY_EPOCH blocks, inclusive and indexed at 0.
        # For example, [0-2047], [2048-4095], etc. The difficulty changes DIFFICULTY_DELAY into the
        # epoch, as opposed to the first block (as in Bitcoin).
        elif (
            next_height % self.constants["DIFFICULTY_EPOCH"]
            != self.constants["DIFFICULTY_DELAY"]
        ):
            # Not at a point where difficulty would change
            prev_block: Header = self.headers[block.prev_header_hash]
            assert prev_block is not None
            if prev_block is None:
                raise Exception("Previous block is invalid.")
            return uint64(block.weight - prev_block.weight)

        #       old diff                  curr diff       new diff
        # ----------|-----|----------------------|-----|-----...
        #           h1    h2                     h3   i-1
        # Height1 is the last block 2 epochs ago, so we can include the time to mine 1st block in previous epoch
        height1 = uint32(
            next_height
            - self.constants["DIFFICULTY_EPOCH"]
            - self.constants["DIFFICULTY_DELAY"]
            - 1
        )
        # Height2 is the DIFFICULTY DELAYth block in the previous epoch
        height2 = uint32(next_height - self.constants["DIFFICULTY_EPOCH"] - 1)
        # Height3 is the last block in the previous epoch
        height3 = uint32(next_height - self.constants["DIFFICULTY_DELAY"] - 1)

        # h1 to h2 timestamps are mined on previous difficulty, while  and h2 to h3 timestamps are mined on the
        # current difficulty

        block1, block2, block3 = None, None, None
        if block not in self.get_current_tips() or height3 not in self.height_to_hash:
            # This means we are either on a fork, or on one of the chains, but after the LCA,
            # so we manually backtrack.
            curr: Optional[Header] = block
            assert curr is not None
            while (
                curr.height not in self.height_to_hash
                or self.height_to_hash[curr.height] != curr.header_hash
            ):
                if curr.height == height1:
                    block1 = curr
                elif curr.height == height2:
                    block2 = curr
                elif curr.height == height3:
                    block3 = curr
                curr = self.headers.get(curr.prev_header_hash, None)
                assert curr is not None
        # Once we are before the fork point (and before the LCA), we can use the height_to_hash map
        if not block1 and height1 >= 0:
            # height1 could be -1, for the first difficulty calculation
            block1 = self.headers[self.height_to_hash[height1]]
        if not block2:
            block2 = self.headers[self.height_to_hash[height2]]
        if not block3:
            block3 = self.headers[self.height_to_hash[height3]]
        assert block2 is not None and block3 is not None

        # Current difficulty parameter (diff of block h = i - 1)
        Tc = self.get_next_difficulty(block.prev_header_hash)

        # Previous difficulty parameter (diff of block h = i - 2048 - 1)
        Tp = self.get_next_difficulty(block2.prev_header_hash)
        if block1:
            timestamp1 = block1.data.timestamp  # i - 512 - 1
        else:
            # In the case of height == -1, there is no timestamp here, so assume the genesis block
            # took constants["BLOCK_TIME_TARGET"] seconds to mine.
            genesis = self.headers[self.height_to_hash[uint32(0)]]
            timestamp1 = genesis.data.timestamp - self.constants["BLOCK_TIME_TARGET"]
        timestamp2 = block2.data.timestamp  # i - 2048 + 512 - 1
        timestamp3 = block3.data.timestamp  # i - 512 - 1

        # Numerator fits in 128 bits, so big int is not necessary
        # We multiply by the denominators here, so we only have one fraction in the end (avoiding floating point)
        term1 = (
            self.constants["DIFFICULTY_DELAY"]
            * Tp
            * (timestamp3 - timestamp2)
            * self.constants["BLOCK_TIME_TARGET"]
        )
        term2 = (
            (self.constants["DIFFICULTY_WARP_FACTOR"] - 1)
            * (self.constants["DIFFICULTY_EPOCH"] - self.constants["DIFFICULTY_DELAY"])
            * Tc
            * (timestamp2 - timestamp1)
            * self.constants["BLOCK_TIME_TARGET"]
        )

        # Round down after the division
        new_difficulty_precise: uint64 = uint64(
            (term1 + term2)
            // (
                self.constants["DIFFICULTY_WARP_FACTOR"]
                * (timestamp3 - timestamp2)
                * (timestamp2 - timestamp1)
            )
        )
        # Take only DIFFICULTY_SIGNIFICANT_BITS significant bits
        new_difficulty = uint64(
            truncate_to_significant_bits(
                new_difficulty_precise, self.constants["SIGNIFICANT_BITS"]
            )
        )
        assert (
            count_significant_bits(new_difficulty) <= self.constants["SIGNIFICANT_BITS"]
        )

        # Only change by a max factor, to prevent attacks, as in greenpaper, and must be at least 1
        max_diff = uint64(
            truncate_to_significant_bits(
                self.constants["DIFFICULTY_FACTOR"] * Tc,
                self.constants["SIGNIFICANT_BITS"],
            )
        )
        min_diff = uint64(
            truncate_to_significant_bits(
                Tc // self.constants["DIFFICULTY_FACTOR"],
                self.constants["SIGNIFICANT_BITS"],
            )
        )
        if new_difficulty >= Tc:
            return min(new_difficulty, max_diff)
        else:
            return max([uint64(1), new_difficulty, min_diff])

    def get_next_min_iters(self, block: FullBlock) -> uint64:
        """
        Returns the VDF speed in iterations per seconds, to be used for the next block. This depends on
        the number of iterations of the last epoch, and changes at the same block as the difficulty.
        """
        next_height: uint32 = uint32(block.height + 1)
        if next_height < self.constants["DIFFICULTY_EPOCH"]:
            # First epoch has a hardcoded vdf speed
            return self.constants["MIN_ITERS_STARTING"]

        prev_block_header: Header = self.headers[block.prev_header_hash]

        proof_of_space = block.proof_of_space
        difficulty = self.get_next_difficulty(prev_block_header.header_hash)
        iterations = uint64(
            block.header.data.total_iters - prev_block_header.data.total_iters
        )
        prev_min_iters = calculate_min_iters_from_iterations(
            proof_of_space, difficulty, iterations
        )

        if (
            next_height % self.constants["DIFFICULTY_EPOCH"]
            != self.constants["DIFFICULTY_DELAY"]
        ):
            # Not at a point where ips would change, so return the previous ips
            # TODO: cache this for efficiency
            return prev_min_iters

        # min iters (along with difficulty) will change in this block, so we need to calculate the new one.
        # The calculation is (iters_2 - iters_1) // epoch size
        # 1 and 2 correspond to height_1 and height_2, being the last block of the second to last, and last
        # block of the last epochs. Basically, it's total iterations per block on average.

        # Height1 is the last block 2 epochs ago, so we can include the iterations taken for mining first block in epoch
        height1 = uint32(
            next_height
            - self.constants["DIFFICULTY_EPOCH"]
            - self.constants["DIFFICULTY_DELAY"]
            - 1
        )
        # Height2 is the last block in the previous epoch
        height2 = uint32(next_height - self.constants["DIFFICULTY_DELAY"] - 1)

        block1: Optional[Header] = None
        block2: Optional[Header] = None
        if block not in self.get_current_tips() or height2 not in self.height_to_hash:
            # This means we are either on a fork, or on one of the chains, but after the LCA,
            # so we manually backtrack.
            curr: Optional[Header] = block.header
            assert curr is not None
            while (
                curr.height not in self.height_to_hash
                or self.height_to_hash[curr.height] != curr.header_hash
            ):
                if curr.height == height1:
                    block1 = curr
                elif curr.height == height2:
                    block2 = curr
                curr = self.headers.get(curr.prev_header_hash, None)
                assert curr is not None
        # Once we are before the fork point (and before the LCA), we can use the height_to_hash map
        if block1 is None and height1 >= 0:
            # height1 could be -1, for the first difficulty calculation
            block1 = self.headers.get(self.height_to_hash[height1], None)
        if block2 is None:
            block2 = self.headers.get(self.height_to_hash[height2], None)
        assert block2 is not None

        if block1 is not None:
            iters1 = block1.data.total_iters
        else:
            # In the case of height == -1, iters = 0
            iters1 = uint64(0)

        iters2 = block2.data.total_iters

        min_iters_precise = uint64(
            (iters2 - iters1)
            // (
                self.constants["DIFFICULTY_EPOCH"]
                * self.constants["MIN_ITERS_PROPORTION"]
            )
        )
        min_iters = uint64(
            truncate_to_significant_bits(
                min_iters_precise, self.constants["SIGNIFICANT_BITS"]
            )
        )
        assert count_significant_bits(min_iters) <= self.constants["SIGNIFICANT_BITS"]
        return min_iters

    async def receive_block(
        self,
        block: FullBlock,
        pre_validated: bool = False,
        pos_quality_string: bytes32 = None,
    ) -> Tuple[ReceiveBlockResult, Optional[Header], Optional[Err]]:
        """
        Adds a new block into the blockchain, if it's valid and connected to the current
        blockchain, regardless of whether it is the child of a head, or another block.
        Returns a header if block is added to head. Returns an error if the block is
        invalid.
        """
        genesis: bool = block.height == 0 and not self.tips

        if block.header_hash in self.headers:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None, None

        if block.prev_header_hash not in self.headers and not genesis:
            return ReceiveBlockResult.DISCONNECTED_BLOCK, None, None

        error_code: Optional[Err] = await self.validate_block(
            block, genesis, pre_validated, pos_quality_string
        )

        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, None, error_code

        # Cache header in memory
        self.headers[block.header_hash] = block.header

        # Always immediately add the block to the database, after updating blockchain state
        await self.store.add_block(block)
        res, header = await self._reconsider_heads(block.header, genesis)
        if res:
            return ReceiveBlockResult.ADDED_TO_HEAD, header, None
        else:
            return ReceiveBlockResult.ADDED_AS_ORPHAN, None, None

    async def validate_unfinished_block(
        self,
        block: FullBlock,
        prev_full_block: Optional[FullBlock],
        pre_validated: bool = True,
        pos_quality_string: bytes32 = None,
    ) -> Tuple[Optional[Err], Optional[uint64]]:
        """
        Block validation algorithm. Returns the number of VDF iterations that this block's
        proof of time must have, if the candidate block is fully valid (except for proof of
        time). The same as validate_block, but without proof of time and challenge validation.
        If the block is invalid, an error code is returned.
        """
        if not pre_validated:
            # 1. The hash of the proof of space must match header_data.proof_of_space_hash
            if block.proof_of_space.get_hash() != block.header.data.proof_of_space_hash:
                return (Err.INVALID_POSPACE_HASH, None)

            # 2. The coinbase signature must be valid, according the the pool public key
            pair = block.header.data.coinbase_signature.PkMessagePair(
                block.proof_of_space.pool_pubkey, block.header.data.coinbase.name(),
            )

            if not block.header.data.coinbase_signature.validate([pair]):
                return (Err.INVALID_COINBASE_SIGNATURE, None)

            # 3. Check harvester signature of header data is valid based on harvester key
            if not block.header.harvester_signature.verify(
                [blspy.Util.hash256(block.header.data.get_hash())],
                [block.proof_of_space.plot_pubkey],
            ):
                return (Err.INVALID_HARVESTER_SIGNATURE, None)

        # 4. If not genesis, the previous block must exist
        if prev_full_block is not None and block.prev_header_hash not in self.headers:
            return (Err.DOES_NOT_EXTEND, None)

        # 5. If not genesis, the timestamp must be >= the average timestamp of last 11 blocks
        # and less than 2 hours in the future (if block height < 11, average all previous blocks).
        # Average is the sum, int diveded by the number of timestamps
        if prev_full_block is not None:
            last_timestamps: List[uint64] = []
            curr = prev_full_block.header
            while len(last_timestamps) < self.constants["NUMBER_OF_TIMESTAMPS"]:
                last_timestamps.append(curr.data.timestamp)
                fetched = self.headers.get(curr.prev_header_hash, None)
                if not fetched:
                    break
                curr = fetched
            if len(last_timestamps) != self.constants["NUMBER_OF_TIMESTAMPS"]:
                # For blocks 1 to 10, average timestamps of all previous blocks
                assert curr.height == 0
            prev_time: uint64 = uint64(
                int(sum(last_timestamps) // len(last_timestamps))
            )
            if block.header.data.timestamp < prev_time:
                return (Err.TIMESTAMP_TOO_FAR_IN_PAST, None)
            if (
                block.header.data.timestamp
                > time.time() + self.constants["MAX_FUTURE_TIME"]
            ):
                return (Err.TIMESTAMP_TOO_FAR_IN_FUTURE, None)

        # 6. The compact block filter must be correct, according to the body (BIP158)
        if block.header.data.filter_hash != bytes32([0] * 32):
            if block.transactions_filter is None:
                return (Err.INVALID_TRANSACTIONS_FILTER_HASH, None)
            if std_hash(block.transactions_filter) != block.header.data.filter_hash:
                return (Err.INVALID_TRANSACTIONS_FILTER_HASH, None)
        elif block.transactions_filter is not None:
            return (Err.INVALID_TRANSACTIONS_FILTER_HASH, None)

        # 7. Extension data must be valid, if any is present

        # Compute challenge of parent
        challenge_hash: bytes32
        if prev_full_block is not None:
            challenge: Optional[Challenge] = self.get_challenge(prev_full_block)
            assert challenge is not None
            challenge_hash = challenge.get_hash()
            # 8. Check challenge hash of prev is the same as in pos
            if challenge_hash != block.proof_of_space.challenge_hash:
                return (Err.INVALID_POSPACE_CHALLENGE, None)
        else:
            # 9. If genesis, the challenge hash in the proof of time must be the same as in the proof of space
            assert block.proof_of_time is not None
            challenge_hash = block.proof_of_time.challenge_hash

            if challenge_hash != block.proof_of_space.challenge_hash:
                return (Err.INVALID_POSPACE_CHALLENGE, None)

        # 10. The proof of space must be valid on the challenge
        if pos_quality_string is None:
            pos_quality_string = block.proof_of_space.verify_and_get_quality_string()
            if not pos_quality_string:
                return (Err.INVALID_POSPACE, None)

        if prev_full_block is not None:
            # 11. If not genesis, the height on the previous block must be one less than on this block
            if block.height != prev_full_block.height + 1:
                return (Err.INVALID_HEIGHT, None)
        else:
            # 12. If genesis, the height must be 0
            if block.height != 0:
                return (Err.INVALID_HEIGHT, None)

        # 13. The coinbase reward must match the block schedule
        coinbase_reward = calculate_block_reward(block.height)
        if coinbase_reward != block.header.data.coinbase.amount:
            return (Err.INVALID_COINBASE_AMOUNT, None)

        # 13b. The coinbase parent id must be the height
        if block.header.data.coinbase.parent_coin_info != block.height.to_bytes(
            32, "big"
        ):
            return (Err.INVALID_COINBASE_PARENT, None)

        # 13c. The fees coin parent id must be hash(hash(height))
        fee_base = calculate_base_fee(block.height)
        if block.header.data.fees_coin.parent_coin_info != std_hash(
            std_hash(uint32(block.height))
        ):
            return (Err.INVALID_FEES_COIN_PARENT, None)

        # target reward_fee = 1/8 coinbase reward + tx fees
        if block.transactions_generator is not None:
            # 14. Make sure transactions generator hash is valid (or all 0 if not present)
            if (
                std_hash(block.transactions_generator)
                != block.header.data.generator_hash
            ):
                return (Err.INVALID_TRANSACTIONS_GENERATOR_HASH, None)

            # 15. If not genesis, the transactions must be valid and fee must be valid
            # Verifies that fee_base + TX fees = fee_coin.amount
            err = await self._validate_transactions(block, fee_base)
            if err is not None:
                return (err, None)
        else:
            # Make sure transactions generator hash is valid (or all 0 if not present)
            if block.header.data.generator_hash != bytes32(bytes([0] * 32)):
                return (Err.INVALID_TRANSACTIONS_GENERATOR_HASH, None)

            # 16. If genesis, the fee must be the base fee, agg_sig must be None, and merkle roots must be valid
            if fee_base != block.header.data.fees_coin.amount:
                return (Err.INVALID_BLOCK_FEE_AMOUNT, None)
            root_error = self._validate_merkle_root(block)
            if root_error:
                return (root_error, None)
            if block.header.data.aggregated_signature is not None:
                return (Err.BAD_AGGREGATE_SIGNATURE, None)

        difficulty: uint64
        if prev_full_block is not None:
            difficulty = self.get_next_difficulty(prev_full_block.header_hash)
            min_iters = self.get_next_min_iters(prev_full_block)
        else:
            difficulty = uint64(self.constants["DIFFICULTY_STARTING"])
            min_iters = uint64(self.constants["MIN_ITERS_STARTING"])

        number_of_iters: uint64 = calculate_iterations_quality(
            pos_quality_string, block.proof_of_space.size, difficulty, min_iters,
        )

        assert count_significant_bits(difficulty) <= self.constants["SIGNIFICANT_BITS"]
        assert count_significant_bits(min_iters) <= self.constants["SIGNIFICANT_BITS"]

        if prev_full_block is not None:
            # 17. If not genesis, the total weight must be the parent weight + difficulty
            if block.weight != prev_full_block.weight + difficulty:
                return (Err.INVALID_WEIGHT, None)

            # 18. If not genesis, the total iters must be parent iters + number_iters
            if (
                block.header.data.total_iters
                != prev_full_block.header.data.total_iters + number_of_iters
            ):
                return (Err.INVALID_TOTAL_ITERS, None)
        else:
            # 19. If genesis, the total weight must be starting difficulty
            if block.weight != difficulty:
                return (Err.INVALID_WEIGHT, None)

            # 20. If genesis, the total iters must be number iters
            if block.header.data.total_iters != number_of_iters:
                return (Err.INVALID_TOTAL_ITERS, None)

        return (None, number_of_iters)

    async def validate_block(
        self,
        block: FullBlock,
        genesis: bool = False,
        pre_validated: bool = False,
        pos_quality_string: bytes32 = None,
    ) -> Optional[Err]:
        """
        Block validation algorithm. Returns true iff the candidate block is fully valid,
        and extends something in the blockchain.
        """
        prev_full_block: Optional[FullBlock]
        if not genesis:
            prev_full_block = await self.store.get_block(block.prev_header_hash)
            if prev_full_block is None:
                return Err.DOES_NOT_EXTEND
        else:
            prev_full_block = None

        # 0. Validate unfinished block (check the rest of the conditions)
        err, number_of_iters = await self.validate_unfinished_block(
            block, prev_full_block, pre_validated, pos_quality_string
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
            if not block.proof_of_time.is_valid(
                self.constants["DISCRIMINANT_SIZE_BITS"]
            ):
                return Err.INVALID_POT
        # 3. If not genesis, the challenge_hash in the proof of time must match the challenge on the previous block
        if not genesis:
            assert prev_full_block is not None
            prev_challenge: Optional[Challenge] = self.get_challenge(prev_full_block)
            assert prev_challenge is not None

            if block.proof_of_time.challenge_hash != prev_challenge.get_hash():
                return Err.INVALID_POT_CHALLENGE
        return None

    async def pre_validate_blocks(
        self, blocks: List[FullBlock]
    ) -> List[Tuple[bool, Optional[bytes32]]]:

        results = []
        for block in blocks:
            val, pos = self.pre_validate_block_multi(bytes(block))
            if pos is not None:
                pos = bytes32(pos)
            results.append((val, pos))

        return results

    async def pre_validate_blocks_multiprocessing(
        self, blocks: List[FullBlock]
    ) -> List[Tuple[bool, Optional[bytes32]]]:
        futures = []

        cpu_count = multiprocessing.cpu_count()
        # Pool of workers to validate blocks concurrently
        pool = concurrent.futures.ProcessPoolExecutor(max_workers=max(cpu_count - 1, 1))

        for block in blocks:
            futures.append(
                asyncio.get_running_loop().run_in_executor(
                    pool, self.pre_validate_block_multi, bytes(block)
                )
            )
        results = await asyncio.gather(*futures)

        for i, (val, pos) in enumerate(results):
            if pos is not None:
                pos = bytes32(pos)
            results[i] = val, pos
        pool.shutdown(wait=True)
        return results

    def pre_validate_block_multi(self, data) -> Tuple[bool, Optional[bytes]]:
        """
            Validates all parts of FullBlock that don't need to be serially checked
        """
        block = FullBlock.from_bytes(data)

        if not block.proof_of_time:
            return False, None

        # 4. Check PoT
        if not block.proof_of_time.is_valid(self.constants["DISCRIMINANT_SIZE_BITS"]):
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

    async def _reconsider_heads(
        self, block: Header, genesis: bool
    ) -> Tuple[bool, Optional[Header]]:
        """
        When a new block is added, this is called, to check if the new block is heavier
        than one of the heads.
        """
        removed: Optional[Header] = None
        if len(self.tips) == 0 or block.weight > min([b.weight for b in self.tips]):
            self.tips.append(block)
            while len(self.tips) > self.constants["NUMBER_OF_HEADS"]:
                self.tips.sort(key=lambda b: b.weight, reverse=True)
                # This will loop only once
                removed = self.tips.pop()
            await self._reconsider_lca(genesis)
            return True, removed
        return False, None

    async def _reconsider_lca(self, genesis: bool):
        """
        Update the least common ancestor of the heads. This is useful, since we can just assume
        there is one block per height before the LCA (and use the height_to_hash dict).
        """
        cur: List[Header] = self.tips[:]
        old_lca: Optional[Header]
        try:
            old_lca = self.lca_block
        except AttributeError:
            old_lca = None
        while any(b.header_hash != cur[0].header_hash for b in cur):
            heights = [b.height for b in cur]
            i = heights.index(max(heights))
            cur[i] = self.headers[cur[i].prev_header_hash]
        if genesis:
            self._reconsider_heights(None, cur[0])
        else:
            self._reconsider_heights(self.lca_block, cur[0])
        self.lca_block = cur[0]

        if old_lca is None:
            full: Optional[FullBlock] = await self.store.get_block(
                self.lca_block.header_hash
            )
            assert full is not None
            await self.unspent_store.new_lca(full)
            await self._create_diffs_for_tips(self.lca_block)
        # If LCA changed update the unspent store
        elif old_lca.header_hash != self.lca_block.header_hash:
            # New LCA is lower height but not the a parent of old LCA (Reorg)
            fork_h = self._find_fork_point_in_chain(old_lca, self.lca_block)
            # Rollback to fork
            await self.unspent_store.rollback_lca_to_block(fork_h)

            # Add blocks between fork point and new lca
            fork_hash = self.height_to_hash[fork_h]
            fork_head = self.headers[fork_hash]
            await self._from_fork_to_lca(fork_head, self.lca_block)
            if not self.store.get_sync_mode():
                await self.recreate_diff_stores()
        else:
            # If LCA has not changed just update the difference
            self.unspent_store.nuke_diffs()
            # Create DiffStore
            await self._create_diffs_for_tips(self.lca_block)

    async def recreate_diff_stores(self):
        # Nuke DiffStore
        self.unspent_store.nuke_diffs()
        # Create DiffStore
        await self._create_diffs_for_tips(self.lca_block)

    def _reconsider_heights(self, old_lca: Optional[Header], new_lca: Header):
        """
        Update the mapping from height to block hash, when the lca changes.
        """
        curr_old: Optional[Header] = old_lca if old_lca else None
        curr_new: Header = new_lca
        while True:
            fetched: Optional[Header]
            if not curr_old or curr_old.height < curr_new.height:
                self.height_to_hash[uint32(curr_new.height)] = curr_new.header_hash
                self.headers[curr_new.header_hash] = curr_new
                if curr_new.height == 0:
                    return
                curr_new = self.headers[curr_new.prev_header_hash]
            elif curr_old.height > curr_new.height:
                del self.height_to_hash[uint32(curr_old.height)]
                curr_old = self.headers[curr_old.prev_header_hash]
            else:
                if curr_new.header_hash == curr_old.header_hash:
                    return
                self.height_to_hash[uint32(curr_new.height)] = curr_new.header_hash
                curr_new = self.headers[curr_new.prev_header_hash]
                curr_old = self.headers[curr_old.prev_header_hash]

    def _find_fork_point_in_chain(self, block_1: Header, block_2: Header) -> uint32:
        """ Tries to find height where new chain (block_2) diverged from block_1 (assuming prev blocks
        are all included in chain)"""
        while block_2.height > 0 or block_1.height > 0:
            if block_2.height > block_1.height:
                block_2 = self.headers[block_2.prev_header_hash]
            elif block_1.height > block_2.height:
                block_1 = self.headers[block_1.prev_header_hash]
            else:
                if block_2.header_hash == block_1.header_hash:
                    return block_2.height
                block_2 = self.headers[block_2.prev_header_hash]
                block_1 = self.headers[block_1.prev_header_hash]
        assert block_2 == block_1  # Genesis block is the same, genesis fork
        return uint32(0)

    async def _create_diffs_for_tips(self, target: Header):
        """ Adds to unspent store from tips down to target"""
        for tip in self.tips:
            await self._from_tip_to_lca_unspent(tip, target)

    async def _from_tip_to_lca_unspent(self, head: Header, target: Header):
        """ Adds diffs to unspent store, from tip to lca target"""
        blocks: List[FullBlock] = []
        tip_hash: bytes32 = head.header_hash
        while True:
            if tip_hash == target.header_hash:
                break
            full = await self.store.get_block(tip_hash)
            if full is None:
                return
            blocks.append(full)
            tip_hash = full.prev_header_hash
        if len(blocks) == 0:
            return
        blocks.reverse()
        await self.unspent_store.new_heads(blocks)

    async def _from_fork_to_lca(self, fork_point: Header, lca: Header):
        """ Selects blocks between fork_point and LCA, and then adds them to unspent_store. """
        blocks: List[FullBlock] = []
        tip_hash: bytes32 = lca.header_hash
        while True:
            if tip_hash == fork_point.header_hash:
                break
            full = await self.store.get_block(tip_hash)
            if not full:
                return
            blocks.append(full)
            tip_hash = full.prev_header_hash
        blocks.reverse()

        await self.unspent_store.add_lcas(blocks)

    def _validate_merkle_root(
        self,
        block: FullBlock,
        tx_additions: List[Coin] = None,
        tx_removals: List[bytes32] = None,
    ) -> Optional[Err]:
        additions = []
        removals = []
        if tx_additions:
            additions.extend(tx_additions)
        if tx_removals:
            removals.extend(tx_removals)

        removal_merkle_set = MerkleSet()
        addition_merkle_set = MerkleSet()

        # Create removal Merkle set
        for coin_name in removals:
            removal_merkle_set.add_already_hashed(coin_name)

        # Create addition Merkle set
        puzzlehash_coins_map: Dict[bytes32, List[Coin]] = {}
        for coin in additions:
            if coin.puzzle_hash in puzzlehash_coins_map:
                puzzlehash_coins_map[coin.puzzle_hash].append(coin)
            else:
                puzzlehash_coins_map[coin.puzzle_hash] = [coin]

        # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
        for puzzle, coins in puzzlehash_coins_map.items():
            addition_merkle_set.add_already_hashed(puzzle)
            addition_merkle_set.add_already_hashed(hash_coin_list(coins))

        additions_root = addition_merkle_set.get_root()
        removals_root = removal_merkle_set.get_root()

        if block.header.data.additions_root != additions_root:
            return Err.BAD_ADDITION_ROOT
        if block.header.data.removals_root != removals_root:
            return Err.BAD_REMOVAL_ROOT

        return None

    async def _validate_transactions(
        self, block: FullBlock, fee_base: uint64
    ) -> Optional[Err]:
        # TODO(straya): review, further test the code, and number all the validation steps

        # 1. Check that transactions generator is present
        if not block.transactions_generator:
            return Err.UNKNOWN
        # Get List of names removed, puzzles hashes for removed coins and conditions crated
        error, npc_list, cost = calculate_cost_of_program(block.transactions_generator)

        # 2. Check that cost <= MAX_BLOCK_COST_CLVM
        if cost > self.constants["MAX_BLOCK_COST_CLVM"]:
            return Err.BLOCK_COST_EXCEEDS_MAX
        if error:
            return error

        prev_header: Header
        if block.prev_header_hash in self.headers:
            prev_header = self.headers[block.prev_header_hash]
        else:
            return Err.EXTENDS_UNKNOWN_BLOCK

        removals: List[bytes32] = []
        removals_puzzle_dic: Dict[bytes32, bytes32] = {}
        for npc in npc_list:
            removals.append(npc.coin_name)
            removals_puzzle_dic[npc.coin_name] = npc.puzzle_hash

        additions: List[Coin] = additions_for_npc(npc_list)
        additions_dic: Dict[bytes32, Coin] = {}
        # Check additions for max coin amount
        for coin in additions:
            additions_dic[coin.name()] = coin
            if coin.amount >= uint64.from_bytes(self.constants["MAX_COIN_AMOUNT"]):
                return Err.COIN_AMOUNT_EXCEEDS_MAXIMUM

        # Validate addition and removal roots
        root_error = self._validate_merkle_root(block, additions, removals)
        if root_error:
            return root_error

        # TODO(straya): validate filter

        # Watch out for duplicate outputs
        addition_counter = collections.Counter(_.name() for _ in additions)
        for k, v in addition_counter.items():
            if v > 1:
                return Err.DUPLICATE_OUTPUT

        # Check for duplicate spends inside block
        removal_counter = collections.Counter(removals)
        for k, v in removal_counter.items():
            if v > 1:
                log.error(f"DOUBLE SPEND! 1 {k}")
                return Err.DOUBLE_SPEND

        # Check if removals exist and were not previously spend. (unspent_db + diff_store + this_block)
        fork_h = self._find_fork_point_in_chain(self.lca_block, block.header)

        # Get additions and removals since (after) fork_h but not including this block
        additions_since_fork: Dict[bytes32, Tuple[Coin, uint32]] = {}
        removals_since_fork: Set[bytes32] = set()
        coinbases_since_fork: Dict[bytes32, uint32] = {}
        curr: Optional[FullBlock] = await self.store.get_block(block.prev_header_hash)
        assert curr is not None
        log.info(f"curr.height is: {curr.height}, fork height is: {fork_h}")
        while curr.height > fork_h:
            removals_in_curr, additions_in_curr = await curr.tx_removals_and_additions()
            for c_name in removals_in_curr:
                removals_since_fork.add(c_name)
            for c in additions_in_curr:
                additions_since_fork[c.name()] = (c, curr.height)
            additions_since_fork[curr.header.data.coinbase.name()] = (
                curr.header.data.coinbase,
                curr.height,
            )
            additions_since_fork[curr.header.data.fees_coin.name()] = (
                curr.header.data.fees_coin,
                curr.height,
            )
            coinbases_since_fork[curr.header.data.coinbase.name()] = curr.height
            coinbases_since_fork[curr.header.data.fees_coin.name()] = curr.height
            curr = await self.store.get_block(curr.prev_header_hash)
            assert curr is not None

        removal_coin_records: Dict[bytes32, CoinRecord] = {}
        for rem in removals:
            if rem in additions_dic:
                # Ephemeral coin
                rem_coin: Coin = additions_dic[rem]
                new_unspent: CoinRecord = CoinRecord(rem_coin, block.height, 0, 0, 0)  # type: ignore # noqa
                removal_coin_records[new_unspent.name] = new_unspent
            else:
                assert prev_header is not None
                unspent = await self.unspent_store.get_coin_record(rem, prev_header)
                if unspent is not None and unspent.confirmed_block_index <= fork_h:
                    # Spending something in the current chain, confirmed before fork
                    # (We ignore all coins confirmed after fork)
                    if unspent.spent == 1 and unspent.spent_block_index <= fork_h:
                        # Spend in an ancestor block, so this is a double spend
                        log.error(f"DOUBLE SPEND! 2 {unspent}")
                        return Err.DOUBLE_SPEND
                    # If it's a coinbase, check that it's not frozen
                    if unspent.coinbase == 1:
                        if (
                            block.height
                            < unspent.confirmed_block_index + self.coinbase_freeze
                        ):
                            return Err.COINBASE_NOT_YET_SPENDABLE
                    removal_coin_records[unspent.name] = unspent
                else:
                    # This coin is not in the current heaviest chain, so it must be in the fork
                    if rem not in additions_since_fork:
                        # This coin does not exist in the fork
                        return Err.UNKNOWN_UNSPENT
                    if rem in coinbases_since_fork:
                        # This coin is a coinbase coin
                        if (
                            block.height
                            < coinbases_since_fork[rem] + self.coinbase_freeze
                        ):
                            return Err.COINBASE_NOT_YET_SPENDABLE
                    new_coin, confirmed_height = additions_since_fork[rem]
                    new_coin_record: CoinRecord = CoinRecord(
                        new_coin,
                        confirmed_height,
                        uint32(0),
                        False,
                        (rem in coinbases_since_fork),
                    )
                    removal_coin_records[new_coin_record.name] = new_coin_record

                # This check applies to both coins created before fork (pulled from coin_store),
                # and coins created after fork (additions_since_fork)>
                if rem in removals_since_fork:
                    # This coin was spent in the fork
                    log.error(f"DOUBLE SPEND! 3 {rem}")
                    log.error(f"removals_since_fork: {removals_since_fork}")
                    return Err.DOUBLE_SPEND

        # Check fees
        removed = 0
        for unspent in removal_coin_records.values():
            removed += unspent.coin.amount

        added = 0
        for coin in additions:
            added += coin.amount

        if removed < added:
            return Err.MINTING_COIN

        fees = removed - added

        # Check coinbase reward
        if fees + fee_base != block.header.data.fees_coin.amount:
            return Err.BAD_COINBASE_REWARD

        # Verify that removed coin puzzle_hashes match with calculated puzzle_hashes
        for unspent in removal_coin_records.values():
            if unspent.coin.puzzle_hash != removals_puzzle_dic[unspent.name]:
                return Err.WRONG_PUZZLE_HASH

        # Verify conditions, create hash_key list for aggsig check
        hash_key_pairs = []
        for npc in npc_list:
            unspent = removal_coin_records[npc.coin_name]
            error = blockchain_check_conditions_dict(
                unspent, removal_coin_records, npc.condition_dict, block.header,
            )
            if error:
                return error
            hash_key_pairs.extend(
                hash_key_pairs_for_conditions_dict(npc.condition_dict, npc.coin_name)
            )

        # Verify aggregated signature
        if not block.header.data.aggregated_signature:
            return Err.BAD_AGGREGATE_SIGNATURE
        if not block.header.data.aggregated_signature.validate(hash_key_pairs):
            return Err.BAD_AGGREGATE_SIGNATURE

        return None
