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
genesis_block_bytes: bytes = b'\x15N3\xd3\xf9H\xc2K\x96\xfe\xf2f\xa2\xbf\x87\x0e\x0f,\xd0\xd4\x0f6s\xb1".\\\xf5\x8a\xb4\x03\x84\x8e\xf9\xbb\xa1\xca\xdef3:\xe4?\x0c\xe5\xc6\x12\x80\x15N3\xd3\xf9H\xc2K\x96\xfe\xf2f\xa2\xbf\x87\x0e\x0f,\xd0\xd4\x0f6s\xb1".\\\xf5\x8a\xb4\x03\x84\x8e\xf9\xbb\xa1\xca\xdef3:\xe4?\x0c\xe5\xc6\x12\x80\x13\x00\x00\x00\x98\xf9\xeb\x86\x90Kj\x01\x1cZk_\xe1\x9c\x03;Z\xb9V\xe2\xe8\xa5\xc8\n\x0c\xbbU\xa6\xc5\xc5\xbcH\xa3\xb3fd\xcd\xb8\x83\t\xa9\x97\x96\xb5\x91G \xb2\x9e\x05\\\x91\xe1<\xee\xb1\x06\xc3\x18~XuI\xc8\x8a\xb5b\xd7.7\x96Ej\xf3DThs\x18s\xa5\xd4C\x1ea\xfd\xd5\xcf\xb9o\x18\xea6n\xe22*\xb0]%\x15\xd0i\x83\xcb\x9a\xa2.+\x0f1\xcd\x03Z\xf3]\'\xbf|\x8b\xa6\xbcF\x10\xe8Q\x19\xaeZ~\xe5\x1f\xf1)\xa3\xfb\x82\x1a\xb8\x12\xce\x19\xc8\xde\xb9n\x08[\xef\xfd\xf9\x0c\xec\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x12k\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x90\xe5\xc3\xbc;4\xda-1L3\xa2\xe3\xb5\xab\x91\xd3\xbb8!\xaa\xade~j(\r\xf3M`\xc8\x19\xbe\xd4\'\x93q\x9d\xc9N\xc48~\xcc\xd1\xab\x10\x86\xd7\xd7\xa1\x1c#f\xf8\x012>$\x8c\x1btr\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x9d\x9c~\xa4\x96`\x87%\x0c&6\xed\x1f\x1f\r\xe4OL\xca\xb6\xcd\x03\x1c\xb8\x90\x7f\x0e|\x91\xe7\xe2\xd2\xf8\x9a9)\xb0\xdec\x14\x1f\xad\xcb\x05\xf9\xe3\xac\xd2\x91\x10f\xeb\xcf\xab\xda\xf7\x19\x01\xc6JP\xfb]\x03\x00\x00\x03\x8e\x00\x08\xe3\xd0\x86\xdad\xdf\xce\x085\xf0\xcfV\x9d\xfb\x9d\xb1\xe7\xfa\x9b-L\xf6\'|xz\xab[\xb0MH\x1e\x84\xfb\x9e6X\xf5\x9fej*f\xfe-\xa0\xe3>\xc4#\x18\x12\x93O\xa3\x83\x98\xef\xf7\xd0g\x7f\xe4\x00\x02\xc1I\x13\xfc6+j\x87-{U\t\xc3\x9d\x1e\x82\x18\xb2\xc8D[!\xa7t\xad\xaf\x05\x88\xf4e\xfe~\xd2\x015_z@\xc1w\x90\xd2\xf8\xc08\xfbVu3\xeebB\xd5\xb9\x0c\xcf\xc8\x8f\x92\xd1j3g\x00\x19I \xdf=|\xc8\xf9\xf9\xa8y\\\x0f5\xdc\xd6SM\x93\xb2\x1d\xc86\x84wL\x9fy\xd7\xac\xfaa\xcf\\\xae\xfbo\xb0\x0c\xf9\xe9\x17\xd2\xb6\xf1\xbc\x87\xda\xd4Q\xe1\x91>+a\xb0^`\x93%6lP/\xff\xfd\x8eQL"}!;\xa71\xbaM67\xee\xb8&oI\xfc\'a\xb0\x0b\x04>\xb1K\xa0\x87H/\xce\xd9h\xe8\x81\xf8:\xc0b\xa6{x\x1c\xc4\x87\xdd\xb2\xe7i\xc3\x8d\xad\xf2o.\xb5`\xe1\xc7\x1dY\x07\x00\x1b\x19A\xc7\xe3N\xd9\xea\xa2\x1d\xa8\x16\x8f\xb5j\x07G\x91\xc7\x96\x1du\x07\xfe\xd3\xae}\xa7\xf4CD\xd8\x02Z\x99\xee\xe1\x1c\x85\xe4\x84s\xdc\x8b\x9dv~)\xb21pX\x01A\xf4\xeb-\x93c\xbbE\x96\xe9H\x00\x0f\xcd\x94\x8a\xa6G\x0e\x7fT#\xb4sEg\xe0\x0b\xb9\xc4\xf2oc\x87\x1b-\xf0\x8d\xb0\xa1\xe2\x19\x91\x84#\x08\x8b\x00\xe8"\xbf\xb4Ct\xa0\xeb\xad\x84`G2#9\xaf\xa7\x08k\xda\xdf\x8cQ\xa4!\x83*1\x00T\r\xa8\x87z\xc9Z\x11\xff5H\xbe\xda\x96W7p\xa8K\xba8\xeeZ\xf7\xcb\xca\xcc?Q\x16C\x1b\x8e\xb7\xd5U_\xfd\xc4\xeb3A\xa3YT\xe9\x95\xe1\x9c_\x1eX+\tX>\xd3\xe5\x8e_\xfdF\xe4\xe4\x00\x15<y\xa8"\x1e\x10\x0b\xff\x16\x80\\LT\x9f\xcb\xa5J\x81Q\x86\xe1]1\xea\xc9V\x93U\xb4\x88\xf8\xac\xcd\x02q`|\xbb\x0c\x1dO\xec\xbb7\xcdO\x04\x9c\x86\x80\xe7\xe5aUg\x13\'Z\xb2\x86\xe3\x80\x19\x00`\rOC\x18\xbc\x1fg9\x0c\x95\xeeD\xad\xc9n\xee3K\xe9\xd9S\xdb\x8a\xde\xd8\x03\x83\x8e\xe4\x99\xe6\xac\\L!\x9e\xef\x98\r\x9bz\xac\x8a\x8f\xa4\xa8\x8c\xa9S\xf4\xe4\xa6:\xb9\xdf\x8c\xe0\xfc\xd6\xd7W0\x82\x00,\x84y\xf8%\x00\x98\x90e\xbd\x89\xf5\x91\x86\x1c\x91\xd0wl\xd5\xc5\xf5\n\x9a\xfa\xa65fT\x82k\xb9FEt\x8f?\xd33\xb7\x14\x01\xc7\x82x\xf6a\xe6\x081\xa0\x92\xa3>j|/b\x99\xd4\xc4}y\xfd\x007\xb8\xcb\x85\xd4\xcb\xb0\xf8\xfd\xea\x13)+6\xe7kz\x90\xe2\xba\xa2DB\xef3n\xd6-%?\xd3\x9d@Ge!\xf8\xbf\xa7p\xe0\xd2\xbd\x13\r\xd0\x9fY&\x94\x01Cfvl\xc4\xe7Y!+\x0bV$\xca\xff\xe5y\xe7\x15;\x98\x1a\x8a\xb4\xfa\xdd\x17\xf5t\xbfC\xc4\xe4%6\xab\xc8\x024\xaa@\x11\xc2\xce\x7f\xac\x0f\xb6\x93\xe9\xbb7\xc3\xa6\xd9\xa8\x0eD_\xa9\xc8<\xae\x01\x86\x16\xcb#"\xf0O\xcf\x81\xcf\x8e\x97W\xef\xa7\x00v\xec\xd6\x05\xd2p_\xa5\xb1\xd9`\xadD\xb9\xb6\xe6Tt\x15\x0e\x95\xe4\x12j<\x17RG)J\xb4\xee\xd5\x8d\x90"\xec\x1f\x99a\xfb`\xc3\xbc\xe1L^\xd9o\x18]L,&%"\xafsp7\x05\xdf\x8f\xbb\xff\xc1\x06\xfb\xf0\x16!b\x92Q\xac?!\xaf\x10\x9aD\xda\x03\x8a\xaf\xd8$\x8b{a\x8d\x0f\xf5jns\x9d\x12\x0b,\x1c\x9b\xc7`\xad\xbbD;\x9dI|\xad\x1d*(\x11X\xe3\xd3\xaa7#!4\xe2\xad|\xf1!\x01~[u\x1f\x81\x7f\x0c)\x05\xe6\xfd\xe5\xd14\\a\n\xc6I\xccJ\x0cXk\xcf,Z\x1c\xdb>\xe0\xc3\x99\xe3\x93Z\xf2/\x9ec\xc4B\xca\xee\x9c\xe9\xc5B\x85\x0fG\x9c\x0e{\xda8\xa5?\x84\xb8\xa3$\xd7$\x00\x00\x00\x00\x00\x00\x00\x17Hv\xe8\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00]J\xa4\xed\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00~[u\x1f\x81\x7f\x0c)\x05\xe6\xfd\xe5\xd14\\a\n\xc6I\xccJ\x0cXk\xcf,Z\x1c\xdb>\xe0\xc3z!\xc9N\xd5\x03\x8b^\xd9\xe6\xc7I\xba\xb1\x0fm\xd4\xa0=\xb6^s\x94_f\xb5\xc1\\n\xfe\xf9\xd2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Q]\xdaO\xd8\x84 \xcb\xebh\x8ei]7\xd4\x0b\xf1\xb6\xd8%\x9eh\x9a}\x04\xa3u\xe7!v\xb3\xc0c\xba\x9b\xe02\xc9\x13\x85\xa7\x93R\x9bZ\x1a-\xc4\x07\xbd\xd2;\xa3\x9f\x17\x9c\xdc\xc3\xc3\x8d\x9b\x81\xcd\x0e\x9acb\xc2M\xd9j\xa2k\xb6S\xa6\xe2\x97>&\x1b\x05_sv\xfc\xdf\xd6\x17\xff\xb8u+\x1f\x1c\xb5\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n+\x93\xa0\x02\xe4\xc2\x1d\xaa5R\xe5,\xbd\xa5\x15|%}\xa4@\xe5\x11\x00\x80\x1fG\x8aH\x0b\xe7\xe9\x10\xd3tK\xda`\xb5u\xca\x8c\xa2\xf7n\x1d\xd5\x92l\xb13k\xdb\n+\xbe/\x1e\xc0\xfe\xbf\xd9\x83\x88V\x11]~.<\x14\x0f\xce`\x8b\xbf\xb9\xa7\xce"6\x19\xa5\x19|\x81!r\x15V\xa6\x82\x07\x96w\x98F\xce\xb2(G\xcfm\x17@t\xb2\x1b\xba\xcf4I}\x0b\xc4\n\xd4\x9b\xe2E\x9e\x84\x98mY||\xa8[+\x93\xa0\x02\xe4\xc2\x1d\xaa5R\xe5,\xbd\xa5\x15|%}\xa4@\xe5\x11\x00\x80\x1fG\x8aH\x0b\xe7\xe9\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'  # noqa: E501


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
        while warped_trunk.challenge.height % DIFFICULTY_DELAY != 1:
            warped_trunk = self.blocks[warped_trunk.header.header_hash]
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
