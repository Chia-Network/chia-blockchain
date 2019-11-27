import logging
import time
from enum import Enum
from typing import Dict, List, Optional, Tuple

import blspy

from src.consensus.block_rewards import calculate_block_reward
from src.consensus.constants import constants as consensus_constants
from src.consensus.pot_iterations import (
    calculate_ips_from_iterations,
    calculate_iterations_quality,
)
from src.database import FullNodeStore
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.errors import BlockNotInBlockchain, InvalidGenesisBlock
from src.util.ints import uint32, uint64

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
    def __init__(self, store: FullNodeStore, override_constants: Dict = {}):
        # Allow passing in custom overrides for any consesus parameters
        self.constants: Dict = consensus_constants
        for key, value in override_constants.items():
            self.constants[key] = value

        self.store = store
        self.tips: List[FullBlock] = []
        self.lca_block: FullBlock
        self.height_to_hash: Dict[uint32, bytes32] = {}

    async def initialize(self):
        seen_blocks = {}
        async for block in self.store.get_blocks():
            if not self.tips or block.weight > self.tips[0].weight:
                self.tips = [block]
            seen_blocks[block.header_hash] = block

        if len(self.tips) > 0:
            curr = self.tips[0]
            reverse_blocks = [curr]
            while curr.height > 0:
                curr = seen_blocks[curr.prev_header_hash]
                reverse_blocks.append(curr)

            for block in reversed(reverse_blocks):
                self.height_to_hash[block.height] = block.header_hash

            self.lca_block = self.tips[0]

        else:
            self.genesis = FullBlock.from_bytes(self.constants["GENESIS_BLOCK"])

            result = await self.receive_block(self.genesis)
            if result != ReceiveBlockResult.ADDED_TO_HEAD:
                raise InvalidGenesisBlock()
            assert self.lca_block

    def get_current_tips(self) -> List[HeaderBlock]:
        """
        Return the heads.
        """
        return [b.header_block for b in self.tips]

    def is_child_of_head(self, block: FullBlock):
        """
        True iff the block is the direct ancestor of a head.
        """
        for head in self.tips:
            if block.prev_header_hash == head.header_hash:
                return True
        return False

    async def get_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        return await self.store.get_block(header_hash)

    async def get_header_block(self, header_hash: bytes32) -> Optional[HeaderBlock]:
        bl = await self.store.get_block(header_hash)
        if bl:
            return bl.header_block
        else:
            return None

    async def get_header_blocks_by_height(
        self, heights: List[uint32], tip_header_hash: bytes32
    ) -> List[HeaderBlock]:
        """
        Returns a list of header blocks, one for each height requested.
        # TODO: optimize, check correctness for large reorgs
        """
        if len(heights) == 0:
            return []

        sorted_heights = sorted(
            [(height, index) for index, height in enumerate(heights)], reverse=True
        )

        if sorted_heights[0][0] + 100 < self.lca_block.height:
            curr_full_block: Optional[FullBlock] = await self.store.get_block(
                self.height_to_hash[sorted_heights[0][0]]
            )
        else:
            curr_full_block = await self.store.get_block(tip_header_hash)

        if not curr_full_block:
            raise BlockNotInBlockchain(
                f"Header hash {tip_header_hash} not present in chain."
            )
        curr_block = curr_full_block.header_block
        headers: List[Tuple[int, HeaderBlock]] = []
        for height, index in sorted_heights:
            if height > curr_block.height:
                raise ValueError("Height is not valid for tip {tip_header_hash}")
            while height < curr_block.height:
                fetched: Optional[FullBlock] = await self.store.get_block(
                    curr_block.header.data.prev_header_hash
                )
                assert fetched is not None
                curr_block = fetched.header_block
            headers.append((index, curr_block))
        return [b for index, b in sorted(headers)]

    def find_fork_point(self, alternate_chain: List[HeaderBlock]) -> HeaderBlock:
        """
        Takes in an alternate blockchain (headers), and compares it to self. Returns the last header
        where both blockchains are equal.
        """
        lca: HeaderBlock = self.lca_block.header_block

        if lca.height >= alternate_chain[-1].height:
            raise ValueError("Alternate chain is shorter")
        low = 0
        high = lca.height
        while low + 1 < high:
            mid = (low + high) // 2
            if (
                self.height_to_hash[uint32(mid)]
                != alternate_chain[mid].header.get_hash()
            ):
                high = mid
            else:
                low = mid
        if low == high and low == 0:
            assert (
                self.height_to_hash[uint32(0)] == alternate_chain[0].header.get_hash()
            )
            return alternate_chain[0]
        assert low + 1 == high
        if self.height_to_hash[uint32(low)] == alternate_chain[low].header.get_hash():
            if (
                self.height_to_hash[uint32(high)]
                == alternate_chain[high].header.get_hash()
            ):
                return alternate_chain[high]
            else:
                return alternate_chain[low]
        elif low > 0:
            assert (
                self.height_to_hash[uint32(low - 1)]
                == alternate_chain[low - 1].header.get_hash()
            )
            return alternate_chain[low - 1]
        else:
            raise ValueError("Invalid genesis block")

    async def get_next_difficulty(self, header_hash: bytes32) -> uint64:
        """
        Returns the difficulty of the next block that extends onto header_hash.
        Used to calculate the number of iterations.
        """
        block = await self.store.get_block(header_hash)
        if block is None:
            raise Exception("Given header_hash must reference block already added")

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
            prev_block = await self.store.get_block(block.prev_header_hash)
            assert block.header_block.challenge is not None
            assert (
                prev_block is not None and prev_block.header_block.challenge is not None
            )
            if prev_block is None:
                raise Exception("Previous block is invalid.")
            return uint64(
                block.header_block.challenge.total_weight
                - prev_block.header_block.challenge.total_weight
            )

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
        if (
            block.header_block not in self.get_current_tips()
            or height3 not in self.height_to_hash
        ):
            # This means we are either on a fork, or on one of the chains, but after the LCA,
            # so we manually backtrack.
            curr: Optional[FullBlock] = block
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
                curr = await self.store.get_block(curr.prev_header_hash)
                assert curr is not None
        # Once we are before the fork point (and before the LCA), we can use the height_to_hash map
        if not block1 and height1 >= 0:
            # height1 could be -1, for the first difficulty calculation
            block1 = await self.store.get_block(self.height_to_hash[height1])
        if not block2:
            block2 = await self.store.get_block(self.height_to_hash[height2])
        if not block3:
            block3 = await self.store.get_block(self.height_to_hash[height3])
        assert block2 is not None and block3 is not None

        # Current difficulty parameter (diff of block h = i - 1)
        Tc = await self.get_next_difficulty(block.prev_header_hash)

        # Previous difficulty parameter (diff of block h = i - 2048 - 1)
        Tp = await self.get_next_difficulty(block2.prev_header_hash)
        if block1:
            timestamp1 = block1.header_block.header.data.timestamp  # i - 512 - 1
        else:
            # In the case of height == -1, there is no timestamp here, so assume the genesis block
            # took constants["BLOCK_TIME_TARGET"] seconds to mine.
            genesis = await self.store.get_block(self.height_to_hash[uint32(0)])
            assert genesis is not None
            timestamp1 = (
                genesis.header_block.header.data.timestamp
                - self.constants["BLOCK_TIME_TARGET"]
            )
        timestamp2 = block2.header_block.header.data.timestamp  # i - 2048 + 512 - 1
        timestamp3 = block3.header_block.header.data.timestamp  # i - 512 - 1

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
        new_difficulty: uint64 = uint64(
            (term1 + term2)
            // (
                self.constants["DIFFICULTY_WARP_FACTOR"]
                * (timestamp3 - timestamp2)
                * (timestamp2 - timestamp1)
            )
        )

        # Only change by a max factor, to prevent attacks, as in greenpaper, and must be at least 1
        if new_difficulty >= Tc:
            return min(new_difficulty, uint64(self.constants["DIFFICULTY_FACTOR"] * Tc))
        else:
            return max(
                [
                    uint64(1),
                    new_difficulty,
                    uint64(Tc // self.constants["DIFFICULTY_FACTOR"]),
                ]
            )

    async def get_next_ips(self, header_hash) -> uint64:
        """
        Returns the VDF speed in iterations per seconds, to be used for the next block. This depends on
        the number of iterations of the last epoch, and changes at the same block as the difficulty.
        """
        block = await self.store.get_block(header_hash)
        if block is None or block.header_block.challenge is None:
            raise Exception("Given header_hash must reference block already added")

        next_height: uint32 = uint32(block.height + 1)
        if next_height < self.constants["DIFFICULTY_EPOCH"]:
            # First epoch has a hardcoded vdf speed
            return self.constants["VDF_IPS_STARTING"]

        prev_block = await self.store.get_block(block.prev_header_hash)
        if prev_block is None or prev_block.header_block.challenge is None:
            raise Exception("Previous block is invalid.")
        proof_of_space = block.header_block.proof_of_space
        difficulty = await self.get_next_difficulty(prev_block.header_hash)
        iterations = uint64(
            block.header_block.challenge.total_iters
            - prev_block.header_block.challenge.total_iters
        )
        prev_ips = calculate_ips_from_iterations(
            proof_of_space, difficulty, iterations, self.constants["MIN_BLOCK_TIME"]
        )

        if (
            next_height % self.constants["DIFFICULTY_EPOCH"]
            != self.constants["DIFFICULTY_DELAY"]
        ):
            # Not at a point where ips would change, so return the previous ips
            # TODO: cache this for efficiency
            return prev_ips

        # ips (along with difficulty) will change in this block, so we need to calculate the new one.
        # The calculation is (iters_2 - iters_1) // (timestamp_2 - timestamp_1).
        # 1 and 2 correspond to height_1 and height_2, being the last block of the second to last, and last
        # block of the last epochs. Basically, it's total iterations over time, of previous epoch.

        # Height1 is the last block 2 epochs ago, so we can include the iterations taken for mining first block in epoch
        height1 = uint32(
            next_height
            - self.constants["DIFFICULTY_EPOCH"]
            - self.constants["DIFFICULTY_DELAY"]
            - 1
        )
        # Height2 is the last block in the previous epoch
        height2 = uint32(next_height - self.constants["DIFFICULTY_DELAY"] - 1)

        block1: Optional[FullBlock] = None
        block2: Optional[FullBlock] = None
        if (
            block.header_block not in self.get_current_tips()
            or height2 not in self.height_to_hash
        ):
            # This means we are either on a fork, or on one of the chains, but after the LCA,
            # so we manually backtrack.
            curr: Optional[FullBlock] = block
            assert curr is not None
            while (
                curr.height not in self.height_to_hash
                or self.height_to_hash[curr.height] != curr.header_hash
            ):
                if curr.height == height1:
                    block1 = curr
                elif curr.height == height2:
                    block2 = curr
                curr = await self.store.get_block(curr.prev_header_hash)
                assert curr is not None
        # Once we are before the fork point (and before the LCA), we can use the height_to_hash map
        if block1 is None and height1 >= 0:
            # height1 could be -1, for the first difficulty calculation
            block1 = await self.store.get_block(self.height_to_hash[height1])
        if block2 is None:
            block2 = await self.store.get_block(self.height_to_hash[height2])
        assert block2 is not None
        assert block2.header_block.challenge is not None

        if block1 is not None:
            assert block1.header_block.challenge is not None
            timestamp1 = block1.header_block.header.data.timestamp
            iters1 = block1.header_block.challenge.total_iters
        else:
            # In the case of height == -1, there is no timestamp here, so assume the genesis block
            # took constants["BLOCK_TIME_TARGET"] seconds to mine.
            genesis = await self.store.get_block(self.height_to_hash[uint32(0)])
            assert genesis is not None
            timestamp1 = (
                genesis.header_block.header.data.timestamp
                - self.constants["BLOCK_TIME_TARGET"]
            )
            assert genesis.header_block.challenge is not None
            iters1 = genesis.header_block.challenge.total_iters

        timestamp2 = block2.header_block.header.data.timestamp
        iters2 = block2.header_block.challenge.total_iters

        new_ips = uint64((iters2 - iters1) // (timestamp2 - timestamp1))

        # Only change by a max factor, and must be at least 1
        if new_ips >= prev_ips:
            return min(new_ips, uint64(self.constants["IPS_FACTOR"] * new_ips))
        else:
            return max(
                [uint64(1), new_ips, uint64(prev_ips // self.constants["IPS_FACTOR"])]
            )

    async def receive_block(self, block: FullBlock) -> ReceiveBlockResult:
        """
        Adds a new block into the blockchain, if it's valid and connected to the current
        blockchain, regardless of whether it is the child of a head, or another block.
        """
        genesis: bool = block.height == 0 and not self.tips

        if await self.store.get_block(block.header_hash) is not None:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK

        if await self.store.get_block(block.prev_header_hash) is None and not genesis:
            return ReceiveBlockResult.DISCONNECTED_BLOCK

        if not await self.validate_block(block, genesis):
            return ReceiveBlockResult.INVALID_BLOCK

        # Block is valid and connected, so it can be added to the blockchain.
        await self.store.save_block(block)
        if await self._reconsider_heads(block, genesis):
            return ReceiveBlockResult.ADDED_TO_HEAD
        else:
            return ReceiveBlockResult.ADDED_AS_ORPHAN

    async def validate_unfinished_block(
        self, block: FullBlock, genesis: bool = False
    ) -> bool:
        """
        Block validation algorithm. Returns true if the candidate block is fully valid
        (except for proof of time). The same as validate_block, but without proof of time
        and challenge validation.
        """
        # 1. Check previous pointer(s) / flyclient
        if not genesis and await self.store.get_block(block.prev_header_hash) is None:
            return False

        # 2. Check Now+2hrs > timestamp > avg timestamp of last 11 blocks
        prev_block: Optional[FullBlock] = None
        if not genesis:
            # TODO: do something about first 11 blocks
            last_timestamps: List[uint64] = []
            prev_block = await self.store.get_block(block.prev_header_hash)
            if not prev_block or not prev_block.header_block:
                return False
            curr = prev_block
            while len(last_timestamps) < self.constants["NUMBER_OF_TIMESTAMPS"]:
                last_timestamps.append(curr.header_block.header.data.timestamp)
                fetched = await self.store.get_block(curr.prev_header_hash)
                if not fetched:
                    break
                curr = fetched
            if (
                len(last_timestamps) != self.constants["NUMBER_OF_TIMESTAMPS"]
                and curr.body.coinbase.height != 0
            ):
                return False
            prev_time: uint64 = uint64(int(sum(last_timestamps) / len(last_timestamps)))
            if block.header_block.header.data.timestamp < prev_time:
                return False
            if (
                block.header_block.header.data.timestamp
                > time.time() + self.constants["MAX_FUTURE_TIME"]
            ):
                return False

        # 3. Check filter hash is correct TODO

        # 4. Check the proof of space hash is valid
        if block.header_block.proof_of_space.get_hash() != block.header_block.header.data.proof_of_space_hash:
            return False

        # 5. Check body hash
        if block.body.get_hash() != block.header_block.header.data.body_hash:
            return False

        # 6. Check extension data, if any is added

        # 7. Compute challenge of parent
        challenge_hash: bytes32
        if not genesis:
            assert prev_block
            assert prev_block.header_block.challenge
            challenge_hash = prev_block.header_block.challenge.get_hash()

            # 8. Check challenge hash of prev is the same as in pos
            if challenge_hash != block.header_block.proof_of_space.challenge_hash:
                return False
        else:
            assert block.header_block.proof_of_time
            challenge_hash = block.header_block.proof_of_time.challenge_hash

            if challenge_hash != block.header_block.proof_of_space.challenge_hash:
                return False

        # 9. Check harvester signature of header data is valid based on harvester key
        if not block.header_block.header.harvester_signature.verify(
            [blspy.Util.hash256(block.header_block.header.data.get_hash())],
            [block.header_block.proof_of_space.plot_pubkey],
        ):
            return False

        # 10. Check proof of space based on challenge
        pos_quality = block.header_block.proof_of_space.verify_and_get_quality()
        if not pos_quality:
            return False

        # 11. Check coinbase height = parent coinbase height + 1
        if not genesis:
            assert prev_block
            if block.body.coinbase.height != prev_block.body.coinbase.height + 1:
                return False
        else:
            if block.body.coinbase.height != 0:
                return False

        # 12. Check coinbase amount
        if (
            calculate_block_reward(block.body.coinbase.height)
            != block.body.coinbase.amount
        ):
            return False

        # 13. Check coinbase signature with pool pk
        if not block.body.coinbase_signature.verify(
            [blspy.Util.hash256(bytes(block.body.coinbase))],
            [block.header_block.proof_of_space.pool_pubkey],
        ):
            return False

        # TODO: 14a. check transactions
        # TODO: 14b. Aggregate transaction results into signature
        if block.body.aggregated_signature:
            # TODO: 15. check that aggregate signature is valid, based on pubkeys, and messages
            pass
        # TODO: 16. check fees
        # TODO: 17. check cost
        return True

    async def validate_block(self, block: FullBlock, genesis: bool = False) -> bool:
        """
        Block validation algorithm. Returns true iff the candidate block is fully valid,
        and extends something in the blockchain.
        """
        # 1. Validate unfinished block (check the rest of the conditions)
        if not (await self.validate_unfinished_block(block, genesis)):
            return False

        difficulty: uint64
        ips: uint64
        if not genesis:
            difficulty = await self.get_next_difficulty(block.prev_header_hash)
            ips = await self.get_next_ips(block.prev_header_hash)
        else:
            difficulty = uint64(self.constants["DIFFICULTY_STARTING"])
            ips = uint64(self.constants["VDF_IPS_STARTING"])

        # 2. Check proof of space hash
        if not block.header_block.challenge or not block.header_block.proof_of_time:
            return False
        if (
            block.header_block.proof_of_space.get_hash()
            != block.header_block.challenge.proof_of_space_hash
        ):
            return False

        # 3. Check number of iterations on PoT is correct, based on prev block and PoS
        pos_quality: bytes32 = block.header_block.proof_of_space.verify_and_get_quality()

        if pos_quality is None:
            return False

        number_of_iters: uint64 = calculate_iterations_quality(
            pos_quality,
            block.header_block.proof_of_space.size,
            difficulty,
            ips,
            self.constants["MIN_BLOCK_TIME"],
        )

        if number_of_iters != block.header_block.proof_of_time.number_of_iterations:
            return False

        # 4. Check PoT
        if not block.header_block.proof_of_time.is_valid(
            self.constants["DISCRIMINANT_SIZE_BITS"]
        ):
            return False

        if block.body.coinbase.height != block.header_block.challenge.height:
            return False

        if not genesis:
            prev_block: Optional[FullBlock] = await self.store.get_block(
                block.prev_header_hash
            )
            if not prev_block or not prev_block.header_block.challenge:
                return False

            # 5. and check if PoT.challenge_hash matches
            if (
                block.header_block.proof_of_time.challenge_hash
                != prev_block.header_block.challenge.get_hash()
            ):
                return False

            # 6a. Check challenge height = parent height + 1
            if (
                block.header_block.challenge.height
                != prev_block.header_block.challenge.height + 1
            ):
                return False

            # 7a. Check challenge total_weight = parent total_weight + difficulty
            if (
                block.header_block.challenge.total_weight
                != prev_block.header_block.challenge.total_weight + difficulty
            ):
                return False

            # 8a. Check challenge total_iters = parent total_iters + number_iters
            if (
                block.header_block.challenge.total_iters
                != prev_block.header_block.challenge.total_iters + number_of_iters
            ):
                return False
        else:
            # 6b. Check challenge height = parent height + 1
            if block.header_block.challenge.height != 0:
                return False

            # 7b. Check challenge total_weight = parent total_weight + difficulty
            if block.header_block.challenge.total_weight != difficulty:
                return False

            # 8b. Check challenge total_iters = parent total_iters + number_iters
            if block.header_block.challenge.total_iters != number_of_iters:
                return False

        return True

    async def _reconsider_heights(
        self, old_lca: Optional[FullBlock], new_lca: FullBlock
    ):
        """
        Update the mapping from height to block hash, when the lca changes.
        """
        curr_old: Optional[HeaderBlock] = old_lca.header_block if old_lca else None
        curr_new: HeaderBlock = new_lca.header_block
        while True:
            fetched: Optional[FullBlock]
            if not curr_old or curr_old.height < curr_new.height:
                self.height_to_hash[uint32(curr_new.height)] = curr_new.header_hash
                if curr_new.height == 0:
                    return
                fetched = await self.store.get_block(curr_new.prev_header_hash)
                assert fetched is not None
                curr_new = fetched.header_block
            elif curr_old.height > curr_new.height:
                del self.height_to_hash[uint32(curr_old.height)]
                fetched = await self.store.get_block(curr_old.prev_header_hash)
                assert fetched is not None
                curr_old = fetched.header_block
            else:
                if curr_new.header_hash == curr_old.header_hash:
                    return
                self.height_to_hash[uint32(curr_new.height)] = curr_new.header_hash
                fetched_new: Optional[FullBlock] = await self.store.get_block(
                    curr_new.prev_header_hash
                )
                fetched_old: Optional[FullBlock] = await self.store.get_block(
                    curr_old.prev_header_hash
                )
                assert fetched_new is not None and fetched_old is not None
                curr_new = fetched_new.header_block
                curr_old = fetched_old.header_block

    async def _reconsider_lca(self, genesis: bool):
        """
        Update the least common ancestor of the heads. This is useful, since we can just assume
        there is one block per height before the LCA (and use the height_to_hash dict).
        """
        cur: List[FullBlock] = self.tips[:]
        while any(b.header_hash != cur[0].header_hash for b in cur):
            heights = [b.height for b in cur]
            i = heights.index(max(heights))
            fetched: Optional[FullBlock] = await self.store.get_block(
                cur[i].prev_header_hash
            )
            assert fetched is not None
            cur[i] = fetched
        if genesis:
            await self._reconsider_heights(None, cur[0])
        else:
            await self._reconsider_heights(self.lca_block, cur[0])
        self.lca_block = cur[0]

    async def _reconsider_heads(self, block: FullBlock, genesis: bool) -> bool:
        """
        When a new block is added, this is called, to check if the new block is heavier
        than one of the heads.
        """
        if len(self.tips) == 0 or block.weight > min([b.weight for b in self.tips]):
            self.tips.append(block)
            while len(self.tips) > self.constants["NUMBER_OF_HEADS"]:
                self.tips.sort(key=lambda b: b.weight, reverse=True)
                self.tips.pop()
            await self._reconsider_lca(genesis)
            return True
        return False
