import asyncio

import pytest

from src.rpc.farmer_rpc_server import start_farmer_rpc_server
from src.rpc.harvester_rpc_server import start_harvester_rpc_server
from src.rpc.farmer_rpc_client import FarmerRpcClient
from src.rpc.harvester_rpc_client import HarvesterRpcClient
from src.util.ints import uint16
from tests.setup_nodes import setup_full_system, test_constants


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestRpc:
    @pytest.fixture(scope="function")
    async def simulation(self):
        async for _ in setup_full_system(test_constants):
            yield _

    @pytest.mark.asyncio
    async def test1(self, simulation):
        test_rpc_port = uint16(21522)
        test_rpc_port_2 = uint16(21523)
        full_node_1, _, harvester, farmer, _, _, _ = simulation

        def stop_node_cb():
            farmer.server.close_all()

        def stop_node_cb_2():
            farmer.server.close_all()

        rpc_cleanup = await start_farmer_rpc_server(farmer, stop_node_cb, test_rpc_port)
        rpc_cleanup_2 = await start_harvester_rpc_server(
            harvester, stop_node_cb_2, test_rpc_port_2
        )

        try:
            client = await FarmerRpcClient.create(test_rpc_port)
            client_2 = await HarvesterRpcClient.create(test_rpc_port_2)

            await asyncio.sleep(3)
            assert len(await client.get_connections()) == 2

            challenges = await client.get_latest_challenges()
            assert len(challenges) > 0

            res = await client_2.get_plots()
            assert len(res["plots"]) > 0
            await client_2.delete_plot(res["plots"][0]["filename"])
            res_2 = await client_2.get_plots()
            assert len(res_2["plots"]) + 1 == len(res["plots"])

        except AssertionError:
            # Checks that the RPC manages to stop the node
            client.close()
            client_2.close()
            await client.await_closed()
            await client_2.await_closed()
            await rpc_cleanup()
            await rpc_cleanup_2()
            raise

        client.close()
        client_2.close()
        await client.await_closed()
        await client_2.await_closed()
        await rpc_cleanup()
        await rpc_cleanup_2()
