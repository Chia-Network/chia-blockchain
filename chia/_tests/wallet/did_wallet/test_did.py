from __future__ import annotations

import dataclasses
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64

from chia._tests.cmds.test_cmd_framework import check_click_parsing
from chia._tests.conftest import ConsensusMode
from chia._tests.environments.wallet import (
    STANDARD_TX_ENDPOINT_ARGS,
    WalletEnvironment,
    WalletStateTransition,
    WalletTestFramework,
)
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets
from chia._tests.util.time_out_assert import time_out_assert
from chia.cmds.cmd_classes import ChiaCliContext
from chia.cmds.cmd_helpers import NeedsTXConfig, NeedsWalletRPC, TransactionsOut
from chia.cmds.param_types import CliAddress
from chia.cmds.wallet import (
    CreateDidWalletCMD,
    DidFindLostCMD,
    DidGetDetailsCMD,
    DidGetDidCMD,
    DidMessageSpendCMD,
    DidSetWalletNameCMD,
    DidSignMessageCMD,
    DidTransferDidCMD,
    DidUpdateMetadataCMD,
)
from chia.consensus.condition_tools import conditions_dict_for_solution
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.program import Program
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.peer_info import PeerInfo
from chia.types.signing_mode import CHIP_0002_SIGN_MESSAGE_PREFIX
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.wallet.did_wallet.did_info import did_recovery_is_nil
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.singleton import create_singleton_puzzle
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.curry_and_treehash import NIL_TREEHASH
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_request_types import (
    CreateNewWallet,
    CreateNewWalletType,
    DIDGetCurrentCoinInfo,
    DIDGetInfo,
    DIDType,
)
from chia.wallet.wallet_rpc_api import WalletRpcApi
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


async def get_wallet_num(wallet_manager):
    return len(await wallet_manager.get_all_wallet_info_entries())


def get_parent_num(did_wallet: DIDWallet):
    return len(did_wallet.did_info.parent_info)


async def get_did_wallet(env) -> DIDWallet:
    did_wallets = [
        w for w in await env.wallet_state_manager.get_all_wallet_info_entries() if w.type == WalletType.DECENTRALIZED_ID
    ]
    did_wallet = env.wallet_state_manager.wallets[did_wallets[-1].id]
    assert isinstance(did_wallet, DIDWallet)
    return did_wallet


async def create_did_via_cli(
    wallet_environments: WalletTestFramework,
    env: WalletEnvironment,
    amount: int,
    fee: uint64 = uint64(0),
    name: str | None = None,
    metadata: dict[str, str] = dict(),
) -> DIDWallet:
    await CreateDidWalletCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            "amount": amount,
            "fee": fee,
            "name": name,
            "push": True,
            "metadata": [f"{key}:{value}" for key, value in metadata.items()] if metadata is not None else None,
        }
    ).run()
    await env.change_balances({"nft": {"init": True}})
    return await get_did_wallet(env)


async def make_did_wallet(
    wallet_state_manager: Any,
    wallet: Wallet,
    amount: uint64,
    action_scope: WalletActionScope,
    metadata: dict[str, str] = {},
    fee: uint64 = uint64(0),
) -> DIDWallet:
    did_wallet = await DIDWallet.create_new_did_wallet(
        wallet_state_manager, wallet, amount, action_scope, metadata=metadata, fee=fee
    )

    return did_wallet


@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_create_new_did_wallet_failures_no_orphan(
    wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Regression test for https://github.com/Chia-Network/chia-blockchain/pull/20575
    create_new_did_wallet should not leave orphaned wallet records in failure paths.
    """
    env = wallet_environments.environments[0]
    wallet_state_manager = env.wallet_state_manager
    initial_wallet_count = len(await wallet_state_manager.user_store.get_all_wallet_info_entries())
    base_args = wallet_environments.cmd_tx_endpoint_args(env)

    capsys.readouterr()
    await CreateDidWalletCMD(**{**base_args, "amount": 2_000_000_000_001, "push": True}).run()
    assert "Failed to create DID wallet" in capsys.readouterr().out
    assert len(await wallet_state_manager.user_store.get_all_wallet_info_entries()) == initial_wallet_count

    capsys.readouterr()
    await CreateDidWalletCMD(**{**base_args, "amount": 2, "push": True}).run()
    assert "Failed to create DID wallet" in capsys.readouterr().out
    assert len(await wallet_state_manager.user_store.get_all_wallet_info_entries()) == initial_wallet_count

    error_message = "mocked generate failure"
    with patch.object(
        DIDWallet, "generate_new_decentralised_id", new=AsyncMock(side_effect=RuntimeError(error_message))
    ) as mock_generate:
        with pytest.raises(RuntimeError, match=error_message):
            async with wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
                await DIDWallet.create_new_did_wallet(
                    wallet_state_manager=wallet_state_manager,
                    wallet=wallet_state_manager.main_wallet,
                    amount=uint64(1),
                    action_scope=action_scope,
                )
        assert mock_generate.await_count == 1

    assert len(await wallet_state_manager.user_store.get_all_wallet_info_entries()) == initial_wallet_count


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_creation_from_coin_spend(
    self_hostname: str,
    two_nodes_two_wallets_with_same_keys: OldSimulatorsAndWallets,
    trusted: bool,
) -> None:
    """
    Verify that DIDWallet.create_new_did_wallet_from_coin_spend() is called after Singleton creation on
    the blockchain, and that the wallet is created in the second wallet node.
    """
    full_nodes, wallets, _ = two_nodes_two_wallets_with_same_keys
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, server_0 = wallets[0]
    wallet_node_1, server_1 = wallets[1]

    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        ph0 = await action_scope.get_puzzle_hash(wallet_0.wallet_state_manager)
    async with wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        ph1 = await action_scope.get_puzzle_hash(wallet_1.wallet_state_manager)

    sk0 = await wallet_node_0.wallet_state_manager.get_private_key(ph0)
    sk1 = await wallet_node_1.wallet_state_manager.get_private_key(ph1)
    assert sk0 == sk1

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
    await server_0.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await server_1.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)

    await full_node_api.farm_blocks_to_wallet(1, wallet_0)
    await full_node_api.farm_blocks_to_wallet(1, wallet_1)

    # Wallet1 sets up DIDWallet1 without any backup set
    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        did_wallet_0: DIDWallet = await make_did_wallet(
            wallet_node_0.wallet_state_manager,
            wallet_0,
            uint64(101),
            action_scope,
        )

    with pytest.raises(RuntimeError):
        assert await did_wallet_0.get_coin() == set()

    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_0, wallet_node_1])

    await time_out_assert(15, did_wallet_0.get_confirmed_balance, 101)
    await time_out_assert(15, did_wallet_0.get_unconfirmed_balance, 101)
    await time_out_assert(15, did_wallet_0.get_pending_change_balance, 0)

    await full_node_api.farm_blocks_to_wallet(1, wallet_0)

    #######################
    all_node_0_wallets = await wallet_node_0.wallet_state_manager.user_store.get_all_wallet_info_entries()
    all_node_1_wallets = await wallet_node_1.wallet_state_manager.user_store.get_all_wallet_info_entries()
    assert (
        json.loads(all_node_0_wallets[1].data)["current_inner"]
        == json.loads(all_node_1_wallets[1].data)["current_inner"]
    )


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 3, "blocks_needed": [1, 1, 1]}],
    indirect=True,
)
@pytest.mark.anyio
async def test_creation_from_backup_file(wallet_environments: WalletTestFramework) -> None:
    env_0, env_1, env_2 = wallet_environments.environments
    for env in (env_0, env_1, env_2):
        env.wallet_aliases = {"xch": 1, "did": 2, "nft": 3}

    did_wallet_0 = await create_did_via_cli(wallet_environments, env_0, amount=101)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -101,
                        "<=#spendable_balance": -101,
                        "<=#max_send_amount": -101,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {
                        "init": True,
                        "unconfirmed_wallet_balance": 101,
                        "pending_change": 101,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -101,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "did": {
                        "confirmed_wallet_balance": 101,
                        "spendable_balance": 101,
                        "max_send_amount": 101,
                        "unspent_coin_count": 1,
                        "pending_change": -101,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
            WalletStateTransition(),
        ]
    )

    await create_did_via_cli(wallet_environments, env_1, amount=201)
    did_wallet_1 = await get_did_wallet(env_1)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -201,
                        "<=#spendable_balance": -201,
                        "<=#max_send_amount": -201,
                        ">=#pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "did": {
                        "init": True,
                        "unconfirmed_wallet_balance": 201,
                        "pending_change": 201,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -201,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "did": {
                        "confirmed_wallet_balance": 201,
                        "spendable_balance": 201,
                        "max_send_amount": 201,
                        "unspent_coin_count": 1,
                        "pending_change": -201,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    backup_data = did_wallet_1.create_backup()
    await env_2.rpc_client.create_new_wallet(
        CreateNewWallet(
            wallet_type=CreateNewWalletType.DID_WALLET,
            did_type=DIDType.RECOVERY,
            backup_data=backup_data,
            push=True,
        ),
        wallet_environments.tx_config,
    )
    did_wallet_2 = env_2.wallet_state_manager.get_wallet(id=uint32(2), required_type=DIDWallet)
    current_coin_info_response = await env_0.rpc_client.did_get_current_coin_info(
        DIDGetCurrentCoinInfo(wallet_id=uint32(env_0.wallet_aliases["did"]))
    )
    assert current_coin_info_response.wallet_id == env_0.wallet_aliases["did"]
    for wallet in [did_wallet_0, did_wallet_1, did_wallet_2]:
        assert wallet.wallet_state_manager.wallets[wallet.id()] == wallet


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_did_find_lost_did(wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]) -> None:
    env_0 = wallet_environments.environments[0]
    env_0.wallet_aliases = {"xch": 1, "did": 2, "nft": 3}
    did_wallet_0 = await create_did_via_cli(wallet_environments, env_0, amount=101)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "init": True,
                        "unconfirmed_wallet_balance": 101,
                        "pending_change": 101,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "confirmed_wallet_balance": 101,
                        "spendable_balance": 101,
                        "max_send_amount": 101,
                        "unspent_coin_count": 1,
                        "pending_change": -101,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
        ]
    )

    coin = await did_wallet_0.get_coin()
    await env_0.wallet_state_manager.coin_store.delete_coin_record(coin.name())
    await env_0.wallet_state_manager.delete_wallet(did_wallet_0.wallet_info.id)
    env_0.wallet_state_manager.wallets.pop(did_wallet_0.wallet_info.id)
    assert len(env_0.wallet_state_manager.wallets) == 2

    assert did_wallet_0.did_info.origin_coin is not None
    capsys.readouterr()
    await DidFindLostCMD(
        rpc_info=wallet_environments.cmd_tx_endpoint_args(env_0)["rpc_info"],
        coin_id=did_wallet_0.did_info.origin_coin.name().hex(),
        metadata=None,
        recovery_list_hash=None,
        num_verification=None,
    ).run()
    assert "Successfully found lost DID" in capsys.readouterr().out

    did_wallets = [
        w
        for w in await env_0.wallet_state_manager.get_all_wallet_info_entries()
        if w.type == WalletType.DECENTRALIZED_ID
    ]
    did_wallet = env_0.wallet_state_manager.wallets[did_wallets[0].id]
    assert isinstance(did_wallet, DIDWallet)
    env_0.wallet_aliases["did_found"] = did_wallets[0].id
    await env_0.change_balances(
        {
            "did_found": {
                "init": True,
                "confirmed_wallet_balance": 101,
                "unconfirmed_wallet_balance": 101,
                "spendable_balance": 101,
                "max_send_amount": 101,
                "unspent_coin_count": 1,
            }
        }
    )
    await env_0.check_balances()

    async with did_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await did_wallet.create_update_spend(action_scope)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "did_found": {
                        "spendable_balance": -101,
                        "max_send_amount": -101,
                        "pending_change": 101,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "did_found": {
                        "spendable_balance": 101,
                        "max_send_amount": 101,
                        "pending_change": -101,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
        ]
    )

    coin = await did_wallet.get_coin()
    await env_0.wallet_state_manager.coin_store.delete_coin_record(coin.name())
    with wallet_environments.new_puzzle_hashes_allowed():
        async with did_wallet.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            new_inner_puzzle = await did_wallet.get_did_innerpuz(action_scope, override_reuse_puzhash_with=False)
    did_wallet.did_info = dataclasses.replace(did_wallet.did_info, current_inner=new_inner_puzzle)

    assert did_wallet.did_info.origin_coin is not None
    capsys.readouterr()
    await DidFindLostCMD(
        rpc_info=wallet_environments.cmd_tx_endpoint_args(env_0)["rpc_info"],
        coin_id=did_wallet.did_info.origin_coin.name().hex(),
        metadata=None,
        recovery_list_hash=None,
        num_verification=None,
    ).run()
    assert "Successfully found lost DID" in capsys.readouterr().out
    found_coin = await did_wallet.get_coin()
    assert found_coin == coin
    assert did_wallet.did_info.current_inner != new_inner_puzzle


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.anyio
async def test_did_transfer(wallet_environments: WalletTestFramework) -> None:
    env_0, env_1 = wallet_environments.environments
    env_0.wallet_aliases = {"xch": 1, "did": 2, "nft": 3}
    env_1.wallet_aliases = {"xch": 1, "did": 2, "nft": 3}
    fee = uint64(1000)

    await create_did_via_cli(
        wallet_environments,
        env_0,
        amount=101,
        name="Profile 1",
        metadata={"Twitter": "https://twitter.com/myusername", "GitHub": "测试"},
    )
    did_wallet_1 = await get_did_wallet(env_0)
    assert did_wallet_1.get_name() == "Profile 1"

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "init": True,
                        "unconfirmed_wallet_balance": 101,
                        "pending_change": 101,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "confirmed_wallet_balance": 101,
                        "spendable_balance": 101,
                        "max_send_amount": 101,
                        "unspent_coin_count": 1,
                        "pending_change": -101,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={"xch": {"set_remainder": True}, "did": {"set_remainder": True}},
                post_block_balance_updates={"xch": {"set_remainder": True}, "did": {"set_remainder": True}},
            ),
        ]
    )

    async with env_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        new_puzhash = await action_scope.get_puzzle_hash(env_1.wallet_state_manager)
    target_address = CliAddress(
        new_puzhash,
        encode_puzzle_hash(new_puzhash, AddressType.XCH.hrp(env_1.node.config)),
        AddressType.XCH,
    )
    await DidTransferDidCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env_0),
            "wallet_id": env_0.wallet_aliases["did"],
            "target_address": target_address,
            "reset_recovery": False,
            "fee": fee,
            "push": True,
        }
    ).run()

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"unconfirmed_wallet_balance": -101, "set_remainder": True},
                },
                post_block_balance_updates={"xch": {"set_remainder": True}},
            ),
            WalletStateTransition(
                post_block_balance_updates={
                    "did": {"init": True, "confirmed_wallet_balance": 101, "set_remainder": True},
                },
            ),
        ]
    )

    did_wallets = [
        w
        for w in await env_1.wallet_state_manager.get_all_wallet_info_entries()
        if w.type == WalletType.DECENTRALIZED_ID
    ]
    did_wallet_2 = env_1.wallet_state_manager.wallets[did_wallets[0].id]
    assert isinstance(did_wallet_2, DIDWallet)
    assert len(env_0.wallet_state_manager.wallets) == 2
    assert did_wallet_1.did_info.origin_coin == did_wallet_2.did_info.origin_coin
    metadata = json.loads(did_wallet_2.did_info.metadata)
    assert metadata["Twitter"] == "https://twitter.com/myusername"
    assert metadata["GitHub"] == "测试"
    assert await did_wallet_2.match_hinted_coin(await did_wallet_2.get_coin(), new_puzhash)


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_did_auto_transfer_limit(
    self_hostname: str,
    two_wallet_nodes: tuple[list[FullNodeSimulator], list[tuple[WalletNode, ChiaServer]], BlockTools],
    trusted: bool,
) -> None:
    fee = uint64(1000)
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    server_1 = full_node_api.server
    wallet_node, server_2 = wallets[0]
    wallet_node_2, server_3 = wallets[1]
    wallet = wallet_node.wallet_state_manager.main_wallet
    wallet2 = wallet_node_2.wallet_state_manager.main_wallet
    api_1 = WalletRpcApi(wallet_node_2)

    if trusted:
        wallet_node.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
        wallet_node_2.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node.config["trusted_peers"] = {}
        wallet_node_2.config["trusted_peers"] = {}

    await server_2.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
    await server_3.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
    await full_node_api.farm_blocks_to_wallet(1, wallet)

    # Check that we cap out at 10 DID Wallets automatically created upon transfer received
    for i in range(14):
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node.wallet_state_manager,
                wallet,
                uint64(101),
                action_scope,
                {"Twitter": "https://twitter.com/myusername", "GitHub": "测试"},
                fee=fee,
            )
        assert did_wallet_1.get_name() == "Profile 1"
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
        await time_out_assert(15, did_wallet_1.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_1.get_unconfirmed_balance, 101)
        # Transfer DID
        assert did_wallet_1.did_info.origin_coin is not None
        origin_coin = did_wallet_1.did_info.origin_coin
        async with wallet2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            new_puzhash = await action_scope.get_puzzle_hash(wallet2.wallet_state_manager)
        async with did_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await did_wallet_1.transfer_did(new_puzhash, fee, action_scope)
        await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
        await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
        # Check if the DID wallet is created in the wallet2

        await time_out_assert(
            30, get_wallet_num, min(2 + i, 11), wallet_node_2.wallet_state_manager
        )  # check we haven't made more than 10 DID wallets
        await time_out_assert(30, get_wallet_num, 1, wallet_node.wallet_state_manager)
    # Get the new DID wallets
    did_wallets = list(
        filter(
            lambda w: w.type == WalletType.DECENTRALIZED_ID,
            await wallet_node_2.wallet_state_manager.get_all_wallet_info_entries(),
        )
    )

    assert len(did_wallets) == 10
    # Test we can use the DID
    did_wallet_10 = wallet_node_2.wallet_state_manager.get_wallet(id=uint32(did_wallets[9].id), required_type=DIDWallet)
    # Delete the coin and change inner puzzle
    coin = await did_wallet_10.get_coin()
    # origin_coin = did_wallet_10.did_info.origin_coin
    backup_data = did_wallet_10.create_backup()
    await wallet_node_2.wallet_state_manager.coin_store.delete_coin_record(coin.name())
    await time_out_assert(15, did_wallet_10.get_confirmed_balance, 0)
    await wallet_node_2.wallet_state_manager.user_store.delete_wallet(did_wallet_10.wallet_info.id)
    wallet_node_2.wallet_state_manager.wallets.pop(did_wallet_10.wallet_info.id)
    # Recover the coin
    async with wallet_node_2.wallet_state_manager.lock:
        did_wallet_10 = await DIDWallet.create_new_did_wallet_from_recovery(
            wallet_node_2.wallet_state_manager,
            wallet2,
            backup_data,
        )
    assert did_wallet_10.did_info.origin_coin is not None
    await api_1.did_find_lost_did({"coin_id": did_wallet_10.did_info.origin_coin.name().hex()})
    await time_out_assert(15, did_wallet_10.get_confirmed_balance, 101)
    await time_out_assert(15, did_wallet_10.get_unconfirmed_balance, 101)

    # Check we can recover an auto-discarded DID
    did_wallet_9 = wallet_node_2.wallet_state_manager.get_wallet(id=uint32(did_wallets[8].id), required_type=DIDWallet)
    # Delete the coin and wallet to make space for a auto-discarded DID
    coin = await did_wallet_9.get_coin()
    await wallet_node_2.wallet_state_manager.coin_store.delete_coin_record(coin.name())
    await time_out_assert(15, did_wallet_9.get_confirmed_balance, 0)
    await wallet_node_2.wallet_state_manager.user_store.delete_wallet(did_wallet_9.wallet_info.id)
    wallet_node_2.wallet_state_manager.wallets.pop(did_wallet_9.wallet_info.id)

    did_wallets = list(
        filter(
            lambda w: w.type == WalletType.DECENTRALIZED_ID,
            await wallet_node_2.wallet_state_manager.get_all_wallet_info_entries(),
        )
    )
    assert len(did_wallets) == 9

    # Try and find lost coin
    await api_1.did_find_lost_did({"coin_id": origin_coin.name().hex()})
    did_wallets = list(
        filter(
            lambda w: w.type == WalletType.DECENTRALIZED_ID,
            await wallet_node_2.wallet_state_manager.get_all_wallet_info_entries(),
        )
    )
    assert len(did_wallets) == 10

    # Check we can still manually add new DIDs while at cap
    await full_node_api.farm_blocks_to_wallet(1, wallet2)
    async with wallet2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        did_wallet_11: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_2.wallet_state_manager,
            wallet2,
            uint64(101),
            action_scope,
            {"Twitter": "https://twitter.com/myusername", "GitHub": "测试"},
            fee=fee,
        )
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node, wallet_node_2])
    await time_out_assert(15, did_wallet_11.get_confirmed_balance, 101)
    await time_out_assert(15, did_wallet_11.get_unconfirmed_balance, 101)

    did_wallets = list(
        filter(
            lambda w: w.type == WalletType.DECENTRALIZED_ID,
            await wallet_node_2.wallet_state_manager.get_all_wallet_info_entries(),
        )
    )
    assert len(did_wallets) == 11


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 2, "blocks_needed": [1, 1]}], indirect=True)
@pytest.mark.anyio
async def test_get_info(wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]) -> None:
    env_0, env_1 = wallet_environments.environments
    env_0.wallet_aliases = {"xch": 1, "did": 2, "nft": 3}
    env_1.wallet_aliases = {"xch": 1, "did": 2, "nft": 3}
    fee = uint64(1000)
    did_amount = uint64(101)

    async with env_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        ph_1 = await action_scope.get_puzzle_hash(env_1.wallet_state_manager)

    await create_did_via_cli(
        wallet_environments, env_0, amount=did_amount, fee=fee, name="Profile 1", metadata={"twitter": "twitter"}
    )
    did_wallet_1 = await get_did_wallet(env_0)
    assert did_wallet_1.get_name() == "Profile 1"
    metadata = json.loads(did_wallet_1.did_info.metadata)
    assert metadata["twitter"] == "twitter"

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "init": True,
                        "unconfirmed_wallet_balance": did_amount,
                        "pending_change": did_amount,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "confirmed_wallet_balance": did_amount,
                        "spendable_balance": did_amount,
                        "max_send_amount": did_amount,
                        "unspent_coin_count": 1,
                        "pending_change": -did_amount,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={"xch": {"set_remainder": True}, "did": {"set_remainder": True}},
                post_block_balance_updates={"xch": {"set_remainder": True}, "did": {"set_remainder": True}},
            ),
        ]
    )

    assert did_wallet_1.did_info.origin_coin is not None
    coin_id_as_bech32 = encode_puzzle_hash(did_wallet_1.did_info.origin_coin.name(), AddressType.DID.value)
    capsys.readouterr()
    await DidGetDetailsCMD(
        rpc_info=wallet_environments.cmd_tx_endpoint_args(env_0)["rpc_info"],
        coin_id=did_wallet_1.did_info.origin_coin.name().hex(),
        latest=True,
    ).run()
    output = capsys.readouterr().out
    assert coin_id_as_bech32 in output
    assert "twitter" in output

    response = await env_0.rpc_client.get_did_info(DIDGetInfo(coin_id=did_wallet_1.did_info.origin_coin.name().hex()))
    response_with_bech32 = await env_0.rpc_client.get_did_info(DIDGetInfo(coin_id=coin_id_as_bech32))
    assert response == response_with_bech32
    assert response.did_id == coin_id_as_bech32
    assert response.launcher_id == did_wallet_1.did_info.origin_coin.name()
    assert did_wallet_1.did_info.current_inner is not None
    assert response.full_puzzle == create_singleton_puzzle(
        did_wallet_1.did_info.current_inner, did_wallet_1.did_info.origin_coin.name()
    )
    assert response.metadata["twitter"] == "twitter"
    assert response.latest_coin == (await did_wallet_1.get_coin()).name()
    assert response.num_verification == 0
    assert response.recovery_list_hash == Program(Program.to([])).get_tree_hash()
    assert decode_puzzle_hash(response.p2_address) == response.hints[0]

    async with env_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        coin = (await env_0.xch_wallet.select_coins(uint64(1), action_scope)).pop()
    coin_id = coin.name()
    capsys.readouterr()
    await DidGetDetailsCMD(
        rpc_info=wallet_environments.cmd_tx_endpoint_args(env_0)["rpc_info"],
        coin_id=coin_id.hex(),
        latest=True,
    ).run()
    assert "The coin is not a DID" in capsys.readouterr().out

    odd_amount = uint64(1)
    async with env_0.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        async with action_scope.use() as interface:
            interface.side_effects.selected_coins.append(coin)
        coin_1 = (await env_0.xch_wallet.select_coins(odd_amount, action_scope)).pop()
    async with env_0.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config.override(excluded_coin_ids=[coin_id]), push=True
    ) as action_scope:
        await env_0.xch_wallet.generate_signed_transaction([odd_amount], [ph_1], action_scope, fee)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"unconfirmed_wallet_balance": -odd_amount - fee, "set_remainder": True},
                    "did": {"set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"confirmed_wallet_balance": -odd_amount - fee, "set_remainder": True},
                    "did": {"set_remainder": True},
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={"xch": {"unconfirmed_wallet_balance": 0, "set_remainder": True}},
                post_block_balance_updates={
                    "xch": {"confirmed_wallet_balance": odd_amount, "set_remainder": True},
                },
            ),
        ]
    )

    capsys.readouterr()
    await DidGetDetailsCMD(
        rpc_info=wallet_environments.cmd_tx_endpoint_args(env_0)["rpc_info"],
        coin_id=coin_1.name().hex(),
        latest=True,
    ).run()
    assert "This is not a singleton, multiple children coins found." in capsys.readouterr().out


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_message_spend(wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {"xch": 1, "did": 2, "nft": 3}
    await create_did_via_cli(wallet_environments, env, amount=101, fee=uint64(1000))
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "init": True,
                        "unconfirmed_wallet_balance": 101,
                        "pending_change": 101,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "confirmed_wallet_balance": 101,
                        "spendable_balance": 101,
                        "max_send_amount": 101,
                        "unspent_coin_count": 1,
                        "pending_change": -101,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
        ]
    )

    capsys.readouterr()
    await DidMessageSpendCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            "wallet_id": env.wallet_aliases["did"],
            "coin_announcements": "0abc",
            "puzzle_announcements": "0def",
            "push": True,
        }
    ).run()
    command_output = capsys.readouterr().out
    assert "Message Spend Bundle:" in command_output
    bundle_json = command_output.split("Message Spend Bundle: ")[1].strip()
    bundle = WalletSpendBundle.from_json_dict(json.loads(bundle_json))
    spend = bundle.coin_spends[0]
    conditions = conditions_dict_for_solution(
        spend.puzzle_reveal, spend.solution, env.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM
    )
    assert len(conditions[ConditionOpcode.CREATE_COIN_ANNOUNCEMENT]) == 1
    assert conditions[ConditionOpcode.CREATE_COIN_ANNOUNCEMENT][0].vars[0].hex() == "0abc"
    assert len(conditions[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT]) == 1
    assert conditions[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT][0].vars[0].hex() == "0def"


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_update_metadata(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {"xch": 1, "did": 2, "nft": 3}
    fee = uint64(1000)
    did_wallet_1 = await create_did_via_cli(wallet_environments, env, amount=101, fee=fee)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "init": True,
                        "unconfirmed_wallet_balance": 101,
                        "pending_change": 101,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "confirmed_wallet_balance": 101,
                        "spendable_balance": 101,
                        "max_send_amount": 101,
                        "unspent_coin_count": 1,
                        "pending_change": -101,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
        ]
    )

    assert did_wallet_1.did_info.current_inner is not None
    puzhash = did_wallet_1.did_info.current_inner.get_tree_hash()
    parent_num = get_parent_num(did_wallet_1)

    with pytest.raises(ValueError, match="Metadata key value pairs must be strings"):
        await did_wallet_1.update_metadata({"Twitter": {"url": "http://www.twitter.com"}})  # type: ignore[dict-item]

    await DidUpdateMetadataCMD(
        rpc_info=wallet_environments.cmd_tx_endpoint_args(env)["rpc_info"],
        transaction_writer=TransactionsOut(transaction_file_out=None),
        tx_config_loader=wallet_environments.cmd_tx_endpoint_args(env)["tx_config_loader"],
        wallet_id=env.wallet_aliases["did"],
        metadata=json.dumps({"Twitter": "http://www.twitter.com"}),
        fee=fee,
        push=True,
        valid_at=None,
        expires_at=None,
    ).run()
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"unconfirmed_wallet_balance": -fee, "set_remainder": True},
                    "did": {"unconfirmed_wallet_balance": 0, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"confirmed_wallet_balance": -fee, "set_remainder": True},
                    "did": {"confirmed_wallet_balance": 0, "set_remainder": True},
                },
            ),
        ]
    )

    assert get_parent_num(did_wallet_1) == parent_num + 2
    assert did_wallet_1.did_info.current_inner is not None
    assert puzhash != did_wallet_1.did_info.current_inner.get_tree_hash()
    assert did_wallet_1.did_info.metadata.find("Twitter") > 0


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_environments", [{"num_environments": 1, "blocks_needed": [1]}], indirect=True)
@pytest.mark.anyio
async def test_did_sign_message(wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {"xch": 1, "did": 2, "nft": 3}
    api_0 = env.rpc_api
    fee = uint64(1000)

    did_wallet_1 = await create_did_via_cli(
        wallet_environments,
        env,
        name="Profile 1",
        amount=101,
        fee=fee,
        metadata={"Twitter": "https://twitter.com/myusername", "GitHub": "测试"},
    )
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "init": True,
                        "unconfirmed_wallet_balance": 101,
                        "pending_change": 101,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {
                        "confirmed_wallet_balance": 101,
                        "spendable_balance": 101,
                        "max_send_amount": 101,
                        "unspent_coin_count": 1,
                        "pending_change": -101,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={"xch": {"set_remainder": True}, "did": {"set_remainder": True}},
                post_block_balance_updates={"xch": {"set_remainder": True}, "did": {"set_remainder": True}},
            ),
        ]
    )

    assert did_wallet_1.did_info.origin_coin is not None
    did_id = encode_puzzle_hash(did_wallet_1.did_info.origin_coin.name(), AddressType.DID.value)
    message = "Hello World"
    capsys.readouterr()
    await DidSignMessageCMD(
        rpc_info=wallet_environments.cmd_tx_endpoint_args(env)["rpc_info"],
        did_id=CliAddress(did_wallet_1.did_info.origin_coin.name(), did_id, AddressType.DID),
        hex_message=message.encode().hex(),
    ).run()
    output = capsys.readouterr().out
    assert f"Message: {message.encode().hex()}" in output
    assert "Public Key:" in output
    assert "Signature:" in output

    response = await api_0.sign_message_by_id({"id": did_id, "message": message})
    puzzle: Program = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message))
    assert AugSchemeMPL.verify(
        G1Element.from_bytes(hexstr_to_bytes(response["pubkey"])),
        puzzle.get_tree_hash(),
        G2Element.from_bytes(hexstr_to_bytes(response["signature"])),
    )

    message = "0123456789ABCDEF"
    response = await api_0.sign_message_by_id({"id": did_id, "message": message, "is_hex": True})
    puzzle = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message)))
    assert AugSchemeMPL.verify(
        G1Element.from_bytes(hexstr_to_bytes(response["pubkey"])),
        puzzle.get_tree_hash(),
        G2Element.from_bytes(hexstr_to_bytes(response["signature"])),
    )

    message = "Hello World"
    response = await api_0.sign_message_by_id({"id": did_id, "message": message, "is_hex": False, "safe_mode": False})
    assert AugSchemeMPL.verify(
        G1Element.from_bytes(hexstr_to_bytes(response["pubkey"])),
        bytes(message, "utf-8"),
        G2Element.from_bytes(hexstr_to_bytes(response["signature"])),
    )

    message = "0123456789ABCDEF"
    response = await api_0.sign_message_by_id({"id": did_id, "message": message, "is_hex": True, "safe_mode": False})
    assert AugSchemeMPL.verify(
        G1Element.from_bytes(hexstr_to_bytes(response["pubkey"])),
        hexstr_to_bytes(message),
        G2Element.from_bytes(hexstr_to_bytes(response["signature"])),
    )


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 1, "blocks_needed": [1]}],
    indirect=True,
)
@pytest.mark.anyio
async def test_did_coin_records(wallet_environments: WalletTestFramework) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {"xch": 1, "did": 2, "nft": 3}
    did_wallet = await create_did_via_cli(wallet_environments, env, amount=1)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={1: {"set_remainder": True}, 2: {"init": True, "set_remainder": True}},
                post_block_balance_updates={1: {"set_remainder": True}, 2: {"set_remainder": True}},
            ),
            WalletStateTransition(),
        ]
    )

    for _ in range(2):
        async with did_wallet.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            target_puzhash = await action_scope.get_puzzle_hash(did_wallet.wallet_state_manager)
        target_address = CliAddress(
            target_puzhash,
            encode_puzzle_hash(target_puzhash, AddressType.XCH.hrp(env.node.config)),
            AddressType.XCH,
        )
        await DidTransferDidCMD(
            **{
                **wallet_environments.cmd_tx_endpoint_args(env),
                "wallet_id": env.wallet_aliases["did"],
                "target_address": target_address,
                "reset_recovery": False,
                "fee": uint64(0),
                "push": True,
            }
        ).run()
        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={1: {"set_remainder": True}, 2: {"set_remainder": True}},
                    post_block_balance_updates={1: {"set_remainder": True}, 2: {"set_remainder": True}},
                ),
                WalletStateTransition(),
            ]
        )

    assert len(await env.wallet_state_manager.get_spendable_coins_for_wallet(did_wallet.id())) == 1


def test_did_command_parsing() -> None:
    bare_rpc = NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None)
    reuse_tx_config = NeedsTXConfig(
        coins_to_exclude=tuple(), coins_to_include=tuple(), amounts_to_exclude=tuple(), reuse=True
    )
    did_puzzle_hash = bytes32([1] * 32)
    did_address = encode_puzzle_hash(did_puzzle_hash, "did:chia:")
    target_puzzle_hash = bytes32([2] * 32)
    target_address = encode_puzzle_hash(target_puzzle_hash, "txch")
    coin_id = bytes32(bytes([1] * 32))
    message = b"hello did world!!"

    check_click_parsing(
        CreateDidWalletCMD(
            **{
                **STANDARD_TX_ENDPOINT_ARGS,
                "name": "test",
                "amount": 3,
                "valid_at": 100,
                "expires_at": 150,
                "fee": uint64(100_000_000_000),
            }
        ),
        "-n",
        "test",
        "-a",
        "3",
        "-m",
        "0.1",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    )

    check_click_parsing(
        DidSignMessageCMD(
            rpc_info=bare_rpc,
            did_id=CliAddress(did_puzzle_hash, did_address, AddressType.DID),
            hex_message=message.hex(),
        ),
        "-i",
        did_address,
        "-m",
        message.hex(),
        context=ChiaCliContext(expected_prefix="txch"),
    )

    check_click_parsing(
        DidSetWalletNameCMD(rpc_info=bare_rpc, wallet_id=3, name="testdid"),
        "-i",
        "3",
        "-n",
        "testdid",
    )

    check_click_parsing(DidGetDidCMD(rpc_info=bare_rpc, wallet_id=3), "-i", "3")

    check_click_parsing(
        DidGetDetailsCMD(rpc_info=bare_rpc, coin_id=coin_id.hex(), latest=True),
        "--coin_id",
        coin_id.hex(),
    )

    check_click_parsing(
        DidUpdateMetadataCMD(
            rpc_info=bare_rpc,
            transaction_writer=TransactionsOut(transaction_file_out=None),
            tx_config_loader=reuse_tx_config,
            wallet_id=3,
            metadata='{"foo": "bar"}',
            push=True,
            valid_at=100,
            expires_at=150,
            fee=uint64(0),
        ),
        "-i",
        "3",
        "--metadata",
        '{"foo": "bar"}',
        "--reuse",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    )

    check_click_parsing(
        DidFindLostCMD(
            rpc_info=bare_rpc,
            coin_id=coin_id.hex(),
            metadata='{"foo": "bar"}',
            recovery_list_hash=None,
            num_verification=None,
        ),
        "--coin_id",
        coin_id.hex(),
        "--metadata",
        '{"foo": "bar"}',
    )

    check_click_parsing(
        DidMessageSpendCMD(
            rpc_info=bare_rpc,
            transaction_writer=TransactionsOut(transaction_file_out=None),
            tx_config_loader=reuse_tx_config,
            wallet_id=3,
            puzzle_announcements=",".join([bytes32(bytes([3] * 32)).hex(), bytes32(bytes([4] * 32)).hex()]),
            coin_announcements=",".join([bytes32(bytes([1] * 32)).hex(), bytes32(bytes([2] * 32)).hex()]),
            push=True,
            fee=uint64(0),
            valid_at=100,
            expires_at=150,
        ),
        "-i",
        "3",
        "--coin_announcements",
        ",".join([bytes32(bytes([1] * 32)).hex(), bytes32(bytes([2] * 32)).hex()]),
        "--puzzle_announcements",
        ",".join([bytes32(bytes([3] * 32)).hex(), bytes32(bytes([4] * 32)).hex()]),
        "--reuse",
        "--valid-at",
        "100",
        "--expires-at",
        "150",
    )

    check_click_parsing(
        DidTransferDidCMD(
            rpc_info=bare_rpc,
            tx_config_loader=reuse_tx_config,
            transaction_writer=TransactionsOut(transaction_file_out=None),
            wallet_id=3,
            target_address=CliAddress(target_puzzle_hash, target_address, AddressType.XCH),
            reset_recovery=False,
            fee=uint64(500_000_000_000),
            push=True,
            valid_at=100,
            expires_at=150,
        ),
        "-i",
        "3",
        "-m",
        "0.5",
        "--reuse",
        "--target-address",
        target_address,
        "--valid-at",
        "100",
        "--expires-at",
        "150",
        context=ChiaCliContext(expected_prefix="txch"),
    )


#  TODO: See Issue CHIA-1544
#  This test should be ported to WalletTestFramework once we can replace keys in the wallet node
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_did_resync(
    self_hostname: str,
    two_wallet_nodes: tuple[list[FullNodeSimulator], list[tuple[WalletNode, ChiaServer]], BlockTools],
    trusted: bool,
) -> None:
    full_nodes, wallets, _ = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.full_node.server
    wallet_node_1, wallet_server_1 = wallets[0]
    wallet_node_2, wallet_server_2 = wallets[1]
    wallet = wallet_node_1.wallet_state_manager.main_wallet
    wallet2 = wallet_node_2.wallet_state_manager.main_wallet
    fee = uint64(0)
    wallet_api_1 = WalletRpcApi(wallet_node_1)
    wallet_api_2 = WalletRpcApi(wallet_node_2)
    if trusted:
        wallet_node_1.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        wallet_node_2.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    else:
        wallet_node_1.config["trusted_peers"] = {}
        wallet_node_2.config["trusted_peers"] = {}
    assert full_node_server._port is not None
    await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await wallet_server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await full_node_api.farm_blocks_to_wallet(1, wallet)

    async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_1.wallet_state_manager,
            wallet,
            uint64(101),
            action_scope,
            {"Twitter": "https://twitter.com/myusername", "GitHub": "测试"},
            fee=fee,
        )
    assert did_wallet_1.get_name() == "Profile 1"
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_1, wallet_node_2])
    await time_out_assert(15, did_wallet_1.get_confirmed_balance, 101)
    await time_out_assert(15, did_wallet_1.get_unconfirmed_balance, 101)
    # Transfer DID
    async with wallet2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        new_puzhash = await action_scope.get_puzzle_hash(wallet2.wallet_state_manager)
    async with did_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await did_wallet_1.transfer_did(new_puzhash, fee, action_scope=action_scope)
    await full_node_api.process_transaction_records(records=action_scope.side_effects.transactions)
    await full_node_api.wait_for_wallets_synced(wallet_nodes=[wallet_node_1, wallet_node_2])
    # Check if the DID wallet is created in the wallet2
    await time_out_assert(30, get_wallet_num, 2, wallet_node_2.wallet_state_manager)
    await time_out_assert(30, get_wallet_num, 1, wallet_node_1.wallet_state_manager)
    did_wallet_2 = wallet_node_2.wallet_state_manager.get_wallet(uint32(2), DIDWallet)
    did_info = did_wallet_2.did_info
    # set flag to reset wallet sync data on start
    await wallet_api_1.set_wallet_resync_on_startup({"enable": True})
    fingerprint_1 = wallet_node_1.logged_in_fingerprint
    await wallet_api_2.set_wallet_resync_on_startup({"enable": True})
    fingerprint_2 = wallet_node_2.logged_in_fingerprint
    # 2 reward coins
    assert len(await wallet_node_1.wallet_state_manager.coin_store.get_all_unspent_coins()) == 2
    # Delete tx records
    await wallet_node_1.wallet_state_manager.tx_store.rollback_to_block(0)
    wallet_node_1._close()
    await wallet_node_1._await_closed()
    wallet_node_2._close()
    await wallet_node_2._await_closed()
    wallet_node_1.config["database_path"] = "wallet/db/blockchain_wallet_v2_test_1_CHALLENGE_KEY.sqlite"
    wallet_node_2.config["database_path"] = "wallet/db/blockchain_wallet_v2_test_2_CHALLENGE_KEY.sqlite"
    # Start resync
    await wallet_node_1._start_with_fingerprint(fingerprint_1)
    await wallet_node_2._start_with_fingerprint(fingerprint_2)
    assert full_node_server._port is not None
    await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await wallet_server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(b"\00" * 32)))
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_1, timeout=20)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_2, timeout=20)
    await time_out_assert(30, get_wallet_num, 1, wallet_node_1.wallet_state_manager)
    await time_out_assert(30, get_wallet_num, 2, wallet_node_2.wallet_state_manager)
    did_wallet_2 = wallet_node_2.wallet_state_manager.get_wallet(uint32(2), DIDWallet)
    assert did_info == did_wallet_2.did_info


@pytest.mark.parametrize(
    argnames=["program", "result"],
    argvalues=[
        (Program.to(NIL_TREEHASH), True),
        (Program.NIL, True),
        (Program.to(bytes32([1] * 32)), False),
    ],
)
def test_did_recovery_is_nil(program: Program, result: bool) -> None:
    # test that the alternate wallet nil recovery list bytes are used
    assert did_recovery_is_nil(program) is result
