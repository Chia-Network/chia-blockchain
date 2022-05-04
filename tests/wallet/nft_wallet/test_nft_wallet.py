import asyncio

# pytestmark = pytest.mark.skip("TODO: Fix tests")
import logging
from tests.conftest import two_wallet_nodes

import pytest

from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from tests.time_out_assert import time_out_assert, time_out_assert_not_none

# TODO: remove me
logging.getLogger("aiosqlite").setLevel(logging.INFO)  # Too much logging on debug level
logging.getLogger("websockets").setLevel(logging.INFO)  # Too much logging on debug level
logging.getLogger("fsevents").setLevel(logging.INFO)  # Too much logging on debug level
logging.getLogger("chia.plotting.create_plots").setLevel(logging.INFO)  # Too much logging on debug level
logging.getLogger("filelock").setLevel(logging.INFO)  # Too much logging on debug level
logging.getLogger("chia.plotting").setLevel(logging.INFO)  # Too much logging on debug level
logging.getLogger("cchia.full_node.block_store").setLevel(logging.INFO)  # Too much logging on debug level

logging.getLogger("wallet_server").setLevel(logging.INFO)  # Too much logging on debug level
logging.getLogger("full_node_server").setLevel(logging.INFO)  # Too much logging on debug level


async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32):
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


class TestNFTWallet:
    @pytest.mark.parametrize(
        "trusted",
        [True],
    )
    @pytest.mark.asyncio
    async def test_nft_wallet_creation_and_transfer(self, two_wallet_nodes, trusted):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_node_1, server_1 = wallets[1]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        ph = await wallet_0.get_new_puzzlehash()
        ph1 = await wallet_1.get_new_puzzlehash()

        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_1.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        # funds = sum(
        #     [
        #         calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
        #         for i in range(1, num_blocks - 1)
        #     ]
        # )

        # await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        # await time_out_assert(10, wallet_0.get_confirmed_balance, funds)
        # for i in range(1, num_blocks):
        #     await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
        # for i in range(1, num_blocks):
        #     await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph2))

        # for i in range(1, num_blocks):
        #     await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        # await time_out_assert(15, wallet_0.get_pending_change_balance, 0)
        nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, name="NFT WALLET 1"
        )
        metadata = Program.to(
            [
                ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
                ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
            ]
        )

        tr = await nft_wallet_0.generate_new_nft(metadata)

        await time_out_assert_not_none(
            5, full_node_api.full_node.mempool_manager.get_spendbundle, tr.spend_bundle.name()
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

        await asyncio.sleep(5)
        coins = nft_wallet_0.nft_wallet_info.my_nft_coins
        assert len(coins) == 1, "nft not generated"

        nft_wallet_1 = await NFTWallet.create_new_nft_wallet(
            wallet_node_1.wallet_state_manager, wallet_1, name="NFT WALLET 2"
        )
        # nft_puzzle = await nft_wallet_1.get_new_puzzle()
        sb = await nft_wallet_0.transfer_nft(coins[0], ph1)  # nft_puzzle.get_tree_hash())

        assert sb is not None
        await asyncio.sleep(3)
        await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, sb.name())

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
        await asyncio.sleep(5)

        coins = nft_wallet_0.nft_wallet_info.my_nft_coins
        assert len(coins) == 0
        coins = nft_wallet_1.nft_wallet_info.my_nft_coins
        assert len(coins) == 1

        # Send it back to original owner
        nsb = await nft_wallet_1.transfer_nft(coins[0], ph)
        assert sb is not None

        # full_sb = await nft_wallet_0.receive_nft(nsb)
        # await nft_wallet_0.receive_nft(nsb)
        assert nsb is not None
        await asyncio.sleep(5)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

        await asyncio.sleep(5)
        coins = nft_wallet_0.nft_wallet_info.my_nft_coins
        assert len(coins) == 1

        coins = nft_wallet_1.nft_wallet_info.my_nft_coins
        assert len(coins) == 0
