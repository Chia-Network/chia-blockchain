from typing import AsyncGenerator, List, Optional

from src.consensus.sub_block_record import SubBlockRecord
from src.full_node.full_node_api import FullNodeAPI
from src.protocols.full_node_protocol import RespondSubBlock
from src.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from src.server.outbound_message import OutboundMessage
from src.types.full_block import FullBlock
from src.types.spend_bundle import SpendBundle

from src.util.api_decorators import api_request
from src.util.ints import uint8

OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]


class FullNodeSimulator(FullNodeAPI):
    def __init__(self, full_node, block_tools):
        super().__init__(full_node)
        self.bt = block_tools
        self.full_node = full_node

    async def get_all_full_blocks(self) -> List[FullBlock]:
        peak: Optional[SubBlockRecord] = self.full_node.blockchain.get_peak()
        if peak is None:
            return []
        blocks = []
        peak_block = await self.full_node.blockchain.get_full_block(peak.header_hash)
        if peak_block is None:
            return []
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
            genesis = self.bt.get_consecutive_blocks(uint8(1))[0]
            await self.full_node.blockchain.receive_block(genesis)

        peak = self.full_node.blockchain.get_peak()
        assert peak is not None
        bundle: Optional[SpendBundle] = await self.full_node.mempool_manager.create_bundle_from_mempool(
            peak.header_hash
        )
        current_blocks = await self.get_all_full_blocks()
        target = request.puzzle_hash
        more = self.bt.get_consecutive_blocks(
            1,
            transaction_data=bundle,
            farmer_reward_puzzle_hash=target,
            pool_reward_puzzle_hash=target,
            block_list_input=current_blocks,
            force_overflow=True,
            guarantee_block=True,
        )
        rr = RespondSubBlock(more[-1])
        await self.full_node.respond_sub_block(rr)

    @api_request
    async def reorg_from_index_to_new_index(self, request: ReorgProtocol):
        new_index = request.new_index
        old_index = request.old_index
        coinbase_ph = request.puzzle_hash

        current_blocks = await self.get_all_full_blocks()
        block_count = new_index - old_index

        more_blocks = self.bt.get_consecutive_blocks(
            block_count,
            farmer_reward_puzzle_hash=coinbase_ph,
            pool_reward_puzzle_hash=coinbase_ph,
            block_list_input=current_blocks[:old_index],
            force_overflow=True,
            guarantee_block=True,
            seed=32 * b"1",
        )

        for block in more_blocks:
            await self.full_node.respond_sub_block(RespondSubBlock(block))
