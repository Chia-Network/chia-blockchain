from __future__ import annotations

import contextlib
import io
import sys
from decimal import Decimal

import pytest

from chia.cmds.coin_funcs import async_combine, async_list, async_split
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import SimulatorsAndWalletsServices
from chia.simulator.time_out_assert import time_out_assert
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint64
from chia.wallet.util.tx_config import CoinSelectionConfigLoader


def check_mempool_spend_count(full_node_api: FullNodeSimulator, num_of_spends: int) -> bool:
    return full_node_api.full_node.mempool_manager.mempool.size() == num_of_spends


@pytest.mark.asyncio
async def test_list_and_combine_and_split(one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices) -> None:
    # Wallet environment setup
    num_blocks = 1
    full_nodes, wallets, bt = one_wallet_and_one_simulator_services
    full_node_api = full_nodes[0]._api
    full_node_server = full_node_api.full_node.server
    wallet_service_0 = wallets[0]
    wallet_node_0 = wallet_service_0._node
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    assert wallet_service_0.rpc_server is not None

    wallet_node_0.config["trusted_peers"] = {
        full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
    }

    await wallet_node_0.server.start_client(PeerInfo("127.0.0.1", uint16(full_node_server._port)), None)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    assert wallet_service_0.rpc_server.webserver is not None
    fingerprint = wallet_0.wallet_state_manager.private_key.get_g1().get_fingerprint()

    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        await async_list(
            wallet_rpc_port=wallet_service_0.rpc_server.webserver.listen_port,
            fingerprint=fingerprint,
            wallet_id=wallet_0.id(),
            max_coin_amount="100",
            min_coin_amount="0",
            excluded_amounts=[],
            excluded_coin_ids=[],
            show_unconfirmed=False,
            paginate=False,
            root_path=wallet_service_0.root_path,
        )

    assert "There are a total of 2 coins in wallet 1" in f.getvalue()
    assert "2 confirmed coins" in f.getvalue()
    assert "0 unconfirmed additions" in f.getvalue()
    assert "0 unconfirmed removals" in f.getvalue()

    f.truncate(0)

    sys.stdin = io.StringIO("y")
    with contextlib.redirect_stdout(f):
        await async_combine(
            wallet_rpc_port=wallet_service_0.rpc_server.webserver.listen_port,
            fingerprint=fingerprint,
            wallet_id=wallet_0.id(),
            fee=Decimal("0.0"),
            max_coin_amount="100",
            min_coin_amount="0",
            excluded_amounts=[],
            number_of_coins=2,
            target_coin_amount=Decimal("2.0"),
            target_coin_ids_str=[],
            largest_first=True,
            root_path=wallet_service_0.root_path,
        )

    assert "Combining 2 coins" in f.getvalue()
    assert "Transaction sent" in f.getvalue()

    f.truncate(0)

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    coin_set = await wallet_0.select_coins(
        uint64(2_000_000_000_000),
        CoinSelectionConfigLoader(excluded_coin_amounts=[uint64(1_750_000_000_000), uint64(250_000_000_000)]).autofill(
            constants=DEFAULT_CONSTANTS
        ),
    )
    assert len(coin_set) == 1

    target_coin = (
        await wallet_0.select_coins(
            uint64(250_000_000_000),
            CoinSelectionConfigLoader().autofill(constants=DEFAULT_CONSTANTS),
        )
    ).pop()

    with contextlib.redirect_stdout(f):
        await async_split(
            wallet_rpc_port=wallet_service_0.rpc_server.webserver.listen_port,
            fingerprint=fingerprint,
            wallet_id=wallet_0.id(),
            fee=Decimal("0.0"),
            number_of_coins=2,
            amount_per_coin=Decimal("0.125"),
            target_coin_id_str=target_coin.name().hex(),
            root_path=wallet_service_0.root_path,
        )

    assert "Transaction sent" in f.getvalue()

    await time_out_assert(5, check_mempool_spend_count, True, full_node_api, 1)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    coin_set = await wallet_0.select_coins(
        uint64(250_000_000_000),
        CoinSelectionConfigLoader(
            excluded_coin_amounts=[uint64(1_750_000_000_000), uint64(250_000_000_000), uint64(2_000_000_000_000)]
        ).autofill(constants=DEFAULT_CONSTANTS),
    )
    assert len(coin_set) == 2
