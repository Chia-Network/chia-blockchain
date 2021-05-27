import asyncio
import logging
from typing import Dict, Optional

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.full_node_api import FullNodeAPI
from chia.pools.pool_wallet_info import SELF_POOLING
from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.sized_bytes import bytes32

from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint16, uint32
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets, bt
from tests.time_out_assert import time_out_assert


log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestPoolWalletRpc:
    @pytest.fixture(scope="function")
    async def one_wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    async def get_total_block_rewards(self, num_blocks):
        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )
        return funds

    async def farm_blocks(self, full_node_api, ph: bytes32, num_blocks: int):
        for i in range(num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        return num_blocks
        # TODO also return calculated block rewards

    @pytest.mark.asyncio
    async def test_create_new_pool_wallet(self, one_wallet_node):
        num_blocks = 4  # Num blocks to farm at a time
        total_blocks = 0  # Total blocks farmed so far
        full_nodes, wallets = one_wallet_node
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, wallet_server_0 = wallets[0]

        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        ph = await wallet_0.get_new_puzzlehash()

        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        api_user = WalletRpcApi(wallet_node_0)
        config = bt.config
        hostname = config["self_hostname"]
        daemon_port = config["daemon_port"]
        test_rpc_port = uint16(21529)

        rpc_cleanup = await start_rpc_server(
            api_user,
            hostname,
            daemon_port,
            test_rpc_port,
            lambda x: None,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )
        client = await WalletRpcClient.create(self_hostname, test_rpc_port, bt.root_path, config)

        try:
            total_blocks += await self.farm_blocks(full_node_api, ph, num_blocks)
            total_block_rewards = await self.get_total_block_rewards(total_blocks)

            await time_out_assert(10, wallet_0.get_unconfirmed_balance, total_block_rewards)
            await time_out_assert(10, wallet_0.get_confirmed_balance, total_block_rewards)
            await time_out_assert(10, wallet_0.get_spendable_balance, total_block_rewards)
            assert total_block_rewards > 0

            summaries_response = await client.get_wallets()
            for summary in summaries_response:
                if WalletType(int(summary["type"])) == WalletType.POOLING_WALLET:
                    assert False

            creation_tx: TransactionRecord = await client.create_new_pool_wallet(
                ph, "", 0, "localhost:5000", "new", "SELF_POOLING"
            )

            await time_out_assert(
                10,
                full_node_api.full_node.mempool_manager.get_spendbundle,
                creation_tx.spend_bundle,
                creation_tx.name,
            )

            await self.farm_blocks(full_node_api, ph, 3)
            assert full_node_api.full_node.mempool_manager.get_spendbundle(creation_tx.name) is None

            summaries_response = await client.get_wallets()
            wallet_id: Optional[int] = None
            for summary in summaries_response:
                if WalletType(int(summary["type"])) == WalletType.POOLING_WALLET:
                    wallet_id = summary["id"]
            assert wallet_id is not None

            status: Dict = await client.pw_status(wallet_id)
            log.warning(f"New status: {status}")

            # log.warning(f"Reponse: {val}")
            #
            # assert isinstance(val, dict)
            # assert val["success"]
            # assert val["wallet_id"] == 2
            # assert val["type"] == WalletType.POOLING_WALLET.value
            # log.warning(f"Current stat: {val['current_state']}")
            #
            # assert val["target_state"]["state"] == SELF_POOLING.value
            #
            # assert val["current_state"] == {
            #     "owner_pubkey": "0x844ab45b6bb8e674c8452de2a018209cf8a05ee25782fd12c6a202ffd953a28caa560f20a3838d4f31a1ad4fed573e94",
            #     "pool_url": None,
            #     "relative_lock_height": 0,
            #     "state": 1,
            #     "target_puzzle_hash": "0x738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7",
            #     "version": 1,
            # }
            # # TODO: Put the p2_puzzle_hash in the config for the plotter
            #
            # status: Dict = await client.pw_status(2)
            # log.warning(f"Initial staus: {status}")
            # await asyncio.sleep(2)
            # assert (
            #     full_node_api.full_node.mempool_manager.get_mempool_item(
            #         bytes32(hexstr_to_bytes(val["pending_transaction_id"]))
            #     )
            #     is not None
            # )

        finally:
            client.close()
            await client.await_closed()
            await rpc_cleanup()

    @pytest.mark.asyncio
    async def test_self_pooling_to_pooling(self, two_wallet_nodes):
        num_blocks = 4  # Num blocks to farm at a time
        total_blocks = 0  # Total blocks farmed so far
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, wallet_server_0 = wallets[0]
        pool_wallet_node, pool_wallet_server = wallets[1]

        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        pool_wallet = pool_wallet_node.wallet_state_manager.main_wallet
        our_ph = await wallet_0.get_new_puzzlehash()
        pool_ph = await pool_wallet.get_new_puzzlehash()

        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        total_blocks += await self.farm_blocks(full_node_api, our_ph, num_blocks)
        total_block_rewards = await self.get_total_block_rewards(total_blocks)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, total_block_rewards)
        await time_out_assert(10, wallet_0.get_confirmed_balance, total_block_rewards)
        await time_out_assert(10, wallet_0.get_spendable_balance, total_block_rewards)
        assert total_block_rewards > 0
        print(f"total_block_rewards: {total_block_rewards}")
        wallet_initial_confirmed_balance = await wallet_0.get_confirmed_balance()
        print(f"wallet_initial_confirmed_balance: {wallet_initial_confirmed_balance}")

        api_user = WalletRpcApi(wallet_node_0)
        our_address = our_ph
        initial_state = {
            "state": "SELF_POOLING",
            "target_puzzlehash": our_address.hex(),
            "pool_url": None,
            "relative_lock_height": 0,
        }
        val = await api_user.create_new_wallet(
            {
                "wallet_type": "pool_wallet",
                "mode": "new",
                "initial_target_state": initial_state,
                "host": f"{self_hostname}:5000",
            }
        )
        assert isinstance(val, dict)
        if "success" in val:
            assert val["success"]

        val2 = await api_user.pw_join_pool(
            {
                "wallet_id": val["wallet_id"],
                "pool_url": "https://pool.example.com",
                "relative_lock_height": 10,
                "target_puzzlehash": pool_ph.hex(),
                "host": f"{self_hostname}:5000",
            }
        )

        print(val2["pool_wallet_state"])

        correct_dict = {
            "current": {
                "version": 1,
                "state": 1,
                "target_puzzlehash": "0x738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7",
                "owner_pubkey": "0x844ab45b6bb8e674c8452de2a018209cf8a05ee25782fd12c6a202ffd953a28caa560f20a3838d4f31a1ad4fed573e94",
                "pool_url": None,
                "relative_lock_height": 0,
            },
            "target": {
                "version": 1,
                "state": 2,
                "target_puzzlehash": "0x738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7",
                "owner_pubkey": "0x844ab45b6bb8e674c8452de2a018209cf8a05ee25782fd12c6a202ffd953a28caa560f20a3838d4f31a1ad4fed573e94",
                "pool_url": None,
                "relative_lock_height": 0,
            },
            "pending_transaction": {
                "confirmed_at_height": 0,
                "created_at_time": 1622005799,
                "to_puzzle_hash": "0x924175b2583440413221321541e672989fe6d201ee0643d945b6679671f20d74",
                "amount": 1,
                "fee_amount": 0,
                "confirmed": False,
                "sent": 0,
                "spend_bundle": {
                    "coin_solutions": [
                        {
                            "coin": {
                                "parent_coin_info": "0xe3b0c44298fc1c149afbf4c8996fb92400000000000000000000000000000002",
                                "puzzle_hash": "0xeb03d4dd0d9a6a2cd28bbf944d19d5e733b3b7889e4e23e4fb3e91634ed76e05",
                                "amount": 1750000000000,
                            },
                            "puzzle_reveal": "0xff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a4687664078102d42fb49d2ece6f134069aaeb7fa87eee6ef9e3b77a4d8abad6f8b75981ba97c4d687830626380f1c3eff018080",
                            "solution": "0xff80ffff01ffff33ffa0879d46938cfe331fb3cb1ea7ac5abde72e17041a0a2208549dfac1cb18d2e073ff0180ffff33ffa086cfe5abf131b272bbaed6bdec78cabb17a15ed5522a0a96bf5aa6963c2e9533ff8601977420dbff80ffff3cffa0c642b129a76a02d2ec0a710bd1092a0f2dbada4cb874ab57c7ebde0ad48ee20380ffff3dffa0b6be54edeb996a151e19dcb2e2ab28f62070c03d3644993350bf6a453d0fa3ac8080ff8080",
                        },
                        {
                            "coin": {
                                "parent_coin_info": "0x9f2f042d178394772aa485bc59254174fceb78d111db98bb77b821c222118183",
                                "puzzle_hash": "0x924175b2583440413221321541e672989fe6d201ee0643d945b6679671f20d74",
                                "amount": 1,
                            },
                            "puzzle_reveal": "0xff02ffff01ff02ffff01ff02ff38ffff04ff02ffff04ff05ffff04ffff0bffff0101ff0580ffff04ff0bffff04ff2fffff04ffff02ff36ffff04ff02ffff04ff17ff80808080ffff04ff5fffff04ffff02ff17ffff04ffff04ff0bffff04ffff02ffff03ff81efffff0182016fff8080ff0180ff808080ff81bf8080ff80808080808080808080ffff04ffff01ffffff46ff33ff04ffff02ff34ffff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff5fffff04ff2fffff04ff81bfff808080808080808080ffff02ff2cffff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff82017fffff01ff80ff808080808080808080ffffff02ffff03ffff09ff0bffff0bff05ff26ff178080ffff01ff04ff10ffff04ffff0bff0bff2fff5f80ff808080ffff01ff08ff0bffff0bff05ff26ff17808080ff0180ff02ffff03ffff18ff81bfffff010180ffff01ff02ffff03ff8201dfffff01ff04ff10ffff04ffff0bffff0bff819fffff02ff2effff04ff02ffff04ffff02ff3cffff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff82015fff80808080808080ffff04ff05ffff04ff0bffff04ff82015fff80808080808080ff8202df80ffff02ff2effff04ff02ffff04ffff02ff3cffff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff2fff80808080808080ffff04ff05ffff04ff0bffff04ff2fff80808080808080ff81bf80ff808080ffff01ff02ff24ffff04ff02ffff04ff819fffff04ff17ffff04ff82015fffff04ffff02ff2effff04ff02ffff04ffff02ff3cffff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff2fff80808080808080ffff04ff05ffff04ff0bffff04ff2fff80808080808080ffff04ff81bfff808080808080808080ff0180ffff01ff088080ff0180ffff02ffff03ff2fffff01ff02ffff03ffff09ff818fff2880ffff01ff02ffff03ffff18ff8202cfffff010180ffff01ff02ffff03ffff09ff5fffff010280ffff01ff02ff2cffff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff6fffff04ffff0102ffff04ffff04ff4fff81bf80ff808080808080808080ffff01ff02ffff03ffff09ff8202cfffff0182fac780ffff01ff02ff2cffff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff6fffff04ffff0102ffff04ff81bfff808080808080808080ffff01ff02ffff03ff5fffff01ff0880ffff01ff02ff2cffff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff6fffff04ffff0101ffff04ffff04ffff04ff28ffff04ffff02ff2effff04ff02ffff04ffff02ff3cffff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff82014fff80808080808080ffff04ff05ffff04ff0bffff04ff82014fff80808080808080ffff04ff8202cfff80808080ff81bf80ff80808080808080808080ff018080ff018080ff0180ffff01ff02ff2cffff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff6fffff04ff5fffff04ffff04ff4fff81bf80ff80808080808080808080ff0180ffff01ff02ff2cffff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff6fffff04ff5fffff04ffff04ff4fff81bf80ff80808080808080808080ff0180ffff01ff02ffff03ff5fffff0181bfffff01ff088080ff018080ff0180ff02ff12ffff04ff02ffff04ff05ffff04ff07ff8080808080ffffff04ffff0102ffff04ffff04ffff0101ff0580ffff04ffff02ff2affff04ff02ffff04ff0bffff01ff0180808080ff80808080ffff02ffff03ff05ffff01ff04ffff0104ffff04ffff04ffff0101ff0980ffff04ffff02ff2affff04ff02ffff04ff0dffff04ff0bff8080808080ff80808080ffff010b80ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff05ff1380ffff01ff0101ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bff808080808080ff0180ff8080ff0180ffffa0879d46938cfe331fb3cb1ea7ac5abde72e17041a0a2208549dfac1cb18d2e073ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff36ffff04ff02ffff04ff09ff80808080ffff02ff36ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff02ff3effff04ff02ffff04ff05ffff04ff07ff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff3effff04ff02ffff04ff09ffff04ff0bff8080808080ffff02ff3effff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff02ffff03ffff02ff3affff04ff02ffff04ff05ffff04ff0bff8080808080ffff0105ffff01ff0bffff0101ff058080ff018080ff0180ff018080ffff04ffff01a06ad34a7694edf03138eb287082e317697f6db35b7bfca66baefaf7f645210695ffff04ffff01a09f2f042d178394772aa485bc59254174fceb78d111db98bb77b821c222118183ffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff8202ffffff01ff04ffff04ff10ffff04ff81bfffff01ff00808080ffff04ffff04ff34ffff04ff2fffff04ff820bffff80808080ffff04ffff04ff38ffff04ff820bffff808080ff80808080ffff01ff02ff12ffff04ff02ffff04ff05ffff04ff0bffff04ff82027fffff04ff17ffff04ff8205ffffff04ff820bffffff04ff8217ffffff04ffff0bffff19ff3cff822fff80ff5fff8217ff80ff808080808080808080808080ff0180ffff04ffff01ffffff32ff3d49ffff4833ff3ea0ccd5bb71183532bff220ba46c268991a00000000000000000000000000000000ffffff04ffff04ff34ffff04ff5fffff04ff81bfff80808080ffff04ffff04ff24ffff04ffff02ff2effff04ff02ffff04ffff02ff2affff04ff02ffff04ff05ffff04ff0bffff04ff17ffff04ff5fff80808080808080ffff04ff05ffff04ff0bffff04ff5fff80808080808080ff808080ffff04ffff04ff38ffff04ff81bfff808080ffff04ffff04ff34ffff04ff2fffff04ff82017fff80808080ffff04ffff04ff2cffff04ff8202ffff808080ffff04ffff04ff28ffff04ffff0bff8202ffffff01818080ff808080ff80808080808080ffff02ff3affff04ff02ffff04ff05ffff04ff07ff8080808080ff04ffff0102ffff04ffff04ffff0101ff0580ffff04ffff02ff26ffff04ff02ffff04ff0bffff01ff0180808080ff80808080ffffff02ffff03ff05ffff01ff04ffff0104ffff04ffff04ffff0101ff0980ffff04ffff02ff26ffff04ff02ffff04ff0dffff04ff0bff8080808080ff80808080ffff010b80ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff05ff1380ffff01ff0101ffff01ff02ff36ffff04ff02ffff04ff05ffff04ff1bff808080808080ff0180ff8080ff0180ffff02ff3effff04ff02ffff04ff05ffff04ff07ff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff3effff04ff02ffff04ff09ffff04ff0bff8080808080ffff02ff3effff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff02ffff03ffff02ff36ffff04ff02ffff04ff05ffff04ff0bff8080808080ffff0105ffff01ff0bffff0101ff058080ff018080ff0180ff018080ffff04ffff01a0738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7ffff04ffff0180ffff04ffff01a00f4f6e42b20b11b2f75c2a0303fd3493a87135c90f631a4efa005530aa2de93affff04ffff01a05e3e887d9a8a2631aad0df4c649f3f56b383e26c0b8ea4ab59caa9850afda76cffff04ffff01b0844ab45b6bb8e674c8452de2a018209cf8a05ee25782fd12c6a202ffd953a28caa560f20a3838d4f31a1ad4fed573e94ff01808080808080ff0180808080",
                            "solution": "0xffffa0e3b0c44298fc1c149afbf4c8996fb92400000000000000000000000000000002ff8601977420dc0080ff01ffff80ffa052a2bf3773569d931f100eed839e9ed2aa91e0defa8be4499d98d4e25e15d3e3ff01ff64ff038080",
                        },
                        {
                            "coin": {
                                "parent_coin_info": "0x67674b16d39e1a78f9d33eaae434c67c8412a1b0f42c7d8bc1fbbe947d1b1ea1",
                                "puzzle_hash": "0x879d46938cfe331fb3cb1ea7ac5abde72e17041a0a2208549dfac1cb18d2e073",
                                "amount": 1,
                            },
                            "puzzle_reveal": "0xff02ffff01ff04ffff04ffff0133ffff04ff05ffff04ff0bff80808080ffff04ffff04ffff013cffff04ffff02ff02ffff04ff02ffff04ffff04ff05ffff04ff0bffff04ff17ff80808080ff80808080ff808080ff808080ffff04ffff01ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff02ffff04ff02ffff04ff09ff80808080ffff02ff02ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080",
                            "solution": "0xffa0924175b2583440413221321541e672989fe6d201ee0643d945b6679671f20d74ff01ffc080000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000080",
                        },
                    ],
                    "aggregated_signature": "0xa02365bfd8bbc2d624dc5fb2643845e425cb87e444ea508c308f6f068850e51ba556a923312c32e0aa5a2b434e009d0b0c7c465fb0cbf97425ef9eb2d5ae2f9454ad7a6f5e46e12ac96f726998c39643d13a834d784481c9f251c8544b71e607",
                },
                "additions": [
                    {
                        "parent_coin_info": "0x67674b16d39e1a78f9d33eaae434c67c8412a1b0f42c7d8bc1fbbe947d1b1ea1",
                        "puzzle_hash": "0x879d46938cfe331fb3cb1ea7ac5abde72e17041a0a2208549dfac1cb18d2e073",
                        "amount": 1,
                    },
                    {
                        "parent_coin_info": "0x67674b16d39e1a78f9d33eaae434c67c8412a1b0f42c7d8bc1fbbe947d1b1ea1",
                        "puzzle_hash": "0x86cfe5abf131b272bbaed6bdec78cabb17a15ed5522a0a96bf5aa6963c2e9533",
                        "amount": 1749999999999,
                    },
                    {
                        "parent_coin_info": "0x9f2f042d178394772aa485bc59254174fceb78d111db98bb77b821c222118183",
                        "puzzle_hash": "0x924175b2583440413221321541e672989fe6d201ee0643d945b6679671f20d74",
                        "amount": 1,
                    },
                ],
                "removals": [
                    {
                        "parent_coin_info": "0xe3b0c44298fc1c149afbf4c8996fb92400000000000000000000000000000002",
                        "puzzle_hash": "0xeb03d4dd0d9a6a2cd28bbf944d19d5e733b3b7889e4e23e4fb3e91634ed76e05",
                        "amount": 1750000000000,
                    },
                    {
                        "parent_coin_info": "0x9f2f042d178394772aa485bc59254174fceb78d111db98bb77b821c222118183",
                        "puzzle_hash": "0x924175b2583440413221321541e672989fe6d201ee0643d945b6679671f20d74",
                        "amount": 1,
                    },
                    {
                        "parent_coin_info": "0x67674b16d39e1a78f9d33eaae434c67c8412a1b0f42c7d8bc1fbbe947d1b1ea1",
                        "puzzle_hash": "0x879d46938cfe331fb3cb1ea7ac5abde72e17041a0a2208549dfac1cb18d2e073",
                        "amount": 1,
                    },
                ],
                "wallet_id": 1,
                "sent_to": [],
                "trade_id": None,
                "type": 1,
                "name": "0x46ff79a67da9c60f8531d564f8064b2c63c4bb5f44170639067d63b9b8fb6521",
            },
            "origin_coin": {
                "parent_coin_info": "0x67674b16d39e1a78f9d33eaae434c67c8412a1b0f42c7d8bc1fbbe947d1b1ea1",
                "puzzle_hash": "0x879d46938cfe331fb3cb1ea7ac5abde72e17041a0a2208549dfac1cb18d2e073",
                "amount": 1,
            },
            "launcher_id": "0x9f2f042d178394772aa485bc59254174fceb78d111db98bb77b821c222118183",
            "parent_list": [
                [
                    "0x9f2f042d178394772aa485bc59254174fceb78d111db98bb77b821c222118183",
                    {
                        "parent_name": "0x67674b16d39e1a78f9d33eaae434c67c8412a1b0f42c7d8bc1fbbe947d1b1ea1",
                        "inner_puzzle_hash": "0x879d46938cfe331fb3cb1ea7ac5abde72e17041a0a2208549dfac1cb18d2e073",
                        "amount": 1,
                    },
                ],
                [
                    "0x33c7a24db44201f5d37eb39c19bb7466a523d50fc32aac38d2d716f282aa6ad2",
                    {
                        "parent_name": "0x9f2f042d178394772aa485bc59254174fceb78d111db98bb77b821c222118183",
                        "inner_puzzle_hash": "0x52a2bf3773569d931f100eed839e9ed2aa91e0defa8be4499d98d4e25e15d3e3",
                        "amount": 1,
                    },
                ],
            ],
            "current_inner": None,
            "self_pooled_reward_list": [],
            "owner_pubkey": "0x844ab45b6bb8e674c8452de2a018209cf8a05ee25782fd12c6a202ffd953a28caa560f20a3838d4f31a1ad4fed573e94",
            "owner_pay_to_puzzlehash": "0x738127e26cb61ffe5530ce0cef02b5eeadb1264aa423e82204a6d6bf9f31c2b7",
        }

        real_dict = val2["pool_wallet_state"]

        assert real_dict["current"] == correct_dict["current"]
        assert real_dict["target"] == correct_dict["target"]
        assert real_dict["pending_transaction"] == correct_dict["pending_transaction"]
        assert real_dict == correct_dict

    # pooling -> escaping -> self pooling
    # Pool A -> Pool B
    # Recover pool wallet from genesis_id
