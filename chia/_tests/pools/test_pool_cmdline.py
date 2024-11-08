from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from click.testing import CliRunner

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.misc import Marks, datacases
from chia._tests.util.time_out_assert import time_out_assert
from chia.cmds.cmd_classes import NeedsWalletRPC, WalletClientInfo
from chia.cmds.plotnft import CreatePlotNFTCMD, ShowPlotNFTCMD
from chia.pools.pool_wallet_info import PoolSingletonState, PoolWalletInfo
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.util.errors import CliRpcConnectionError
from chia.util.ints import uint32, uint64
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_state_manager import WalletStateManager


@dataclass
class StateUrlCase:
    id: str
    state: str
    pool_url: Optional[str]
    expected_error: Optional[str] = None
    marks: Marks = ()


async def verify_pool_state(wallet_rpc: WalletRpcClient, w_id: int, expected_state: PoolSingletonState) -> bool:
    pw_status: PoolWalletInfo = (await wallet_rpc.pw_status(w_id))[0]
    return pw_status.current.state == expected_state.value


async def create_new_plotnft(wallet_test_framework: WalletTestFramework) -> int:
    wallet_state_manager: WalletStateManager = wallet_test_framework.environments[0].wallet_state_manager
    wallet_rpc: WalletRpcClient = wallet_test_framework.environments[0].rpc_client

    our_ph = await wallet_state_manager.main_wallet.get_new_puzzlehash()

    await wallet_rpc.create_new_pool_wallet(
        target_puzzlehash=our_ph,
        pool_url="http://pool.example.com",
        relative_lock_height=uint32(10),
        backup_host="",
        mode="new",
        state="FARMING_TO_POOL",
        fee=uint64(0),
    )

    await wallet_test_framework.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "spendable_balance": -250000000000,
                        "max_send_amount": -250000000000,
                        "pending_change": 249999999999,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 249999999999,
                        "max_send_amount": 249999999999,
                        "unspent_coin_count": 0,
                        "pending_change": -249999999999,
                        "pending_coin_removal_count": -1,
                    },
                    2: {"init": True, "unspent_coin_count": 1},
                },
            )
        ]
    )

    summaries_response = await wallet_rpc.get_wallets(WalletType.POOLING_WALLET)
    assert len(summaries_response) == 1
    wallet_id: int = summaries_response[0]["id"]

    await time_out_assert(45, verify_pool_state, True, wallet_rpc, wallet_id, PoolSingletonState.FARMING_TO_POOL)
    return wallet_id


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "trusted": True,
            "reuse_puzhash": False,
        }
    ],
    indirect=True,
)
@datacases(
    StateUrlCase(
        id="local state without pool url",
        state="local",
        pool_url=None,
        expected_error=None,
    )
)
@pytest.mark.anyio
async def test_plotnft_cli_create(
    wallet_environments: WalletTestFramework,
    case: StateUrlCase,
) -> None:
    wallet_state_manager: WalletStateManager = wallet_environments.environments[0].wallet_state_manager
    wallet_rpc: WalletRpcClient = wallet_environments.environments[0].rpc_client
    client_info: WalletClientInfo = WalletClientInfo(
        wallet_rpc,
        wallet_state_manager.root_pubkey.get_fingerprint(),
        wallet_state_manager.config,
    )

    runner = CliRunner()
    with runner.isolated_filesystem():
        await CreatePlotNFTCMD(
            rpc_info=NeedsWalletRPC(
                client_info=client_info,
                wallet_rpc_port=wallet_rpc.port,
                fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
            ),
            state=case.state,
            dont_prompt=True,
            pool_url=case.pool_url,
        ).run()

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "spendable_balance": -250000000000,
                        "max_send_amount": -250000000000,
                        "pending_change": 249999999999,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 249999999999,
                        "max_send_amount": 249999999999,
                        "unspent_coin_count": 0,
                        "pending_change": -249999999999,
                        "pending_coin_removal_count": -1,
                    },
                    2: {"init": True, "unspent_coin_count": 1},
                },
            )
        ]
    )

    summaries_response = await wallet_rpc.get_wallets(WalletType.POOLING_WALLET)
    assert len(summaries_response) == 1
    wallet_id: int = summaries_response[0]["id"]

    await time_out_assert(45, verify_pool_state, True, wallet_rpc, wallet_id, PoolSingletonState.SELF_POOLING)


@datacases(
    StateUrlCase(
        id="local state with pool url",
        state="local",
        pool_url="https://pool.example.com",
        expected_error="is not allowed with 'local' state",
    ),
    StateUrlCase(
        id="pool state no pool url",
        state="pool",
        pool_url=None,
        expected_error="is required with 'pool' state",
    ),
)
@pytest.mark.anyio
async def test_plotnft_cli_create_errors(
    case: StateUrlCase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        with pytest.raises(CliRpcConnectionError, match=case.expected_error):
            await CreatePlotNFTCMD(
                rpc_info=NeedsWalletRPC(
                    client_info=None,
                    wallet_rpc_port=None,
                    fingerprint=None,
                ),
                state=case.state,
                dont_prompt=True,
                pool_url=case.pool_url,
            ).run()


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "trusted": True,
            "reuse_puzhash": False,
        }
    ],
    indirect=True,
)
# @boolean_datacases(name="with_wallet_id", false="no_wallet_id", true="with_wallet_id")
@pytest.mark.anyio
async def test_plotnft_cli_show(
    wallet_environments: WalletTestFramework,
    capsys: pytest.CaptureFixture[str],
    # with_wallet_id: bool,
) -> None:
    wallet_state_manager: WalletStateManager = wallet_environments.environments[0].wallet_state_manager
    wallet_rpc: WalletRpcClient = wallet_environments.environments[0].rpc_client
    client_info: WalletClientInfo = WalletClientInfo(
        wallet_rpc,
        wallet_state_manager.root_pubkey.get_fingerprint(),
        wallet_state_manager.config,
    )

    runner = CliRunner()
    with runner.isolated_filesystem():
        with pytest.raises(CliRpcConnectionError, match="No pool wallet found"):
            await ShowPlotNFTCMD(
                rpc_info=NeedsWalletRPC(
                    client_info=client_info,
                    wallet_rpc_port=wallet_rpc.port,
                    fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
                ),
                id=None,
            ).run()
            capsys.readouterr()

        with pytest.raises(CliRpcConnectionError, match="is not a pool wallet"):
            await ShowPlotNFTCMD(
                rpc_info=NeedsWalletRPC(
                    client_info=client_info,
                    wallet_rpc_port=wallet_rpc.port,
                    fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
                ),
                id=15,
            ).run()
            capsys.readouterr()

        wallet_id = await create_new_plotnft(wallet_environments)

        # need to capute the output and verify
        await ShowPlotNFTCMD(
            rpc_info=NeedsWalletRPC(
                client_info=client_info,
                wallet_rpc_port=wallet_rpc.port,
                fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
            ),
            id=wallet_id,
        ).run()
        out, _err = capsys.readouterr()
        assert "Current state: FARMING_TO_POOL" in out

        # wallet_id = await create_new_plotnft(wallet_environments)

        await ShowPlotNFTCMD(
            rpc_info=NeedsWalletRPC(
                client_info=client_info,
                wallet_rpc_port=wallet_rpc.port,
                fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
            ),
            id=None,
        ).run()
        out, _err = capsys.readouterr()
        assert "Current state: FARMING_TO_POOL" in out

        #  Need to run the farmer to make further tests
