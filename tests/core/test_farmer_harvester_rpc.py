import asyncio
import dataclasses
import logging
import operator
import time
from math import ceil
from os import mkdir
from pathlib import Path
from shutil import copy
from typing import Any, Awaitable, Callable, Dict, List, Union, cast

import pytest
import pytest_asyncio
from aiohttp import ClientResponseError

from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.plot_sync.receiver import Receiver
from chia.plotting.util import add_plot_directory
from chia.protocols import farmer_protocol
from chia.protocols.harvester_protocol import Plot
from chia.rpc.farmer_rpc_api import (
    FilterItem,
    PaginatedRequestData,
    PlotInfoRequestData,
    PlotPathRequestData,
    plot_matches_filter,
)
from chia.rpc.farmer_rpc_client import FarmerRpcClient
from chia.rpc.harvester_rpc_client import HarvesterRpcClient
from chia.simulator.block_tools import get_plot_dir
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_custom_interval
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config, lock_and_load_config, save_config
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64
from chia.util.misc import get_list_or_len
from chia.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_wallet_sk_unhardened
from tests.plot_sync.test_delta import dummy_plot
from tests.util.misc import assert_rpc_error
from tests.util.rpc import validate_get_routes

log = logging.getLogger(__name__)


async def wait_for_plot_sync(receiver: Receiver, previous_last_sync_id: uint64) -> None:
    def wait():
        current_last_sync_id = receiver.last_sync().sync_id
        return current_last_sync_id != 0 and current_last_sync_id != previous_last_sync_id

    await time_out_assert(30, wait)


@pytest_asyncio.fixture(scope="function")
async def harvester_farmer_environment(farmer_one_harvester, self_hostname):
    harvesters, farmer_service, bt = farmer_one_harvester
    harvester_service = harvesters[0]

    farmer_rpc_cl = await FarmerRpcClient.create(
        self_hostname, farmer_service.rpc_server.listen_port, farmer_service.root_path, farmer_service.config
    )
    harvester_rpc_cl = await HarvesterRpcClient.create(
        self_hostname, harvester_service.rpc_server.listen_port, harvester_service.root_path, harvester_service.config
    )

    async def have_connections():
        return len(await farmer_rpc_cl.get_connections()) > 0

    await time_out_assert(15, have_connections, True)

    yield farmer_service, farmer_rpc_cl, harvester_service, harvester_rpc_cl, bt

    farmer_rpc_cl.close()
    harvester_rpc_cl.close()
    await farmer_rpc_cl.await_closed()
    await harvester_rpc_cl.await_closed()


@pytest.mark.parametrize(
    "endpoint, filtering, sort_key, reverse, expected_plot_count",
    [
        (FarmerRpcClient.get_harvester_plots_valid, [], "filename", False, 20),
        (FarmerRpcClient.get_harvester_plots_valid, [], "size", True, 20),
        (
            FarmerRpcClient.get_harvester_plots_valid,
            [FilterItem("pool_contract_puzzle_hash", None)],
            "file_size",
            True,
            15,
        ),
        (
            FarmerRpcClient.get_harvester_plots_valid,
            [FilterItem("size", "20"), FilterItem("filename", "81")],
            "plot_id",
            False,
            4,
        ),
        (FarmerRpcClient.get_harvester_plots_invalid, [], None, True, 13),
        (FarmerRpcClient.get_harvester_plots_invalid, ["invalid_0"], None, False, 6),
        (FarmerRpcClient.get_harvester_plots_invalid, ["inval", "lid_1"], None, False, 2),
        (FarmerRpcClient.get_harvester_plots_keys_missing, [], None, True, 3),
        (FarmerRpcClient.get_harvester_plots_keys_missing, ["keys_missing_1"], None, False, 2),
        (FarmerRpcClient.get_harvester_plots_duplicates, [], None, True, 7),
        (FarmerRpcClient.get_harvester_plots_duplicates, ["duplicates_0"], None, False, 3),
    ],
)
@pytest.mark.asyncio
async def test_farmer_get_harvester_plots_endpoints(
    harvester_farmer_environment: Any,
    endpoint: Callable[[FarmerRpcClient, PaginatedRequestData], Awaitable[Dict[str, Any]]],
    filtering: Union[List[FilterItem], List[str]],
    sort_key: str,
    reverse: bool,
    expected_plot_count: int,
) -> None:
    (
        farmer_service,
        farmer_rpc_client,
        harvester_service,
        harvester_rpc_client,
        _,
    ) = harvester_farmer_environment

    harvester = harvester_service._node
    harvester_id = harvester_service._server.node_id
    receiver = farmer_service._api.farmer.plot_sync_receivers[harvester_id]

    if receiver.initial_sync():
        await wait_for_plot_sync(receiver, receiver.last_sync().sync_id)

    try:
        log.warning(f"harvester_rpc healthz: {await harvester_rpc_client.fetch('healthz', {})}")
        log.warning(f"harvester_rpc plots {len((await harvester_rpc_client.fetch('get_plots', {}))['plots'])}")
    except ClientResponseError:
        log.warning(
            f"Ports: farmer_rpc: {farmer_service.rpc_server.listen_port} harvester_rpc: {harvester_service.rpc_server.listen_port}"
        )
        await asyncio.sleep(10)
        log.warning("Slept 10. Trying the other one")
        log.warning(f"farmer_rpc healthz: {await farmer_rpc_client.fetch('healthz', {})}")
        log.warning(f"farmer_rpc plots {len((await farmer_rpc_client.fetch('get_plots', {}))['plots'])}")
        log.warning("Succeesfully fetched plots from farmer")
        raise ValueError("SUccess")
    # plots = []
    #
    # request: PaginatedRequestData
    # if endpoint == FarmerRpcClient.get_harvester_plots_valid:
    #     request = PlotInfoRequestData(
    #         harvester_id, uint32(0), uint32(0), cast(List[FilterItem], filtering), sort_key, reverse
    #     )
    # else:
    #     request = PlotPathRequestData(harvester_id, uint32(0), uint32(0), cast(List[str], filtering), reverse)
    #
    # def add_plot_directories(prefix: str, count: int) -> List[Path]:
    #     new_paths = []
    #     for i in range(count):
    #         new_paths.append(harvester.root_path / f"{prefix}_{i}")
    #         mkdir(new_paths[-1])
    #         add_plot_directory(harvester.root_path, str(new_paths[-1]))
    #     return new_paths
    #
    # # Generate the plot data and
    # if endpoint == FarmerRpcClient.get_harvester_plots_valid:
    #     plots = harvester_plots
    # elif endpoint == FarmerRpcClient.get_harvester_plots_invalid:
    #     invalid_paths = add_plot_directories("invalid", 3)
    #     for dir_index, r in [(0, range(0, 6)), (1, range(6, 8)), (2, range(8, 13))]:
    #         plots += [str(invalid_paths[dir_index] / f"{i}.plot") for i in r]
    #     for plot in plots:
    #         with open(plot, "w"):
    #             pass
    # elif endpoint == FarmerRpcClient.get_harvester_plots_keys_missing:
    #     keys_missing_plots = [path for path in (Path(get_plot_dir()) / "not_in_keychain").iterdir() if path.is_file()]
    #     keys_missing_paths = add_plot_directories("keys_missing", 2)
    #     for dir_index, copy_plots in [(0, keys_missing_plots[:1]), (1, keys_missing_plots[1:3])]:
    #         for plot in copy_plots:
    #             copy(plot, keys_missing_paths[dir_index])
    #             plots.append(str(keys_missing_paths[dir_index] / plot.name))
    #
    # elif endpoint == FarmerRpcClient.get_harvester_plots_duplicates:
    #     duplicate_paths = add_plot_directories("duplicates", 2)
    #     for dir_index, r in [(0, range(0, 3)), (1, range(3, 7))]:
    #         for i in r:
    #             plot_path = Path(harvester_plots[i]["filename"])
    #             plots.append(str(duplicate_paths[dir_index] / plot_path.name))
    #             copy(plot_path, plots[-1])
    #
    # # Sort and filter the data
    # if endpoint == FarmerRpcClient.get_harvester_plots_valid:
    #     for filter_item in filtering:
    #         assert isinstance(filter_item, FilterItem)
    #         plots = [plot for plot in plots if plot_matches_filter(Plot.from_json_dict(plot), filter_item)]
    #     plots.sort(key=operator.itemgetter(sort_key, "plot_id"), reverse=reverse)
    # else:
    #     for filter_item in filtering:
    #         plots = [plot for plot in plots if filter_item in plot]
    #     plots.sort(reverse=reverse)
    #
    # total_count = len(plots)
    # assert total_count == expected_plot_count
    #
    # last_sync_id = receiver.last_sync().sync_id
    #
    # harvester.plot_manager.trigger_refresh()
    # harvester.plot_manager.start_refreshing()
    #
    # await wait_for_plot_sync(receiver, last_sync_id)
    #
    # for page_size in [1, int(total_count / 2), total_count - 1, total_count, total_count + 1, 100]:
    #     request = dataclasses.replace(request, page_size=uint32(page_size))
    #     expected_page_count = ceil(total_count / page_size)
    #     for page in range(expected_page_count):
    #         request = dataclasses.replace(request, page=uint32(page))
    #         page_result = await endpoint(farmer_rpc_client, request)
    #         offset = page * page_size
    #         expected_plots = plots[offset : offset + page_size]
    #         assert page_result == {
    #             "success": True,
    #             "node_id": harvester_id.hex(),
    #             "page": page,
    #             "page_count": expected_page_count,
    #             "total_count": total_count,
    #             "plots": expected_plots,
    #         }
