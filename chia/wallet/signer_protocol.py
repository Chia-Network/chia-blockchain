from __future__ import annotations

from dataclasses import dataclass
from typing import List

from chia.types.blockchain_format.coin import Coin as _Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.util.streamable import Streamable
from chia.wallet.util.clvm_streamable import clvm_streamable

# This file contains the base types for communication between a wallet and an offline transaction signer.
# These types should be compliant with CHIP-0028


@clvm_streamable
@dataclass(frozen=True)
class Coin(Streamable):
    parent_coin_id: bytes32
    puzzle_hash: bytes32
    amount: uint64


@clvm_streamable
@dataclass(frozen=True)
class Spend(Streamable):
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


@clvm_streamable
@dataclass(frozen=True)
class TransactionInfo(Streamable):
    spends: List[Spend]


@clvm_streamable
@dataclass(frozen=True)
class SigningTarget(Streamable):
    fingerprint: bytes
    message: bytes
    hook: bytes32


@clvm_streamable
@dataclass(frozen=True)
class SumHint(Streamable):
    fingerprints: List[bytes]
    synthetic_offset: bytes
    final_pubkey: bytes


@clvm_streamable
@dataclass(frozen=True)
class PathHint(Streamable):
    root_fingerprint: bytes
    path: List[uint64]


@clvm_streamable
@dataclass(frozen=True)
class KeyHints(Streamable):
    sum_hints: List[SumHint]
    path_hints: List[PathHint]


@clvm_streamable
@dataclass(frozen=True)
class SigningInstructions(Streamable):
    key_hints: KeyHints
    targets: List[SigningTarget]


@clvm_streamable
@dataclass(frozen=True)
class UnsignedTransaction(Streamable):
    transaction_info: TransactionInfo
    signing_instructions: SigningInstructions


@clvm_streamable
@dataclass(frozen=True)
class SigningResponse(Streamable):
    signature: bytes
    hook: bytes32


@clvm_streamable
@dataclass(frozen=True)
class Signature(Streamable):
    type: str
    signature: bytes


@clvm_streamable
@dataclass(frozen=True)
class SignedTransaction(Streamable):
    transaction_info: TransactionInfo
    signatures: List[Signature]
