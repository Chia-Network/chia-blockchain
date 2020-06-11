import asyncio
import pytest
import time
from typing import Dict, Any
from tests.setup_nodes import setup_full_system
from tests.block_tools import BlockTools
from src.consensus.constants import constants as consensus_constants
from src.util.ints import uint32

bt = BlockTools()
test_constants: Dict[str, Any] = consensus_constants.copy()
test_constants.update({"DIFFICULTY_STARTING": 500, "MIN_ITERS_STARTING": 500})

test_constants["GENESIS_BLOCK"] = bytes(
    bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestSimulation:
    @pytest.fixture(scope="function")
    async def simulation(self):
        async for _ in setup_full_system(test_constants):
            yield _

    @pytest.mark.asyncio
    async def test_simulation_1(self, simulation):
        node1, node2, _, _, _, _, _, _, _ = simulation
        start = time.time()
        # Use node2 to test node communication, since only node1 extends the chain.
        while time.time() - start < 500:
            if max([h.height for h in node2.blockchain.get_current_tips()]) > 10:
                break
            await asyncio.sleep(1)
        
        if max([h.height for h in node2.blockchain.get_current_tips()]) <= 10:
            raise Exception("Failed: could not get 10 blocks.") 

        # Wait additional 2 minutes to get a compact block.
        while time.time() - start < 620:
            max_height = node1.blockchain.lca_block.height
            for h in range(1, max_height):
                blocks_1: List[FullBlock] = await node1.block_store.get_blocks_at(
                    [uint32(h)]
                )
                blocks_2: List[FullBlock] = await node2.block_store.get_blocks_at(
                    [uint32(h)]
                )
                has_compact_1 = False
                has_compact_2 = False
                for block in blocks_1:
                    if block.proof_of_time.witness_type == 0:
                        has_compact_1 = True
                        break
                for block in blocks_2:
                    if block.proof_of_time.witness_type == 0:
                        has_compact_2 = True
                        break
                if has_compact_1 and has_compact_2:
                    return
            await asyncio.sleep(1)
        raise Exception("Failed: no block with compact proof of time.")
