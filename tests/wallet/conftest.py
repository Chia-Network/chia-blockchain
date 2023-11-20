from __future__ import annotations

import json
import operator
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass, field, replace
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import pytest

from chia.consensus.constants import ConsensusConstants
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import setup_simulators_and_wallets_service
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint32, uint64, uint128
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
        """
        This function turns something that is either a wallet id or a wallet alias into a wallet id.
        """
        return (
            uint32(wallet_id_or_alias)
            if isinstance(wallet_id_or_alias, int)
            else uint32(self.wallet_aliases[wallet_id_or_alias])
        )

    def alias_wallet_id(self, wallet_id: uint32) -> Union[uint32, str]:
        """
        This function turns a wallet id into an alias if one is available or the same wallet id if one is not.
        """
        inverted_wallet_aliases: Dict[int, str] = {v: k for k, v in self.wallet_aliases.items()}
        if wallet_id in inverted_wallet_aliases:
            return inverted_wallet_aliases[wallet_id]
        else:
            return wallet_id

    async def check_balances(self, additional_balance_info: Dict[Union[int, str], Dict[str, int]] = {}) -> None:
        """
        This function checks the internal representation of what the balances should be against the balances that the
        wallet actually returns via the RPC.

        Likely this should be called as part of WalletTestFramework.process_pending_states instead of directly.
        """
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
        """
        This method changes the internal representation of what the wallet balances should be. This is probably
        necessary to call before check_balances as most wallet operations will result in a balance change that causes
        the wallet to be out of sync with our internal representation.

        The update dictionary is a dictionary of wallet ids/aliases mapped to a second dictionary of balance keys and
        deltas that those balances should change by (i.e {"confirmed_wallet_balance": -100}).

        There are two special keys that can be included in the update dictionary: "init" and "set_remainder". "init"
        means that you are acknowledging there is currently no internal representation of state for the specified
        wallet and instead of specifying deltas, you are specifying initial values. "set_remainder" is a boolean value
        that indicates whether or not the remaining values that are unspecified should be set automatically with the
        response from the RPC. This exists to avoid having to specify every balance every time especially for wallets
        that are not part of the main focus of the test.

        There's also a special syntax to say "I want to update to the correct balance number automatically so long as
        it is >/</<=/>= the balance value after the following change". This potentially sounds complex, but the idea is
        to allow for tests to say that they know a value should change by a certain amount AT LEAST which provides some
        validation on balances that otherwise the test writer might automatically set due to the difficulty of knowing
        EXACTLY what the next balance will be.  The most common use case is during a pre-block balance update: The
        spendable balance will drop by AT LEAST the amount in the transaction, but potentially more depending on the
        coin selection that happened.  To specify that you expect this behavior, you would use the following entry:
        {"<=#spendable_balance": -100} (where 100 is the amount sent in the transaction).
        """
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
        """
        This is the main entry point for processing state in wallet tests. It does the following things:

        1) Ensures all pending transactions have entered the mempool
        2) Checks that all balances have changed properly prior to a block being farmed
        3) Farms a block (to no one in particular)
        4) Chacks that all balances have changed properly after the block was farmed
        5) Checks that all pending transactions that were gathered in step 1 are now confirmed
        6) Checks that if `reuse_puzhash` was set, no new derivations were created
        7) Ensures the wallet is in a synced state before progressing to the rest of the test
        """
        # Take note of the number of puzzle hashes if we're supposed to be reusing
        if self.tx_config.reuse_puzhash:
            puzzle_hash_indexes: List[Dict[uint32, Optional[DerivationRecord]]] = []
            for env in self.environments:
                ph_indexes: Dict[uint32, Optional[DerivationRecord]] = {}
                for wallet_id in env.wallet_state_manager.wallets:
                    ph_indexes[
                        wallet_id
                    ] = await env.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(wallet_id)
                puzzle_hash_indexes.append(ph_indexes)

        # Gather all pending transactions and ensure they enter mempool
        pending_txs: List[List[TransactionRecord]] = [
            await env.wallet_state_manager.tx_store.get_all_unconfirmed() for env in self.environments
        ]
        await self.full_node.wait_transaction_records_entered_mempool([tx for txs in pending_txs for tx in txs])
        for local_pending_txs, (i, env) in zip(pending_txs, enumerate(self.environments)):
            try:
                await self.full_node.wait_transaction_records_marked_as_in_mempool(
                    [tx.name for tx in local_pending_txs], env.wallet_node
                )
            except TimeoutError:  # pragma: no cover
                raise ValueError(f"All tx records from env index {i} were not marked correctly with `.is_in_mempool()`")

        # Check balances prior to block
        try:
            for env in self.environments:
                await self.full_node.wait_for_wallet_synced(wallet_node=env.wallet_node, timeout=20)
            for i, (env, transition) in enumerate(zip(self.environments, state_transitions)):
                try:
                    async with env.wallet_state_manager.db_wrapper.reader_no_transaction():
                        await env.change_balances(transition.pre_block_balance_updates)
                        await env.check_balances(transition.pre_block_additional_balance_info)
                except Exception:
                    raise ValueError(f"Error with env index {i}")
        except Exception:
            raise ValueError("Error before block was farmed")

        # Farm block
        await self.full_node.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)

        # Check balances after block
        try:
            for env in self.environments:
                await self.full_node.wait_for_wallet_synced(wallet_node=env.wallet_node, timeout=20)
            for i, (env, transition) in enumerate(zip(self.environments, state_transitions)):
                try:
                    async with env.wallet_state_manager.db_wrapper.reader_no_transaction():
                        await env.change_balances(transition.post_block_balance_updates)
                        await env.check_balances(transition.post_block_additional_balance_info)
                except Exception:
                    raise ValueError(f"Error with env {i}")
        except Exception:
            raise ValueError("Error after block was farmed")

        # Make sure all pending txs are now confirmed
        for i, (env, txs) in enumerate(zip(self.environments, pending_txs)):
            try:
                await self.full_node.check_transactions_confirmed(env.wallet_state_manager, txs)
            except TimeoutError:  # pragma: no cover
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


# This fixture automatically creates 4 parametrized tests trusted/untrusted x reuse/new derivations
# These parameterizations can be skipped by manually specifying "trusted" or "reuse puzhash" to the fixture
@pytest.fixture(scope="function")
async def wallet_environments(
    trusted_full_node: bool,
    tx_config: TXConfig,
    blockchain_constants: ConsensusConstants,
    request: pytest.FixtureRequest,
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
    async with setup_simulators_and_wallets_service(
        1, request.param["num_environments"], blockchain_constants
    ) as wallet_nodes_services:
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
