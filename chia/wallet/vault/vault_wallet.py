from __future__ import annotations

import dataclasses
import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from chia_rs import G1Element, G2Element
from typing_extensions import Unpack

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.signing_mode import SigningMode
from chia.util.ints import uint32, uint64
from chia.wallet.conditions import Condition
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.payment import Payment
from chia.wallet.signer_protocol import (
    PathHint,
    SignedTransaction,
    SigningInstructions,
    SigningResponse,
    Spend,
    SumHint,
)
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.tx_config import TXConfig
from chia.wallet.util.wallet_sync_utils import fetch_coin_spend
from chia.wallet.vault.vault_drivers import (
    construct_p2_delegated_secp,
    get_vault_hidden_puzzle_with_index,
    get_vault_inner_puzzle_hash,
)
from chia.wallet.vault.vault_info import RecoveryInfo, VaultInfo
from chia.wallet.vault.vault_root import VaultRoot
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import GSTOptionalArgs


class Vault(Wallet):
    @staticmethod
    async def create(
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = __name__,
    ) -> Vault:
        self = Vault()
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = info
        self.wallet_id = info.id
        self.log = logging.getLogger(name)
        return self

    async def get_new_puzzle(self) -> Program:
        dr = await self.wallet_state_manager.get_unused_derivation_record(self.id())
        puzzle = construct_p2_delegated_secp(dr.pubkey, DEFAULT_CONSTANTS.GENESIS_CHALLENGE, dr.puzzle_hash)
        return puzzle

    async def get_new_puzzlehash(self) -> bytes32:
        puzzle = await self.get_new_puzzle()
        return puzzle.get_tree_hash()

    async def generate_signed_transaction(
        self,
        amount: uint64,
        puzzle_hash: bytes32,
        tx_config: TXConfig,
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        primaries: Optional[List[Payment]] = None,
        memos: Optional[List[bytes]] = None,
        puzzle_decorator_override: Optional[List[Dict[str, Any]]] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> List[TransactionRecord]:
        raise NotImplementedError("vault wallet")

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        raise NotImplementedError("vault wallet")

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        raise NotImplementedError("vault wallet")

    async def sign_message(self, message: str, puzzle_hash: bytes32, mode: SigningMode) -> Tuple[G1Element, G2Element]:
        raise NotImplementedError("vault wallet")

    async def get_puzzle_hash(self, new: bool) -> bytes32:
        if new:
            return await self.get_new_puzzlehash()
        else:
            record: Optional[
                DerivationRecord
            ] = await self.wallet_state_manager.get_current_derivation_record_for_wallet(self.id())
            if record is None:
                return await self.get_new_puzzlehash()
            return record.puzzle_hash

    async def apply_signatures(
        self, spends: List[Spend], signing_responses: List[SigningResponse]
    ) -> SignedTransaction:
        raise NotImplementedError("vault wallet")

    async def execute_signing_instructions(
        self, signing_instructions: SigningInstructions, partial_allowed: bool = False
    ) -> List[SigningResponse]:
        raise NotImplementedError("vault wallet")

    async def path_hint_for_pubkey(self, pk: bytes) -> Optional[PathHint]:
        raise NotImplementedError("vault wallet")

    async def sum_hint_for_pubkey(self, pk: bytes) -> Optional[SumHint]:
        raise NotImplementedError("vault wallet")

    def make_solution(
        self,
        primaries: List[Payment],
        conditions: Tuple[Condition, ...] = tuple(),
        fee: uint64 = uint64(0),
    ) -> Program:
        raise NotImplementedError("vault wallet")

    async def get_puzzle(self, new: bool) -> Program:
        if new:
            return await self.get_new_puzzle()
        else:
            record: Optional[
                DerivationRecord
            ] = await self.wallet_state_manager.get_current_derivation_record_for_wallet(self.id())
            if record is None:
                return await self.get_new_puzzle()
            puzzle = construct_p2_delegated_secp(record.pubkey, DEFAULT_CONSTANTS.GENESIS_CHALLENGE, record.puzzle_hash)
            return puzzle

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise ValueError("This won't work")

    def require_derivation_paths(self) -> bool:
        if getattr(self, "vault_info", None):
            return True
        return False

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        raise NotImplementedError("vault wallet")

    def handle_own_derivation(self) -> bool:
        return True

    def get_recovery_info(self) -> Tuple[Optional[G1Element], Optional[uint64]]:
        if self.vault_info.is_recoverable:
            return self.recovery_info.bls_pk, self.recovery_info.timelock
        return None, None

    def derivation_for_index(self, index: int) -> List[DerivationRecord]:
        hidden_puzzle = get_vault_hidden_puzzle_with_index(uint32(index))
        hidden_puzzle_hash = hidden_puzzle.get_tree_hash()
        bls_pk, timelock = self.get_recovery_info()
        inner_puzzle_hash = get_vault_inner_puzzle_hash(
            self.vault_info.pubkey,
            DEFAULT_CONSTANTS.GENESIS_CHALLENGE,
            hidden_puzzle_hash,
            bls_pk,
            timelock,
        )
        record = DerivationRecord(
            uint32(index), inner_puzzle_hash, self.vault_info.pubkey, self.type(), self.id(), False
        )
        return [record]

    async def sync_singleton(self) -> None:
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer = wallet_node.get_full_node_peer()
        assert peer is not None

        assert isinstance(self.wallet_state_manager.observation_root, VaultRoot)
        launcher_id = bytes32(self.wallet_state_manager.observation_root.launcher_id)

        coin_states = await wallet_node.get_coin_state([launcher_id], peer)
        if not coin_states:
            raise ValueError(f"No coin found for launcher id: {launcher_id}.")
        coin_state: CoinState = coin_states[0]
        parent_state: CoinState = (await wallet_node.get_coin_state([coin_state.coin.parent_coin_info], peer))[0]
        assert parent_state.spent_height is not None
        launcher_spend = await fetch_coin_spend(uint32(parent_state.spent_height), parent_state.coin, peer)
        launcher_solution = launcher_spend.solution.to_program()

        is_recoverable = False
        bls_pk = None
        timelock = None
        memos = launcher_solution.at("rrf")
        secp_pk = memos.at("f").as_atom()
        hidden_puzzle_hash = bytes32(memos.at("rf").as_atom())
        if memos.list_len() == 4:
            is_recoverable = True
            bls_pk = G1Element.from_bytes(memos.at("rrf").as_atom())
            timelock = uint64(memos.at("rrrf").as_int())
            self.recovery_info = RecoveryInfo(bls_pk, timelock)
        inner_puzzle_hash = get_vault_inner_puzzle_hash(
            secp_pk, DEFAULT_CONSTANTS.GENESIS_CHALLENGE, hidden_puzzle_hash, bls_pk, timelock
        )
        vault_info = VaultInfo(
            coin_state.coin, launcher_id, secp_pk, hidden_puzzle_hash, inner_puzzle_hash, is_recoverable
        )

        if coin_state.spent_height:
            while coin_state.spent_height is not None:
                coin_states = await wallet_node.fetch_children(coin_state.coin.name(), peer=peer)
                odd_coin = None
                for coin in coin_states:
                    if coin.coin.amount % 2 == 1:
                        if odd_coin is not None:
                            raise ValueError("This is not a singleton, multiple children coins found.")
                        odd_coin = coin
                if odd_coin is None:
                    raise ValueError("Cannot find child coin, please wait then retry.")
                parent_state = coin_state
                coin_state = odd_coin

        vault_info = dataclasses.replace(vault_info, coin=coin_state.coin)
        await self.save_info(vault_info)
        await self.wallet_state_manager.create_more_puzzle_hashes()

    async def save_info(self, vault_info: VaultInfo) -> None:
        self.vault_info = vault_info
        current_info = self.wallet_info
        data_str = json.dumps(vault_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        # TODO: push new info to user store
        # await self.wallet_state_manager.user_store.update_wallet(wallet_info)
