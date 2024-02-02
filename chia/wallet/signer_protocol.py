from __future__ import annotations

from typing import List

from chia.types.blockchain_format.coin import Coin as _Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.util.clvm_streamable import ClvmStreamable

# This file contains the base types for communication between a wallet and an offline transaction signer.
# These types should be compliant with CHIP-TBD


class Coin(ClvmStreamable):
    parent_coin_id: bytes32
    puzzle_hash: bytes32
    amount: uint64


class Spend(ClvmStreamable):
    coin: Coin
    puzzle: Program
    solution: Program

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend) -> Spend:
        return cls(
            Coin(
                coin_spend.coin.parent_coin_info,
                coin_spend.coin.puzzle_hash,
                uint64(coin_spend.coin.amount),
            ),
            coin_spend.puzzle_reveal.to_program(),
            coin_spend.solution.to_program(),
        )

    def as_coin_spend(self) -> CoinSpend:
        return CoinSpend(
            _Coin(
                self.coin.parent_coin_id,
                self.coin.puzzle_hash,
                self.coin.amount,
            ),
            SerializedProgram.from_program(self.puzzle),
            SerializedProgram.from_program(self.solution),
        )


class TransactionInfo(ClvmStreamable):
    spends: List[Spend]


class SigningTarget(ClvmStreamable):
    fingerprint: bytes
    message: bytes
    hook: bytes32


class SumHint(ClvmStreamable):
    fingerprints: List[bytes]
    synthetic_offset: bytes
    final_pubkey: bytes


class PathHint(ClvmStreamable):
    root_fingerprint: bytes
    path: List[uint64]


class KeyHints(ClvmStreamable):
    sum_hints: List[SumHint]
    path_hints: List[PathHint]


class SigningInstructions(ClvmStreamable):
    key_hints: KeyHints
    targets: List[SigningTarget]


class UnsignedTransaction(ClvmStreamable):
    transaction_info: TransactionInfo
    signing_instructions: SigningInstructions


class SigningResponse(ClvmStreamable):
    signature: bytes
    hook: bytes32


class Signature(ClvmStreamable):
    type: str
    signature: bytes


class SignedTransaction(ClvmStreamable):
    transaction_info: TransactionInfo
    signatures: List[Signature]
