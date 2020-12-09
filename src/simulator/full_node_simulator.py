from secrets import token_bytes

from typing import AsyncGenerator, List, Optional

from src.consensus.sub_block_record import SubBlockRecord
from src.full_node.full_node_api import FullNodeAPI
from src.protocols import (
    full_node_protocol,
)
from src.protocols.full_node_protocol import RespondSubBlock
from src.server.server import ChiaServer
from src.server.ws_connection import WSChiaConnection
from src.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from src.full_node.bundle_tools import best_solution_program
from src.server.outbound_message import OutboundMessage
from src.types.full_block import FullBlock
from src.types.spend_bundle import SpendBundle

# from src.types.header import Header
from src.util.api_decorators import api_request
from src.util.block_tools import BlockTools, test_constants
from src.util.ints import uint64

OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]

bt = BlockTools(constants=test_constants)

class FullNodeSimulator(FullNodeAPI):
    def __init__(self, full_node, bt):
        super().__init__(full_node)
        self.full_node = full_node
        self.bt = bt

    async def get_all_full_blocks(self) -> List[FullBlock]:
        peak: Optional[SubBlockRecord] = self.full_node.blockchain.get_peak()
        if peak is None:
            return []
        blocks = []
        peak_block = await self.full_node.blockchain.get_full_block(peak.header_hash)
        blocks.append(peak_block)
        current = peak_block
        while True:
            prev = await self.full_node.blockchain.get_full_block(current.prev_header_hash)
            if prev is not None:
                current = prev
                blocks.append(prev)
            else:
                break

        blocks.reverse()
        return blocks

    @api_request
    async def farm_new_block(self, request: FarmNewBlockProtocol):
        self.log.info("Farming new block!")
        current_blocks = await self.get_all_full_blocks()
        if len(current_blocks) == 0:
            genesis = bt.get_consecutive_blocks(1, force_overflow=True)[0]
            await self.full_node.blockchain.receive_block(genesis)

        peak = self.full_node.blockchain.get_peak()
        bundle: Optional[SpendBundle] = await self.full_node.mempool_manager.create_bundle_from_mempool(peak.header_hash)
        current_blocks = await self.get_all_full_blocks()
        target = request.puzzle_hash
        more = bt.get_consecutive_blocks(1, transaction_data=bundle,
                                         farmer_reward_puzzle_hash=target,
                                         pool_reward_puzzle_hash=target,
                                         block_list_input=current_blocks,
                                         force_overflow=True,
                                         guarantee_block=True)
        rr = RespondSubBlock(more[-1])
        await self.respond_sub_block(rr)