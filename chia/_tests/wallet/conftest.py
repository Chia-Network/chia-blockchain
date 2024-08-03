from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import replace
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Literal, Optional, Tuple

import pytest
from chia_rs import G1Element
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from chia._tests.conftest import ConsensusMode
from chia._tests.environments.wallet import WalletEnvironment, WalletState, WalletStateTransition, WalletTestFramework
from chia._tests.util.setup_nodes import setup_simulators_and_wallets_service
from chia._tests.wallet.wallet_block_tools import WalletBlockTools
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult
from chia.full_node.full_node import FullNode
from chia.rpc.wallet_request_types import VaultCreate
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, TXConfig
from chia.wallet.vault.vault_root import VaultRoot
from chia.wallet.vault.vault_wallet import Vault
from chia.wallet.wallet_node import Balance
from chia.wallet.wallet_state_manager import WalletStateManager


@pytest.fixture(scope="function", autouse=True)
def block_is_current_at(monkeypatch: pytest.MonkeyPatch) -> None:
    def make_new_synced(func: Callable[..., Awaitable[bool]]) -> Any:
        async def mocked_synced(self: Any, block_is_current_at: Optional[uint64] = uint64(0)) -> bool:
            return await func(self, block_is_current_at)

        return mocked_synced

    monkeypatch.setattr(WalletStateManager, "synced", make_new_synced(WalletStateManager.synced))
    monkeypatch.setattr(FullNode, "synced", make_new_synced(FullNode.synced))


@pytest.fixture(scope="function", autouse=True)
async def ignore_block_validation(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    This fixture exists to patch the existing BlockTools with WalletBlockTools and to patch existing code to work with
    simplified blocks. This is done as a step towards the separation of the wallet into its own self contained project.

    Many consensus concepts are irrelevant when testing wallet code which generally only cares about the mempool's
    acceptance of its spends and notifications of new representations of the coin set.  One day, it would be good to
    patch away the full node entirely in favor of the bare minimum logic to emulate the two features above.

    In addition, making truly consensus valid blocks is often slow so shortcutting the logic makes wallet tests as of
    today (3/4/24) about ~30% faster.
    """
    if "standard_block_tools" in request.keywords:
        return None

    async def validate_block_body(*args: Any, **kwargs: Any) -> Tuple[Literal[None], NPCResult]:
        return None, args[7]

    def create_wrapper(original_create: Any) -> Any:
        async def new_create(*args: Any, **kwargs: Any) -> Any:
            # Modify the config argument directly since it's a mutable dictionary
            if "config" in kwargs:
                kwargs["config"]["single_threaded"] = True
            else:  # pragma: no cover
                # Nowhere covers this line right now but its entirely possible
                args[0]["single_threaded"] = True

            # Call the original function with modified arguments
            full_node = await original_create(*args, **kwargs)
            return full_node

        return new_create

    monkeypatch.setattr("chia.simulator.block_tools.BlockTools", WalletBlockTools)
    monkeypatch.setattr(FullNode, "create", create_wrapper(FullNode.create))
    monkeypatch.setattr("chia.consensus.blockchain.validate_block_body", validate_block_body)
    monkeypatch.setattr(
        "chia.consensus.block_header_validation.validate_unfinished_header_block", lambda *_, **__: (uint64(1), None)
    )
    monkeypatch.setattr(
        "chia.wallet.wallet_blockchain.validate_finished_header_block", lambda *_, **__: (uint64(1), None)
    )
    monkeypatch.setattr(
        "chia.consensus.multiprocess_validation.validate_finished_header_block", lambda *_, **__: (uint64(1), None)
    )
    monkeypatch.setattr(
        "chia.consensus.multiprocess_validation.verify_and_get_quality_string", lambda *_, **__: bytes32([0] * 32)
    )
    monkeypatch.setattr("chia.consensus.block_record.BlockRecord.sp_total_iters", lambda *_: uint128(0))
    monkeypatch.setattr("chia.consensus.block_record.BlockRecord.ip_sub_slot_total_iters", lambda *_: uint128(0))
    monkeypatch.setattr("chia.consensus.make_sub_epoch_summary.calculate_sp_iters", lambda *_: uint64(0))
    monkeypatch.setattr("chia.consensus.make_sub_epoch_summary.calculate_ip_iters", lambda *_: uint64(0))
    monkeypatch.setattr("chia.consensus.difficulty_adjustment._get_next_sub_slot_iters", lambda *_: uint64(1))
    monkeypatch.setattr("chia.consensus.difficulty_adjustment._get_next_difficulty", lambda *_: uint64(1))
    monkeypatch.setattr("chia.full_node.full_node_store.calculate_sp_interval_iters", lambda *_: uint64(1))
    monkeypatch.setattr("chia.consensus.pot_iterations.calculate_sp_interval_iters", lambda *_: uint64(1))
    monkeypatch.setattr("chia.consensus.pot_iterations.calculate_ip_iters", lambda *_: uint64(1))
    monkeypatch.setattr("chia.consensus.block_record.BlockRecord.sp_sub_slot_total_iters", lambda *_: uint64(1))


@pytest.fixture(scope="function", params=[True, False])
def trusted_full_node(request: Any) -> bool:
    trusted: bool = request.param
    return trusted


@pytest.fixture(scope="function", params=[True, False])
def tx_config(request: Any) -> TXConfig:
    return replace(DEFAULT_TX_CONFIG, reuse_puzhash=request.param)

@pytest.fixture(scope="function", params=[True, False])
def as_vault(request: Any) -> bool:
    as_vault: bool = request.param
    return as_vault

# This fixture automatically creates 4 parametrized tests trusted/untrusted x reuse/new derivations
# These parameterizations can be skipped by manually specifying "trusted" or "reuse puzhash" to the fixture
@pytest.fixture(scope="function")
async def wallet_environments(
    trusted_full_node: bool,
    tx_config: TXConfig,
    blockchain_constants: ConsensusConstants,
    consensus_mode: ConsensusMode,
    request: pytest.FixtureRequest,
    as_vault: bool,
) -> AsyncIterator[WalletTestFramework]:
    if "trusted" in request.param:
        if request.param["trusted"] != trusted_full_node:
            pytest.skip("Skipping not specified trusted mode")
    if "reuse_puzhash" in request.param:
        if request.param["reuse_puzhash"] != tx_config.reuse_puzhash:
            pytest.skip("Skipping not specified reuse_puzhash mode")
    assert len(request.param["blocks_needed"]) == request.param["num_environments"]
    if "config_overrides" in request.param:
        config_overrides: Dict[str, Any] = request.param["config_overrides"]
    else:  # pragma: no cover
        config_overrides = {}
    if (("as_vault" not in request.param) or (not request.param["as_vault"])) and as_vault:
        pytest.skip("Vault tests not requested")
    if as_vault and (consensus_mode != ConsensusMode.HARD_FORK_2_0):
        pytest.skip("Skipping vault tests for consensus modes other than HARD_FORK_2_0")
    async with setup_simulators_and_wallets_service(
        1,
        request.param["num_environments"],
        blockchain_constants,
        initial_num_public_keys=config_overrides.get("initial_num_public_keys", 5),
    ) as wallet_nodes_services:
        full_node, wallet_services, bt = wallet_nodes_services

        full_node[0]._api.full_node.config = {**full_node[0]._api.full_node.config, **config_overrides}

        rpc_clients: List[WalletRpcClient] = []
        async with AsyncExitStack() as astack:
            for service in wallet_services:
                service._node.config = {
                    **service._node.config,
                    "trusted_peers": (
                        {full_node[0]._api.server.node_id.hex(): full_node[0]._api.server.node_id.hex()}
                        if trusted_full_node
                        else {}
                    ),
                    **config_overrides,
                }
                service._node.wallet_state_manager.config = service._node.config
                await service._node.server.start_client(
                    PeerInfo(bt.config["self_hostname"], full_node[0]._api.full_node.server.get_port()), None
                )
                rpc_clients.append(
                    await astack.enter_async_context(
                        WalletRpcClient.create_as_context(
                            bt.config["self_hostname"],
                            # Semantics guarantee us a non-None value here
                            service.rpc_server.listen_port,  # type: ignore[union-attr]
                            service.root_path,
                            service.config,
                        )
                    )
                )

            wallet_states: List[WalletState] = []
            for service, blocks_needed in zip(wallet_services, request.param["blocks_needed"]):
                if blocks_needed > 0:
                    await full_node[0]._api.farm_blocks_to_wallet(
                        count=blocks_needed, wallet=service._node.wallet_state_manager.main_wallet
                    )
                    await full_node[0]._api.wait_for_wallet_synced(wallet_node=service._node, timeout=20)
                wallet_states.append(
                    WalletState(
                        Balance(
                            confirmed_wallet_balance=uint128(2_000_000_000_000 * blocks_needed),
                            unconfirmed_wallet_balance=uint128(2_000_000_000_000 * blocks_needed),
                            spendable_balance=uint128(2_000_000_000_000 * blocks_needed),
                            pending_change=uint64(0),
                            max_send_amount=uint128(2_000_000_000_000 * blocks_needed),
                            unspent_coin_count=uint32(2 * blocks_needed),
                            pending_coin_removal_count=uint32(0),
                        ),
                    )
                )

            wallet_environments = WalletTestFramework(
                full_node[0]._api,
                trusted_full_node,
                [
                    WalletEnvironment(
                        service=service,
                        rpc_client=rpc_client,
                        wallet_states={uint32(1): wallet_state},
                    )
                    for service, rpc_client, wallet_state in zip(wallet_services, rpc_clients, wallet_states)
                ],
                tx_config,
            )

            if as_vault:
                for index, env in enumerate(wallet_environments.environments):
                    seed = 0x1A62C9636D1C9DB2E7D564D0C11603BF456AAD25AA7B12BDFD762B4E38E7EDC6 * (index + 1)
                    SECP_SK = ec.derive_private_key(seed, ec.SECP256R1(), default_backend())
                    SECP_PK = SECP_SK.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
                    # Temporary hack so execute_signing_instructions can access the key
                    env.wallet_state_manager.config["test_sk"] = SECP_SK
                    client = env.rpc_client
                    fingerprint = (await client.get_public_keys())[0]
                    bls_pk_hex = (await client.get_private_key(fingerprint))["pk"]
                    bls_pk = G1Element.from_bytes(bytes.fromhex(bls_pk_hex))
                    timelock = uint64(10)
                    hidden_puzzle_index = uint32(0)
                    res = await client.vault_create(
                        VaultCreate(
                            secp_pk=SECP_PK,
                            hp_index=hidden_puzzle_index,
                            bls_pk=bls_pk,
                            timelock=timelock,
                            push=True,
                        ),
                        tx_config=tx_config,
                    )
                    all_removals = [coin for tx in res.transactions for coin in tx.removals]
                    eve_coin = [
                        item
                        for tx in res.transactions
                        for item in tx.additions
                        if item not in all_removals and item.amount == 1
                    ][0]
                    launcher_id = eve_coin.parent_coin_info
                    vault_root = VaultRoot.from_bytes(launcher_id)

                    await wallet_environments.process_pending_states(
                        [
                            WalletStateTransition(
                                pre_block_balance_updates={
                                    1: {
                                        "init": True,
                                        "set_remainder": True,
                                    }
                                },
                                post_block_balance_updates={
                                    1: {
                                        "set_remainder": True,
                                    }
                                },
                            )
                            for _ in wallet_environments.environments
                        ]
                    )
                    await env.node.keychain_proxy.add_key(launcher_id.hex(), label="vault", private=False)
                    await env.restart(vault_root.get_fingerprint())
                    await wallet_environments.full_node.wait_for_wallet_synced(env.node, 20)
                    assert isinstance(env.xch_wallet, Vault)  # mypy
                    await env.xch_wallet.sync_vault_launcher()

                for env, blocks_needed in zip(wallet_environments.environments, request.param["blocks_needed"]):
                    if blocks_needed > 0:
                        assert isinstance(env.xch_wallet, Vault)  # mypy
                        farm_to = env.xch_wallet.get_p2_singleton_puzzle_hash()
                        await wallet_environments.full_node.farm_blocks_to_puzzlehash(
                            count=blocks_needed,
                            farm_to=farm_to,
                            guarantee_transaction_blocks=True,
                        )
                        await full_node[0]._api.wait_for_wallet_synced(wallet_node=service._node, timeout=20)
                        await wallet_environments.process_pending_states(
                            [
                                WalletStateTransition(
                                    pre_block_balance_updates={
                                        1: {
                                            "init": True,
                                            "set_remainder": True,
                                        }
                                    },
                                    post_block_balance_updates={
                                        1: {
                                            "set_remainder": True,
                                        }
                                    },
                                )
                                for _ in wallet_environments.environments
                            ]
                        )

            yield wallet_environments
