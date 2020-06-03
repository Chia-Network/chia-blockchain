import asyncio
import pytest
import time
from typing import Dict, Any
from tests.setup_nodes import setup_full_system
from tests.block_tools import BlockTools
from src.consensus.constants import constants as consensus_constants

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
        node1, node2, _, _, _, _, _ = simulation
        start = time.time()
        while time.time() - start < 500:
            if max([h.height for h in node1.blockchain.get_current_tips()]) > 10:
                return
            await asyncio.sleep(1)
        raise Exception("Failed due to timeout")
