from secrets import token_bytes

import pytest
from blspy import AugSchemeMPL
from chiapos import DiskPlotter

from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.plotting.plot_tools import stream_plot_info_ph, stream_plot_info_pk
from chia.protocols import farmer_protocol
from chia.rpc.farmer_rpc_api import FarmerRpcApi
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.harvester_rpc_api import HarvesterRpcApi
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.rpc.rpc_server import start_rpc_server
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.block_tools import get_plot_dir
from chia.util.config import load_config
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.wallet.derive_keys import master_sk_to_wallet_sk
from tests.setup_nodes import bt, self_hostname, setup_farmer_harvester, test_constants
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

            targets_1 = await client.get_reward_targets(False)
            assert "have_pool_sk" not in targets_1
            assert "have_farmer_sk" not in targets_1
            targets_2 = await client.get_reward_targets(True)
            assert targets_2["have_pool_sk"] and targets_2["have_farmer_sk"]

            new_ph: bytes32 = create_puzzlehash_for_pk(master_sk_to_wallet_sk(bt.farmer_master_sk, uint32(10)).get_g1())
            new_ph_2: bytes32 = create_puzzlehash_for_pk(
                master_sk_to_wallet_sk(bt.pool_master_sk, uint32(472)).get_g1()
            )

            await client.set_reward_targets(encode_puzzle_hash(new_ph, "xch"), encode_puzzle_hash(new_ph_2, "xch"))
            targets_3 = await client.get_reward_targets(True)
            assert decode_puzzle_hash(targets_3["farmer_target"]) == new_ph
            assert decode_puzzle_hash(targets_3["pool_target"]) == new_ph_2
            assert targets_3["have_pool_sk"] and targets_3["have_farmer_sk"]

            new_ph_3: bytes32 = create_puzzlehash_for_pk(
                master_sk_to_wallet_sk(bt.pool_master_sk, uint32(1888)).get_g1()
            )
            await client.set_reward_targets(None, encode_puzzle_hash(new_ph_3, "xch"))
            targets_4 = await client.get_reward_targets(True)
            assert decode_puzzle_hash(targets_4["farmer_target"]) == new_ph
            assert decode_puzzle_hash(targets_4["pool_target"]) == new_ph_3
            assert not targets_4["have_pool_sk"] and targets_3["have_farmer_sk"]

            root_path = farmer_api.farmer._root_path
            config = load_config(root_path, "config.yaml")
            assert config["farmer"]["xch_target_address"] == encode_puzzle_hash(new_ph, "xch")
            assert config["pool"]["xch_target_address"] == encode_puzzle_hash(new_ph_3, "xch")

            new_ph_3_encoded = encode_puzzle_hash(new_ph_3, "xch")
            added_char = new_ph_3_encoded + "a"
            with pytest.raises(ValueError):
                await client.set_reward_targets(None, added_char)

            replaced_char = new_ph_3_encoded[0:-1] + "a"
            with pytest.raises(ValueError):
                await client.set_reward_targets(None, replaced_char)

        finally:
            # Checks that the RPC manages to stop the node
            client.close()
            client_2.close()
            await client.await_closed()
            await client_2.await_closed()
            await rpc_cleanup()
            await rpc_cleanup_2()
