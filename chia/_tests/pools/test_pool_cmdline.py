from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from click.testing import CliRunner
from pytest_mock import MockerFixture

from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.misc import Marks, datacases
from chia.cmds.cmd_classes import NeedsWalletRPC, WalletClientInfo
from chia.cmds.plotnft import CreatePlotNFTCMD, JoinPlotNFTCMD, LeavePlotNFTCMD, ShowPlotNFTCMD
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


async def process_plotnft_create(
    wallet_test_framework: WalletTestFramework, expected_state: PoolSingletonState, num_pool_wallets: int
) -> int:
    wallet_rpc: WalletRpcClient = wallet_test_framework.environments[0].rpc_client

    await wallet_test_framework.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": 1,
                        "<=#max_send_amount": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": 1,  # any amount decrease
                        "<=#pending_coin_removal_count": 1,
                    },
                    num_pool_wallets + 1: {"init": True, "unspent_coin_count": 1},
                },
            )
        ]
    )

    summaries_response = await wallet_rpc.get_wallets(WalletType.POOLING_WALLET)
    assert len(summaries_response) == num_pool_wallets
    wallet_id: int = summaries_response[-1]["id"]

    await verify_pool_state(wallet_rpc, wallet_id, expected_state=expected_state)
    return wallet_id


async def create_new_plotnft(wallet_test_framework: WalletTestFramework, num_pool_wallets: int) -> int:
    wallet_state_manager: WalletStateManager = wallet_test_framework.environments[0].wallet_state_manager
    wallet_rpc: WalletRpcClient = wallet_test_framework.environments[0].rpc_client

    our_ph = await wallet_state_manager.main_wallet.get_new_puzzlehash()

    await wallet_rpc.create_new_pool_wallet(
        target_puzzlehash=our_ph,
        pool_url="http://pool.example.com",
        relative_lock_height=uint32(5),
        backup_host="",
        mode="new",
        state="FARMING_TO_POOL",
        fee=uint64(0),
    )

    return await process_plotnft_create(
        wallet_test_framework=wallet_test_framework,
        expected_state=PoolSingletonState.FARMING_TO_POOL,
        num_pool_wallets=num_pool_wallets,
    )


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
                        "<=#spendable_balance": 1,
                        "<=#max_send_amount": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": 1,  # any amount decrease
                        "<=#pending_coin_removal_count": 1,
                    },
                    2: {"init": True, "unspent_coin_count": 1},
                },
            )
        ]
    )

    summaries_response = await wallet_rpc.get_wallets(WalletType.POOLING_WALLET)
    assert len(summaries_response) == 1
    wallet_id: int = summaries_response[0]["id"]

    await verify_pool_state(wallet_rpc, wallet_id, PoolSingletonState.SELF_POOLING)


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
        await ShowPlotNFTCMD(
            rpc_info=NeedsWalletRPC(
                client_info=client_info,
                wallet_rpc_port=wallet_rpc.port,
                fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
            ),
            id=None,
        ).run()
        out, _err = capsys.readouterr()
        assert "Wallet height: 3\nSync status: Synced\n" == out

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

        wallet_id = await create_new_plotnft(wallet_environments, 1)

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

        wallet_id = await create_new_plotnft(wallet_environments, 2)

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
        assert "Wallet ID: 2" in out
        assert "Wallet ID: 3" in out

        #  Need to run the farmer to make further tests


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [10],
            "trusted": True,
            "reuse_puzhash": False,
        }
    ],
    indirect=True,
)
@pytest.mark.anyio
async def test_plotnft_cli_leave(
    wallet_environments: WalletTestFramework,
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
            await LeavePlotNFTCMD(
                rpc_info=NeedsWalletRPC(
                    client_info=client_info,
                    wallet_rpc_port=wallet_rpc.port,
                    fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
                ),
                id=None,
                dont_prompt=True,
            ).run()

        with pytest.raises(CliRpcConnectionError, match="is not a pool wallet"):
            await LeavePlotNFTCMD(
                rpc_info=NeedsWalletRPC(
                    client_info=client_info,
                    wallet_rpc_port=wallet_rpc.port,
                    fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
                ),
                id=15,
                dont_prompt=True,
            ).run()

        wallet_id = await create_new_plotnft(wallet_environments, 1)

        await LeavePlotNFTCMD(
            rpc_info=NeedsWalletRPC(
                client_info=client_info,
                wallet_rpc_port=wallet_rpc.port,
                fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
            ),
            id=wallet_id,
            dont_prompt=True,
        ).run()

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "<=#spendable_balance": 1,
                            "<=#max_send_amount": 1,
                            "pending_coin_removal_count": 0,
                        },
                        2: {"pending_coin_removal_count": 1},
                    },
                    post_block_balance_updates={
                        1: {
                            "<=#pending_coin_removal_count": 1,
                        },
                        2: {"pending_coin_removal_count": -1},
                    },
                )
            ]
        )

        await verify_pool_state(wallet_rpc, wallet_id, PoolSingletonState.LEAVING_POOL)

        await wallet_environments.full_node.farm_blocks_to_puzzlehash(count=12, guarantee_transaction_blocks=True)

        await verify_pool_state(wallet_rpc, wallet_id, PoolSingletonState.SELF_POOLING)


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [10],
            "trusted": True,
            "reuse_puzhash": False,
        }
    ],
    indirect=True,
)
@pytest.mark.anyio
async def test_plotnft_cli_join(
    wallet_environments: WalletTestFramework,
    mocker: MockerFixture,
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

        # Test error cases
        # No pool wallet found
        with pytest.raises(CliRpcConnectionError, match="No pool wallet found"):
            await JoinPlotNFTCMD(
                rpc_info=NeedsWalletRPC(
                    client_info=client_info,
                    wallet_rpc_port=wallet_rpc.port,
                    fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
                ),
                pool_url="http://127.0.0.1",
                id=None,
                dont_prompt=True,
            ).run()

        # Wallet id not a pool wallet
        with pytest.raises(CliRpcConnectionError, match="is not a pool wallet"):
            await JoinPlotNFTCMD(
                rpc_info=NeedsWalletRPC(
                    client_info=client_info,
                    wallet_rpc_port=wallet_rpc.port,
                    fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
                ),
                pool_url="http://127.0.0.1",
                id=1,
                dont_prompt=True,
            ).run()

        # Create a farming plotnft to url http://pool.example.com
        wallet_id = await create_new_plotnft(wallet_environments, 1)

        # Some more error cases
        with pytest.raises(CliRpcConnectionError, match="Error connecting to pool"):
            await JoinPlotNFTCMD(
                rpc_info=NeedsWalletRPC(
                    client_info=client_info,
                    wallet_rpc_port=wallet_rpc.port,
                    fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
                ),
                id=wallet_id,
                pool_url="http://127.0.0.1",
                dont_prompt=True,
            ).run()

            await JoinPlotNFTCMD(
                rpc_info=NeedsWalletRPC(
                    client_info=client_info,
                    wallet_rpc_port=wallet_rpc.port,
                    fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
                ),
                id=wallet_id,
                pool_url="",
                dont_prompt=True,
            ).run()

        # Mock the pool response
        pool_response = json.dumps(
            {
                "name": "Pool Name",
                "description": "Pool Description",
                "logo_url": "https://subdomain.pool-domain.tld/path/to/logo.svg",
                "target_puzzle_hash": "344587cf06a39db471d2cc027504e8688a0a67cce961253500c956c73603fd58",
                "fee": "0.01",
                "protocol_version": 1,
                "relative_lock_height": 5,
                "minimum_difficulty": 1,
                "authentication_token_timeout": 5,
            }
        )

        mock_get = mocker.patch("aiohttp.ClientSession.get")
        mock_get.return_value.__aenter__.return_value.status = 200
        mock_get.return_value.__aenter__.return_value.text.return_value = pool_response

        # Join the new pool - this will leave the prior pool and join the new one
        await JoinPlotNFTCMD(
            rpc_info=NeedsWalletRPC(
                client_info=client_info,
                wallet_rpc_port=wallet_rpc.port,
                fingerprint=wallet_state_manager.root_pubkey.get_fingerprint(),
            ),
            id=wallet_id,
            pool_url="http://127.0.0.1",
            dont_prompt=True,
        ).run()

        await wallet_environments.full_node.farm_blocks_to_puzzlehash(count=3, guarantee_transaction_blocks=True)

        verify_pool_state(wallet_rpc, wallet_id, PoolSingletonState.LEAVING_POOL)

        await wallet_environments.full_node.farm_blocks_to_puzzlehash(count=12, guarantee_transaction_blocks=True)

        verify_pool_state(wallet_rpc, wallet_id, PoolSingletonState.FARMING_TO_POOL)