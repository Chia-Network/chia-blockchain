from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Type, TypeVar

from clvm.casts import int_from_bytes

from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


def serialize_item(item: Any, from_hex_atoms: bool = False) -> Program:
    if isinstance(item, list):
        return_value: Program = Program.to(("$l", Program.to([serialize_item(_, from_hex_atoms) for _ in item])))
    elif isinstance(item, dict):
        return_value = dictionary_to_program(item, from_hex_atoms)
    else:
        if from_hex_atoms:
            # This is a solution for the local library because we're using the Streamable class
            # It is not part of the protocol and should be ignored if ported elsewhere
            item = Program.fromhex(item)
        return_value = Program.to(item)
    return return_value


def deserialize_item(prog: Program, to_hex_atoms: bool = False) -> Any:
    if prog.atom is None and prog.first() == Program.to("$l"):
        return [deserialize_item(_, to_hex_atoms) for _ in prog.rest().as_iter()]
    elif prog.atom is None and prog.first() == Program.to("$d"):
        return program_to_dictionary(prog.rest(), to_hex_atoms)
    else:
        if to_hex_atoms:
            # This is a solution for the local library because we're using the Streamable class
            # It is not part of the protocol and should be ignored if ported elsewhere
            return f"0x{bytes(prog).hex()}"
        else:
            # Not sure this is the final serialization library so not covering for now
            return prog  # pragma: no cover


def dictionary_to_program(dictionary: Dict[str, Any], from_hex_atoms: bool = False) -> Program:
    prog_list: List[Program] = [
        Program.to((Program.to(key), serialize_item(value, from_hex_atoms))) for key, value in dictionary.items()
    ]
    return_value: Program = Program.to(("$d", prog_list))
    return return_value


def program_to_dictionary(prog: Program, to_hex_atoms: bool = False) -> Dict[str, Any]:
    return {item.first().atom.decode("utf8"): deserialize_item(item.rest(), to_hex_atoms) for item in prog.as_iter()}


_T_ClvmStreamable = TypeVar("_T_ClvmStreamable", bound="ClvmStreamable")


class ClvmStreamable(Streamable):
    def as_program(self) -> Program:
        return dictionary_to_program(self.to_json_dict(), from_hex_atoms=True)

    @classmethod
    def from_program(cls: Type[_T_ClvmStreamable], prog: Program) -> _T_ClvmStreamable:
        return cls.from_json_dict(program_to_dictionary(prog.rest(), to_hex_atoms=True))


@streamable
@dataclass(frozen=True)
class SigningTarget(ClvmStreamable):
    pubkey: Program
    message: Program
    hook: Program


@streamable
@dataclass(frozen=True)
class SigningResponse(ClvmStreamable):
    signature: Program
    hook: Program


@streamable
@dataclass(frozen=True)
class SumHint(ClvmStreamable):
    fingerprints: List[Program]
    synthetic_offset: Program


@streamable
@dataclass(frozen=True)
class PathHint(ClvmStreamable):
    root_fingerprint: Program
    path: List[Program]


@streamable
@dataclass(frozen=True)
class KeyHints(ClvmStreamable):
    sum_hints: List[SumHint]
    path_hints: List[PathHint]


@streamable
@dataclass(frozen=True)
class SigningInstructions(ClvmStreamable):
    key_hints: KeyHints
    targets: List[SigningTarget]


@streamable
@dataclass(frozen=True)
class Spend(ClvmStreamable):
    coin: Program
    puzzle: Program
    solution: Program

    @classmethod
    def from_coin_spend(cls, coin_spend: CoinSpend) -> Spend:
        return cls(
            Program.to(coin_as_list(coin_spend.coin)),
            coin_spend.puzzle_reveal.to_program(),
            coin_spend.solution.to_program(),
        )

    def as_coin_spend(self) -> CoinSpend:
        return CoinSpend(
            Coin(
                bytes32(self.coin.at("f").atom),
                bytes32(self.coin.at("rf").atom),
                uint64(int_from_bytes(self.coin.at("rrf").atom)),
            ),
            SerializedProgram.from_program(self.puzzle),
            SerializedProgram.from_program(self.solution),
        )


@streamable
@dataclass(frozen=True)
class TransactionInfo(ClvmStreamable):
    spends: List[Spend]


@streamable
@dataclass(frozen=True)
class UnsignedTransaction(ClvmStreamable):
    tx_info: TransactionInfo
    signing_instructions: SigningInstructions
