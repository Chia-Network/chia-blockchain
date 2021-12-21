import asyncio
import pytest
import time
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.protocols.full_node_protocol import RespondBlock
from chia.server.server import ChiaServer
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.derive_keys import master_sk_to_wallet_sk
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_state_manager import WalletStateManager
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert, time_out_assert_not_none
from tests.wallet.cat_wallet.test_cat_wallet import tx_in_pool


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletSimulator:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}, True):
            yield _

    @pytest.fixture(scope="function")
    async def wallet_node_100_pk(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}, initial_num_public_keys=100):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}, True):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes_five_freeze(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}, True):
            yield _

    @pytest.fixture(scope="function")
    async def three_sim_two_wallets(self):
        async for _ in setup_simulators_and_wallets(3, 2, {}, True):
            yield _

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_coinbase(self, wallet_node, trusted):
        num_blocks = 10
        full_nodes, wallets = wallet_node
        full_node_api = full_nodes[0]
        server_1: ChiaServer = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id: server_1.node_id}
        else:
            wallet_node.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 2)
            ]
        )

        async def check_tx_are_pool_farm_rewards():
            wsm: WalletStateManager = wallet_node.wallet_state_manager
            all_txs = await wsm.get_all_transactions(1)
            expected_count = (num_blocks + 1) * 2
            if len(all_txs) != expected_count:
                return False
            pool_rewards = 0
            farm_rewards = 0

            for tx in all_txs:
                if tx.type == TransactionType.COINBASE_REWARD:
                    pool_rewards += 1
                elif tx.type == TransactionType.FEE_REWARD:
                    farm_rewards += 1

            if pool_rewards != expected_count / 2:
                return False
            if farm_rewards != expected_count / 2:
                return False
            return True

        await time_out_assert(10, check_tx_are_pool_farm_rewards, True)
        await time_out_assert(5, wallet.get_confirmed_balance, funds)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction(self, two_wallet_nodes, trusted):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id: server_1.node_id}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id: server_1.node_id}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(5, wallet.get_confirmed_balance, funds)
        await time_out_assert(5, wallet.get_unconfirmed_balance, funds)

        tx = await wallet.generate_signed_transaction(
            10,
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            0,
        )
        await wallet.push_transaction(tx)

        await time_out_assert(5, wallet.get_confirmed_balance, funds)
        await time_out_assert(5, wallet.get_unconfirmed_balance, funds - 10)
        await time_out_assert(5, full_node_api.full_node.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        new_funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, (2 * num_blocks))
            ]
        )

        await time_out_assert(5, wallet.get_confirmed_balance, new_funds - 10)
        await time_out_assert(5, wallet.get_unconfirmed_balance, new_funds - 10)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_coinbase_reorg(self, wallet_node, trusted):
        num_blocks = 5
        full_nodes, wallets = wallet_node
        full_node_api = full_nodes[0]
        fn_server = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {fn_server.node_id: fn_server.node_id}
        else:
            wallet_node.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(5, wallet.get_confirmed_balance, funds)

        await full_node_api.reorg_from_index_to_new_index(ReorgProtocol(uint32(2), uint32(num_blocks + 6), 32 * b"0"))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await time_out_assert(5, wallet.get_confirmed_balance, funds)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_send_to_three_peers(self, three_sim_two_wallets, trusted):
        num_blocks = 10
        full_nodes, wallets = three_sim_two_wallets

        wallet_0, wallet_server_0 = wallets[0]
        full_node_api_0 = full_nodes[0]
        full_node_api_1 = full_nodes[1]
        full_node_api_2 = full_nodes[2]

        full_node_0 = full_node_api_0.full_node
        full_node_1 = full_node_api_1.full_node
        full_node_2 = full_node_api_2.full_node

        server_0 = full_node_0.server
        server_1 = full_node_1.server
        server_2 = full_node_2.server

        ph = await wallet_0.wallet_state_manager.main_wallet.get_new_puzzlehash()
        if trusted:
            wallet_0.config["trusted_peers"] = {server_0.node_id: server_0.node_id}
        else:
            wallet_0.config["trusted_peers"] = {}

        # wallet0 <-> sever0
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)

        for i in range(0, num_blocks):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        all_blocks = await full_node_api_0.get_all_full_blocks()

        for block in all_blocks:
            await full_node_1.respond_block(RespondBlock(block))
            await full_node_2.respond_block(RespondBlock(block))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(5, wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance, funds)

        tx = await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(10, 32 * b"0", 0)
        await wallet_0.wallet_state_manager.main_wallet.push_transaction(tx)

        await time_out_assert_not_none(5, full_node_0.mempool_manager.get_spendbundle, tx.spend_bundle.name())

        # wallet0 <-> sever1
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_1._port)), wallet_0.on_connect)

        await time_out_assert_not_none(15, full_node_1.mempool_manager.get_spendbundle, tx.spend_bundle.name())

        # wallet0 <-> sever2
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_2._port)), wallet_0.on_connect)

        await time_out_assert_not_none(15, full_node_2.mempool_manager.get_spendbundle, tx.spend_bundle.name())

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction_hop(self, two_wallet_nodes_five_freeze, trusted):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes_five_freeze
        full_node_api_0 = full_nodes[0]
        full_node_0 = full_node_api_0.full_node
        server_0 = full_node_0.server

        wallet_node_0, wallet_0_server = wallets[0]
        wallet_node_1, wallet_1_server = wallets[1]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
        ph = await wallet_0.get_new_puzzlehash()
        if trusted:
            wallet_node_0.config["trusted_peers"] = {server_0.node_id: server_0.node_id}
            wallet_node_1.config["trusted_peers"] = {server_0.node_id: server_0.node_id}
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}
        await wallet_0_server.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)

        await wallet_1_server.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)

        for i in range(0, num_blocks):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(5, wallet_0.get_confirmed_balance, funds)
        await time_out_assert(5, wallet_0.get_unconfirmed_balance, funds)

        assert await wallet_0.get_confirmed_balance() == funds
        assert await wallet_0.get_unconfirmed_balance() == funds

        tx = await wallet_0.generate_signed_transaction(
            10,
            await wallet_node_1.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            0,
        )

        await wallet_0.push_transaction(tx)

        await time_out_assert(5, full_node_0.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)
        # Full node height 11, wallet height 9
        await time_out_assert(5, wallet_0.get_confirmed_balance, funds)
        await time_out_assert(5, wallet_0.get_unconfirmed_balance, funds - 10)

        for i in range(0, 4):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        # here it's num_blocks + 1 because our last reward is included in the first block that we just farmed
        new_funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        # Full node height 17, wallet height 15
        await time_out_assert(5, wallet_0.get_confirmed_balance, new_funds - 10)
        await time_out_assert(5, wallet_0.get_unconfirmed_balance, new_funds - 10)
        await time_out_assert(5, wallet_1.get_confirmed_balance, 10)

        tx = await wallet_1.generate_signed_transaction(5, await wallet_0.get_new_puzzlehash(), 0)
        await wallet_1.push_transaction(tx)
        await time_out_assert(5, full_node_0.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)

        for i in range(0, 4):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await wallet_0.get_confirmed_balance()
        await wallet_0.get_unconfirmed_balance()
        await wallet_1.get_confirmed_balance()

        await time_out_assert(5, wallet_0.get_confirmed_balance, new_funds - 5)
        await time_out_assert(5, wallet_0.get_unconfirmed_balance, new_funds - 5)
        await time_out_assert(5, wallet_1.get_confirmed_balance, 5)

    # @pytest.mark.asyncio
    # async def test_wallet_finds_full_node(self):
    #     node_iters = [
    #         setup_full_node(
    #             test_constants,
    #             "blockchain_test.db",
    #             11234,
    #             introducer_port=11236,
    #             simulator=False,
    #         ),
    #         setup_wallet_node(
    #             11235,
    #             test_constants,
    #             None,
    #             introducer_port=11236,
    #         ),
    #         setup_introducer(11236),
    #     ]
    #
    #     full_node_api = await node_iters[0].__anext__()
    #     wallet, wallet_server = await node_iters[1].__anext__()
    #     introducer, introducer_server = await node_iters[2].__anext__()
    #
    #     async def has_full_node():
    #         outbound: List[WSChiaConnection] = wallet.server.get_outgoing_connections()
    #         for connection in outbound:
    #             if connection.connection_type is NodeType.FULL_NODE:
    #                 return True
    #         return False
    #
    #     await time_out_assert(
    #         2 * 60,
    #         has_full_node,
    #         True,
    #     )
    #     await _teardown_nodes(node_iters)
    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction_with_fee(self, two_wallet_nodes, trusted):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id: full_node_1.full_node.server.node_id
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id: full_node_1.full_node.server.node_id
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_1.full_node.server._port)), None)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(5, wallet.get_confirmed_balance, funds)
        await time_out_assert(5, wallet.get_unconfirmed_balance, funds)

        assert await wallet.get_confirmed_balance() == funds
        assert await wallet.get_unconfirmed_balance() == funds
        tx_amount = 3200000000000
        tx_fee = 10
        tx = await wallet.generate_signed_transaction(
            tx_amount,
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            tx_fee,
        )

        fees = tx.spend_bundle.fees()
        assert fees == tx_fee

        await wallet.push_transaction(tx)
        await time_out_assert(5, full_node_1.full_node.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)

        await time_out_assert(5, wallet.get_confirmed_balance, funds)
        await time_out_assert(5, wallet.get_unconfirmed_balance, funds - tx_amount - tx_fee)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        new_funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        await time_out_assert(5, wallet.get_confirmed_balance, new_funds - tx_amount - tx_fee)
        await time_out_assert(5, wallet.get_unconfirmed_balance, new_funds - tx_amount - tx_fee)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_create_hit_max_send_amount(self, two_wallet_nodes, trusted):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id: full_node_1.full_node.server.node_id
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id: full_node_1.full_node.server.node_id
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_1.full_node.server._port)), None)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(5, wallet.get_confirmed_balance, funds)

        primaries = []
        for i in range(0, 600):
            primaries.append({"puzzlehash": ph, "amount": 100000000 + i})

        tx_split_coins = await wallet.generate_signed_transaction(1, ph, 0, primaries=primaries)

        await wallet.push_transaction(tx_split_coins)
        await time_out_assert(
            15, tx_in_pool, True, full_node_1.full_node.mempool_manager, tx_split_coins.spend_bundle.name()
        )
        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        await time_out_assert(90, wallet.get_confirmed_balance, funds)
        max_sent_amount = await wallet.get_max_send_amount()

        # 1) Generate transaction that is under the limit
        under_limit_tx = None
        try:
            under_limit_tx = await wallet.generate_signed_transaction(
                max_sent_amount - 1,
                ph,
                0,
            )
        except ValueError:
            assert ValueError

        assert under_limit_tx is not None

        # 2) Generate transaction that is equal to limit
        at_limit_tx = None
        try:
            at_limit_tx = await wallet.generate_signed_transaction(
                max_sent_amount,
                ph,
                0,
            )
        except ValueError:
            assert ValueError

        assert at_limit_tx is not None

        # 3) Generate transaction that is greater than limit
        above_limit_tx = None
        try:
            above_limit_tx = await wallet.generate_signed_transaction(
                max_sent_amount + 1,
                ph,
                0,
            )
        except ValueError:
            pass

        assert above_limit_tx is None

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_prevent_fee_theft(self, two_wallet_nodes, trusted):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id: full_node_1.full_node.server.node_id
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id: full_node_1.full_node.server.node_id
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_1.full_node.server._port)), None)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(5, wallet.get_confirmed_balance, funds)
        await time_out_assert(5, wallet.get_unconfirmed_balance, funds)

        assert await wallet.get_confirmed_balance() == funds
        assert await wallet.get_unconfirmed_balance() == funds
        tx_amount = 3200000000000
        tx_fee = 300000000000
        tx = await wallet.generate_signed_transaction(
            tx_amount,
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            tx_fee,
        )

        # extract coin_spend from generated spend_bundle
        for cs in tx.spend_bundle.coin_spends:
            if cs.additions() == []:
                stolen_cs = cs
        # get a legit signature
        stolen_sb = await wallet.sign_transaction([stolen_cs])
        now = uint64(int(time.time()))
        add_list = list(stolen_sb.additions())
        rem_list = list(stolen_sb.removals())
        name = stolen_sb.name()
        stolen_tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=now,
            to_puzzle_hash=32 * b"0",
            amount=0,
            fee_amount=stolen_cs.coin.amount,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=stolen_sb,
            additions=add_list,
            removals=rem_list,
            wallet_id=wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=name,
            memos=list(stolen_sb.get_memos().items()),
        )
        await wallet.push_transaction(stolen_tx)

        await time_out_assert(5, wallet.get_confirmed_balance, funds)
        await time_out_assert(5, wallet.get_unconfirmed_balance, funds - stolen_cs.coin.amount)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        # Funds have not decreased because stolen_tx was rejected
        outstanding_coinbase_rewards = 2000000000000
        await time_out_assert(20, wallet.get_confirmed_balance, funds + outstanding_coinbase_rewards)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_tx_reorg(self, two_wallet_nodes, trusted):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        fn_server = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node: WalletNode = wallet_node
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        ph2 = await wallet_2.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {fn_server.node_id: fn_server.node_id}
            wallet_node_2.config["trusted_peers"] = {fn_server.node_id: fn_server.node_id}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )
        # Waits a few seconds to receive rewards
        all_blocks = await full_node_api.get_all_full_blocks()

        # Ensure that we use a coin that we will not reorg out
        coin = list(all_blocks[-3].get_included_reward_coins())[0]
        await asyncio.sleep(5)

        tx = await wallet.generate_signed_transaction(1000, ph2, coins={coin})
        await wallet.push_transaction(tx)
        await full_node_api.full_node.respond_transaction(tx.spend_bundle, tx.name)
        await time_out_assert(5, full_node_api.full_node.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)
        await time_out_assert(5, wallet.get_confirmed_balance, funds)
        for i in range(0, 2):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))
        await time_out_assert(5, wallet_2.get_confirmed_balance, 1000)

        await time_out_assert(5, wallet_node.wallet_state_manager.blockchain.get_peak_height, 7)
        peak_height = full_node_api.full_node.blockchain.get_peak().height
        print(peak_height)

        # Perform a reorg, which will revert the transaction in the full node and wallet, and cause wallet to resubmit
        await full_node_api.reorg_from_index_to_new_index(
            ReorgProtocol(uint32(peak_height - 3), uint32(peak_height + 3), 32 * b"0")
        )

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, peak_height - 2)
            ]
        )

        await time_out_assert(7, full_node_api.full_node.blockchain.get_peak_height, peak_height + 3)
        await time_out_assert(7, wallet_node.wallet_state_manager.blockchain.get_peak_height, peak_height + 3)

        # Farm a few blocks so we can confirm the resubmitted transaction
        for i in range(0, num_blocks):
            await asyncio.sleep(1)
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        # By this point, the transaction should be confirmed
        print(await wallet.get_confirmed_balance())
        await time_out_assert(15, wallet.get_confirmed_balance, funds - 1000)
        unconfirmed = await wallet_node.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(int(wallet.id()))
        assert len(unconfirmed) == 0
        tx_record = await wallet_node.wallet_state_manager.tx_store.get_transaction_record(tx.name)
        removed = tx_record.removals[0]
        added = tx_record.additions[0]
        added_1 = tx_record.additions[1]
        wallet_coin_record_rem = await wallet_node.wallet_state_manager.coin_store.get_coin_record(removed.name())
        assert wallet_coin_record_rem.spent

        coin_record_full_node = await full_node_api.full_node.coin_store.get_coin_record(removed.name())
        assert coin_record_full_node.spent
        add_1_coin_record_full_node = await full_node_api.full_node.coin_store.get_coin_record(added.name())
        assert add_1_coin_record_full_node is not None
        assert add_1_coin_record_full_node.confirmed_block_index > 0
        add_2_coin_record_full_node = await full_node_api.full_node.coin_store.get_coin_record(added_1.name())
        assert add_2_coin_record_full_node is not None
        assert add_2_coin_record_full_node.confirmed_block_index > 0

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_address_sliding_window(self, wallet_node_100_pk, trusted):
        full_nodes, wallets = wallet_node_100_pk
        full_node_api = full_nodes[0]
        server_1: ChiaServer = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
        wallet = wallet_node.wallet_state_manager.main_wallet

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        puzzle_hashes = []
        for i in range(211):
            pubkey = master_sk_to_wallet_sk(wallet_node.wallet_state_manager.private_key, i).get_g1()
            puzzle: Program = wallet.puzzle_for_pk(bytes(pubkey))
            puzzle_hash: bytes32 = puzzle.get_tree_hash()
            puzzle_hashes.append(puzzle_hash)

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[0]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[210]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[114]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(5, wallet.get_confirmed_balance, 2 * 10 ** 12)

        # TODO: fix after merging new wallet. These 210 and 114 should be found
        # TODO: This is fixed in trusted mode, needs to work in untrusted too.
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[50]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))
        if trusted:
            await time_out_assert(15, wallet.get_confirmed_balance, 8 * 10 ** 12)
        else:
            await time_out_assert(15, wallet.get_confirmed_balance, 4 * 10 ** 12)

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[113]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[209]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))
        if trusted:
            await time_out_assert(15, wallet.get_confirmed_balance, 12 * 10 ** 12)
        else:
            await time_out_assert(15, wallet.get_confirmed_balance, 8 * 10 ** 12)
