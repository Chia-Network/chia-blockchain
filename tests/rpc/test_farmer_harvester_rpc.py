import asyncio

import pytest

from src.rpc.farmer_rpc_api import FarmerRpcApi
from src.rpc.harvester_rpc_api import HarvesterRpcApi
from blspy import PrivateKey
from chiapos import DiskPlotter
from src.types.proof_of_space import ProofOfSpace
from src.rpc.farmer_rpc_client import FarmerRpcClient
from src.rpc.harvester_rpc_client import HarvesterRpcClient
from src.rpc.rpc_server import start_rpc_server
from src.util.ints import uint16
from tests.setup_nodes import setup_farmer_harvester, test_constants
from tests.block_tools import get_plot_dir
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestRpc:
    @pytest.fixture(scope="function")
    async def simulation(self):
        async for _ in setup_farmer_harvester(test_constants):
            yield _

    @pytest.mark.asyncio
    async def test1(self, simulation):
        test_rpc_port = uint16(21522)
        test_rpc_port_2 = uint16(21523)
        harvester, farmer = simulation

        def stop_node_cb():
            pass

        def stop_node_cb_2():
            pass

        farmer_rpc_api = FarmerRpcApi(farmer)
        harvester_rpc_api = HarvesterRpcApi(harvester)

        rpc_cleanup = await start_rpc_server(
            farmer_rpc_api, test_rpc_port, stop_node_cb
        )
        rpc_cleanup_2 = await start_rpc_server(
            harvester_rpc_api, test_rpc_port_2, stop_node_cb_2
        )

        try:
            client = await FarmerRpcClient.create(test_rpc_port)
            client_2 = await HarvesterRpcClient.create(test_rpc_port_2)

            async def have_connections():
                return len(await client.get_connections()) > 0

            await time_out_assert(5, have_connections, True)

            challenges = await client.get_latest_challenges()

            async def have_challenges():
                return len(await client.get_latest_challenges()) > 0

            await time_out_assert(5, have_challenges, True)

            res = await client_2.get_plots()
            num_plots = len(res["plots"])
            assert num_plots > 0
            plot_dir = get_plot_dir()
            plotter = DiskPlotter()
            pool_pk = harvester.pool_pubkeys[0]
            plot_sk = PrivateKey.from_seed(b"Farmer harvester rpc test seed")
            plot_seed = ProofOfSpace.calculate_plot_seed(
                pool_pk, plot_sk.get_public_key()
            )
            filename = "test_farmer_harvester_rpc_plot.dat"
            plotter.create_plot_disk(
                str(plot_dir),
                str(plot_dir),
                str(plot_dir),
                filename,
                18,
                b"genesis",
                plot_seed,
                128,
            )
            await client_2.add_plot(str(plot_dir / filename), plot_sk)

            res_2 = await client_2.get_plots()
            assert len(res_2["plots"]) == num_plots + 1

            await client_2.delete_plot(str(plot_dir / filename))
            res_3 = await client_2.get_plots()
            assert len(res_3["plots"]) == num_plots

            filename = "test_farmer_harvester_rpc_plot_2.dat"
            plotter.create_plot_disk(
                str(plot_dir),
                str(plot_dir),
                str(plot_dir),
                filename,
                18,
                b"genesis",
                plot_seed,
                128,
            )
            await client_2.add_plot(str(plot_dir / filename), plot_sk, pool_pk)
            assert len((await client_2.get_plots())["plots"]) == num_plots + 1
            await client_2.delete_plot(str(plot_dir / filename))
            assert len((await client_2.get_plots())["plots"]) == num_plots

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
