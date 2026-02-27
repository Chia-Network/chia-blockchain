from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64, uint128

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia.types.blockchain_format.coin import Coin
from chia.wallet.remote_wallet.remote_info import RemoteInfo
from chia.wallet.remote_wallet.remote_wallet import RemoteWallet
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_request_types import RegisterRemoteCoins


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {"num_environments": 1, "blocks_needed": [2], "reuse_puzhash": True},
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_remote_wallet_register_remote_coin_persists_coin_record(
    wallet_environments: WalletTestFramework,
) -> None:
    env = wallet_environments.environments[0]
    wallet: Wallet = env.xch_wallet
    wallet_node: WalletNode = env.node

    # Create a coin that no wallet owns by sending to a puzzle hash we don't own.
    target_ph = bytes32(bytes([11] * 32))
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await wallet.generate_signed_transaction(
            amounts=[uint64(1)],
            puzzle_hashes=[target_ph],
            action_scope=action_scope,
        )
    [tx] = action_scope.side_effects.transactions

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={1: {"set_remainder": True}},
                post_block_balance_updates={1: {"set_remainder": True}},
            )
        ]
    )

    created_coin = next(coin for coin in tx.additions if coin.puzzle_hash == target_ph and coin.amount == uint64(1))
    coin_id = created_coin.name()

    # Create a remote wallet and register the coin id.
    async with wallet_node.wallet_state_manager.lock:
        remote_wallet = await RemoteWallet.create_new_remote_wallet(
            wallet_node.wallet_state_manager, wallet, name="Remote Wallet #1"
        )

    # Check for CoinRecord before we register interest in the coin.
    assert await wallet_node.wallet_state_manager.coin_store.get_coin_record(coin_id) is None

    await env.rpc_client.register_remote_coins(RegisterRemoteCoins(wallet_id=remote_wallet.id(), coin_ids=[coin_id]))

    # Trigger/allow subscription processing and coin updates.
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {"set_remainder": True},
                    int(remote_wallet.id()): {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    1: {"set_remainder": True},
                    int(remote_wallet.id()): {"set_remainder": True},
                },
            )
        ]
    )

    record = await wallet_node.wallet_state_manager.coin_store.get_coin_record(coin_id)
    assert record is not None
    assert record.wallet_type == WalletType.REMOTE
    assert record.wallet_id == int(remote_wallet.id())


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {"num_environments": 1, "blocks_needed": [2], "reuse_puzhash": True},
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_remote_wallet_register_remote_coins_persists_coin_records(
    wallet_environments: WalletTestFramework,
) -> None:
    env = wallet_environments.environments[0]
    wallet: Wallet = env.xch_wallet
    wallet_node: WalletNode = env.node

    # Create multiple coins that no wallet owns by sending to puzzle hashes we don't own.
    target_ph_1 = bytes32(bytes([21] * 32))
    target_ph_2 = bytes32(bytes([22] * 32))
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await wallet.generate_signed_transaction(
            amounts=[uint64(1), uint64(2)],
            puzzle_hashes=[target_ph_1, target_ph_2],
            action_scope=action_scope,
        )
    [tx] = action_scope.side_effects.transactions

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={1: {"set_remainder": True}},
                post_block_balance_updates={1: {"set_remainder": True}},
            )
        ]
    )

    created_coin_1 = next(coin for coin in tx.additions if coin.puzzle_hash == target_ph_1 and coin.amount == uint64(1))
    created_coin_2 = next(coin for coin in tx.additions if coin.puzzle_hash == target_ph_2 and coin.amount == uint64(2))
    coin_id_1 = created_coin_1.name()
    coin_id_2 = created_coin_2.name()

    async with wallet_node.wallet_state_manager.lock:
        remote_wallet = await RemoteWallet.create_new_remote_wallet(
            wallet_node.wallet_state_manager, wallet, name="Remote Wallet #1"
        )

    assert await wallet_node.wallet_state_manager.coin_store.get_coin_record(coin_id_1) is None
    assert await wallet_node.wallet_state_manager.coin_store.get_coin_record(coin_id_2) is None

    await env.rpc_client.register_remote_coins(
        RegisterRemoteCoins(wallet_id=remote_wallet.id(), coin_ids=[coin_id_1, coin_id_2])
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {"set_remainder": True},
                    int(remote_wallet.id()): {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    1: {"set_remainder": True},
                    int(remote_wallet.id()): {"set_remainder": True},
                },
            )
        ]
    )

    record_1 = await wallet_node.wallet_state_manager.coin_store.get_coin_record(coin_id_1)
    record_2 = await wallet_node.wallet_state_manager.coin_store.get_coin_record(coin_id_2)
    assert record_1 is not None
    assert record_2 is not None
    assert record_1.wallet_type == WalletType.REMOTE
    assert record_2.wallet_type == WalletType.REMOTE
    assert record_1.wallet_id == int(remote_wallet.id())
    assert record_2.wallet_id == int(remote_wallet.id())


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {"num_environments": 1, "blocks_needed": [2], "reuse_puzhash": True},
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_interested_coin_not_persisted_without_remote_wallet(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet: Wallet = env.xch_wallet
    wallet_node: WalletNode = env.node

    # Create an "external" coin by sending to a puzzle hash we don't own.
    target_ph = bytes32(bytes([31] * 32))
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await wallet.generate_signed_transaction(
            amounts=[uint64(1)],
            puzzle_hashes=[target_ph],
            action_scope=action_scope,
        )
    [tx] = action_scope.side_effects.transactions

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={1: {"set_remainder": True}},
                post_block_balance_updates={1: {"set_remainder": True}},
            )
        ]
    )

    created_coin = next(coin for coin in tx.additions if coin.puzzle_hash == target_ph and coin.amount == uint64(1))
    coin_id = created_coin.name()

    # Register interest without associating it to any RemoteWallet id.
    await wallet_node.wallet_state_manager.add_interested_coin_ids([coin_id])

    await wallet_environments.process_pending_states(
        [WalletStateTransition(pre_block_balance_updates={1: {"set_remainder": True}})]
    )

    # Give the wallet node a moment to process subscription/updates, then assert nothing was stored.
    record = await wallet_node.wallet_state_manager.coin_store.get_coin_record(coin_id)
    assert record is None


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {"num_environments": 1, "blocks_needed": [1]},
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_remote_wallet_create_and_save_info_paths(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet: Wallet = env.xch_wallet
    wsm = env.wallet_state_manager

    async with wsm.lock:
        remote_wallet = await RemoteWallet.create_new_remote_wallet(wsm, wallet, name="Remote Wallet #1")

    assert remote_wallet.id() > 0
    assert remote_wallet.get_name() == "Remote Wallet #1"
    assert remote_wallet.type() == WalletType.REMOTE
    assert remote_wallet.require_derivation_paths() is False

    await remote_wallet.save_info(RemoteInfo(remote_coin_ids=[bytes32.zeros]))
    assert bytes32.zeros in remote_wallet.remote_info.remote_coin_ids
    saved_wallet_info = await wsm.user_store.get_wallet_by_id(int(remote_wallet.id()))
    assert saved_wallet_info is not None
    saved_remote_info = RemoteInfo.from_json_dict(json.loads(saved_wallet_info.data))
    assert bytes32.zeros in saved_remote_info.remote_coin_ids

    # If a remote wallet already exists, creation is rejected.
    async with wsm.lock:
        with pytest.raises(ValueError, match="Only one RemoteWallet instance is supported"):
            await RemoteWallet.create_new_remote_wallet(wsm, wallet, name="Remote Wallet #2")


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {"num_environments": 1, "blocks_needed": [1]},
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_remote_wallet_create_resubscribes_existing_remote_coin_ids(
    wallet_environments: WalletTestFramework,
) -> None:
    env = wallet_environments.environments[0]
    wallet: Wallet = env.xch_wallet
    wsm = env.wallet_state_manager

    coin_id_1 = bytes32(bytes([1] * 32))
    coin_id_2 = bytes32(bytes([2] * 32))
    async with wsm.lock:
        remote_wallet = await RemoteWallet.create_new_remote_wallet(wsm, wallet, name="Remote Wallet #1")

    await remote_wallet.save_info(RemoteInfo(remote_coin_ids=[coin_id_1, coin_id_2]))

    wsm.interested_coin_cache.pop(coin_id_1, None)
    wsm.interested_coin_cache.pop(coin_id_2, None)

    reloaded_wallet = await RemoteWallet.create(wsm, wallet, remote_wallet.wallet_info)

    assert reloaded_wallet.remote_info.remote_coin_ids == [coin_id_1, coin_id_2]
    assert coin_id_1 in wsm.interested_coin_cache
    assert coin_id_2 in wsm.interested_coin_cache
    assert remote_wallet.id() in wsm.interested_coin_cache[coin_id_1]
    assert remote_wallet.id() in wsm.interested_coin_cache[coin_id_2]


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {"num_environments": 1, "blocks_needed": [1]},
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_wallet_state_manager_loads_remote_wallet_on_restart(
    wallet_environments: WalletTestFramework,
) -> None:
    env = wallet_environments.environments[0]
    wsm = env.wallet_state_manager
    coin_id = bytes32(bytes([9] * 32))

    async with wsm.lock:
        remote_wallet = await RemoteWallet.create_new_remote_wallet(wsm, env.xch_wallet, name="Remote Wallet #1")
    await remote_wallet.save_info(RemoteInfo(remote_coin_ids=[coin_id]))

    env.node._close()
    await env.node._await_closed()
    await env.node._start()

    restarted_wsm = env.node.wallet_state_manager
    loaded_remote_wallet = restarted_wsm.get_existing_remote_wallet()
    assert loaded_remote_wallet is not None
    assert isinstance(loaded_remote_wallet, RemoteWallet)
    assert loaded_remote_wallet.id() == remote_wallet.id()
    assert coin_id in restarted_wsm.interested_coin_cache
    assert loaded_remote_wallet.id() in restarted_wsm.interested_coin_cache[coin_id]


@pytest.mark.anyio
async def test_remote_wallet_create_with_invalid_data_raises_error() -> None:
    wallet_info = WalletInfo(uint32(5), "Remote Wallet #5", uint8(WalletType.REMOTE.value), "{bad_json")
    with pytest.raises(json.JSONDecodeError):
        await RemoteWallet.create(Mock(), Mock(spec=Wallet), wallet_info)


@pytest.mark.anyio
async def test_remote_wallet_stub_methods_and_errors() -> None:
    wallet = RemoteWallet()
    wallet.wallet_info = WalletInfo(uint32(1), "Remote Wallet #1", uint8(WalletType.REMOTE.value), "{}")
    wallet.wallet_state_manager = Mock(wallets={})
    wallet.remote_info = RemoteInfo(remote_coin_ids=[])
    wallet.standard_wallet = Mock(spec=Wallet)
    wallet.log = Mock()

    assert await wallet.get_confirmed_balance() == uint128(0)
    assert await wallet.get_unconfirmed_balance() == uint128(0)
    assert await wallet.get_spendable_balance() == uint128(0)
    assert await wallet.get_pending_change_balance() == uint64(0)
    assert await wallet.get_max_send_amount() == uint128(0)
    await wallet.coin_added(Coin(bytes32.zeros, bytes32.zeros, uint64(1)), uint32(1), None, None)
    assert await wallet.match_hinted_coin(Coin(bytes32.zeros, bytes32.zeros, uint64(1)), bytes32.zeros) is False

    with pytest.raises(ValueError, match="RemoteWallet cannot select coins"):
        await wallet.select_coins(uint64(1), Mock(spec=WalletActionScope))

    with pytest.raises(ValueError, match="RemoteWallet cannot generate transactions"):
        await wallet.generate_signed_transaction([uint64(1)], [bytes32.zeros], Mock(spec=WalletActionScope))

    with pytest.raises(RuntimeError, match="RemoteWallet does not derive puzzle hashes"):
        wallet.puzzle_hash_for_pk(Mock())


@pytest.mark.anyio
async def test_register_remote_coins_with_existing_ids_still_subscribes() -> None:
    coin_id_1 = bytes32(bytes([1] * 32))
    wallet = RemoteWallet()
    wallet.wallet_info = WalletInfo(
        uint32(7), "Remote Wallet #7", uint8(WalletType.REMOTE.value), '{"remote_coin_ids":[]}'
    )
    wallet.remote_info = RemoteInfo(remote_coin_ids=[coin_id_1])
    wallet.wallet_state_manager = Mock()
    wallet.wallet_state_manager.add_interested_coin_ids = AsyncMock()
    wallet.wallet_state_manager.user_store = Mock()
    wallet.wallet_state_manager.user_store.update_wallet = AsyncMock()

    await wallet.register_remote_coins([coin_id_1, coin_id_1])

    wallet.wallet_state_manager.add_interested_coin_ids.assert_awaited_once_with([coin_id_1], [wallet.wallet_info.id])
    wallet.wallet_state_manager.user_store.update_wallet.assert_not_awaited()
