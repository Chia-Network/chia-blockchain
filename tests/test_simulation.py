import asyncio
import pytest
from tests.setup_nodes import setup_full_system


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestSimulation:
    @pytest.fixture(scope="function")
    async def simulation(self):
        async for _ in setup_full_system({"DIFFICULTY_STARTING": 1}):
            yield _

    @pytest.mark.asyncio
    async def test_simulation_1(self, simulation):
        node1, node2 = simulation
        await asyncio.sleep(60)
        tip_heights = [t.height for t in node1.blockchain.get_tips()]
        assert max(tip_heights) > 5
