from collections import defaultdict
from typing import List, Dict
import logging
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.types.trunk_block import TrunkBlock
from src.types.full_block import FullBlock
from src.types.block_body import BlockBody
from src.types.block_header import BlockHeader
from src.consensus.constants import (
    DIFFICULTY_STARTING,
    DIFFICULTY_TARGET,
    DIFFICULTY_EPOCH,
    DIFFICULTY_DELAY,
    DIFFICULTY_WARP_FACTOR,
    DIFFICULTY_FACTOR,
)

log = logging.getLogger(__name__)
genesis_block_bytes: bytes = b'\x15N3\xd3\xf9H\xc2K\x96\xfe\xf2f\xa2\xbf\x87\x0e\x0f,\xd0\xd4\x0f6s\xb1".\\\xf5\x8a\xb4\x03\x84\x8e\xf9\xbb\xa1\xca\xdef3:\xe4?\x0c\xe5\xc6\x12\x80\x15N3\xd3\xf9H\xc2K\x96\xfe\xf2f\xa2\xbf\x87\x0e\x0f,\xd0\xd4\x0f6s\xb1".\\\xf5\x8a\xb4\x03\x84\x8e\xf9\xbb\xa1\xca\xdef3:\xe4?\x0c\xe5\xc6\x12\x80\x13\x00\x00\x00\x98\xf9\xeb\x86\x90Kj\x01\x1cZk_\xe1\x9c\x03;Z\xb9V\xe2\xe8\xa5\xc8\n\x0c\xbbU\xa6\xc5\xc5\xbcH\xa3\xb3fd\xcd\xb8\x83\t\xa9\x97\x96\xb5\x91G \xb2\x9e\x05\\\x91\xe1<\xee\xb1\x06\xc3\x18~XuI\xc8\x8a\xb5b\xd7.7\x96Ej\xf3DThs\x18s\xa5\xd4C\x1ea\xfd\xd5\xcf\xb9o\x18\xea6n\xe22*\xb0]%\x15\xd0i\x83\xcb\x9a\xa2.+\x0f1\xcd\x03Z\xf3]\'\xbf|\x8b\xa6\xbcF\x10\xe8Q\x19\xaeZ~\xe5\x1f\xf1)\xa3\xfb\x82\x1a\xb8\x12\xce\x19\xc8\xde\xb9n\x08[\xef\xfd\xf9\x0c\xec\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00@\xeb\xc4\x10\xb4$Y\x1b\r\xa3\x1c*\xc9\xb9\xb8\xa8\xd3]\xf6\x9a\x10MJ\xe9\xfc-\x19dU\xda2B\x9bgJ\x0c\xd3\x1f\xdc\xf6\xbd\xe9\x8b\x83k\x87.{\x96\xa2z\xbf\xf8\xe1bT\xef\x95\xa6\x8f\xd8g\xb9\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00?\x02U~X\xc2\x1bE\x87y\xf4\xf8#D\'\xaf5\xc3\xe4\xc7#\x7fAb\x9d}\xeb$o^,\x7f7lK\xbam\xe9\x9e\xfd\x04\xee\x0f\x93\xfe\x0c\xba{B\xe91\xeeT\x03!\x11\xc6k\xb9\x1e\xad\x1e\x07\xfd\x03\x00\x00\x03\x8e\x00%^\xd5&;\xb5g\x9ae\xc6\x07\xf0\xc8\xdcV\x08\xf8\xb4\xfc\xdc5_\x8e\x87\xc1\xca\x99\xb6_\xf7D\xa2}\x81y{\rz\xaf\xf1\xf0\x08\xd9\xc0\x97\x08v\x19\x9f\x82\xa3\xcc\xb2\x176N\xa2\x8f>\xa3\x92\xb27\xc9\x00\x01\x97\xeb\x18:\xfc\xb2\x8e\'1r\xdf\xb9\xcc\x1a\xa3\xff\xc6\x162\xf0;\xb5\xd1\x8a\xc0K^\xbdO\x8b\xf5\xdesh1\x91\tu\x0e\xd7~\x9d\xb7\x86EG$"\x9f\x92\xaeP\x94D[.\xfa\xbb\x91w\xf9O-\x00\x02\xb4\x8f:nb\x02\x00\x15\xf2r3s\xa7x\xb6\xf7\x8a\xd8\xc4\xb1v\xd1m4Jk\xee!\x0f\x80\x1e|\xf7\x1c\x9e\x86\x91\xa9\xf9\x9e\xddj\x81\x0bk\x86\x9d(a\xd3\x84\xc7\xbd\xd2E\xe7\x07\xdf\x1b\x06;\xfc$\x00\x01GA\x861-\xc6+\xbcJ5,\xa6\xd13\x8ez\xb0\xc8#\xa4\xcf\xa2\xbc\xf9\xfc!\xae7a\xc1+\x948x\x90\x86\x0c\xbceG\xb6\xc4y\xaa\xe8-\x04%c\x950\x95\xc2e\x1a\r\xc3&wO\x15\xd2\x0f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x02\xb4\x8f:nb\x02\x00\x15\xf2r3s\xa7x\xb6\xf7\x8a\xd8\xc4\xb1v\xd1m4Jk\xee!\x0f\x80\x1e|\xf7\x1c\x9e\x86\x91\xa9\xf9\x9e\xddj\x81\x0bk\x86\x9d(a\xd3\x84\xc7\xbd\xd2E\xe7\x07\xdf\x1b\x06;\xfc$\x00\x01GA\x861-\xc6+\xbcJ5,\xa6\xd13\x8ez\xb0\xc8#\xa4\xcf\xa2\xbc\xf9\xfc!\xae7a\xc1+\x948x\x90\x86\x0c\xbceG\xb6\xc4y\xaa\xe8-\x04%c\x950\x95\xc2e\x1a\r\xc3&wO\x15\xd2\x0f\x00\x17\x0e\x06\x0co\x13\xe3Q\xdc\xd6K\x184\x95\x97\x83a\x85in\x89K\xc6\x16!\xd2\xa9\xac\xba\x9b\xefb+\x93q\x1b\xb6\x95F7aH\xd1[+qA\x9a#x\xa3{\xd4B\xc8\xab*\x0f\x82\xe4>\xd4\xeb\xfc\x00\t\xea\x12\x959\xc4J\x12\x1a\x813\t\xb8\x17\xbd0T\xa2>k~&\xaa\xdf|\xfcC\xda\xd8\xb0\x19kC"\xbd\x9c\x17.\x9e\xf1\x9a\xeb\xfc\xe9)I\x93o\xe7\xe3((\x9b\xd3\x8cJ\x02\xc2\xe7\xb9\x8a\xb3\x1c\xff\x00S\xdd\x08\x06\x9f )\xda\x87\xbb\xac\\\xdd|hx\xd4\x9dO\x03\xa71\xc2\x8b_\x8b\x8c)\x04+-\xcf}\x9d\x96\x92`\xea\xee\xb2\x1f\xccm\x0fN\xe1\xectRa\xbb4\x0f\xba\nj\x1b\x108@\xf0\x8bK\xaf\xff\xf4f\xf6>\t\xe0c\xfcs\x00\x14\xe0\xf6H\x8eb\x05\x80\xb4\x96\xf4\xe4d\x82\xf4\x9a<!\xfew\x8c\x99!%\x9c\xf1\xa4\xaf\x8f\x93\xdb\xfb\xbd\xd7\x125\x98V@n3l-\x92\xbe\xf5\x03\xbf\x0e\xc9n\xd6\xb5\x95\x00<\rh\xfe\x08&\x02wC\xd2\x94JV\xc9\xd0\x82\xe2S\xf0\x91\x16\xe9\xc0\xd6\xa9\xfb9\x9f"\x91\x1aA,\xe5\t*\xd4\xd0r\x0faq6\x87&\xea\xe0\x13\xae\x15\xf1+oa[m\x07W\xdbv\x93\xa4E\xfb\xff\xeeLkr\xd2\xc1\xc1T\xe8j7\x83\x9a\xc4\xa6\xf4\xc7\x83\xb1\x19z?5\x95\x07\x1c \x8102\x8b\xf62\xbbb1\xee\xc5\xa4?S\xb3\x9fH\xe1b\x1c\x88\x97J\x02\xa8\x86|\xf6\xe5?\xda\xd8g\'D\xb7C\x01~[u\x1f\x81\x7f\x0c)\x05\xe6\xfd\xe5\xd14\\a\n\xc6I\xccJ\x0cXk\xcf,Z\x1c\xdb>\xe0\xc3\xec\xcf\x04\xab\x06\xac\xe62g\x15i\x13\xd4\xda\xdc\xee\xbd\xb6\xea\x19\x1d\x1a3p\xc6\xdb\x0e\x15\xcf\x90\x0f\x02\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00]^8\x9e\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00~[u\x1f\x81\x7f\x0c)\x05\xe6\xfd\xe5\xd14\\a\n\xc6I\xccJ\x0cXk\xcf,Z\x1c\xdb>\xe0\xc3z!\xc9N\xd5\x03\x8b^\xd9\xe6\xc7I\xba\xb1\x0fm\xd4\xa0=\xb6^s\x94_f\xb5\xc1\\n\xfe\xf9\xd2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xca\x10\x1d\xda\xf1@\xb0C\x0eG\xc9\x8e\xc5Af\xa5\x98hb\xb5l\xcb\x1dO"\xbe\x96\x0b\xfc\x1d\x7f@\xda\x91\x042\xfd\xcc\x16\xae\xff0\xe2\x13\x811H\xc4\x10\xabs\x8f\xb0\x98|J\xf8\xd2\xd7\xeb\x1e]\x10\xacS\x15d\x88Nw\x8c\x9e\xe0\xb50\x8f\xda\xbd\xf5j&.P\x8d\x91\xf7ZY\xbd\x10\x8c\x9eJ\x01\x0bT\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n+\x93\xa0\x02\xe4\xc2\x1d\xaa5R\xe5,\xbd\xa5\x15|%}\xa4@\xe5\x11\x00\x80\x1fG\x8aH\x0b\xe7\xe9\x10\xd3tK\xda`\xb5u\xca\x8c\xa2\xf7n\x1d\xd5\x92l\xb13k\xdb\n+\xbe/\x1e\xc0\xfe\xbf\xd9\x83\x88V\x11]~.<\x14\x0f\xce`\x8b\xbf\xb9\xa7\xce"6\x19\xa5\x19|\x81!r\x15V\xa6\x82\x07\x96w\x98F\xce\xb2(G\xcfm\x17@t\xb2\x1b\xba\xcf4I}\x0b\xc4\n\xd4\x9b\xe2E\x9e\x84\x98mY||\xa8[+\x93\xa0\x02\xe4\xc2\x1d\xaa5R\xe5,\xbd\xa5\x15|%}\xa4@\xe5\x11\x00\x80\x1fG\x8aH\x0b\xe7\xe9\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'


class Blockchain:

    def __init__(self):
        try:
            self.genesis_trunk = FullBlock.from_bytes(genesis_block_bytes).trunk_block
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

    def _reconsider_heads(self, trunk: TrunkBlock) -> bool:
        if trunk.challenge.height > min(t.challenge.height for t in self.heads):
            self.heads.append(trunk)
            while len(self.heads) >= 4:
                self.heads.sort(key=lambda b: b.challenge.height, reverse=True)
                self.heads.pop()
            log.info(f"Updated heads, new heights: {[t.challenge.height for t in self.heads]}")
            return True
        return False

    def block_can_be_added(self, block_header: BlockHeader, block_body: BlockBody) -> bool:
        """
        Called by the full node of the farmer, when making a new block
        (that doesn't have PoT yet).  True iff the block connects to some head.

        Assumes that block_header and block_body are internally valid already.
        """
        prev_header_hash = block_header.data.prev_header_hash
        for trunk in self.heads:
            if (prev_header_hash == trunk.header.header_hash
                    and block_header.data.timestamp > trunk.header.data.timestamp):
                # TODO:  "foliage arrow" ?
                return True
        return False

    def get_trunk_block(self, header_hash: bytes32) -> TrunkBlock:
        return self.blocks[header_hash]

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
