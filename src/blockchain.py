from collections import defaultdict
from typing import List, Dict, Optional
import logging
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.genesis_block import genesis_block_hardcoded
from src.types.trunk_block import TrunkBlock
from src.types.full_block import FullBlock
from src.consensus.pot_iterations import calculate_iterations
from src.consensus.constants import (
    DIFFICULTY_STARTING,
    DIFFICULTY_TARGET,
    DIFFICULTY_EPOCH,
    DIFFICULTY_DELAY,
    DIFFICULTY_WARP_FACTOR,
    DIFFICULTY_FACTOR,
)

log = logging.getLogger(__name__)


class Blockchain:
    def __init__(self):
        try:
            self.genesis_trunk = FullBlock.from_bytes(genesis_block_hardcoded).trunk_block
        except ValueError:
            raise ValueError("Failed to parse genesis block.")
        self.heads: List[TrunkBlock] = [self.genesis_trunk]
        self.blocks: Dict[bytes32, TrunkBlock] = {
            self.genesis_trunk.header.get_hash(): self.genesis_trunk
        }
        # Block is unconnected iff floating_demand[prev_hash] contains header_hash
        self.floating_demand: Dict[bytes32, List[bytes32]] = defaultdict(list)
        # For blocks with height % DIFFICULTY_DELAY == 1, a link to the hash of
        # the (DIFFICULTY_DELAY)-th parent of this block
        self.header_warp: Dict[bytes32, bytes32] = {}

    def get_current_heads(self) -> List[TrunkBlock]:
        return self.heads

    def is_child_of_head(self, block: FullBlock):
        """
        True iff the block is the direct ancestor of a head.
        """
        prev_header_hash = block.trunk_block.prev_header_hash
        for trunk in self.heads:
            if (prev_header_hash == trunk.header.header_hash):
                return True
        return False

    def get_trunk_block(self, header_hash: bytes32) -> TrunkBlock:
        return self.blocks[header_hash]

    def get_difficulty(self, header_hash: bytes32) -> uint64:
        trunk = self.blocks.get(header_hash, None)
        if trunk is None:
            raise Exception("No block found for given header_hash")
        elif trunk is self.genesis_trunk:
            return uint64(DIFFICULTY_STARTING)

        prev_trunk = self.blocks.get(trunk.prev_header_hash, None)
        if prev_trunk is None:
            raise Exception("No previous block found to compare total weight to")
        return trunk.challenge.total_weight - prev_trunk.challenge.total_weight

    def get_next_difficulty(self, header_hash: bytes32) -> uint64:
        # Returns the difficulty of the next block that extends onto header_hash.
        # Used to calculate the number of iterations.
        # TODO:  Assumes header_hash is of a connected block

        trunk = self.blocks.get(header_hash, None)
        if trunk is None:
            raise Exception("Given header_hash must reference block already added")
        height = trunk.challenge.height
        if height % DIFFICULTY_EPOCH != DIFFICULTY_DELAY:
            # Not at a point where difficulty would change
            return self.get_difficulty(header_hash)
        elif height == DIFFICULTY_DELAY:
            return uint64(DIFFICULTY_FACTOR * DIFFICULTY_STARTING)

        # The current block has height i + DELAY.
        Tc = self.get_difficulty(header_hash)
        warp = header_hash
        for _ in range(DIFFICULTY_DELAY - 1):
            warp = self.blocks[warp].header.header_hash
        # warp: header_hash of height {i + 1}

        warp2 = warp
        for _ in range(DIFFICULTY_WARP_FACTOR - 1):
            warp2 = self.header_warp.get(warp2, None)
        # warp2: header_hash of height {i + 1 - EPOCH + DELAY}
        Tp = self.get_difficulty(self.blocks[warp2].prev_header_hash)

        # X_i : timestamp of i-th block, (EPOCH divides i, genesis is block height 1)
        # Current block @warp is i+1
        temp_trunk = self.blocks[warp]
        timestamp1 = temp_trunk.header.data.timestamp  # X_{i+1}
        temp_trunk = self.blocks[warp2]
        timestamp2 = temp_trunk.header.data.timestamp  # X_{i+1-EPOCH+DELAY}
        temp_trunk = self.blocks[self.header_warp[temp_trunk.header.header_hash]]
        timestamp3 = temp_trunk.header.data.timestamp  # X_{i+1-EPOCH}

        diff_natural = (DIFFICULTY_EPOCH - DIFFICULTY_DELAY) * Tc * (timestamp2 - timestamp3)
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

    def add_block(self, block: FullBlock) -> bool:
        if not block.is_valid():
            # TODO(alex): discredit/blacklist sender
            log.info("block is not valid")
            return False

        trunk = block.trunk_block
        header_hash = trunk.header.header_hash
        prev_hash = trunk.prev_header_hash
        self.blocks[header_hash] = trunk
        added_to_head = False

        prev_trunk = self.blocks.get(prev_hash, None)
        if prev_trunk is None or prev_hash in self.floating_demand.get(
                prev_trunk.prev_header_hash, ()):
            # This block's previous block doesn't exist or is not connected
            self.floating_demand[prev_hash].append(header_hash)
        else:
            # This block's previous block is connected
            # Now connect any children demanding this block

            # TODO(alex): verify block is consistent with blockchain
            stack = [header_hash]

            while stack:  # DFS
                sky_block_hash = stack.pop()
                sky_trunk = self.blocks[sky_block_hash]
                self._consider_warping_link(sky_trunk)
                added_to_head |= self._reconsider_heads(sky_trunk)
                stack.extend(self.floating_demand.pop(sky_block_hash, []))

        return added_to_head

    def add_blocks_and_prune(self, blocks: List[FullBlock]):
        # Put all blocks in
        for _, block in enumerate(blocks):
            trunk = block.trunk_block
            header_hash = trunk.header.header_hash
            self.blocks[header_hash] = trunk
            self._reconsider_heads(trunk)

        # Mark all header_hashes connected from a head to genesis
        connected_hashes = {self.genesis_trunk.header.header_hash}
        for trunk in self.heads:
            cur_trunk = trunk
            current_hashes = set()
            warpables_to_link = []
            while cur_trunk.header.header_hash not in connected_hashes:
                current_hashes.add(cur_trunk.header.header_hash)
                if cur_trunk.challenge.height % DIFFICULTY_DELAY == 1:
                    warpables_to_link.append(cur_trunk)
                cur_trunk = self.blocks.get(trunk.prev_header_hash, None)
                if cur_trunk is None:
                    break
            else:
                connected_hashes |= current_hashes

                # Add warping links
                if warpables_to_link:
                    bottom_header_hash = self._get_warpable_trunk(
                            self.blocks[warpables_to_link[-1].prev_header_hash])
                    for trunk in reversed(warpables_to_link):
                        cur_header_hash = trunk.header.header_hash
                        self.header_warp[cur_header_hash] = bottom_header_hash
                        bottom_header_hash = cur_header_hash

        # Delete all blocks that aren't marked
        for block in blocks:
            trunk = block.trunk_block
            header_hash = trunk.header.header_hash
            if header_hash not in connected_hashes:
                del self.blocks[header_hash]

    def heads_lca(self):
        cur = self.heads[:]
        heights = [t.challenge.height for t in cur]
        while any(h != heights[0] for h in heights):
            i = heights.index(max(heights))
            cur[i] = self.blocks[cur[i].prev_header_hash]
            heights[i] = cur[i].challenge.height
        return cur[0]

    def validate_unfinished_block(self, candidate: FullBlock):
        """
        Returns true if the candidate block is fully valid (except for proof of time),
        and extends one of the current heads. The same as validate_block, but without
        #11-13.
        """
        pass

    def validate_block(self, candidate: FullBlock):
        """
        Block validation algorithm. Returns true iff the candidate block is fully valid,
        and extends one of the current heads.
        1. Takes in chain: Blockchain, candidate: FullBlock
        2. Check previous pointer(s)
        3. Check Now+2hrs > timestamp > avg timestamp of last 11 blocks
        4. Check filter hash is correct
        5. Check proof of space hash
        6. Check body hash
        7. Check extension data
        8. Compute challenge of parent
        9. Check plotter signature of header data is valid based on plotter key
        10. Check proof of space based on challenge
        11. Check number of iterations on PoT is correct, based on prev block and PoS
        12. Check PoT
        13. and check if PoT.output.challenge_hash matches
        14. Check coinbase height = parent height + 1
        15. Check coinbase amount
        16. Check coinbase signature with pool pk
        17. Check transactions are valid
        18. Check aggregate BLS signature is valid
        19. Check fees amount is correct
        """
        return True

    def _reconsider_heads(self, trunk: TrunkBlock) -> bool:
        # TODO(alex): use weight instead
        if trunk.challenge.height > min(t.challenge.height for t in self.heads):
            self.heads.append(trunk)
            while len(self.heads) >= 4:
                self.heads.sort(key=lambda b: b.challenge.height, reverse=True)
                self.heads.pop()
            log.info(f"Updated heads, new heights: {[t.challenge.height for t in self.heads]}")
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
