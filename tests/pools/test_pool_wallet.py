import asyncio
import logging
from typing import List

import pytest
from blspy import PrivateKey

from chia.pools.pool_wallet import PoolWallet
from chia.pools.pool_wallet_info import PoolState, FARMING_TO_POOL
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.coin_spend import CoinSpend
from chia.types.full_block import FullBlock
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32
from chia.wallet.derive_keys import master_sk_to_singleton_owner_sk
from chia.wallet.wallet_state_manager import WalletStateManager
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets


log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestPoolWallet2:
    @pytest.fixture(scope="function")
    async def one_wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.mark.asyncio
    async def test_create_new_pool_wallet(self, one_wallet_node):
        full_nodes, wallets = one_wallet_node
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, wallet_server_0 = wallets[0]
        wsm: WalletStateManager = wallet_node_0.wallet_state_manager

        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        ph = await wallet_0.get_new_puzzlehash()
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        for i in range(3):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        all_blocks: List[FullBlock] = await full_node_api.get_all_full_blocks()
        h: uint32 = all_blocks[-1].height

        await asyncio.sleep(3)
        owner_sk: PrivateKey = master_sk_to_singleton_owner_sk(wsm.private_key, 3)
        initial_state = PoolState(1, FARMING_TO_POOL, ph, owner_sk.get_g1(), "pool.com", uint32(10))
        tx_record, _, _ = await PoolWallet.create_new_pool_wallet_transaction(wsm, wallet_0, initial_state)

        launcher_spend: CoinSpend = tx_record.spend_bundle.coin_spends[1]

        async with wsm.db_wrapper.lock:
            pw = await PoolWallet.create(
                wsm, wallet_0, launcher_spend.coin.name(), tx_record.spend_bundle.coin_spends, h, True
            )

        log.warning(await pw.get_current_state())

        # Claim rewards
        # Escape pool
        # Claim rewards
        # Self pool
