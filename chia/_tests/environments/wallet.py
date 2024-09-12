from __future__ import annotations

import json
import operator
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, ClassVar, Dict, List, Optional, Tuple, Union, cast

from chia._tests.environments.common import ServiceEnvironment
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.rpc_server import RpcServer
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.server import ChiaServer
from chia.server.start_service import Service
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import CLAWBACK_INCOMING_TRANSACTION_TYPES
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, TXConfig
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_node import Balance, WalletNode
from chia.wallet.wallet_node_api import WalletNodeAPI
from chia.wallet.wallet_state_manager import WalletStateManager

OPP_DICT = {"<": operator.lt, ">": operator.gt, "<=": operator.le, ">=": operator.ge}


class BalanceCheckingError(Exception):
    errors: Dict[Union[int, str], List[str]]

    def __init__(self, errors: Dict[Union[int, str], List[str]]) -> None:
        self.errors = errors

    def __repr__(self) -> str:
        return json.dumps(self.errors, indent=2)

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
    if TYPE_CHECKING:
        _protocol_check: ClassVar[ServiceEnvironment[WalletNode, WalletRpcApi, WalletNodeAPI]] = cast(
            "WalletEnvironment", None
        )

    __match_args__: ClassVar[Tuple[str, ...]] = ()

    service: Service[WalletNode, WalletNodeAPI, WalletRpcApi]
    # TODO: maybe put this in the protocol?
    rpc_client: WalletRpcClient
    # TODO: added the default, but should think through implementing it etc.  `.create()`?
    wallet_states: Dict[uint32, WalletState] = field(default_factory=dict)
    wallet_aliases: Dict[str, int] = field(default_factory=dict)

    @property
    def node(self) -> WalletNode:
        return self.service._node

    @property
    def rpc_api(self) -> WalletRpcApi:
        assert self.service.rpc_server is not None
        return self.service.rpc_server.rpc_api

    @property
    def rpc_server(self) -> RpcServer[WalletRpcApi]:
        assert self.service.rpc_server is not None
        return self.service.rpc_server

    @property
    def peer_api(self) -> WalletNodeAPI:
        return self.service._api

    @property
    def peer_server(self) -> ChiaServer:
        return self.service._server

    @property
    def wallet_state_manager(self) -> WalletStateManager:
        return self.service._node.wallet_state_manager

    @property
    def xch_wallet(self) -> Wallet:
        return self.service._node.wallet_state_manager.main_wallet

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

            assert self.node.logged_in_fingerprint is not None
            expected_result: Dict[str, int] = {
                **wallet_state.balance.to_json_dict(),
                "wallet_id": wallet_id,
                "wallet_type": self.wallet_state_manager.wallets[wallet_id].type().value,
                "fingerprint": self.node.logged_in_fingerprint,
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
            existing_values: Balance = await self.node.get_balance(wallet_id)
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
                                    else (
                                        {}
                                        if "init" in kwargs and kwargs["init"]
                                        else asdict(self.wallet_states[wallet_id].balance)
                                    )
                                ),
                                **new_values,
                            }
                        ),
                    }
                ),
            }

    async def wait_for_transactions_to_settle(
        self, full_node_api: FullNodeSimulator, _exclude_from_mempool_check: List[bytes32] = []
    ) -> List[TransactionRecord]:
        # Gather all pending transactions
        pending_txs: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_all_unconfirmed()
        # Filter clawback txs
        pending_txs = [
            tx
            for tx in pending_txs
            if tx.type not in CLAWBACK_INCOMING_TRANSACTION_TYPES and tx.name not in _exclude_from_mempool_check
        ]
        # Ensure txs enter mempool and are marked as such locally
        await full_node_api.wait_transaction_records_entered_mempool(pending_txs)
        await full_node_api.wait_transaction_records_marked_as_in_mempool([tx.name for tx in pending_txs], self.node)

        return pending_txs


@dataclass
class WalletTestFramework:
    full_node: FullNodeSimulator
    full_node_rpc_client: FullNodeRpcClient
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
                    ph_indexes[wallet_id] = (
                        await env.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(wallet_id)
                    )
                puzzle_hash_indexes.append(ph_indexes)

        pending_txs: List[List[TransactionRecord]] = []

        # Check balances prior to block
        try:
            for i, env in enumerate(self.environments):
                await self.full_node.wait_for_wallet_synced(wallet_node=env.node, timeout=20)
                try:
                    pending_txs.append(await env.wait_for_transactions_to_settle(self.full_node))
                except TimeoutError:  # pragma: no cover
                    raise TimeoutError(f"All TXs for env-{i} were not found in mempool or marked as in mempool")
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
        peak = self.full_node.full_node.blockchain.get_peak_height()
        assert peak is not None
        await self.full_node.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)

        # Check balances after block
        try:
            for i, (env, local_pending_txs) in enumerate(zip(self.environments, pending_txs)):
                await self.full_node.wait_for_wallet_synced(
                    wallet_node=env.node, timeout=20, peak_height=uint32(peak + 1)
                )
                try:
                    await env.wait_for_transactions_to_settle(
                        self.full_node, _exclude_from_mempool_check=[tx.name for tx in local_pending_txs]
                    )
                except TimeoutError:  # pragma: no cover
                    raise TimeoutError(f"All TXs for env-{i} were not found in mempool or marked as in mempool")
            for i, (env, transition) in enumerate(zip(self.environments, state_transitions)):
                try:
                    async with env.wallet_state_manager.db_wrapper.reader_no_transaction():
                        await env.change_balances(transition.post_block_balance_updates)
                        await env.check_balances(transition.post_block_additional_balance_info)
                except Exception:
                    raise ValueError(f"Error with env {i}")
        except Exception:
            raise ValueError("Error after block was farmed")

        # Make sure all pending txs from before the block are now confirmed
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
