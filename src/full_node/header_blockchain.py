import concurrent
import multiprocessing
from typing import Dict, Optional, Tuple, List

from src.full_node.blockchain import Blockchain, ReceiveBlockResult
from src.consensus.constants import constants as consensus_constants
from src.types.header import Header
from src.types.header_block import HeaderBlock
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.errors import Err, ConsensusError
from src.util.ints import uint32, uint128
from src.full_node.block_header_validation import (
    validate_finished_block_header,
    pre_validate_finished_block_headers,
)


class HeaderBlockchain:
    constants: Dict
    headers: Dict[bytes32, Header]
    height_to_hash: Dict[uint32, bytes32]
    tip_header_block: HeaderBlock
    pool: concurrent.futures.ProcessPoolExecutor

    @staticmethod
    async def create(
        original_chain: Blockchain, fork_point: uint32, override_constants: Dict = {}
    ):
        self = HeaderBlockchain()
        self.constants = consensus_constants.copy()
        cpu_count = multiprocessing.cpu_count()
        self.pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=max(cpu_count - 1, 1)
        )

        self.headers = {}
        self.height_to_hash = {}

        if fork_point == 0:
            # Syncing from scratch, so only adds the genesis block
            for key, value in override_constants.items():
                self.constants[key] = value
            genesis = FullBlock.from_bytes(self.constants["GENESIS_BLOCK"])
            genesis_hb = original_chain.get_header_block(genesis)
            assert genesis_hb is not None
            res, code = await self.receive_block(genesis_hb)
            if res != ReceiveBlockResult.ADDED_TO_HEAD:
                assert code is not None
                raise ConsensusError(code, genesis_hb.header_hash)
        else:
            # Copies over the original headers from the chain (up to the fork point), so we can appropriately
            # calculalate the difficulty adjustments.

            for i in range(0, fork_point + 1):
                self.height_to_hash[uint32(i)] = original_chain.height_to_hash[
                    uint32(i)
                ]
                self.headers[self.height_to_hash[uint32(i)]] = original_chain.headers[
                    self.height_to_hash[uint32(i)]
                ]
            tip_fb: Optional[FullBlock] = await original_chain.block_store.get_block(
                self.height_to_hash[fork_point]
            )
            assert tip_fb is not None
            tip_hb = original_chain.get_header_block(tip_fb)
            assert tip_hb is not None
            self.tip_header_block = tip_hb
        return self

    def shut_down(self):
        self.pool.shutdown(wait=True)

    async def receive_block(
        self,
        block: HeaderBlock,
        pre_validated: bool = False,
        pos_quality_string: bytes32 = None,
    ) -> Tuple[ReceiveBlockResult, Optional[Err]]:
        if block.header_hash in self.headers:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None

        if not block.height == 0:
            assert self.tip_header_block is not None
            if self.tip_header_block.height + 1 != block.height:
                return ReceiveBlockResult.DISCONNECTED_BLOCK, None

        if block.prev_header_hash not in self.headers and not block.height == 0:
            return ReceiveBlockResult.DISCONNECTED_BLOCK, None

        if not block.height == 0:
            error_code: Optional[Err] = await validate_finished_block_header(
                self.constants,
                self.headers,
                self.height_to_hash,
                block,
                self.tip_header_block,
                False,
                pre_validated,
                pos_quality_string,
            )
        else:
            error_code = await validate_finished_block_header(
                self.constants,
                self.headers,
                self.height_to_hash,
                block,
                None,
                True,
                pre_validated,
                pos_quality_string,
            )

        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error_code

        self.headers[block.header_hash] = block.header
        self.height_to_hash[block.height] = block.header_hash
        self.tip_header_block = block
        return ReceiveBlockResult.ADDED_TO_HEAD, None

    def get_weight(self) -> uint128:
        if self.tip_header_block is None:
            return uint128(0)
        return self.tip_header_block.weight

    async def pre_validate_blocks_multiprocessing(
        self, blocks: List[HeaderBlock]
    ) -> List[Tuple[bool, Optional[bytes32]]]:
        return await pre_validate_finished_block_headers(
            self.constants, self.pool, blocks
        )
