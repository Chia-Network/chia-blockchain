from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from chia_rs import CoinSpend, CoinState
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.cmds.test_cmd_framework import check_click_parsing
from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia.cmds.cmd_classes import ChiaCliContext
from chia.cmds.cmd_helpers import NeedsTXConfig, NeedsWalletRPC, TransactionsOut, WalletClientInfo
from chia.cmds.param_types import CliAddress, CliAmount
from chia.cmds.wallet import DeleteNotificationsCMD, GetNotificationsCMD, SendNotificationCMD
from chia.util.bech32m import encode_puzzle_hash
from chia.util.db_wrapper import DBWrapper2
from chia.wallet.notification_store import NotificationStore
from chia.wallet.util.address_type import AddressType


# For testing backwards compatibility with a DB change to add height
@pytest.mark.anyio
async def test_notification_store_backwards_compat() -> None:
    # First create the DB the way it would have otheriwse been created
    with tempfile.TemporaryDirectory() as temporary_directory:
        db_name = Path(temporary_directory).joinpath("test.sqlite")
        db_name.parent.mkdir(parents=True, exist_ok=True)
        async with DBWrapper2.managed(
            database=db_name,
        ) as db_wrapper:
            async with db_wrapper.writer_maybe_transaction() as conn:
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS notifications(coin_id blob PRIMARY KEY,msg blob,amount blob)"
                )
                cursor = await conn.execute(
                    "INSERT OR REPLACE INTO notifications (coin_id, msg, amount) VALUES(?, ?, ?)",
                    (
                        bytes32.zeros,
                        bytes([0] * 10),
                        bytes([0]),
                    ),
                )
                await cursor.close()

            await NotificationStore.create(db_wrapper)
            await NotificationStore.create(db_wrapper)


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [2, 1]}],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_notifications(wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]) -> None:
    env_1 = wallet_environments.environments[0]
    env_2 = wallet_environments.environments[1]

    env_1.wallet_aliases = {"xch": 1}
    env_2.wallet_aliases = {"xch": 1}

    client_info_1 = WalletClientInfo(
        env_1.rpc_client,
        env_1.wallet_state_manager.root_pubkey.get_fingerprint(),
        env_1.wallet_state_manager.config,
    )
    client_info_2 = WalletClientInfo(
        env_2.rpc_client,
        env_2.wallet_state_manager.root_pubkey.get_fingerprint(),
        env_2.wallet_state_manager.config,
    )

    async with env_2.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        ph_2 = await action_scope.get_puzzle_hash(env_2.wallet_state_manager)

    notification_manager_1 = env_1.wallet_state_manager.notification_manager
    notification_manager_2 = env_2.wallet_state_manager.notification_manager

    most_recent_args: tuple[CoinState, CoinSpend] = (Mock(), Mock())

    func = notification_manager_2.potentially_add_new_notification

    async def track_coin_state(coin_state: CoinState, parent_spend: CoinSpend) -> bool:
        nonlocal most_recent_args
        most_recent_args = (coin_state, parent_spend)
        result: bool = await func(coin_state, parent_spend)
        return result

    # there's maybe a more reasonable way to do this with monkypatching but this works for now
    notification_manager_2.potentially_add_new_notification = track_coin_state  # type: ignore[method-assign]

    allow_larger_height: int | None = None
    allow_height: int | None = None

    for case in ("block all", "block too low", "allow", "allow_larger", "block_too_large"):
        msg = case
        if case == "block all":
            env_2.node.config["enable_notifications"] = False
            env_2.node.config["required_notification_amount"] = 100
            AMOUNT = uint64(100)
            FEE = uint64(0)
        elif case == "block too low":
            env_2.node.config["enable_notifications"] = True
            AMOUNT = uint64(1)
            FEE = uint64(0)
        elif case in {"allow", "allow_larger"}:
            env_2.node.config["required_notification_amount"] = 750000000000
            if case == "allow_larger":
                AMOUNT = uint64(1000000000000)
            else:
                AMOUNT = uint64(750000000000)
            FEE = uint64(1)
        elif case == "block_too_large":
            msg = str(bytes([0] * 10001), "utf8")
            AMOUNT = uint64(750000000000)
            FEE = uint64(0)
        else:
            raise Exception(f"Unhandled case: {case!r}")
        peak = wallet_environments.full_node.full_node.blockchain.get_peak()
        assert peak is not None
        if case == "allow":
            allow_height = peak.height + 1
        if case == "allow_larger":
            allow_larger_height = peak.height + 1
        await SendNotificationCMD(
            rpc_info=NeedsWalletRPC(client_info=client_info_1),
            tx_config_loader=NeedsTXConfig(
                min_coin_amount=CliAmount(amount=wallet_environments.tx_config.min_coin_amount, mojos=True),
                max_coin_amount=CliAmount(amount=wallet_environments.tx_config.max_coin_amount, mojos=True),
                coins_to_exclude=wallet_environments.tx_config.excluded_coin_ids,
                coins_to_include=wallet_environments.tx_config.included_coin_ids,
                amounts_to_exclude=[
                    CliAmount(amount=amount, mojos=True)
                    for amount in wallet_environments.tx_config.excluded_coin_amounts
                ],
                primary_coin=wallet_environments.tx_config.primary_coin,
                reuse=wallet_environments.tx_config.reuse_puzhash,
            ),
            transaction_writer=TransactionsOut(transaction_file_out=None),
            to_address=CliAddress(ph_2, "doesn't matter", AddressType.XCH),
            message=msg,
            amount=CliAmount(amount=AMOUNT, mojos=True),
            fee=uint64(FEE),
            push=True,
        ).run()
        capsys.readouterr()

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {
                            "unconfirmed_wallet_balance": -(AMOUNT + FEE),
                            "<=#spendable_balance": -(AMOUNT + FEE),
                            "<=#max_send_amount": -(AMOUNT + FEE),
                            ">=#pending_change": 0,
                            ">=#pending_coin_removal_count": 1,
                        }
                    },
                    post_block_balance_updates={
                        "xch": {
                            "confirmed_wallet_balance": -(AMOUNT + FEE),
                            ">=#spendable_balance": 0,
                            ">=#max_send_amount": 0,
                            "<=#pending_change": 0,
                            "<=#pending_coin_removal_count": -1,
                            "<=#unspent_coin_count": 0,
                        }
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={
                        "xch": {
                            "confirmed_wallet_balance": AMOUNT,
                            "unconfirmed_wallet_balance": AMOUNT,
                            "spendable_balance": AMOUNT,
                            "max_send_amount": AMOUNT,
                            "unspent_coin_count": 1,
                        }
                    },
                ),
            ]
        )

    assert allow_larger_height is not None
    assert allow_height is not None

    notifications = await notification_manager_2.notification_store.get_notifications(pagination=(0, 2))
    await GetNotificationsCMD(rpc_info=NeedsWalletRPC(client_info=client_info_2), ids=tuple(), start=0, end=2).run()
    out, _ = capsys.readouterr()
    assert "message: allow_larger\n" in out
    assert "message: allow\n" in out
    assert len(notifications) == 2
    assert notifications[0].message == b"allow_larger"
    assert notifications[0].height == allow_larger_height
    notifications = await notification_manager_2.notification_store.get_notifications(pagination=(1, None))
    await GetNotificationsCMD(rpc_info=NeedsWalletRPC(client_info=client_info_2), ids=tuple(), start=1, end=None).run()
    out, _ = capsys.readouterr()
    assert "message: allow_larger\n" not in out
    assert "message: allow\n" in out
    assert len(notifications) == 1
    assert notifications[0].message == b"allow"
    assert notifications[0].height == allow_height
    notifications = await notification_manager_2.notification_store.get_notifications(pagination=(0, 1))
    await GetNotificationsCMD(rpc_info=NeedsWalletRPC(client_info=client_info_2), ids=tuple(), start=0, end=1).run()
    out, _ = capsys.readouterr()
    assert "message: allow_larger\n" in out
    assert "message: allow\n" not in out
    assert len(notifications) == 1
    assert notifications[0].message == b"allow_larger"
    notifications = await notification_manager_2.notification_store.get_notifications(pagination=(None, 1))
    await GetNotificationsCMD(rpc_info=NeedsWalletRPC(client_info=client_info_2), ids=tuple(), start=None, end=1).run()
    out, _ = capsys.readouterr()
    assert "message: allow_larger\n" in out
    assert "message: allow\n" not in out
    assert len(notifications) == 1
    assert notifications[0].message == b"allow_larger"
    assert (
        await notification_manager_2.notification_store.get_notifications(coin_ids=[n.id for n in notifications])
        == notifications
    )
    await GetNotificationsCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_2), ids=[n.id for n in notifications]
    ).run()
    out, _ = capsys.readouterr()
    assert "message: allow_larger\n" in out
    assert "message: allow\n" not in out

    sent_notifications = await notification_manager_1.notification_store.get_notifications()
    assert len(sent_notifications) == 0

    await DeleteNotificationsCMD(rpc_info=NeedsWalletRPC(client_info=client_info_2), delete_all=True).run()
    assert len(await notification_manager_2.notification_store.get_notifications()) == 0
    await notification_manager_2.notification_store.add_notification(notifications[0])
    await DeleteNotificationsCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info_2), ids=[n.id for n in notifications]
    ).run()
    assert len(await notification_manager_2.notification_store.get_notifications()) == 0

    assert not await notification_manager_2.potentially_add_new_notification(most_recent_args[0], most_recent_args[1])
    await DeleteNotificationsCMD(rpc_info=NeedsWalletRPC(client_info=client_info_2), delete_all=True).run()
    assert not await notification_manager_2.potentially_add_new_notification(most_recent_args[0], most_recent_args[1])


def test_notification_command_parsing() -> None:
    puzzle_hash = bytes32.zeros
    address = encode_puzzle_hash(puzzle_hash, "txch")
    check_click_parsing(
        SendNotificationCMD(
            rpc_info=NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None),
            tx_config_loader=NeedsTXConfig(
                coins_to_exclude=tuple(), coins_to_include=tuple(), amounts_to_exclude=tuple()
            ),
            transaction_writer=TransactionsOut(transaction_file_out=None),
            to_address=CliAddress(puzzle_hash, address, AddressType.XCH),
            message="a message",
            amount=CliAmount(amount=uint64(1), mojos=False),
            fee=uint64(0),
        ),
        "--to-address",
        address,
        "--message",
        "a message",
        "--amount",
        "1",
        "--fee",
        "0",
        # Needed for AddressParamType to work correctly without config
        context=ChiaCliContext(expected_prefix="txch"),
    )

    check_click_parsing(
        GetNotificationsCMD(
            rpc_info=NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None),
            ids=tuple(),
            start=None,
            end=None,
        ),
    )

    check_click_parsing(
        GetNotificationsCMD(
            rpc_info=NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None),
            ids=(bytes32.zeros, bytes32(bytes([1] * 32))),
            start=100,
            end=200,
        ),
        "--id",
        bytes32.zeros.hex(),
        "--id",
        "01" * 32,
        "--start",
        "100",
        "--end",
        "200",
    )

    check_click_parsing(
        DeleteNotificationsCMD(
            rpc_info=NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None), ids=tuple()
        )
    )

    check_click_parsing(
        DeleteNotificationsCMD(
            rpc_info=NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None),
            ids=(bytes32.zeros, bytes32(bytes([1] * 32))),
        ),
        "--id",
        bytes32.zeros.hex(),
        "--id",
        "01" * 32,
    )

    check_click_parsing(
        DeleteNotificationsCMD(
            rpc_info=NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None),
            ids=tuple(),
            delete_all=True,
        ),
        "--all",
    )
