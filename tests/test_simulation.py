import asyncio
import pytest


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestSimulation:
    @pytest.mark.asyncio
    async def test_simulation_1(self):
        db_id_1 = "1001"
        db_id_2 = "1002"
        db_id_3 = "1003"

        
