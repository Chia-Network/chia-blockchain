from __future__ import annotations

import json
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
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_node import Balance, WalletNode
from chia.wallet.wallet_state_manager import WalletStateManager


@dataclass
class WalletState:
    balance: Balance


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

    async def init_wallet_state(self, wallet_id_or_alias: Union[int, str], balance: Optional[Balance] = None) -> None:
        wallet_id: uint32 = self.dealias_wallet_id(wallet_id_or_alias)
        self.wallet_states = {
            **self.wallet_states,
            wallet_id: WalletState(
                await self.wallet_node.get_balance(wallet_id) if balance is None else balance,
            ),
        }

    async def check_balances(self, additional_balance_info: Dict[Union[uint32, str], Dict[str, int]] = {}) -> None:
        dealiased_additional_balance_info: Dict[uint32, Dict[str, int]] = {
            self.dealias_wallet_id(k): v for k, v in additional_balance_info.items()
        }
        errors: Dict[int, List[str]] = {}
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
                errors[wallet_id] = wallet_errors

        if errors != {}:
            raise ValueError(json.dumps(errors, indent=4))

    async def change_balances(self, update_dictionary: Dict[Union[int, str], Dict[str, int]]) -> None:
        for wallet_id_or_alias, kwargs in update_dictionary.items():
            wallet_id: uint32 = self.dealias_wallet_id(wallet_id_or_alias)
            new_values: Dict[str, int] = {}
            for key, change in kwargs.items():
                if key == "set_remainder":
                    continue
                new_values[key] = getattr(self.wallet_states[wallet_id].balance, key) + change

            self.wallet_states = {
                **self.wallet_states,
                wallet_id: replace(
                    self.wallet_states[wallet_id],
                    balance=Balance(
                        **{
                            **(
                                asdict(await self.wallet_node.get_balance(wallet_id))
                                if "set_remainder" in kwargs and kwargs["set_remainder"]
                                else asdict(self.wallet_states[wallet_id].balance)
                            ),
                            **new_values,
                        }
                    ),
                ),
            }


@dataclass
class WalletTestFramework:
    full_node: FullNodeSimulator
    trusted_full_node: bool
    environments: List[WalletEnvironment]


@pytest.fixture(scope="function", params=[True, False])
def trusted_full_node(request: Any) -> bool:
    trusted: bool = request.param
    return trusted


@pytest_asyncio.fixture(scope="function")
async def wallet_environments(trusted_full_node: bool, request: Any) -> AsyncIterator[WalletTestFramework]:
    assert len(request.param["blocks_needed"]) == request.param["num_environments"]
    async with setup_simulators_and_wallets_service(1, request.param["num_environments"], {}) as wallet_nodes_services:
        full_node, wallet_services, bt = wallet_nodes_services

        full_node[0]._api.full_node.config = {**full_node[0]._api.full_node.config, **request.param["config_overrides"]}

        rpc_clients: List[WalletRpcClient] = []
        async with AsyncExitStack() as astack:
            for service in wallet_services:
                service._node.config = {
                    **service._node.config,
                    "trusted_peers": {full_node[0]._api.server.node_id.hex(): full_node[0]._api.server.node_id.hex()}
                    if trusted_full_node
                    else {},
                    **request.param["config_overrides"],
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
            )
