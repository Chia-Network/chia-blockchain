from __future__ import annotations

import json
import operator
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass, field, replace
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import pytest
import pytest_asyncio

from chia.rpc.rpc_client import client_as_context_manager
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import setup_simulators_and_wallets_service
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64, uint128
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, TXConfig
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_node import Balance, WalletNode
from chia.wallet.wallet_state_manager import WalletStateManager

OPP_DICT = {"<": operator.lt, ">": operator.gt, "<=": operator.le, ">=": operator.ge}


class BalanceCheckingError(Exception):
    errors: Dict[Union[int, str], List[str]]

    def __init__(self, errors: Dict[Union[int, str], List[str]]) -> None:
        self.errors = errors

    def __repr__(self) -> str:
        return json.dumps(self.errors, indent=4)

    def __str__(self) -> str:
        return self.__repr__()


@dataclass
class WalletState:
    balance: Balance


@dataclass
class WalletStateTransition:
    pre_block_balance_updates: Dict[Union[int, str], Dict[str, int]] = field(default_factory=dict)
    post_block_balance_updates: Dict[Union[int, str], Dict[str, int]] = field(default_factory=dict)
    pre_block_additional_balance_info: Dict[Union[int, str], Dict[str, int]] = field(default_factory=dict)
    post_block_additional_balance_info: Dict[Union[int, str], Dict[str, int]] = field(default_factory=dict)


@dataclass
class WalletEnvironment:
    wallet_node: WalletNode
    wallet_state_manager: WalletStateManager
    xch_wallet: Wallet
    rpc_client: WalletRpcClient
    wallet_states: Dict[uint32, WalletState]
    wallet_aliases: Dict[str, int] = field(default_factory=dict)

    def dealias_wallet_id(self, wallet_id_or_alias: Union[int, str]) -> uint32:
        return (
            uint32(wallet_id_or_alias)
            if isinstance(wallet_id_or_alias, int)
            else uint32(self.wallet_aliases[wallet_id_or_alias])
        )

    def alias_wallet_id(self, wallet_id: uint32) -> Union[uint32, str]:
        inverted_wallet_aliases: Dict[int, str] = {v: k for k, v in self.wallet_aliases.items()}
        if wallet_id in inverted_wallet_aliases:
            return inverted_wallet_aliases[wallet_id]
        else:
            return wallet_id

    async def check_balances(self, additional_balance_info: Dict[Union[int, str], Dict[str, int]] = {}) -> None:
        dealiased_additional_balance_info: Dict[uint32, Dict[str, int]] = {
            self.dealias_wallet_id(k): v for k, v in additional_balance_info.items()
        }
        errors: Dict[Union[int, str], List[str]] = {}
        for wallet_id in self.wallet_state_manager.wallets:
            if wallet_id not in self.wallet_states:
                raise KeyError(f"No wallet state for wallet id {wallet_id} (alias: {self.alias_wallet_id(wallet_id)})")
            wallet_state: WalletState = self.wallet_states[wallet_id]
            wallet_errors: List[str] = []

            assert self.wallet_node.logged_in_fingerprint is not None
            expected_result: Dict[str, int] = {
                **wallet_state.balance.to_json_dict(),
                "wallet_id": wallet_id,
                "wallet_type": self.wallet_state_manager.wallets[wallet_id].type().value,
                "fingerprint": self.wallet_node.logged_in_fingerprint,
                **(
                    dealiased_additional_balance_info[wallet_id]
                    if wallet_id in dealiased_additional_balance_info
                    else {}
                ),
            }
            balance_response: Dict[str, int] = await self.rpc_client.get_wallet_balance(wallet_id)

            if not expected_result.items() <= balance_response.items():
                for key, value in expected_result.items():
                    if key not in balance_response:
                        wallet_errors.append(f"{key} not in balance response")
                    elif value != balance_response[key]:
                        wallet_errors.append(
                            f"{key} has different value {value} compared to balance response {balance_response[key]}"
                        )

            if wallet_errors != []:
                errors[self.alias_wallet_id(wallet_id)] = wallet_errors

        if errors != {}:
            raise BalanceCheckingError(errors)

    async def change_balances(self, update_dictionary: Dict[Union[int, str], Dict[str, int]]) -> None:
        for wallet_id_or_alias, kwargs in update_dictionary.items():
            wallet_id: uint32 = self.dealias_wallet_id(wallet_id_or_alias)

            new_values: Dict[str, int] = {}
            existing_values: Balance = await self.wallet_node.get_balance(wallet_id)
            if "init" in kwargs and kwargs["init"]:
                new_values = {k: v for k, v in kwargs.items() if k not in ("set_remainder", "init")}
            elif wallet_id not in self.wallet_states:
                raise ValueError(
                    f"Wallet id {wallet_id} (alias: {self.alias_wallet_id(wallet_id)}) does not have a current state. "
                    "Please use 'init': True if you intended to initialize its state."
                )
            else:
                for key, change in kwargs.items():
                    if key in "set_remainder":
                        continue
                    if "#" in key:
                        opp: str = key[0 : key.index("#")]
                        key_str: str = key[key.index("#") + 1 :]
                        if OPP_DICT[opp](
                            getattr(existing_values, key_str),
                            getattr(self.wallet_states[wallet_id].balance, key_str) + change,
                        ):
                            new_values[key_str] = getattr(existing_values, key_str)
                        else:
                            raise ValueError(
                                f"Setting {key_str} on {self.alias_wallet_id(wallet_id)} failed because "
                                f"{getattr(existing_values, key_str)} is not {opp} "
                                f"{getattr(self.wallet_states[wallet_id].balance, key_str)} + {change}"
                            )
                    else:
                        new_values[key] = getattr(self.wallet_states[wallet_id].balance, key) + change

            self.wallet_states = {
                **self.wallet_states,
                wallet_id: WalletState(
                    **{
                        **({} if "init" in kwargs and kwargs["init"] else asdict(self.wallet_states[wallet_id])),
                        "balance": Balance(
                            **{
                                **(
                                    asdict(existing_values)
                                    if "set_remainder" in kwargs and kwargs["set_remainder"]
                                    else {}
                                    if "init" in kwargs and kwargs["init"]
                                    else asdict(self.wallet_states[wallet_id].balance)
                                ),
                                **new_values,
                            }
                        ),
                    }
                ),
            }


@dataclass
class WalletTestFramework:
    full_node: FullNodeSimulator
    trusted_full_node: bool
    environments: List[WalletEnvironment]
    tx_config: TXConfig = DEFAULT_TX_CONFIG

    async def process_pending_states(self, state_transitions: List[WalletStateTransition]) -> None:
        # First, let's take note of the number of puzzle hashes if we're supposed to be reusing
        if self.tx_config.reuse_puzhash:
            puzzle_hash_indexes: List[Dict[uint32, Optional[DerivationRecord]]] = []
            for env in self.environments:
                ph_indexes: Dict[uint32, Optional[DerivationRecord]] = {}
                for wallet_id in env.wallet_state_manager.wallets:
                    ph_indexes[
                        wallet_id
                    ] = await env.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(wallet_id)
                puzzle_hash_indexes.append(ph_indexes)

        pending_txs: List[List[TransactionRecord]] = []
        for env in self.environments:
            pending_txs.append(await env.wallet_state_manager.tx_store.get_all_unconfirmed())
        await self.full_node.wait_transaction_records_entered_mempool([tx for txs in pending_txs for tx in txs])
        try:
            for env in self.environments:
                await self.full_node.wait_for_wallet_synced(wallet_node=env.wallet_node, timeout=20)
            for i, (env, transition) in enumerate(zip(self.environments, state_transitions)):
                try:
                    await env.change_balances(transition.pre_block_balance_updates)
                    await env.check_balances(transition.pre_block_additional_balance_info)
                except Exception:
                    raise ValueError(f"Error with env index {i}")
        except Exception:
            raise ValueError("Error before block was farmed")
        await self.full_node.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
        try:
            for env in self.environments:
                await self.full_node.wait_for_wallet_synced(wallet_node=env.wallet_node, timeout=20)
            for i, (env, transition) in enumerate(zip(self.environments, state_transitions)):
                try:
                    await env.change_balances(transition.post_block_balance_updates)
                    await env.check_balances(transition.post_block_additional_balance_info)
                except Exception:
                    raise ValueError(f"Error with env {i}")
        except Exception:
            raise ValueError("Error after block was farmed")
        for i, (env, txs) in enumerate(zip(self.environments, pending_txs)):
            try:
                await self.full_node.check_transactions_confirmed(env.wallet_state_manager, txs)
            except TimeoutError:
                unconfirmed: List[TransactionRecord] = await env.wallet_state_manager.tx_store.get_all_unconfirmed()
                raise TimeoutError(
                    f"ENV-{i} TXs not confirmed: {[tx.to_json_dict() for tx in unconfirmed if tx in txs]}"
                )

        # Finally, check that the number of puzzle hashes did or did not increase by the specified amount
        if self.tx_config.reuse_puzhash:
            for env, ph_indexes_before in zip(self.environments, puzzle_hash_indexes):
                for wallet_id, ph_index in zip(env.wallet_state_manager.wallets, ph_indexes_before):
                    assert ph_indexes_before[wallet_id] == (
                        await env.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(wallet_id)
                    )


@pytest.fixture(scope="function", params=[True, False])
def trusted_full_node(request: Any) -> bool:
    trusted: bool = request.param
    return trusted


@pytest.fixture(scope="function", params=[True, False])
def tx_config(request: Any) -> TXConfig:
    return replace(DEFAULT_TX_CONFIG, reuse_puzhash=request.param)


@pytest_asyncio.fixture(scope="function")
async def wallet_environments(
    trusted_full_node: bool, tx_config: TXConfig, request: Any
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
    else:
        config_overrides = {}
    async with setup_simulators_and_wallets_service(1, request.param["num_environments"], {}) as wallet_nodes_services:
        full_node, wallet_services, bt = wallet_nodes_services

        full_node[0]._api.full_node.config = {**full_node[0]._api.full_node.config, **config_overrides}

        rpc_clients: List[WalletRpcClient] = []
        async with AsyncExitStack() as astack:
            for service in wallet_services:
                service._node.config = {
                    **service._node.config,
                    "trusted_peers": {full_node[0]._api.server.node_id.hex(): full_node[0]._api.server.node_id.hex()}
                    if trusted_full_node
                    else {},
                    **config_overrides,
                }
                service._node.wallet_state_manager.config = service._node.config
                await service._node.server.start_client(
                    PeerInfo(bt.config["self_hostname"], uint16(full_node[0]._api.full_node.server._port)), None
                )
                rpc_clients.append(
                    await astack.enter_async_context(
                        client_as_context_manager(
                            WalletRpcClient,
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

            yield WalletTestFramework(
                full_node[0]._api,
                trusted_full_node,
                [
                    WalletEnvironment(
                        service._node,
                        service._node.wallet_state_manager,
                        service._node.wallet_state_manager.main_wallet,
                        rpc_client,
                        {uint32(1): wallet_state},
                    )
                    for service, rpc_client, wallet_state in zip(wallet_services, rpc_clients, wallet_states)
                ],
                tx_config,
            )
