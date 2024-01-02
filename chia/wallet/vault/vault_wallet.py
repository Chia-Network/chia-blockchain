from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from chia_rs import G1Element, G2Element
from typing_extensions import Unpack

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.signing_mode import SigningMode
from chia.util.ints import uint64
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
        raise NotImplementedError("vault wallet")

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        raise NotImplementedError("vault wallet")

    def handle_own_derivation(self) -> bool:
        raise NotImplementedError("vault wallet")

    def derivation_for_index(self, index: int) -> List[DerivationRecord]:
        raise NotImplementedError("vault wallet")
