from src.consensus.block_rewards import calculate_block_reward
import time
import logging
from enum import Enum
import blspy
from typing import List, Dict, Optional, Tuple
from src.util.errors import BlockNotInBlockchain
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.genesis_block import genesis_block_hardcoded
from src.types.trunk_block import TrunkBlock
from src.types.full_block import FullBlock
from src.consensus.pot_iterations import calculate_iterations, calculate_iterations_quality
from src.consensus.constants import (
    DIFFICULTY_STARTING,
    DIFFICULTY_TARGET,
    DIFFICULTY_EPOCH,
    DIFFICULTY_DELAY,
    DIFFICULTY_WARP_FACTOR,
    DIFFICULTY_FACTOR,
    NUMBER_OF_TIMESTAMPS,
    MAX_FUTURE_TIME
)

log = logging.getLogger(__name__)


class ReceiveBlockResult(Enum):
    ADDED_TO_HEAD = 1
    ADDED_AS_ORPHAN = 2
    INVALID_BLOCK = 3
    ALREADY_HAVE_BLOCK = 4
    DISCONNECTED_BLOCK = 5


class Blockchain:
    def __init__(self):
        try:
            self.genesis = self.get_genesis_block()
        except ValueError:
            raise ValueError("Failed to parse genesis block.")

        self.heads: List[FullBlock] = [self.genesis]
        self.lca_block: FullBlock = self.genesis
        self.blocks: Dict[bytes32, FullBlock] = {
            self.genesis.header_hash: self.genesis
        }
        self.height_to_hash: Dict[uint64, bytes32] = {
            uint64(0): self.genesis.header_hash
        }
        # For blocks with height % DIFFICULTY_DELAY == 1, a link to the hash of
        # the (DIFFICULTY_DELAY)-th parent of this block
        self.header_warp: Dict[bytes32, bytes32] = {}

    @staticmethod
    def get_genesis_block() -> FullBlock:
        return FullBlock.from_bytes(genesis_block_hardcoded)

    def get_current_heads(self) -> List[FullBlock]:
        """
        Return the heads.
        """
        return self.heads

    def is_child_of_head(self, block: FullBlock):
        """
        True iff the block is the direct ancestor of a head.
        """
        for head in self.heads:
            if (block.prev_hash == head.header_hash):
                return True
        return False

    def get_trunk_block(self, header_hash: bytes32) -> TrunkBlock:
        return self.blocks[header_hash].trunk_block

    def get_trunk_blocks_by_height(self, heights: List[uint64], tip_header_hash: bytes32) -> List[TrunkBlock]:
        """
        Returns a list of trunk blocks, one for each height requested.
        """
        log.info("Starting get trunks by height")
        # TODO: optimize, don't look at all blocks

        sorted_heights = sorted([(height, index) for index, height in enumerate(heights)], reverse=True)

        if tip_header_hash not in self.blocks:
            raise BlockNotInBlockchain(f"Header hash {tip_header_hash} not present in chain.")
        curr_block: TrunkBlock = self.blocks[tip_header_hash]
        trunks: List[Tuple[int, TrunkBlock]] = []
        for height, index in sorted_heights:
            if height > curr_block.challenge.height:
                raise ValueError("Height is not valid for tip {tip_header_hash}")
            while height < curr_block.challenge.height:
                curr_block = self.blocks[curr_block.header.data.prev_header_hash]
            trunks.append((index, curr_block))
        log.info("Returning get trunks by height")
        return [b for index, b in sorted(trunks)]

    def find_fork_point(self, alternate_chain: List[TrunkBlock]):
        """
        Takes in an alternate blockchain (trunks), and compares it to self. Returns the last trunk
        where both blockchains are equal.
        """
        lca: TrunkBlock = self.lca_block.trunk_block
        assert lca.challenge.height < alternate_chain[-1].challenge.height
        low = 0
        high = lca.challenge.height
        while low + 1 < high:
            mid = (low + high) // 2
            if self.height_to_hash[uint64(mid)] != alternate_chain[mid].header.get_hash():
                high = mid
            else:
                low = mid
        if low == high and low == 0:
            assert self.height_to_hash[uint64(0)] == alternate_chain[0].header.get_hash()
            return alternate_chain[0]
        assert low + 1 == high
        if self.height_to_hash[uint64(low)] == alternate_chain[low].header.get_hash():
            if self.height_to_hash[uint64(high)] == alternate_chain[high].header.get_hash():
                return alternate_chain[high]
            else:
                return alternate_chain[low]
        elif low > 0:
            assert self.height_to_hash[uint64(low - 1)] == alternate_chain[low - 1].header.get_hash()
            return alternate_chain[low - 1]
        else:
            raise ValueError("Invalid genesis block")

    def get_difficulty(self, header_hash: bytes32) -> uint64:
        trunk = self.blocks.get(header_hash, None)
        if trunk is None:
            raise Exception("No block found for given header_hash")
        elif trunk is self.genesis:
            return uint64(DIFFICULTY_STARTING)

        prev_trunk = self.blocks.get(trunk.prev_header_hash, None)
        if prev_trunk is None:
            raise Exception("No previous block found to compare total weight to")
        return trunk.challenge.total_weight - prev_trunk.challenge.total_weight

    def get_next_difficulty(self, header_hash: bytes32) -> uint64:
        return self.get_difficulty(header_hash)

        # Returns the difficulty of the next block that extends onto header_hash.
        # Used to calculate the number of iterations.
        # TODO:  Assumes header_hash is of a connected block

        block = self.blocks.get(header_hash, None)
        if block is None:
            raise Exception("Given header_hash must reference block already added")
        if block.height % DIFFICULTY_EPOCH != DIFFICULTY_DELAY:
            # Not at a point where difficulty would change
            return self.get_difficulty(header_hash)
        elif block.height == DIFFICULTY_DELAY:
            return uint64(DIFFICULTY_FACTOR * DIFFICULTY_STARTING)

        # The current block has height i + DELAY.
        Tc = self.get_difficulty(header_hash)
        warp = header_hash
        for _ in range(DIFFICULTY_DELAY - 1):
            warp = self.blocks[warp].hash
        # warp: header_hash of height {i + 1}

        warp2 = warp
        for _ in range(DIFFICULTY_WARP_FACTOR - 1):
            warp2 = self.header_warp.get(warp2, None)
        # warp2: header_hash of height {i + 1 - EPOCH + DELAY}
        Tp = self.get_difficulty(self.blocks[warp2].prev_hash)

        # X_i : timestamp of i-th block, (EPOCH divides i)
        # Current block @warp is i+1
        temp_block = self.blocks[warp]
        timestamp1 = temp_block.trunk_block.header.data.timestamp  # X_{i+1}
        temp_block = self.blocks[warp2]
        timestamp2 = temp_block.trunk_block.header.data.timestamp  # X_{i+1-EPOCH+DELAY}
        temp_block = self.blocks[self.header_warp[temp_block.hash]]
        timestamp3 = temp_block.trunk_block.header.data.timestamp  # X_{i+1-EPOCH}

        diff_natural = (
            (DIFFICULTY_EPOCH - DIFFICULTY_DELAY) * Tc * (timestamp2 - timestamp3)
        )
        diff_natural += DIFFICULTY_DELAY * Tp * (timestamp1 - timestamp2)
        diff_natural *= DIFFICULTY_TARGET
        diff_natural //= (timestamp1 - timestamp2) * (timestamp2 - timestamp3)
        difficulty = max(min(diff_natural, Tc * 4), Tc // 4)  # truncated comparison
        return difficulty

    def get_vdf_rate_estimate(self) -> Optional[uint64]:
        """
        Returns an estimate of how fast VDFs are running in the network, in iterations per second.
        Looks at the last N blocks from one of the heads, and divides timestamps. Returns None
        if no time has elapsed, or if genesis block.
        """
        head: TrunkBlock = self.heads[0]
        curr = head
        total_iterations_performed = 0
        for _ in range(0, 200):
            if curr.challenge.height > 1:
                # Ignores the genesis block, since it may have an older timestamp
                iterations_performed = calculate_iterations(curr.proof_of_space,
                                                            curr.proof_of_time.output.challenge_hash,
                                                            self.get_difficulty(curr.header.get_hash()))
                total_iterations_performed += iterations_performed
                curr: TrunkBlock = self.blocks[curr.header.data.prev_header_hash]
            else:
                break
        head_timestamp: int = int(head.header.data.timestamp)
        curr_timestamp: int = int(curr.header.data.timestamp)
        time_elapsed_secs: int = head_timestamp - curr_timestamp
        if time_elapsed_secs == 0:
            return None
        return uint64(total_iterations_performed // time_elapsed_secs)

    def receive_block(self, block: FullBlock) -> ReceiveBlockResult:
        if block.hash in self.blocks:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK

        start = time.time()
        if not self.validate_block(block):
            return ReceiveBlockResult.INVALID_BLOCK
        print(f"Time taken for validation: {time.time() - start}")

        if block.prev_hash not in self.blocks:
            return ReceiveBlockResult.DISCONNECTED_BLOCK

        self.blocks[block.header_hash] = block
        if self._reconsider_heads(block):
            return ReceiveBlockResult.ADDED_TO_HEAD
        else:
            return ReceiveBlockResult.ADDED_AS_ORPHAN

    def validate_unfinished_block(self, block: FullBlock):
        """
        Block validation algorithm. Returns true if the candidate block is fully valid
        (except for proof of time). The same as validate_block, but without proof of time
        and challenge validation.
        1. Takes in chain: Blockchain, candidate: FullBlock
        2. Check previous pointer(s) / flyclient
        3. Check Now+2hrs > timestamp > avg timestamp of last 11 blocks
        4. Check filter hash is correct
        5. Check body hash
        6. Check extension data
        7. Compute challenge of parent
        8. Check plotter signature of header data is valid based on plotter key
        9. Check proof of space based on challenge
        10. Check coinbase height = parent coinbase height + 1
        11. Check coinbase amount
        12. Check coinbase signature with pool pk
        13. Check transactions are valid
        14. Check aggregate BLS signature is valid
        15. Check fees amount is correct
        """
        if block.prev_hash not in self.blocks:
            return False
        last_timestamps: List[uint64] = []
        prev_block: FullBlock = self.blocks[block.prev_hash]
        curr = prev_block
        while len(last_timestamps) < NUMBER_OF_TIMESTAMPS:
            last_timestamps.append(curr.trunk_block.header.data.timestamp)
            try:
                curr = self.blocks[curr.prev_hash]
            except KeyError:
                break
        if len(last_timestamps) != NUMBER_OF_TIMESTAMPS and curr.trunk_block.challenge.height != 0:
            return False
        prev_time: uint64 = uint64(sum(last_timestamps) / len(last_timestamps))
        if block.trunk_block.header.data.timestamp < prev_time:
            return False
        if block.trunk_block.header.data.timestamp > prev_time + MAX_FUTURE_TIME:
            return False

        # TODO: check filter hash

        if (block.trunk_block.proof_of_time.output.get_hash() !=
                block.trunk_block.challenge.proof_of_time_output_hash):
            return False

        # If any extension data is added, it should be checked here

        if block.body.get_hash() != block.trunk_block.header.data.body_hash:
            return False

        if not block.trunk_block.header.plotter_signature.verify([blspy.Util.hash256(block.header_hash)],
                                                                 [block.trunk_block.proof_of_space.plot_pubkey]):
            return False

        pos_quality = block.trunk_block.proof_of_space.verify_and_get_quality(
                block.trunk_block.proof_of_time.output.challenge_hash)
        if not pos_quality:
            return False

        if block.body.coinbase.height != prev_block.body.coinbase.height + 1:
            return False

        if calculate_block_reward(block.trunk_block.challenge.height) != block.body.coinbase.amount:
            return False

        if not block.body.coinbase_signature.verify([blspy.Util.hash256()],
                                                    [block.trunk_block.proof_of_space.pool_pubkey]):
            return False

        # TODO: check transactions
        # TODO: check that transactions result in signature
        if block.body.aggregated_signature:
            # TODO: check that aggregate signature is valid, based on pubkeys, and messages
            pass
        # TODO: check fees

        return True

    def validate_block(self, block: FullBlock):
        """
        Block validation algorithm. Returns true iff the candidate block is fully valid,
        and extends something in the blockchain.
        1. Validate unfinished block (check the rest of the conditions)
        2. Check proof of space hash
        3. Check number of iterations on PoT is correct, based on prev block and PoS
        4. Check PoT
        5. and check if PoT.output.challenge_hash matches
        6. Check challenge height = parent height + 1
        7. Check challenge total_weight = parent total_weight + difficulty
        8. Check challenge total_iters = parent total_iters + number_iters
        """
        if not self.validate_unfinished_block(block):
            return False

        prev_block: FullBlock = self.blocks[block.prev_hash]
        difficulty: uint64 = self.get_next_difficulty(block.prev_hash)

        if block.trunk_block.proof_of_space.get_hash() != block.trunk_block.challenge.proof_of_space_hash:
            return False

        pos_quality: bytes32 = block.trunk_block.proof_of_space.verify_and_get_quality(
            block.trunk_block.proof_of_time.output.challenge_hash)

        number_of_iters: uint64 = calculate_iterations_quality(pos_quality, block.trunk_block.proof_of_space.size,
                                                               difficulty)
        if number_of_iters != block.trunk_block.proof_of_time.output.number_of_iterations:
            return False

        if not block.trunk_block.proof_of_time.is_valid():
            return False

        if (block.trunk_block.proof_of_time.output.challenge_hash !=
                prev_block.trunk_block.challenge.get_hash()):
            return False

        if block.body.coinbase.height != block.trunk_block.challenge.height:
            return False

        if block.trunk_block.challenge.height != prev_block.trunk_block.challenge.height + 1:
            return False

        if (block.trunk_block.challenge.total_weight !=
                prev_block.trunk_block.challenge.total_weight + difficulty):
            return False

        if (block.trunk_block.challenge.total_iters !=
                prev_block.trunk_block.challenge.total_iters + number_of_iters):
            return False
        return True

    def _reconsider_heights(self, old_lca: FullBlock, new_lca: FullBlock):
        """
        Update the mapping from height to block hash, when the lca changes.
        """
        curr_old: TrunkBlock = old_lca
        curr_new: TrunkBlock = new_lca
        while True:
            if curr_old.height > curr_new.height:
                del self.height_to_hash[uint64(curr_old.height)]
                curr_old = self.blocks[curr_old.prev_hash]
            elif curr_old.height < curr_new.height:
                self.height_to_hash[uint64(curr_new.height)] = curr_new.header_hash
                curr_new = self.blocks[curr_new.prev_hash]
            else:
                if curr_new.header_hash == curr_old.header_hash:
                    return
                self.height_to_hash[uint64(curr_new.height)] = curr_new.header_hash
                curr_new = self.blocks[curr_new.prev_hash]
                curr_old = self.blocks[curr_old.prev_hash]

    def _reconsider_lca(self):
        cur: List[FullBlock] = self.heads[:]
        heights: List[uint64] = [b.height for b in cur]
        while any(h != heights[0] for h in heights):
            i = heights.index(max(heights))
            cur[i] = self.blocks[cur[i].prev_hash]
            heights[i] = cur[i].height
        self._reconsider_heights(self.lca_block, cur[0])
        self.lca_block = cur[0]

    def _reconsider_heads(self, block: FullBlock) -> bool:
        if block.weight > min(b.weight for b in self.heads):
            self.heads.append(block)
            while len(self.heads) >= 4:
                self.heads.sort(key=lambda b: b.weight, reverse=True)
                self.heads.pop()
            log.info(f"Updated heads, new heights: {[b.height for b in self.heads]}")
            self._reconsider_lca()
            return True
        return False

    def _get_warpable_trunk(self, trunk: TrunkBlock) -> TrunkBlock:
        height = trunk.challenge.height
        while height % DIFFICULTY_DELAY != 1:
            trunk = self.blocks[trunk.header.header_hash]
            height = trunk.challenge.height
        return trunk

    def _consider_warping_link(self, trunk: TrunkBlock):
        # Assumes trunk is already connected
        if trunk.challenge.height % DIFFICULTY_DELAY != 1:
            return
        warped_trunk = self.blocks[trunk.prev_header_hash]
        while warped_trunk and warped_trunk.challenge.height % DIFFICULTY_DELAY != 1:
            warped_trunk = self.blocks.get(warped_trunk.prev_header_hash, None)
        if warped_trunk is not None:
            self.header_warp[trunk.header.header_hash] = warped_trunk.header.header_hash
