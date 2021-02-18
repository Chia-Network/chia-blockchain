import pytest

from secrets import token_bytes
from blspy import AugSchemeMPL
from chiapos import DiskPlotter

from src.protocols import farmer_protocol
from src.rpc.farmer_rpc_client import FarmerRpcClient
from src.rpc.harvester_rpc_client import HarvesterRpcClient
from src.rpc.rpc_server import start_rpc_server
from src.util.hash import std_hash
from src.util.ints import uint16, uint64, uint8
from src.plotting.plot_tools import stream_plot_info_pk, stream_plot_info_ph
from src.rpc.farmer_rpc_api import FarmerRpcApi
from src.rpc.harvester_rpc_api import HarvesterRpcApi

from tests.setup_nodes import setup_farmer_harvester, test_constants, bt, self_hostname
from src.util.block_tools import get_plot_dir
from tests.time_out_assert import time_out_assert


class TestRpc:
    @pytest.fixture(scope="function")
    async def simulation(self):
        async for _ in setup_farmer_harvester(test_constants):
            yield _

    @pytest.mark.asyncio
    async def test1(self, simulation):
        test_rpc_port = uint16(21522)
        test_rpc_port_2 = uint16(21523)
        harvester, farmer_api = simulation

        def stop_node_cb():
            pass

        def stop_node_cb_2():
            pass

        config = bt.config
        hostname = config["self_hostname"]
        daemon_port = config["daemon_port"]

        farmer_rpc_api = FarmerRpcApi(farmer_api.farmer)
        harvester_rpc_api = HarvesterRpcApi(harvester)

        rpc_cleanup = await start_rpc_server(
            farmer_rpc_api,
            hostname,
            daemon_port,
            test_rpc_port,
            stop_node_cb,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )
        rpc_cleanup_2 = await start_rpc_server(
            harvester_rpc_api,
            hostname,
            daemon_port,
            test_rpc_port_2,
            stop_node_cb_2,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )

        try:
            client = await FarmerRpcClient.create(self_hostname, test_rpc_port, bt.root_path, config)
            client_2 = await HarvesterRpcClient.create(self_hostname, test_rpc_port_2, bt.root_path, config)

            async def have_connections():
                return len(await client.get_connections()) > 0

            await time_out_assert(15, have_connections, True)

            assert (await client.get_signage_point(std_hash(b"2"))) is None
            assert len(await client.get_signage_points()) == 0

            async def have_signage_points():
                return len(await client.get_signage_points()) > 0

            sp = farmer_protocol.NewSignagePoint(
                std_hash(b"1"), std_hash(b"2"), std_hash(b"3"), uint64(1), uint64(1000000), uint8(2)
            )
            await farmer_api.new_signage_point(sp)

            await time_out_assert(5, have_signage_points, True)
            assert (await client.get_signage_point(std_hash(b"2"))) is not None

            async def have_plots():
                return len((await client_2.get_plots())["plots"]) > 0

            await time_out_assert(5, have_plots, True)

            res = await client_2.get_plots()
            num_plots = len(res["plots"])
            assert num_plots > 0
            plot_dir = get_plot_dir() / "subdir"
            plot_dir.mkdir(parents=True, exist_ok=True)

            plot_dir_sub = get_plot_dir() / "subdir" / "subsubdir"
            plot_dir_sub.mkdir(parents=True, exist_ok=True)

            plotter = DiskPlotter()
            filename = "test_farmer_harvester_rpc_plot.plot"
            filename_2 = "test_farmer_harvester_rpc_plot2.plot"
            plotter.create_plot_disk(
                str(plot_dir),
                str(plot_dir),
                str(plot_dir),
                filename,
                18,
                stream_plot_info_pk(bt.pool_pk, bt.farmer_pk, AugSchemeMPL.key_gen(bytes([4] * 32))),
                token_bytes(32),
                128,
                0,
                2000,
                0,
                False,
            )

            # Making a plot with a puzzle hash encoded into it instead of pk
            plot_id_2 = token_bytes(32)
            plotter.create_plot_disk(
                str(plot_dir),
                str(plot_dir),
                str(plot_dir),
                filename_2,
                18,
                stream_plot_info_ph(std_hash(b"random ph"), bt.farmer_pk, AugSchemeMPL.key_gen(bytes([5] * 32))),
                plot_id_2,
                128,
                0,
                2000,
                0,
                False,
            )

            # Making the same plot, in a different dir. This should not be farmed
            plotter.create_plot_disk(
                str(plot_dir_sub),
                str(plot_dir_sub),
                str(plot_dir_sub),
                filename_2,
                18,
                stream_plot_info_ph(std_hash(b"random ph"), bt.farmer_pk, AugSchemeMPL.key_gen(bytes([5] * 32))),
                plot_id_2,
                128,
                0,
                2000,
                0,
                False,
            )

            res_2 = await client_2.get_plots()
            assert len(res_2["plots"]) == num_plots

            assert len(await client_2.get_plot_directories()) == 1

            await client_2.add_plot_directory(str(plot_dir))
            await client_2.add_plot_directory(str(plot_dir_sub))

            assert len(await client_2.get_plot_directories()) == 3

            res_2 = await client_2.get_plots()
            assert len(res_2["plots"]) == num_plots + 2

            await client_2.delete_plot(str(plot_dir / filename))
            await client_2.delete_plot(str(plot_dir / filename_2))
            res_3 = await client_2.get_plots()
            assert len(res_3["plots"]) == num_plots

            await client_2.remove_plot_directory(str(plot_dir))
            assert len(await client_2.get_plot_directories()) == 2

        finally:
            # Checks that the RPC manages to stop the node
            client.close()
            client_2.close()
            await client.await_closed()
            await client_2.await_closed()
            await rpc_cleanup()
            await rpc_cleanup_2()
