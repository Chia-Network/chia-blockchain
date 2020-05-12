from typing import Dict, Optional, Tuple

from src.full_node.blockchain import Blockchain, ReceiveBlockResult
from src.types.header import Header
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.error import Err
from src.util.ints import uint32, uint128


class HeaderBlockchain:
    def __init__(self, original_chain: Blockchain, fork_point: uint32):
        # Get blocks 1 2 and 3, and save the headers

        # self._original_chain =
        self.headers: Dict[bytes32, Header] = {}
        self.tip_height = 0
        self.tip_hash = bytes()

    async def receive_block(
        self, block: HeaderBlock
    ) -> Tuple[ReceiveBlockResult, Optional[Err]]:
        if block.header_hash in self.headers:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None

        if not block.height == 0:
            if self.tip_height + 1 != block.height:
                return ReceiveBlockResult.DISCONNECTED_BLOCK, None

        if block.prev_header_hash not in self.headers and not block.height == 0:
            return ReceiveBlockResult.DISCONNECTED_BLOCK, None

        error_code: Optional[Err] = await self.validate_block(block)

        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error_code

        self.headers[block.header_hash] = block.header
        self.tip_height = block.height
        self.tip_hash = block.header_hash
        return ReceiveBlockResult.ADDED_TO_HEAD, None

    def get_weight(self) -> uint128:
        return self.headers[self.tip_hash].weight

    async def validate_block(self, block: HeaderBlock) -> Optional[Err]:
        pass
