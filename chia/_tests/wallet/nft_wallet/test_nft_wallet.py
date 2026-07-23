from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import pytest
from chia_rs import AugSchemeMPL
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64
from clvm_tools.binutils import disassemble

from chia._tests.cmds.test_cmd_framework import check_click_parsing
from chia._tests.conftest import ConsensusMode
from chia._tests.environments.wallet import (
    STANDARD_TX_ENDPOINT_ARGS,
    WalletEnvironment,
    WalletStateTransition,
    WalletTestFramework,
)
from chia._tests.util.time_out_assert import time_out_assert
from chia.cmds.cmd_classes import ChiaCliContext
from chia.cmds.cmd_helpers import NeedsTXConfig, NeedsWalletRPC, TransactionsOut
from chia.cmds.param_types import CliAddress
from chia.cmds.wallet import (
    AddUriToNftCMD,
    CreateNftWalletCMD,
    GetNftInfoCMD,
    ListNftsCMD,
    MintNftCMD,
    NftSignMessageCMD,
    SetNftDidCMD,
    TransferNftCMD,
)
from chia.rpc.rpc_client import ResponseFailureError
from chia.simulator.simulator_protocol import ReorgProtocol
from chia.types.blockchain_format.program import Program
from chia.types.signing_mode import CHIP_0002_SIGN_MESSAGE_PREFIX
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.timing import adjusted_timeout
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_request_types import (
    NFTCoin,
    NFTCountNFTs,
    NFTGetByDID,
    NFTGetInfo,
    NFTGetNFTs,
    NFTGetWalletDID,
    NFTMintNFTRequest,
    NFTSetDIDBulk,
    NFTSetNFTDID,
    NFTSetNFTStatus,
    NFTTransferBulk,
    NFTWalletWithDID,
    SignMessageByID,
)
from chia.wallet.wallet_rpc_api import MAX_NFT_CHUNK_SIZE
from chia.wallet.wallet_state_manager import WalletStateManager


async def get_nft_count(wallet: NFTWallet) -> int:
    return await wallet.get_nft_count()


async def get_wallet_number(manager: WalletStateManager) -> int:
    return len(manager.wallets)


# TODO: This is not a very paradigmatic function and should be updated
async def wait_rpc_state_condition(
    timeout: float,
    async_function: Any,
    params: list[Any],
    condition_func: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    __tracebackhide__ = True

    timeout = adjusted_timeout(timeout=timeout)

    start = time.monotonic()

    while True:
        resp = await async_function(*params)
        assert isinstance(resp, dict)
        if condition_func(resp):
            return resp

        now = time.monotonic()
        elapsed = now - start
        if elapsed >= timeout:
            raise asyncio.TimeoutError(
                f"timed out while waiting for {async_function.__name__}(): {elapsed} >= {timeout}",
            )

        await asyncio.sleep(0.3)


async def create_nft_wallet_via_cli(
    wallet_environments: WalletTestFramework,
    env: WalletEnvironment,
    *,
    name: str | None = None,
    did_id: CliAddress | None = None,
) -> None:
    await CreateNftWalletCMD(
        rpc_info=wallet_environments.cmd_tx_endpoint_args(env)["rpc_info"],
        did_id=did_id,
        name=name,
    ).run()


async def mint_nft_via_cli(
    wallet_environments: WalletTestFramework,
    env: WalletEnvironment,
    *,
    wallet_id: int,
    hash: str,
    uris: str | list[str],
    royalty_address: CliAddress | None = None,
    target_address: CliAddress | None = None,
    no_did_ownership: bool = False,
    metadata_hash: str | None = None,
    metadata_uris: str | None = None,
    license_hash: str | None = None,
    license_uris: str | None = None,
    edition_total: int = 1,
    edition_number: int = 1,
    fee: uint64 = uint64(0),
    royalty_percentage_fraction: int = 0,
    push: bool = True,
) -> None:
    await MintNftCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            "wallet_id": wallet_id,
            "hash": hash,
            "uris": ",".join(uris) if isinstance(uris, list) else uris,
            "royalty_address": royalty_address,
            "target_address": target_address,
            "no_did_ownership": no_did_ownership,
            "metadata_hash": metadata_hash,
            "metadata_uris": metadata_uris,
            "license_hash": license_hash,
            "license_uris": license_uris,
            "edition_total": edition_total,
            "edition_number": edition_number,
            "fee": fee,
            "royalty_percentage_fraction": royalty_percentage_fraction,
            "push": push,
        }
    ).run()


async def add_uri_to_nft_via_cli(
    wallet_environments: WalletTestFramework,
    env: WalletEnvironment,
    *,
    wallet_id: int,
    nft_coin_id: str,
    uri: str | None = None,
    metadata_uri: str | None = None,
    license_uri: str | None = None,
    fee: uint64 = uint64(0),
    push: bool = True,
) -> None:
    await AddUriToNftCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            "wallet_id": wallet_id,
            "nft_coin_id": nft_coin_id,
            "uri": uri,
            "metadata_uri": metadata_uri,
            "license_uri": license_uri,
            "fee": fee,
            "push": push,
        }
    ).run()


async def transfer_nft_via_cli(
    wallet_environments: WalletTestFramework,
    env: WalletEnvironment,
    *,
    wallet_id: int,
    nft_coin_id: str,
    target_address: CliAddress,
    fee: uint64 = uint64(0),
    push: bool = True,
) -> None:
    await TransferNftCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            "wallet_id": wallet_id,
            "nft_coin_id": nft_coin_id,
            "target_address": target_address,
            "fee": fee,
            "push": push,
        }
    ).run()


async def set_nft_did_via_cli(
    wallet_environments: WalletTestFramework,
    env: WalletEnvironment,
    *,
    wallet_id: int,
    did_id: str,
    nft_coin_id: str,
    fee: uint64 = uint64(0),
    push: bool = True,
) -> None:
    await SetNftDidCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            "wallet_id": wallet_id,
            "did_id": did_id,
            "nft_coin_id": nft_coin_id,
            "fee": fee,
            "push": push,
        }
    ).run()


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_wallet_creation_automatically(wallet_environments: WalletTestFramework) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_node_0 = env_0.node
    wallet_node_1 = env_1.node
    wallet_0 = env_0.xch_wallet
    wallet_1 = env_1.xch_wallet

    env_0.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, name="NFT WALLET 1"
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )

    async with nft_wallet_0.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_0.generate_new_nft(metadata, action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "max_send_amount": 0,
                        "pending_coin_removal_count": 1,  # a bit weird but correct?
                        "pending_change": 0,
                        "unspent_coin_count": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    await time_out_assert(30, get_nft_count, 1, nft_wallet_0)
    coins = await nft_wallet_0.get_current_nfts()
    assert len(coins) == 1, "nft not generated"

    async with wallet_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        wallet_1_ph = await action_scope.get_puzzle_hash(wallet_1.wallet_state_manager)
    async with nft_wallet_0.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_0.generate_signed_transaction(
            [uint64(coins[0].coin.amount)],
            [wallet_1_ph],
            action_scope,
            coins={coins[0].coin},
        )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {},
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                },
                post_block_balance_updates={
                    "xch": {},
                    "nft": {
                        "init": True,
                        "unspent_coin_count": 1,
                    },
                },
            ),
        ]
    )

    async def num_wallets() -> int:
        return len(await wallet_node_1.wallet_state_manager.get_all_wallet_info_entries())

    await time_out_assert(30, num_wallets, 2)
    # Get the new NFT wallet
    nft_wallets = await wallet_node_1.wallet_state_manager.get_all_wallet_info_entries(WalletType.NFT)
    assert len(nft_wallets) == 1
    nft_wallet_1 = wallet_node_1.wallet_state_manager.wallets[nft_wallets[0].id]
    assert isinstance(nft_wallet_1, NFTWallet)
    await time_out_assert(30, get_nft_count, 0, nft_wallet_0)
    await time_out_assert(30, get_nft_count, 1, nft_wallet_1)

    assert await nft_wallet_0.get_nft_count() == 0
    assert await nft_wallet_1.get_nft_count() == 1


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_wallet_creation_and_transfer(wallet_environments: WalletTestFramework) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    full_node_api = wallet_environments.full_node
    wallet_node_0 = env_0.node
    wallet_node_1 = env_1.node
    wallet_0 = env_0.xch_wallet
    wallet_1 = env_1.xch_wallet

    env_0.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
        wallet_node_0.wallet_state_manager, wallet_0, name="NFT WALLET 1"
    )
    metadata = Program.to(
        [
            ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
            ("h", "0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185"),
        ]
    )
    async with nft_wallet_0.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_0.generate_new_nft(metadata, action_scope)
    for tx in action_scope.side_effects.transactions:
        if tx.spend_bundle is not None:
            # ensure hints are generated
            assert len(compute_memos(tx.spend_bundle)) > 0

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "max_send_amount": 0,
                        "pending_coin_removal_count": 1,
                        "pending_change": 0,
                        "unspent_coin_count": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    await time_out_assert(10, get_nft_count, 1, nft_wallet_0)

    # Test Reorg mint
    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32.zeros, None)
    )
    await time_out_assert(60, full_node_api.full_node.blockchain.get_peak_height, height + 1)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, peak_height=uint32(height + 1), timeout=10)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_1, peak_height=uint32(height + 1), timeout=10)
    await env_0.change_balances(
        {
            "xch": {
                "set_remainder": True,  # Not testing XCH reorg functionality in this test
            },
            "nft": {
                # State back to before confirmation
                "unspent_coin_count": -1,
                "pending_coin_removal_count": 1,
            },
        }
    )
    await env_0.check_balances()

    await time_out_assert(30, get_nft_count, 0, nft_wallet_0)
    await time_out_assert(30, get_wallet_number, 2, wallet_node_0.wallet_state_manager)

    new_metadata = Program.to([("u", ["https://www.test.net/logo.svg"]), ("h", "0xD4584AD463139FA8C0D9F68F4B59F181")])

    async with nft_wallet_0.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_0.generate_new_nft(new_metadata, action_scope)
    for tx in action_scope.side_effects.transactions:
        if tx.spend_bundle is not None:
            # ensure hints are generated
            assert len(compute_memos(tx.spend_bundle)) > 0

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -2,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -2,
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                    },
                    "nft": {
                        "pending_coin_removal_count": -2,
                        "unspent_coin_count": 2,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    await time_out_assert(30, get_nft_count, 2, nft_wallet_0)
    coins = await nft_wallet_0.get_current_nfts()
    assert len(coins) == 2, "nft not generated"

    nft_wallet_1 = await NFTWallet.create_new_nft_wallet(
        wallet_node_1.wallet_state_manager, wallet_1, name="NFT WALLET 2"
    )
    async with wallet_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        wallet_1_ph = await action_scope.get_puzzle_hash(wallet_1.wallet_state_manager)
    async with nft_wallet_0.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_0.generate_signed_transaction(
            [uint64(coins[1].coin.amount)],
            [wallet_1_ph],
            action_scope,
            coins={coins[1].coin},
        )
    assert action_scope.side_effects.transactions[0].spend_bundle is not None

    assert len(compute_memos(action_scope.side_effects.transactions[0].spend_bundle)) > 0

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "nft": {
                        "pending_coin_removal_count": 1,
                    }
                },
                post_block_balance_updates={
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    }
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "nft": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "max_send_amount": 0,
                        "pending_coin_removal_count": 0,
                        "pending_change": 0,
                        "unspent_coin_count": 0,
                    }
                },
                post_block_balance_updates={
                    "nft": {
                        "unspent_coin_count": 1,
                    }
                },
            ),
        ]
    )

    await time_out_assert(30, get_nft_count, 1, nft_wallet_0)
    await time_out_assert(30, get_nft_count, 1, nft_wallet_1)

    coins = await nft_wallet_1.get_current_nfts()
    assert len(coins) == 1

    # Send it back to original owner
    async with wallet_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        wallet_0_ph = await action_scope.get_puzzle_hash(wallet_0.wallet_state_manager)
    async with nft_wallet_1.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await nft_wallet_1.generate_signed_transaction(
            [uint64(coins[0].coin.amount)],
            [wallet_0_ph],
            action_scope,
            coins={coins[0].coin},
        )
    assert action_scope.side_effects.transactions[0].spend_bundle is not None

    assert len(compute_memos(action_scope.side_effects.transactions[0].spend_bundle)) > 0

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "nft": {
                        "unspent_coin_count": 1,
                    }
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "nft": {
                        "pending_coin_removal_count": 1,
                    }
                },
                post_block_balance_updates={
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    }
                },
            ),
        ]
    )

    await time_out_assert(30, get_nft_count, 2, nft_wallet_0)
    await time_out_assert(30, get_nft_count, 0, nft_wallet_1)

    # Test Reorg
    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 2), bytes32.zeros, None)
    )

    await full_node_api.wait_for_self_synced()
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, peak_height=uint32(height + 2))
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_1, peak_height=uint32(height + 2))

    await env_0.change_balances(
        {
            "nft": {
                "unspent_coin_count": -1,
            }
        }
    )
    await env_1.change_balances(
        {
            "nft": {
                "pending_coin_removal_count": 1,
                "unspent_coin_count": 1,
            }
        }
    )
    await env_0.check_balances()
    await env_1.check_balances()

    await time_out_assert(30, get_nft_count, 1, nft_wallet_0)
    await time_out_assert(30, get_nft_count, 1, nft_wallet_1)

    # Test an error case
    with pytest.raises(ResponseFailureError, match="The NFT doesn't support setting a DID"):
        await env_1.rpc_client.set_nft_did(
            NFTSetNFTDID(
                wallet_id=uint32(env_1.wallet_aliases["nft"]),
                did_id=None,
                nft_coin_id=(
                    await env_1.rpc_client.list_nfts(NFTGetNFTs(wallet_id=uint32(env_1.wallet_aliases["nft"])))
                )
                .nft_list[0]
                .nft_coin_id,
            ),
            tx_config=wallet_environments.tx_config,
        )


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_wallet_rpc_creation_and_list(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet = env.xch_wallet

    env.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    await create_nft_wallet_via_cli(wallet_environments, env, name="NFT WALLET 1")
    assert env.wallet_aliases["nft"] in env.wallet_state_manager.wallets

    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        wallet_ph = await action_scope.get_puzzle_hash(wallet.wallet_state_manager)
    royalty_address = CliAddress(
        wallet_ph,
        encode_puzzle_hash(wallet_ph, AddressType.XCH.hrp(env.node.config)),
        AddressType.XCH,
    )
    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft"],
        royalty_address=royalty_address,
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        no_did_ownership=True,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},  # tested above
                    "nft": {"init": True, "pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},  # tested above
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            )
        ]
    )

    await wait_rpc_state_condition(
        30, env.rpc_client.fetch, ["nft_get_nfts", dict(wallet_id=env.wallet_aliases["nft"])], lambda x: x["nft_list"]
    )
    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft"],
        royalty_address=royalty_address,
        hash="0xD4584AD463139FA8C0D9F68F4B59F184D4584AD463139FA8C0D9F68F4B59F184",
        uris=["https://chialisp.com/img/logo.svg"],
        metadata_uris=(
            "https://bafybeigzcazxeu7epmm4vtkuadrvysv74lbzzbl2evphtae6k57yhgynp4.ipfs.nftstorage.link/6590.json"
        ),
        metadata_hash="0x6a9cb99b7b9a987309e8dd4fd14a7ca2423858585da68cc9ec689669dd6dd6ab",
        no_did_ownership=True,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},  # tested above
                    "nft": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},  # tested above
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            )
        ]
    )

    coins_response = await wait_rpc_state_condition(
        30,
        env.rpc_client.fetch,
        ["nft_get_nfts", dict(wallet_id=env.wallet_aliases["nft"])],
        lambda x: x["success"] and len(x["nft_list"]) == 2,
    )
    coins: list[NFTInfo] = [NFTInfo.from_json_dict(d) for d in coins_response["nft_list"]]
    uris = []
    for coin in coins:
        assert not coin.supports_did
        uris.append(coin.data_uris[0])
        assert coin.mint_height > 0
    assert len(uris) == 2
    assert "https://chialisp.com/img/logo.svg" in uris

    coins_response = await wait_rpc_state_condition(
        5,
        env.rpc_client.fetch,
        ["nft_get_nfts", {"wallet_id": env.wallet_aliases["nft"], "start_index": 1, "num": 1}],
        lambda x: x["success"] and len(x["nft_list"]) == 1,
    )
    coins = [NFTInfo.from_json_dict(d) for d in coins_response["nft_list"]]
    assert len(coins) == 1
    assert coins[0].data_hash.hex() == "0xD4584AD463139FA8C0D9F68F4B59F184D4584AD463139FA8C0D9F68F4B59F184"[2:].lower()

    # test counts
    assert (await env.rpc_client.count_nfts(NFTCountNFTs(wallet_id=uint32(env.wallet_aliases["nft"])))).count == 2
    assert (await env.rpc_client.count_nfts(NFTCountNFTs())).count == 2
    with pytest.raises(ResponseFailureError, match="Wallet with id 50 does not exist"):
        await env.rpc_client.count_nfts(NFTCountNFTs(wallet_id=uint32(50)))


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_sign_message_by_nft_id(
    wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]
) -> None:
    env = wallet_environments.environments[0]
    wallet = env.xch_wallet

    env.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    await create_nft_wallet_via_cli(wallet_environments, env, name="NFT WALLET 1")
    assert env.wallet_aliases["nft"] in env.wallet_state_manager.wallets

    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        wallet_ph = await action_scope.get_puzzle_hash(wallet.wallet_state_manager)
    royalty_address = CliAddress(
        wallet_ph,
        encode_puzzle_hash(wallet_ph, AddressType.XCH.hrp(env.node.config)),
        AddressType.XCH,
    )
    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft"],
        royalty_address=royalty_address,
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        no_did_ownership=True,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},  # tested above
                    "nft": {"init": True, "pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},  # tested above
                    "nft": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            )
        ]
    )

    nft_list = await env.rpc_client.list_nfts(NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft"])))
    nft_id = nft_list.nft_list[0].nft_id
    nft_cli_address = CliAddress(decode_puzzle_hash(nft_id), nft_id, AddressType.NFT)

    # Test CLI signing
    message = "Hello World"
    capsys.readouterr()
    await NftSignMessageCMD(
        rpc_info=wallet_environments.cmd_tx_endpoint_args(env)["rpc_info"],
        nft_id=nft_cli_address,
        hex_message=message.encode().hex(),
    ).run()
    output = capsys.readouterr().out
    assert f"Message: {message.encode().hex()}" in output
    assert "Public Key:" in output
    assert "Signature:" in output

    # Test general string
    message = "Hello World"
    response = await env.rpc_client.sign_message_by_id(
        SignMessageByID(
            id=nft_id,
            message=message,
        )
    )
    puzzle: Program = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message))
    assert AugSchemeMPL.verify(
        response.pubkey,
        puzzle.get_tree_hash(),
        response.signature,
    )
    # Test hex string
    message = "0123456789ABCDEF"
    response = await env.rpc_client.sign_message_by_id(
        SignMessageByID(
            id=nft_id,
            message=message,
            is_hex=True,
        )
    )
    puzzle = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message)))

    assert AugSchemeMPL.verify(
        response.pubkey,
        puzzle.get_tree_hash(),
        response.signature,
    )

    # Test BLS sign string
    message = "Hello World"
    response = await env.rpc_client.sign_message_by_id(
        SignMessageByID(
            id=nft_id,
            message=message,
            is_hex=False,
            safe_mode=False,
        )
    )

    assert AugSchemeMPL.verify(
        response.pubkey,
        bytes(message, "utf-8"),
        response.signature,
    )
    # Test BLS sign hex
    message = "0123456789ABCDEF"
    response = await env.rpc_client.sign_message_by_id(
        SignMessageByID(
            id=nft_id,
            message=message,
            is_hex=True,
            safe_mode=False,
        )
    )

    assert AugSchemeMPL.verify(
        response.pubkey,
        hexstr_to_bytes(message),
        response.signature,
    )


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_wallet_rpc_update_metadata(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet_node = env.node
    wallet = env.xch_wallet

    env.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    nft_wallet = await NFTWallet.create_new_nft_wallet(wallet_node.wallet_state_manager, wallet, name="NFT WALLET 1")

    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=nft_wallet.id(),
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        no_did_ownership=True,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "nft": {"init": True, "pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "nft": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            )
        ]
    )

    coins: list[NFTInfo] = (
        await env.rpc_client.list_nfts(NFTGetNFTs(wallet_id=nft_wallet.id(), start_index=uint32(0), num=uint32(1)))
    ).nft_list
    coin = coins[0]
    assert coin.mint_height > 0
    assert coin.data_hash == bytes32.from_hexstr("0xd4584ad463139fa8c0d9f68f4b59f185d4584ad463139fa8c0d9f68f4b59f185")
    assert coin.chain_info == disassemble(
        Program.to(
            [
                ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
                ("h", hexstr_to_bytes("0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185")),
                ("mu", []),
                ("lu", []),
                ("sn", uint64(1)),
                ("st", uint64(1)),
            ]
        )
    )

    nft_coin_id = encode_puzzle_hash(coin.nft_coin_id, AddressType.NFT.hrp(env.node.config))
    await add_uri_to_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=nft_wallet.id(),
        nft_coin_id=nft_coin_id,
        metadata_uri="http://metadata",
    )

    coins = (
        await env.rpc_client.list_nfts(NFTGetNFTs(wallet_id=nft_wallet.id(), start_index=uint32(0), num=uint32(1)))
    ).nft_list
    assert coins[0].pending_transaction

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "nft": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {},
                    "nft": {"pending_coin_removal_count": -1},
                },
            ),
        ]
    )

    # check that new URI was added
    coins = (
        await env.rpc_client.list_nfts(NFTGetNFTs(wallet_id=nft_wallet.id(), start_index=uint32(0), num=uint32(1)))
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.mint_height > 0
    uris = coin.data_uris
    assert len(uris) == 1
    assert "https://www.chia.net/img/branding/chia-logo.svg" in uris
    assert len(coin.metadata_uris) == 1
    assert "http://metadata" == coin.metadata_uris[0]
    assert len(coin.license_uris) == 0

    # add yet another URI, this time using a hex nft_coin_id
    await add_uri_to_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=nft_wallet.id(),
        nft_coin_id=coin.nft_coin_id.hex(),
        uri="http://data",
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "nft": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {},
                    "nft": {"pending_coin_removal_count": -1},
                },
            ),
        ]
    )

    coins = (
        await env.rpc_client.list_nfts(NFTGetNFTs(wallet_id=nft_wallet.id(), start_index=uint32(0), num=uint32(1)))
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.mint_height > 0
    uris = coin.data_uris
    assert len(uris) == 2
    assert len(coin.metadata_uris) == 1
    assert "http://data" == coin.data_uris[0]


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_with_did_wallet_creation(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet_node = env.node
    wallet = env.xch_wallet

    env.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft_w_did": 3,
        "nft_no_did": 4,
    }

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        did_wallet = await DIDWallet.create_new_did_wallet(env.wallet_state_manager, wallet, uint64(1), action_scope)

    # use "set_remainder" here because this is more of a DID test issue
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
            )
        ]
    )

    hex_did_id = did_wallet.get_my_DID()
    did_id = bytes32.from_hexstr(hex_did_id)
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(env.node.config))

    nft_wallet = await NFTWallet.create_new_nft_wallet(
        wallet_node.wallet_state_manager, wallet, name="NFT WALLET 1", did_id=did_id
    )

    # this shouldn't work
    res = await env.rpc_client.fetch(
        "create_new_wallet", dict(wallet_type="nft_wallet", name="NFT WALLET 1", did_id=hmr_did_id)
    )
    assert res["wallet_id"] == nft_wallet.id()

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={"nft_w_did": {"init": True}},
                post_block_balance_updates={},
            )
        ]
    )

    # now create NFT wallet with P2 standard puzzle for inner puzzle
    await create_nft_wallet_via_cli(wallet_environments, env, name="NFT WALLET 0")
    nft_wallet_p2_puzzle = env.wallet_aliases["nft_no_did"]
    assert nft_wallet_p2_puzzle != nft_wallet.id()

    with pytest.raises(ResponseFailureError, match="Cannot find a NFT wallet DID"):
        await env.rpc_client.get_nft_wallet_by_did(NFTGetByDID(did_id=encode_puzzle_hash(bytes32.zeros, "did")))
    wallet_by_did_response = await env.rpc_client.get_nft_wallet_by_did(NFTGetByDID(did_id=hmr_did_id))
    assert nft_wallet.id() == wallet_by_did_response.wallet_id

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={"nft_no_did": {"init": True}},
                post_block_balance_updates={},
            )
        ]
    )

    assert (await env.rpc_client.get_nft_wallets_with_dids()).nft_wallets == [
        NFTWalletWithDID(wallet_id=nft_wallet.id(), did_id=hmr_did_id, did_wallet_id=did_wallet.id())
    ]

    get_did_res = await env.rpc_client.get_nft_wallet_did(NFTGetWalletDID(wallet_id=nft_wallet.id()))
    assert get_did_res.did_id == hmr_did_id

    # Create a NFT with DID
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        nft_ph = await action_scope.get_puzzle_hash(wallet.wallet_state_manager)
    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=nft_wallet.id(),
        target_address=CliAddress(nft_ph, encode_puzzle_hash(nft_ph, "txch"), AddressType.XCH),
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            )
        ]
    )
    # Create a NFT without DID, this will go the unassigned NFT wallet
    resp = await env.rpc_client.mint_nft(
        request=NFTMintNFTRequest(
            wallet_id=nft_wallet.id(),
            royalty_address=None,
            target_address=None,
            hash=bytes32.from_hexstr("0xD4584AD463139FA8C0D9F68F4B59F181D4584AD463139FA8C0D9F68F4B59F181"),
            uris=["https://url1"],
            did_id="",
            push=True,
        ),
        tx_config=wallet_environments.tx_config,
    )

    # ensure hints are generated
    assert len(compute_memos(resp.spend_bundle)) > 0

    # TODO: the "pending_coin_removal_count" here is a bit weird. I think it's right
    # but it might be worth refactoring the minting flow generally to only add transaction
    # records for the xch wallet rather than some arbitrary nft wallet.
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {},
                    "nft_w_did": {"pending_coin_removal_count": 1},
                    "nft_no_did": {},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {},
                    "nft_w_did": {"pending_coin_removal_count": -1},
                    "nft_no_did": {"unspent_coin_count": 1},
                },
            )
        ]
    )
    # Check DID NFT
    coins: list[NFTInfo] = (
        await env.rpc_client.list_nfts(NFTGetNFTs(wallet_id=nft_wallet.id(), start_index=uint32(0), num=uint32(1)))
    ).nft_list
    assert len(coins) == 1
    did_nft = coins[0]
    assert did_nft.mint_height > 0
    assert did_nft.supports_did
    assert did_nft.data_uris[0] == "https://www.chia.net/img/branding/chia-logo.svg"
    assert did_nft.data_hash == bytes32.from_hexstr(
        "0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185"
    )
    assert did_nft.owner_did is not None
    assert did_nft.owner_did.hex() == hex_did_id
    # Check unassigned NFT
    nft_wallets = await env.wallet_state_manager.get_all_wallet_info_entries(WalletType.NFT)
    assert len(nft_wallets) == 2
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(nft_wallet_p2_puzzle), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    non_did_nft = coins[0]
    assert non_did_nft.mint_height > 0
    assert non_did_nft.supports_did
    assert non_did_nft.data_uris[0] == "https://url1"
    assert non_did_nft.data_hash == bytes32.from_hexstr(
        "0xD4584AD463139FA8C0D9F68F4B59F181D4584AD463139FA8C0D9F68F4B59F181"
    )
    assert non_did_nft.owner_did is None


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_rpc_mint(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet = env.xch_wallet

    env.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft_w_did": 3,
        "nft_no_did": 4,
    }

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        did_wallet = await DIDWallet.create_new_did_wallet(env.wallet_state_manager, wallet, uint64(1), action_scope)

    # use "set_remainder" here because this is more of a DID test issue
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
            )
        ]
    )

    did_id = encode_puzzle_hash(bytes32.from_hexstr(did_wallet.get_my_DID()), AddressType.DID.hrp(env.node.config))

    await create_nft_wallet_via_cli(
        wallet_environments,
        env,
        name="NFT WALLET 1",
        did_id=CliAddress(decode_puzzle_hash(did_id), did_id, AddressType.DID),
    )
    assert env.wallet_aliases["nft_w_did"] in env.wallet_state_manager.wallets

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={"nft_w_did": {"init": True}},
                post_block_balance_updates={},
            )
        ]
    )

    # Create a NFT with DID
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        royalty_address = await action_scope.get_puzzle_hash(wallet.wallet_state_manager)
    royalty_cli = CliAddress(
        royalty_address,
        encode_puzzle_hash(royalty_address, AddressType.XCH.hrp(env.node.config)),
        AddressType.XCH,
    )
    data_hash_param = "0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185"
    license_uris = ["http://mylicenseuri"]
    license_hash = "0xcafef00dcafef00dcafef00dcafef00dcafef00dcafef00dcafef00dcafef00d"
    meta_uris = ["http://metauri"]
    meta_hash = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    royalty_percentage = 200
    sn = 10
    st = 100
    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft_w_did"],
        royalty_address=royalty_cli,
        target_address=royalty_cli,
        hash=data_hash_param,
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        metadata_hash=meta_hash,
        metadata_uris=",".join(meta_uris),
        license_hash=license_hash,
        license_uris=",".join(license_uris),
        edition_total=st,
        edition_number=sn,
        royalty_percentage_fraction=royalty_percentage,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            )
        ]
    )

    coins: list[NFTInfo] = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft_w_did"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    did_nft = coins[0]
    assert did_nft.royalty_puzzle_hash == royalty_address
    assert did_nft.data_hash == bytes.fromhex(data_hash_param[2:])
    assert did_nft.metadata_hash == bytes.fromhex(meta_hash[2:])
    assert did_nft.metadata_uris == meta_uris
    assert did_nft.license_uris == license_uris
    assert did_nft.license_hash == bytes.fromhex(license_hash[2:])
    assert did_nft.edition_total == st
    assert did_nft.edition_number == sn
    assert did_nft.royalty_percentage == royalty_percentage


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_transfer_nft_with_did(wallet_environments: WalletTestFramework) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_0 = env_0.xch_wallet
    wallet_1 = env_1.xch_wallet

    env_0.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
        "nft_w_did": 4,
    }
    # Create DID
    async with wallet_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        did_wallet = await DIDWallet.create_new_did_wallet(
            env_0.wallet_state_manager, wallet_0, uint64(1), action_scope
        )

    # use "set_remainder" here because this is more of a DID test issue
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
            ),
            WalletStateTransition(),
        ]
    )

    hex_did_id = did_wallet.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(env_0.node.config))

    # Create NFT wallet
    await create_nft_wallet_via_cli(
        wallet_environments,
        env_0,
        name="NFT WALLET 1",
        did_id=CliAddress(
            bytes32.from_hexstr(hex_did_id),
            hmr_did_id,
            AddressType.DID,
        ),
    )
    assert env_0.wallet_aliases["nft"] in env_0.wallet_state_manager.wallets

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "nft": {"init": True},
                },
                post_block_balance_updates={},
            ),
            WalletStateTransition(),
        ]
    )

    # Create a NFT with DID
    fee = 100
    await mint_nft_via_cli(
        wallet_environments,
        env_0,
        wallet_id=env_0.wallet_aliases["nft"],
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        fee=uint64(fee),
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee - 1,
                        "<=#spendable_balance": -fee - 1,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -fee - 1,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee - 1,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            ),
            WalletStateTransition(),
        ]
    )

    # Check DID NFT
    coins: list[NFTInfo] = (
        await env_0.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env_0.wallet_aliases["nft"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.owner_did is not None
    assert coin.owner_did.hex() == hex_did_id

    assert len(env_1.wallet_state_manager.wallets) == 1, "NFT wallet shouldn't exist yet"
    assert len(env_0.wallet_state_manager.wallets) == 3

    # transfer DID to the other wallet
    async with wallet_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        wallet_1_ph = await action_scope.get_puzzle_hash(wallet_1.wallet_state_manager)
    async with did_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await did_wallet.transfer_did(wallet_1_ph, uint64(0), action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "did": {
                        "unconfirmed_wallet_balance": -1,
                        "spendable_balance": -1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    }
                },
                post_block_balance_updates={},  # DID wallet is deleted
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "did": {
                        "init": True,
                        "set_remainder": True,  # only important to test creation
                    }
                },
            ),
        ]
    )

    # Transfer NFT, wallet will be deleted
    async with wallet_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        wallet_1_ph = await action_scope.get_puzzle_hash(wallet_1.wallet_state_manager)
    await transfer_nft_via_cli(
        wallet_environments,
        env_0,
        wallet_id=env_0.wallet_aliases["nft"],
        nft_coin_id=coin.nft_coin_id.hex(),
        target_address=CliAddress(
            wallet_1_ph,
            encode_puzzle_hash(wallet_1_ph, "xch"),
            AddressType.XCH,
        ),
        fee=uint64(fee),
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "<=#spendable_balance": -fee,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -fee,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    }
                    # nft wallet deleted
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "nft": {"init": True, "unspent_coin_count": 1},
                },
            ),
        ]
    )

    # Check if the NFT owner DID is reset
    wallet_by_did_response = await env_1.rpc_client.get_nft_wallet_by_did(NFTGetByDID())
    assert env_1.wallet_aliases["nft"] == wallet_by_did_response.wallet_id
    coins = (
        await env_1.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env_1.wallet_aliases["nft"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.owner_did is None
    assert coin.minter_did is not None
    assert coin.minter_did.hex() == hex_did_id
    nft_coin_id = coin.nft_coin_id

    # Set DID
    await set_nft_did_via_cli(
        wallet_environments,
        env_1,
        wallet_id=env_1.wallet_aliases["nft"],
        did_id=hmr_did_id,
        nft_coin_id=nft_coin_id.hex() if isinstance(nft_coin_id, bytes32) else str(nft_coin_id),
        fee=uint64(fee),
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "<=#spendable_balance": -fee,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -fee,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft": {"pending_coin_removal_count": -1, "unspent_coin_count": -1},
                    "nft_w_did": {"init": True, "unspent_coin_count": 1},
                },
            ),
        ]
    )

    wallet_by_did_response = await env_1.rpc_client.get_nft_wallet_by_did(NFTGetByDID(did_id=hmr_did_id))
    assert env_1.wallet_aliases["nft_w_did"] == wallet_by_did_response.wallet_id
    # Check NFT DID is set now
    coins = (
        await env_1.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env_1.wallet_aliases["nft_w_did"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.owner_did is not None
    assert coin.owner_did.hex() == hex_did_id


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_update_metadata_for_nft_did(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet = env.xch_wallet

    env.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft": 3,
    }

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        did_wallet = await DIDWallet.create_new_did_wallet(env.wallet_state_manager, wallet, uint64(1), action_scope)

    # use "set_remainder" here because this is more of a DID test issue
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
            ),
        ]
    )

    hex_did_id = did_wallet.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(env.node.config))

    # Create NFT wallet
    await create_nft_wallet_via_cli(
        wallet_environments,
        env,
        name="NFT WALLET 1",
        did_id=CliAddress(
            bytes32.from_hexstr(hex_did_id),
            hmr_did_id,
            AddressType.DID,
        ),
    )
    assert env.wallet_aliases["nft"] in env.wallet_state_manager.wallets

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "nft": {"init": True},
                },
                post_block_balance_updates={},
            ),
        ]
    )

    # Create a NFT with DID
    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft"],
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        metadata_uris="https://www.chia.net/img/branding/chia-logo.svg",
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            ),
        ]
    )

    # Check DID NFT

    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.minter_did is not None
    assert coin.minter_did.hex() == hex_did_id
    nft_coin_id = coin.nft_coin_id

    # add another URI
    fee = 100
    await add_uri_to_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft"],
        nft_coin_id=nft_coin_id.hex(),
        metadata_uri="http://metadata",
        fee=uint64(fee),
    )

    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.pending_transaction

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "<=#spendable_balance": -fee,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -fee,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "nft": {"pending_coin_removal_count": -1},
                },
            ),
        ]
    )

    # check that new URI was added
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1

    assert coins[0].minter_did is not None
    assert coins[0].minter_did.hex() == hex_did_id
    assert coins[0].mint_height > 0
    uris = coins[0].data_uris
    assert len(uris) == 1
    assert "https://www.chia.net/img/branding/chia-logo.svg" in uris
    assert len(coins[0].metadata_uris) == 2
    assert "http://metadata" == coins[0].metadata_uris[0]
    assert len(coins[0].license_uris) == 0


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_bulk_set_did(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet = env.xch_wallet

    env.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft_w_did": 3,
        "nft_no_did": 4,
    }

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        did_wallet = await DIDWallet.create_new_did_wallet(env.wallet_state_manager, wallet, uint64(1), action_scope)

    # use "set_remainder" here because this is more of a DID test issue
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
            ),
        ]
    )

    hex_did_id = did_wallet.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(env.node.config))
    await create_nft_wallet_via_cli(
        wallet_environments,
        env,
        name="NFT WALLET 1",
        did_id=CliAddress(
            bytes32.from_hexstr(hex_did_id),
            hmr_did_id,
            AddressType.DID,
        ),
    )
    assert env.wallet_aliases["nft_w_did"] in env.wallet_state_manager.wallets
    await create_nft_wallet_via_cli(wallet_environments, env, name="NFT WALLET 2")
    assert env.wallet_aliases["nft_no_did"] in env.wallet_state_manager.wallets

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "nft_w_did": {"init": True},
                    "nft_no_did": {"init": True},
                },
                post_block_balance_updates={},
            ),
        ]
    )

    # Create an NFT with DID
    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft_w_did"],
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        metadata_uris="https://www.chia.net/img/branding/chia-logo.svg",
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            )
        ]
    )

    # And one w/o
    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft_no_did"],
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        metadata_uris="https://www.chia.net/img/branding/chia-logo.svg",
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft_no_did": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "nft_no_did": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            )
        ]
    )

    # Make a second one w/ DID to test "bulk" updating in same wallet
    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft_w_did"],
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        metadata_uris="https://www.chia.net/img/branding/chia-logo.svg",
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            )
        ]
    )

    # Check DID NFT
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft_w_did"]), start_index=uint32(0), num=uint32(2))
        )
    ).nft_list
    assert len(coins) == 2
    nft1 = coins[0]
    nft12 = coins[1]
    assert nft1.owner_did is not None
    assert nft12.owner_did is not None
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft_no_did"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    nft2 = coins[0]
    assert nft2.owner_did is None
    nft_coin_list = [
        NFTCoin(wallet_id=uint32(env.wallet_aliases["nft_w_did"]), nft_coin_id=nft1.nft_coin_id.hex()),
        NFTCoin(
            wallet_id=uint32(env.wallet_aliases["nft_w_did"]), nft_coin_id=encode_puzzle_hash(nft12.launcher_id, "nft")
        ),
        NFTCoin(wallet_id=uint32(env.wallet_aliases["nft_no_did"]), nft_coin_id=nft2.nft_coin_id.hex()),
    ]
    fee = uint64(1000)
    with pytest.raises(ResponseFailureError, match="You can only set"):
        await env.rpc_client.set_nft_did_bulk(
            NFTSetDIDBulk(
                did_id=hmr_did_id, nft_coin_list=[nft_coin_list[0]] * (MAX_NFT_CHUNK_SIZE + 1), fee=fee, push=True
            ),
            wallet_environments.tx_config,
        )
    set_did_bulk_resp = await env.rpc_client.set_nft_did_bulk(
        NFTSetDIDBulk(did_id=hmr_did_id, nft_coin_list=nft_coin_list, fee=fee, push=True),
        wallet_environments.tx_config,
    )
    assert len(set_did_bulk_resp.spend_bundle.coin_spends) == 5
    assert set_did_bulk_resp.tx_num == 5  # 1 for each NFT being spent (3), 1 for fee tx, 1 for did tx
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft_w_did"]), start_index=uint32(0), num=uint32(2))
        )
    ).nft_list
    assert len(coins) == 2
    nft1 = coins[0]
    nft12 = coins[1]
    assert nft1.pending_transaction
    assert nft12.pending_transaction

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "<=#spendable_balance": -fee,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -fee,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": 2},
                    "nft_no_did": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": -2, "unspent_coin_count": 1},
                    "nft_no_did": {"pending_coin_removal_count": -1, "unspent_coin_count": -1},
                },
            )
        ]
    )

    wallet_by_did_response = await env.rpc_client.get_nft_wallet_by_did(NFTGetByDID(did_id=hmr_did_id))
    assert env.wallet_aliases["nft_w_did"] == wallet_by_did_response.wallet_id
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft_w_did"]), start_index=uint32(0), num=uint32(3))
        )
    ).nft_list
    assert len(coins) == 3
    nft1 = coins[0]
    nft12 = coins[1]
    nft13 = coins[2]
    nft_wallet_to_check = env.wallet_state_manager.wallets[uint32(env.wallet_aliases["nft_w_did"])]
    assert isinstance(nft_wallet_to_check, NFTWallet)
    assert await nft_wallet_to_check.get_nft_count() == 3

    assert nft1.owner_did is not None
    assert nft1.owner_did.hex() == hex_did_id
    assert nft12.owner_did is not None
    assert nft12.owner_did.hex() == hex_did_id
    assert nft13.owner_did is not None
    assert nft13.owner_did.hex() == hex_did_id


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_bulk_transfer(wallet_environments: WalletTestFramework) -> None:
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_0 = env_0.xch_wallet
    wallet_1 = env_1.xch_wallet

    env_0.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "nft_w_did": 3,
        "nft_no_did": 4,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }
    async with env_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        did_wallet = await DIDWallet.create_new_did_wallet(
            env_0.wallet_state_manager, wallet_0, uint64(1), action_scope
        )

    # use "set_remainder" here because this is more of a DID test issue
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                },
            ),
            WalletStateTransition(),
        ]
    )

    hex_did_id = did_wallet.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(env_0.node.config))

    await create_nft_wallet_via_cli(
        wallet_environments,
        env_0,
        name="NFT WALLET 1",
        did_id=CliAddress(
            bytes32.from_hexstr(hex_did_id),
            hmr_did_id,
            AddressType.DID,
        ),
    )
    await create_nft_wallet_via_cli(wallet_environments, env_0, name="NFT WALLET 2")
    assert env_0.wallet_aliases["nft_w_did"] in env_0.wallet_state_manager.wallets
    assert env_0.wallet_aliases["nft_no_did"] in env_0.wallet_state_manager.wallets

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "nft_w_did": {"init": True},
                    "nft_no_did": {"init": True},
                },
                post_block_balance_updates={},
            ),
            WalletStateTransition(),
        ]
    )

    # Create an NFT with DID
    await mint_nft_via_cli(
        wallet_environments,
        env_0,
        wallet_id=env_0.wallet_aliases["nft_w_did"],
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        metadata_uris="https://www.chia.net/img/branding/chia-logo.svg",
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            )
        ]
    )

    # And one w/o
    await mint_nft_via_cli(
        wallet_environments,
        env_0,
        wallet_id=env_0.wallet_aliases["nft_no_did"],
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        metadata_uris="https://www.chia.net/img/branding/chia-logo.svg",
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft_no_did": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "nft_no_did": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            )
        ]
    )

    # Make a second one w/ DID to test "bulk" updating in same wallet
    await mint_nft_via_cli(
        wallet_environments,
        env_0,
        wallet_id=env_0.wallet_aliases["nft_w_did"],
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        metadata_uris="https://www.chia.net/img/branding/chia-logo.svg",
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft_w_did": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            )
        ]
    )

    # Check DID NFT
    coins = (
        await env_0.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env_0.wallet_aliases["nft_w_did"]), start_index=uint32(0), num=uint32(2))
        )
    ).nft_list
    assert len(coins) == 2
    nft1 = coins[0]
    nft12 = coins[1]
    assert nft1.owner_did is not None
    assert nft12.owner_did is not None
    coins = (
        await env_0.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env_0.wallet_aliases["nft_no_did"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    nft2 = coins[0]
    assert nft2.owner_did is None
    nft_coin_list = [
        NFTCoin(wallet_id=uint32(env_0.wallet_aliases["nft_w_did"]), nft_coin_id=nft1.nft_coin_id.hex()),
        NFTCoin(
            wallet_id=uint32(env_0.wallet_aliases["nft_w_did"]),
            nft_coin_id=encode_puzzle_hash(nft12.launcher_id, "nft"),
        ),
        NFTCoin(wallet_id=uint32(env_0.wallet_aliases["nft_no_did"]), nft_coin_id=nft2.nft_coin_id.hex()),
    ]

    async with wallet_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        wallet_1_ph = await action_scope.get_puzzle_hash(wallet_1.wallet_state_manager)
    fee = uint64(1000)
    address = encode_puzzle_hash(wallet_1_ph, AddressType.XCH.hrp(env_1.node.config))
    with pytest.raises(ResponseFailureError, match="You can only transfer"):
        await env_0.rpc_client.transfer_nft_bulk(
            NFTTransferBulk(target_address=address, nft_coin_list=[nft_coin_list[0]] * (MAX_NFT_CHUNK_SIZE + 1)),
            wallet_environments.tx_config,
        )
    bulk_transfer_resp = await env_0.rpc_client.transfer_nft_bulk(
        NFTTransferBulk(target_address=address, nft_coin_list=nft_coin_list, fee=fee, push=True),
        wallet_environments.tx_config,
    )
    assert len(bulk_transfer_resp.spend_bundle.coin_spends) == 4
    assert bulk_transfer_resp.tx_num == 4

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "<=#spendable_balance": -fee,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -fee,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {},
                    "nft_w_did": {"pending_coin_removal_count": 2},
                    "nft_no_did": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "did": {},
                    "nft_w_did": {"pending_coin_removal_count": -2, "unspent_coin_count": -2},
                    "nft_no_did": {"pending_coin_removal_count": -1, "unspent_coin_count": -1},
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                },
                post_block_balance_updates={
                    "xch": {},
                    "nft": {"init": True, "unspent_coin_count": 3},
                },
            ),
        ]
    )

    await time_out_assert(30, get_wallet_number, 2, env_1.wallet_state_manager)
    coins = (
        await env_1.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env_1.wallet_aliases["nft"]), start_index=uint32(0), num=uint32(3))
        )
    ).nft_list
    assert len(coins) == 3
    nft0 = coins[0]
    nft02 = coins[1]
    nft03 = coins[2]
    nft_set = {nft1.launcher_id, nft12.launcher_id, nft2.launcher_id}
    assert nft0.launcher_id in nft_set
    assert nft02.launcher_id in nft_set
    assert nft03.launcher_id in nft_set
    assert nft0.owner_did is None
    assert nft02.owner_did is None
    assert nft03.owner_did is None


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_nft_set_did(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    wallet = env.xch_wallet

    env.wallet_aliases = {
        "xch": 1,
        "did1": 2,
        "nft_w_did1": 3,
        "nft_no_did": 4,
        "did2": 5,
        "nft_w_did2": 6,
    }

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        did_wallet = await DIDWallet.create_new_did_wallet(env.wallet_state_manager, wallet, uint64(1), action_scope)

    # use "set_remainder" here because this is more of a DID test issue
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did1": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did1": {"set_remainder": True},
                },
            )
        ]
    )

    hex_did_id = did_wallet.get_my_DID()
    hmr_did_id = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id), AddressType.DID.hrp(env.node.config))

    await create_nft_wallet_via_cli(
        wallet_environments,
        env,
        name="NFT WALLET 1",
        did_id=CliAddress(
            bytes32.from_hexstr(hex_did_id),
            hmr_did_id,
            AddressType.DID,
        ),
    )
    assert env.wallet_aliases["nft_w_did1"] in env.wallet_state_manager.wallets

    await wallet_environments.process_pending_states(
        [WalletStateTransition(pre_block_balance_updates={"nft_w_did1": {"init": True}})]
    )

    await env.rpc_client.mint_nft(
        request=NFTMintNFTRequest(
            wallet_id=uint32(env.wallet_aliases["nft_w_did1"]),
            royalty_address=None,
            target_address=None,  # doesn't matter so we'll just reuse
            hash=bytes32.from_hexstr("0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185"),
            uris=["https://www.chia.net/img/branding/chia-logo.svg"],
            meta_uris=["https://www.chia.net/img/branding/chia-logo.svg"],
            did_id="",
            push=True,
        ),
        tx_config=wallet_environments.tx_config,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft_w_did1": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "nft_w_did1": {"pending_coin_removal_count": -1},
                    "nft_no_did": {"init": True, "unspent_coin_count": 1},
                },
            )
        ]
    )

    # Check DID NFT
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft_no_did"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.owner_did is None
    nft_coin_id = coin.nft_coin_id

    # Test set None -> DID1
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        did_wallet2 = await DIDWallet.create_new_did_wallet(env.wallet_state_manager, wallet, uint64(1), action_scope)

    # use "set_remainder" here because this is more of a DID test issue
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did2": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did2": {"set_remainder": True},
                },
            )
        ]
    )

    await set_nft_did_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft_no_did"],
        did_id=hmr_did_id,
        nft_coin_id=nft_coin_id.hex() if isinstance(nft_coin_id, bytes32) else nft_coin_id,
        fee=uint64(0),
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "did1": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft_no_did": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {},
                    "did1": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft_no_did": {"pending_coin_removal_count": -1, "unspent_coin_count": -1},
                    "nft_w_did1": {"unspent_coin_count": 1},
                },
            )
        ]
    )

    nft_wallet_to_check = env.wallet_state_manager.wallets[uint32(env.wallet_aliases["nft_no_did"])]
    assert isinstance(nft_wallet_to_check, NFTWallet)
    assert len(await nft_wallet_to_check.get_current_nfts()) == 0

    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft_w_did1"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.owner_did is not None
    assert coin.owner_did.hex() == hex_did_id
    nft_coin_id = coin.nft_coin_id

    nft_get_info_res = await env.rpc_client.get_nft_info(NFTGetInfo(coin_id=nft_coin_id.hex(), latest=True))
    assert coins[0] == nft_get_info_res.nft_info

    # Test set DID1 -> DID2
    hex_did_id2 = did_wallet2.get_my_DID()
    hmr_did_id2 = encode_puzzle_hash(bytes32.from_hexstr(hex_did_id2), AddressType.DID.hrp(env.node.config))
    await set_nft_did_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft_w_did1"],
        did_id=hmr_did_id2,
        nft_coin_id=nft_coin_id.hex() if isinstance(nft_coin_id, bytes32) else nft_coin_id,
        fee=uint64(0),
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "did2": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                        "max_send_amount": -1,
                    },
                    "nft_w_did1": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {},
                    "did2": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                        "max_send_amount": 1,
                    },
                    "nft_w_did1": {"pending_coin_removal_count": -1, "unspent_coin_count": -1},
                    "nft_w_did2": {"init": True, "unspent_coin_count": 1},
                },
            )
        ]
    )

    # Check NFT DID
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft_w_did2"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.owner_did is not None
    assert coin.owner_did.hex() == hex_did_id2
    nft_coin_id = coin.nft_coin_id
    nft_get_info_res = await env.rpc_client.get_nft_info(NFTGetInfo(coin_id=nft_coin_id.hex(), latest=True))
    assert coins[0] == nft_get_info_res.nft_info

    # Test set DID2 -> None
    await env.rpc_client.set_nft_did(
        NFTSetNFTDID(
            wallet_id=uint32(env.wallet_aliases["nft_w_did2"]),
            did_id=None,
            nft_coin_id=nft_coin_id,
            fee=uint64(0),
            push=True,
        ),
        tx_config=wallet_environments.tx_config,
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "nft_w_did2": {"pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {},
                    "nft_w_did2": {"pending_coin_removal_count": -1, "unspent_coin_count": -1},
                    "nft_no_did": {"unspent_coin_count": 1},
                },
            )
        ]
    )

    # Check NFT DID
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft_no_did"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.owner_did is None
    nft_get_info_res = await env.rpc_client.get_nft_info(NFTGetInfo(coin_id=nft_coin_id.hex(), latest=True))
    assert coins[0] == nft_get_info_res.nft_info


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_set_nft_status(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]

    env.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    await create_nft_wallet_via_cli(wallet_environments, env, name="NFT WALLET 1")

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "nft": {"init": True},
                },
                post_block_balance_updates={
                    "xch": {},
                    "nft": {},
                },
            )
        ]
    )

    # Create a NFT without DID
    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft"],
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        metadata_uris="https://www.chia.net/img/branding/chia-logo.svg",
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {"init": True, "pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "nft": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            )
        ]
    )

    # Check DID NFT
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.owner_did is None
    assert not coin.pending_transaction
    nft_coin_id = coin.nft_coin_id
    # Set status
    await env.rpc_client.set_nft_status(
        NFTSetNFTStatus(wallet_id=uint32(env.wallet_aliases["nft"]), coin_id=nft_coin_id, in_transaction=True)
    )
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.pending_transaction


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [1], "reuse_puzhash": True, "trusted": True}],
    indirect=True,
)
@pytest.mark.anyio
async def test_nft_sign_message(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]

    env.wallet_aliases = {
        "xch": 1,
        "nft": 2,
    }

    await create_nft_wallet_via_cli(wallet_environments, env, name="NFT WALLET 1")

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {},
                    "nft": {"init": True},
                },
                post_block_balance_updates={
                    "xch": {},
                    "nft": {},
                },
            )
        ]
    )

    # Create a NFT without DID
    await mint_nft_via_cli(
        wallet_environments,
        env,
        wallet_id=env.wallet_aliases["nft"],
        hash="0xD4584AD463139FA8C0D9F68F4B59F185D4584AD463139FA8C0D9F68F4B59F185",
        uris=["https://www.chia.net/img/branding/chia-logo.svg"],
        metadata_uris="https://www.chia.net/img/branding/chia-logo.svg",
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "<=#max_send_amount": -1,
                        "pending_coin_removal_count": 1,
                    },
                    "nft": {"init": True, "pending_coin_removal_count": 1},
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        ">=#max_send_amount": 1,  # any amount increase
                        "pending_coin_removal_count": -1,
                    },
                    "nft": {"pending_coin_removal_count": -1, "unspent_coin_count": 1},
                },
            )
        ]
    )

    # Check DID NFT
    coins = (
        await env.rpc_client.list_nfts(
            NFTGetNFTs(wallet_id=uint32(env.wallet_aliases["nft"]), start_index=uint32(0), num=uint32(1))
        )
    ).nft_list
    assert len(coins) == 1
    coin = coins[0]
    assert coin.owner_did is None
    assert not coin.pending_transaction
    # Test general string
    message = "Hello World"
    sign_by_id_res = await env.rpc_client.sign_message_by_id(
        SignMessageByID(id=encode_puzzle_hash(coin.launcher_id, AddressType.NFT.value), message=message)
    )
    puzzle = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message))
    assert AugSchemeMPL.verify(
        sign_by_id_res.pubkey,
        puzzle.get_tree_hash(),
        sign_by_id_res.signature,
    )
    # Test hex string
    message = "0123456789ABCDEF"
    sign_by_id_res = await env.rpc_client.sign_message_by_id(
        SignMessageByID(id=encode_puzzle_hash(coin.launcher_id, AddressType.NFT.value), message=message, is_hex=True)
    )
    puzzle = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message)))
    assert AugSchemeMPL.verify(
        sign_by_id_res.pubkey,
        puzzle.get_tree_hash(),
        sign_by_id_res.signature,
    )
    # Test BLS sign string
    message = "Hello World"
    sign_by_id_res = await env.rpc_client.sign_message_by_id(
        SignMessageByID(
            id=encode_puzzle_hash(coin.launcher_id, AddressType.NFT.value),
            message=message,
            is_hex=False,
            safe_mode=False,
        )
    )

    assert AugSchemeMPL.verify(
        sign_by_id_res.pubkey,
        bytes(message, "utf-8"),
        sign_by_id_res.signature,
    )
    # Test BLS sign hex
    message = "0123456789ABCDEF"
    sign_by_id_res = await env.rpc_client.sign_message_by_id(
        SignMessageByID(
            id=encode_puzzle_hash(coin.launcher_id, AddressType.NFT.value),
            message=message,
            is_hex=True,
            safe_mode=False,
        )
    )

    assert AugSchemeMPL.verify(
        sign_by_id_res.pubkey,
        bytes.fromhex(message),
        sign_by_id_res.signature,
    )


def test_nft_command_parsing() -> None:
    bare_rpc = NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None)
    reuse_tx_config = NeedsTXConfig(
        coins_to_exclude=tuple(), coins_to_include=tuple(), amounts_to_exclude=tuple(), reuse=True
    )
    did_puzzle_hash = bytes32([1] * 32)
    did_address = encode_puzzle_hash(did_puzzle_hash, "did:chia:")
    nft_puzzle_hash = bytes32([2] * 32)
    nft_address = encode_puzzle_hash(nft_puzzle_hash, "nft")
    target_puzzle_hash = bytes32([3] * 32)
    target_address = encode_puzzle_hash(target_puzzle_hash, "txch")
    nft_coin_id = bytes32([4] * 32)
    content_hash = bytes32([5] * 32)
    message = b"hello nft world!!"

    check_click_parsing(
        CreateNftWalletCMD(
            rpc_info=bare_rpc,
            did_id=CliAddress(did_puzzle_hash, did_address, AddressType.DID),
            name="testnft",
        ),
        "-n",
        "testnft",
        "--did-id",
        did_address,
        context=ChiaCliContext(expected_prefix="txch"),
    )

    check_click_parsing(
        NftSignMessageCMD(
            rpc_info=bare_rpc,
            nft_id=CliAddress(nft_puzzle_hash, nft_address, AddressType.NFT),
            hex_message=message.hex(),
        ),
        "-i",
        nft_address,
        "-m",
        message.hex(),
        context=ChiaCliContext(expected_prefix="txch"),
    )

    check_click_parsing(
        MintNftCMD(
            **{
                **STANDARD_TX_ENDPOINT_ARGS,
                "wallet_id": 3,
                "royalty_address": CliAddress(target_puzzle_hash, target_address, AddressType.XCH),
                "target_address": CliAddress(target_puzzle_hash, target_address, AddressType.XCH),
                "no_did_ownership": True,
                "hash": content_hash.hex(),
                "uris": "https://example.com/a,https://example.com/b",
                "metadata_hash": content_hash.hex(),
                "metadata_uris": "https://example.com/meta",
                "license_hash": content_hash.hex(),
                "license_uris": "https://example.com/license",
                "edition_total": 10,
                "edition_number": 2,
                "royalty_percentage_fraction": 175,
                "fee": uint64(100_000_000_000),
                "valid_at": 100,
                "expires_at": 150,
            }
        ),
        "-i",
        "3",
        "-ra",
        target_address,
        "-ta",
        target_address,
        "--no-did-ownership",
        "-nh",
        content_hash.hex(),
        "-u",
        "https://example.com/a,https://example.com/b",
        "-mh",
        content_hash.hex(),
        "-mu",
        "https://example.com/meta",
        "-lh",
        content_hash.hex(),
        "-lu",
        "https://example.com/license",
        "-et",
        "10",
        "-en",
        "2",
        "-rp",
        "175",
        "-m",
        "0.1",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
        context=ChiaCliContext(expected_prefix="txch"),
    )

    check_click_parsing(
        AddUriToNftCMD(
            rpc_info=bare_rpc,
            transaction_writer=TransactionsOut(transaction_file_out=None),
            tx_config_loader=reuse_tx_config,
            wallet_id=3,
            nft_coin_id=nft_coin_id.hex(),
            uri="https://example.com/new",
            metadata_uri=None,
            license_uri=None,
            push=True,
            valid_at=100,
            expires_at=150,
            fee=uint64(0),
        ),
        "-i",
        "3",
        "--nft-coin-id",
        nft_coin_id.hex(),
        "-u",
        "https://example.com/new",
        "--reuse",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    )

    check_click_parsing(
        TransferNftCMD(
            rpc_info=bare_rpc,
            tx_config_loader=reuse_tx_config,
            transaction_writer=TransactionsOut(transaction_file_out=None),
            wallet_id=3,
            nft_coin_id=nft_coin_id.hex(),
            target_address=CliAddress(target_puzzle_hash, target_address, AddressType.XCH),
            fee=uint64(500_000_000_000),
            push=True,
            valid_at=100,
            expires_at=150,
        ),
        "-i",
        "3",
        "--nft-coin-id",
        nft_coin_id.hex(),
        "-ta",
        target_address,
        "-m",
        "0.5",
        "--reuse",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
        context=ChiaCliContext(expected_prefix="txch"),
    )

    check_click_parsing(ListNftsCMD(rpc_info=bare_rpc, wallet_id=3, num=50, start_index=0), "-i", "3")

    check_click_parsing(
        ListNftsCMD(rpc_info=bare_rpc, wallet_id=3, num=10, start_index=5),
        "-i",
        "3",
        "--num",
        "10",
        "--start-index",
        "5",
    )

    check_click_parsing(
        SetNftDidCMD(
            rpc_info=bare_rpc,
            tx_config_loader=reuse_tx_config,
            transaction_writer=TransactionsOut(transaction_file_out=None),
            wallet_id=3,
            did_id=did_address,
            nft_coin_id=nft_coin_id.hex(),
            fee=uint64(0),
            push=True,
            valid_at=100,
            expires_at=150,
        ),
        "-i",
        "3",
        "--did-id",
        did_address,
        "--nft-coin-id",
        nft_coin_id.hex(),
        "--reuse",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    )

    check_click_parsing(
        GetNftInfoCMD(rpc_info=bare_rpc, nft_coin_id=nft_coin_id.hex()),
        "--nft-coin-id",
        nft_coin_id.hex(),
    )
