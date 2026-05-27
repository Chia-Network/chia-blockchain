from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from chia_rs import CoinState
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia.protocols.outbound_message import NodeType
from chia.types.blockchain_format.coin import Coin
from chia.wallet.remote_wallet.remote_info import RemoteInfo
from chia.wallet.remote_wallet.remote_wallet import RemoteWallet
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
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
        {"num_environments": 1, "blocks_needed": [1], "reuse_puzhash": True},
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_reorged_interested_remote_coin_state_does_not_crash(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet: Wallet = env.xch_wallet
    wsm = env.wallet_state_manager

    async with wsm.lock:
        remote_wallet = await RemoteWallet.create_new_remote_wallet(wsm, wallet, name="Remote Wallet #1")

    coin = Coin(bytes32(bytes([41] * 32)), bytes32(bytes([42] * 32)), uint64(1))
    coin_id = coin.name()
    await remote_wallet.register_remote_coins([coin_id])

    peer = Mock()
    peer.closed = False

    # A reorged-out coin state has created_height=None.
    await wsm._add_coin_states([CoinState(coin, None, None)], peer, None)

    assert await wsm.coin_store.get_coin_record(coin_id) is None


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {"num_environments": 1, "blocks_needed": [1], "reuse_puzhash": True},
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_remote_record_transitions_to_real_wallet_on_reprocess(
    wallet_environments: WalletTestFramework,
) -> None:
    """When a coin was initially stored as a REMOTE interest-only record but the
    wallet later recognizes the puzzle hash (e.g. after derivation-index extension),
    ``_add_coin_states`` must replace the REMOTE record with the real wallet
    identifier so wallet-specific logic (balance tracking, tx matching) applies.

    This exercises the ``local_record = None`` override at
    ``wallet_state_manager.py:1751-1760``.
    """
    env = wallet_environments.environments[0]
    wsm = env.wallet_state_manager
    wallet: Wallet = env.xch_wallet

    async with wsm.lock:
        remote_wallet = await RemoteWallet.create_new_remote_wallet(wsm, wallet, name="Remote Wallet #1")

    # Pick a puzzle hash that the standard wallet already owns so that
    # get_wallet_identifier_for_puzzle_hash will return STANDARD_WALLET.
    derivation_record = await wsm.get_unused_derivation_record(wallet.id())
    owned_ph = derivation_record.puzzle_hash

    # Fabricate a coin at height 1 with that puzzle hash.
    coin = Coin(bytes32(bytes([51] * 32)), owned_ph, uint64(1))
    coin_id = coin.name()

    # Simulate the state where this coin was first processed when the puzzle
    # hash was NOT yet known, and the interest-only REMOTE path stored it.
    await remote_wallet.register_remote_coins([coin_id])
    remote_record = WalletCoinRecord(
        coin, uint32(1), uint32(0), False, False, WalletType.REMOTE, int(remote_wallet.id())
    )
    await wsm.coin_store.add_coin_record(remote_record)

    record = await wsm.coin_store.get_coin_record(coin_id)
    assert record is not None
    assert record.wallet_type == WalletType.REMOTE

    # Re-process the same coin state.  Now the puzzle hash IS recognized, so
    # lines 1751-1760 should clear local_record and let coin_added() store a
    # STANDARD_WALLET record instead.
    peer = env.node.server.get_connections(NodeType.FULL_NODE)[0]
    await wsm._add_coin_states([CoinState(coin, None, uint32(1))], peer, None)

    record = await wsm.coin_store.get_coin_record(coin_id)
    assert record is not None
    assert record.wallet_type == WalletType.STANDARD_WALLET
    assert record.wallet_id == int(wallet.id())


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
        remote_wallet = await RemoteWallet.create_new_remote_wallet(wsm, wallet)

    assert remote_wallet.id() > 0
    assert remote_wallet.get_name() == "Remote Wallet #1"
    assert remote_wallet.type() == WalletType.REMOTE
    assert remote_wallet.require_derivation_paths() is False

    assert await wsm.remote_coin_store.add_coin_ids([], remote_wallet.id()) == 0

    await remote_wallet.register_remote_coins([bytes32.zeros])
    stored_coin_ids = await wsm.remote_coin_store.get_coin_ids(remote_wallet.id())
    assert bytes32.zeros in stored_coin_ids

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

    await remote_wallet.register_remote_coins([coin_id_1, coin_id_2])

    wsm.interested_coin_cache.pop(coin_id_1, None)
    wsm.interested_coin_cache.pop(coin_id_2, None)

    reloaded_wallet = await RemoteWallet.create(wsm, wallet, remote_wallet.wallet_info)

    stored_coin_ids = await wsm.remote_coin_store.get_coin_ids(reloaded_wallet.id())
    assert set(stored_coin_ids) == {coin_id_1, coin_id_2}
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
    await remote_wallet.register_remote_coins([coin_id])

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
async def test_register_remote_coins_with_existing_ids_still_subscribes() -> None:
    coin_id_1 = bytes32(bytes([1] * 32))
    wallet = RemoteWallet()
    wallet.wallet_info = WalletInfo(
        uint32(7), "Remote Wallet #7", uint8(WalletType.REMOTE.value), bytes(RemoteInfo()).hex()
    )
    wallet.remote_info = RemoteInfo()
    wallet.wallet_state_manager = Mock()
    wallet.wallet_state_manager.add_interested_coin_ids = AsyncMock()
    wallet.wallet_state_manager.remote_coin_store = Mock()
    wallet.wallet_state_manager.remote_coin_store.add_coin_ids = AsyncMock(return_value=0)

    await wallet.register_remote_coins([])
    wallet.wallet_state_manager.remote_coin_store.add_coin_ids.assert_not_awaited()
    wallet.wallet_state_manager.add_interested_coin_ids.assert_not_awaited()

    await wallet.register_remote_coins([coin_id_1, coin_id_1])

    wallet.wallet_state_manager.remote_coin_store.add_coin_ids.assert_awaited_once_with(
        [coin_id_1], wallet.wallet_info.id
    )
    wallet.wallet_state_manager.add_interested_coin_ids.assert_awaited_once_with([coin_id_1], [wallet.wallet_info.id])
