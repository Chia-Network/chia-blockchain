from __future__ import annotations

import dataclasses
import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from chia_rs import G1Element, G2Element
from typing_extensions import Unpack

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
from chia.wallet.vault.vault_info import VaultInfo
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
        raise NotImplementedError("vault wallet")

    async def get_new_puzzlehash(self) -> bytes32:
        raise NotImplementedError("vault wallet")

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
        raise NotImplementedError("vault wallet")

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
        raise NotImplementedError("vault wallet")

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise ValueError("This won't work")

    def require_derivation_paths(self) -> bool:
        return False

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        raise NotImplementedError("vault wallet")

    def handle_own_derivation(self) -> bool:
        raise NotImplementedError("vault wallet")

    def derivation_for_index(self, index: int) -> List[DerivationRecord]:
        raise NotImplementedError("vault wallet")

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

        secp_pk = launcher_solution.at("rrff").as_atom()
        hidden_puzzle_hash = bytes32(launcher_solution.at("rrfrf").as_atom())
        vault_info = VaultInfo(coin_state.coin, launcher_id, secp_pk, hidden_puzzle_hash)

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

    async def save_info(self, vault_info: VaultInfo) -> None:
        self.vault_info = vault_info
        current_info = self.wallet_info
        data_str = json.dumps(vault_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        # TODO: push new info to user store
        # await self.wallet_state_manager.user_store.update_wallet(wallet_info)
