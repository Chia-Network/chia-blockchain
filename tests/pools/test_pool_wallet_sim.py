import asyncio
import pytest

# import time
# from secrets import token_bytes

# from blspy import AugSchemeMPL
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.pools.pool_wallet import PoolWallet

from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.pools.pool_wallet_info import create_pool_state, PoolSingletonState
from chia.types.blockchain_format.sized_bytes import bytes32

# from clvm_tools import binutils

from tests.setup_nodes import self_hostname
from tests.time_out_assert import time_out_assert

# from tests.wallet.cc_wallet.test_cc_wallet import tx_in_pool
from tests.setup_nodes import setup_simulators_and_wallets


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestPoolWalletSimulator:
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
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )
        return funds

    async def farm_blocks(self, full_node_api, ph, num_blocks):
        for i in range(num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        return num_blocks
        # TODO combine output block rewards

    @pytest.mark.asyncio
    async def test_pool_wallet_creation(self, one_wallet_node):
        SIM_TIMEOUT = 10
        num_blocks = 5
        full_nodes, wallets = one_wallet_node
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, wallet_server_0 = wallets[0]
        # wallet_node_1, wallet_server_1 = wallets[1]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        # wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
        total_blocks = 0

        ph = await wallet_0.get_new_puzzlehash()
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        total_blocks += await self.farm_blocks(full_node_api, ph, num_blocks)
        funds = await self.get_total_block_rewards(total_blocks)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)

        rewards_puzzlehash = bytes32(b"\x01" * 32)

        dr = await wallet_node_0.wallet_state_manager.get_unused_derivation_record(wallet_0.id())
        # initial_pool_state = create_pool_state(
        #     PoolSingletonState.PENDING_CREATION, rewards_puzzlehash, dr.pubkey, None, 0
        # )
        # pool_wallet_0: PoolWallet = await PoolWallet.create_new_pool_wallet(
        #     wallet_node_0.wallet_state_manager, wallet_0, initial_pool_state, dr.pubkey, dr.puzzle_hash
        # )
        #
        # total_blocks += await self.farm_blocks(full_node_api, ph, num_blocks)
        # funds = await self.get_total_block_rewards(total_blocks)
        # await time_out_assert(10, pool_wallet_0.get_confirmed_balance, 1)

        return
        pool_url = "https://pool.example.org/"
        relative_lock_height = 10
        pool_puzzlehash = bytes32(b"\x02" * 32)
        fee = 5
        # await pool_wallet_0.join_pool(pool_url, rewards_puzzlehash, relative_lock_height, fee)

        # Check to see if the singleton is created
        # for i in range(1, num_blocks):
        #    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        # await time_out_assert(15, pool_wallet.get_confirmed_balance, 100)

        # wallet = wallet_node.wallet_state_manager.main_wallet

        # ph = await wallet.get_new_puzzlehash()

        # XXX note running wallet_server_0.start_client down here creates indeterminism
        # await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        # for i in range(0, num_blocks):
        #    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        # pool_wallet_1: PoolWallet = await PoolWallet.create_new_pool_wallet(
        #    wallet_node_1.wallet_state_manager, wallet_1, initial_pool_state
        # )

        # interval = uint64(2)
        # limit = uint64(1)
        # amount = uint64(100)
        # await pool_wallet.admin_create_coin(interval, limit, pool_wallet.pool_info.user_pubkey.hex(), amount, 0)

        # current: PoolState
        # target: PoolState
        # pending_transaction: Optional[TransactionRecord]
        # origin_coin: Optional[Coin]  # puzzlehash of this coin is our Singleton state
        # parent_info: List[Tuple[bytes32, Optional[CCParent]]]  # {coin.name(): CCParent}
        # current_inner: Optional[Program]  # represents a Program as bytes

        # TODO: need to test recovering this information
        origin = pool_wallet_0.pool_info.origin_coin
        current_rewards_pubkey = pool_wallet_0.current_rewards_pubkey
        current_rewards_puzhash = pool_wallet_0.current_rewards_puzhash

        # pubkey = pool_wallet_0.pool_info.admin_pubkey
        print(f"origin: {origin}")

        print(f"pubkey: {current_rewards_pubkey} puzhash: {current_rewards_puzhash}")

        balance = await pool_wallet_0.get_confirmed_balance()
        assert balance == 0
        print(f"Pool wallet balance: {balance}")

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = await self.get_total_block_rewards(total_blocks)
        bal = await wallet_0.get_confirmed_balance()
        assert bal == funds - 1
        await time_out_assert(SIM_TIMEOUT, wallet_0.get_confirmed_balance, funds - 1)
        # pool_balance = await pool_wallet_0.get_confirmed_balance()
        # assert pool_balance == 1

        """
        await pool_wallet.set_user_info(
            interval,
            limit,
            origin.parent_coin_info.hex(),
            origin.puzzle_hash.hex(),
            origin.amount,
            admin_pubkey.hex(),
        )
        """

        # for i in range(0, num_blocks):
        #    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        # for i in range(0, num_blocks):
        #    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        # await time_out_assert(15, pool_wallet_0.get_confirmed_balance, 1)
        # balance = await pool_wallet.available_balance()

        # tx_record = await pool_wallet_0.generate_signed_transaction(1, 32 * b"\0")

        # await wallet_node_1.wallet_state_manager.main_wallet.push_transaction(tx_record)

        # for i in range(0, num_blocks):
        #    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        balance = await pool_wallet_0.get_confirmed_balance()
        print(f"Pool wallet balance: {balance}")

        # await time_out_assert(15, pool_wallet.get_confirmed_balance, 99)

        # pool_wallet.get_aggregation_puzzlehash(pool_wallet.get_new_puzzle())

    """
    @pytest.mark.asyncio
    async def test_wallet_xxx(self, two_wallet_nodes):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, wallet_server_0 = wallets[0]
        wallet_node_1, wallet_server_1 = wallets[1]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        ph = await wallet_0.get_new_puzzlehash()

        await wallet_server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await wallet_server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)

        current_state = PoolSingletonState.PENDING_CREATION
        target_state = PoolSingletonState.FARMING_TO_POOL
        rewards_puzzlehash = bytes32(b"\x01" * 32)

        initial_pool_state = create_pool_state(PoolSingletonState.PENDING_CREATION, rewards_puzzlehash, None, None)
        pool_wallet_0: PoolWallet = await PoolWallet.create_new_pool_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, initial_pool_state
        )

        pool_url = "https://pool.example.org/"
        relative_lock_height = 10
        pool_puzzlehash = bytes32(b"\x02" * 32)
        fee = 5
        #await pool_wallet_0.join_pool(pool_url, rewards_puzzlehash, relative_lock_height, fee)

        # Check to see if the singleton is created
        #for i in range(1, num_blocks):
        #    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        #await time_out_assert(15, pool_wallet.get_confirmed_balance, 100)

        # wallet = wallet_node.wallet_state_manager.main_wallet

        # ph = await wallet.get_new_puzzlehash()

        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        #for i in range(0, num_blocks):
        #    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))


        #pool_wallet_1: PoolWallet = await PoolWallet.create_new_pool_wallet(
        #    wallet_node_1.wallet_state_manager, wallet_1, initial_pool_state
        #)



        #interval = uint64(2)
        #limit = uint64(1)
        #amount = uint64(100)
        #await pool_wallet.admin_create_coin(interval, limit, pool_wallet.pool_info.user_pubkey.hex(), amount, 0)

        #current: PoolState
        #target: PoolState
        #pending_transaction: Optional[TransactionRecord]
        #origin_coin: Optional[Coin]  # puzzlehash of this coin is our Singleton state
        #parent_info: List[Tuple[bytes32, Optional[CCParent]]]  # {coin.name(): CCParent}
        #current_inner: Optional[Program]  # represents a Program as bytes

        # need to test recovering this information
        origin = pool_wallet_0.pool_info.origin_coin
        current_rewards_pubkey = pool_wallet_0.current_rewards_pubkey
        current_rewards_puzhash = pool_wallet_0.current_rewards_puzhash

        #pubkey = pool_wallet_0.pool_info.admin_pubkey
        print(f"origin: {origin}")

        print(f"pubkey: {current_rewards_pubkey} puzhash: {current_rewards_puzhash}")


        '''
        await pool_wallet.set_user_info(
            interval,
            limit,
            origin.parent_coin_info.hex(),
            origin.puzzle_hash.hex(),
            origin.amount,
            admin_pubkey.hex(),
        )
        '''

        #for i in range(0, num_blocks):
        #    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        #for i in range(0, num_blocks):
        #    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        #await time_out_assert(15, pool_wallet_0.get_confirmed_balance, 1)
        # balance = await pool_wallet.available_balance()

        #tx_record = await pool_wallet_0.generate_signed_transaction(1, 32 * b"\0")

        #await wallet_node_1.wallet_state_manager.main_wallet.push_transaction(tx_record)

        #for i in range(0, num_blocks):
        #    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"\0"))

        balance = await pool_wallet_0.get_confirmed_balance()
        print(f"Pool wallet balance: {balance}")

        #await time_out_assert(15, pool_wallet.get_confirmed_balance, 99)

        # pool_wallet.get_aggregation_puzzlehash(pool_wallet.get_new_puzzle())



    #@pytest.mark.asyncio
    #async def test_creation_of_singleton(self, two_wallet_nodes):
    #    pass


    async def test_creation_of_singleton_failure(self, two_wallet_nodes):
        pass

    async def test_sync_from_blockchain_pooling(self, two_wallet_nodes):
        pass

    async def test_sync_from_blockchain_self_pooling(self, two_wallet_nodes):
        pass

    async def test_leave_pool(self, two_wallet_nodes):
        pass

    async def test_enter_pool_with_unclaimed_rewards(self, two_wallet_nodes):
        pass

    async def test_farm_self_pool(self, two_wallet_nodes):
        pass

    async def test_farm_to_pool(self, two_wallet_nodes):
        pass

"""
