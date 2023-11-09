from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, List, Type, TypeVar

from hsms.clvm_serde import from_program_for_type, to_program_for_type
from typing_extensions import dataclass_transform

from chia.types.blockchain_format.coin import Coin as _Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@dataclass_transform()
class ClvmStreamableMeta(type):
    def __init__(cls: ClvmStreamableMeta, *args: Any) -> None:
        # Not sure how to fix the hints here, but it works
        dcls: Type[ClvmStreamable] = streamable(dataclass(frozen=True)(cls))  # type: ignore[arg-type]
        # Iterate over the fields of the class
        for field_obj in fields(dcls):
            field_name = field_obj.name
            field_metadata = {"key": field_name}
            field_metadata.update(field_obj.metadata)
            setattr(field_obj, "metadata", field_metadata)
        setattr(dcls, "as_program", to_program_for_type(dcls))
        setattr(dcls, "from_program", lambda prog: from_program_for_type(dcls)(prog))
        super().__init__(*args)


_T_ClvmStreamable = TypeVar("_T_ClvmStreamable", bound="ClvmStreamable")


class ClvmStreamable(Streamable, metaclass=ClvmStreamableMeta):
    def as_program(self) -> Program:
        raise NotImplementedError()

    @classmethod
    def from_program(cls: Type[_T_ClvmStreamable], prog: Program) -> _T_ClvmStreamable:
        raise NotImplementedError()


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
    pubkey: bytes
    message: bytes
    hook: bytes32


class SumHint(ClvmStreamable):
    fingerprints: List[bytes]
    synthetic_offset: bytes


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
    tx_info: TransactionInfo
    signing_instructions: SigningInstructions


class SigningResponse(ClvmStreamable):
    signature: bytes
    hook: bytes32


class Signature(ClvmStreamable):
    signature_type: bytes
    signature: bytes


class SignedTransaction(ClvmStreamable):
    transaction_info: TransactionInfo
    signatures: List[Signature]
