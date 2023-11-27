from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, fields
from io import BytesIO
from typing import Any, BinaryIO, Callable, Dict, Iterator, List, Type, TypeVar

from hsms.clvm_serde import from_program_for_type, to_program_for_type
from typing_extensions import dataclass_transform

from chia.types.blockchain_format.coin import Coin as _Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint64
from chia.util.streamable import ConversionError, Streamable, streamable

USE_CLVM_SERIALIZATION = False


@contextmanager
def clvm_serialization_mode(use: bool) -> Iterator[None]:
    global USE_CLVM_SERIALIZATION
    old_mode = USE_CLVM_SERIALIZATION
    USE_CLVM_SERIALIZATION = use
    yield
    USE_CLVM_SERIALIZATION = old_mode


@dataclass_transform()
class ClvmStreamableMeta(type):
    def __init__(cls: ClvmStreamableMeta, *args: Any) -> None:
        if cls.__name__ == "ClvmStreamable":
            return
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
        raise NotImplementedError()  # pragma: no cover

    @classmethod
    def from_program(cls: Type[_T_ClvmStreamable], prog: Program) -> _T_ClvmStreamable:
        raise NotImplementedError()  # pragma: no cover

    def stream(self, f: BinaryIO) -> None:
        global USE_CLVM_SERIALIZATION
        if USE_CLVM_SERIALIZATION:
            f.write(bytes(self.as_program()))
        else:
            super().stream(f)

    @classmethod
    def parse(cls: Type[_T_ClvmStreamable], f: BinaryIO) -> _T_ClvmStreamable:
        assert isinstance(f, BytesIO)
        try:
            result = cls.from_program(Program.from_bytes(bytes(f.getbuffer())))
            f.read()
            return result
        except Exception:
            return super().parse(f)

    def override_json_serialization(self, default_recurse_jsonify: Callable[[Any], Dict[str, Any]]) -> Any:
        global USE_CLVM_SERIALIZATION
        if USE_CLVM_SERIALIZATION:
            return bytes(self).hex()
        else:
            new_dict = {}
            for field in fields(self):
                new_dict[field.name] = default_recurse_jsonify(getattr(self, field.name))
            return new_dict

    @classmethod
    def from_json_dict(cls: Type[_T_ClvmStreamable], json_dict: Any) -> _T_ClvmStreamable:
        if isinstance(json_dict, str):
            try:
                byts = hexstr_to_bytes(json_dict)
            except ValueError as e:
                raise ConversionError(json_dict, cls, e)

            try:
                return cls.from_program(Program.from_bytes(byts))
            except Exception as e:
                raise ConversionError(json_dict, cls, e)
        else:
            return super().from_json_dict(json_dict)


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
