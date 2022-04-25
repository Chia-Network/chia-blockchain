from chia.types.blockchain_format.program import Program
from clvm.casts import int_from_bytes
from clvm.SExp import SExp
from clvm_tools.binutils import assemble, type_for_atom
from dataclasses import dataclass
from ir.Type import Type
from typing import Any, Dict, Optional

"""
The following two classes act as wrapper classes around dictionaries of strings.
Values in the dictionary are assumed to be strings in CLVM format (0x for bytes, etc.)
When you access a value in the dictionary, it will be deserialized to a str, int, bytes, or Program appropriately.
"""


@dataclass(frozen=True)
class PuzzleInfo:
    """
    There are two 'magic' keys in a PuzzleInfo object:
      - 'type' must be an included key (for easy lookup of drivers)
      - 'also' gets its own method as it's the supported way to do recursion of PuzzleInfos
    """

    info: Dict[str, Any]

    def __post_init__(self) -> None:
        if "type" not in self.info:
            raise ValueError("A type is required to initialize a puzzle driver")

    def __getitem__(self, item: str) -> Any:
        value = self.info[item]
        return decode_info_value(PuzzleInfo, value)

    def type(self) -> str:
        return str(self.info["type"])

    def also(self) -> Optional["PuzzleInfo"]:
        if "also" in self.info:
            return PuzzleInfo(self.info["also"])
        else:
            return None


@dataclass(frozen=True)
class Solver:
    info: Dict[str, Any]

    def __getitem__(self, item: str) -> Any:
        value = self.info[item]
        return decode_info_value(Solver, value)


def decode_info_value(cls: Any, value: Any) -> Any:
    if isinstance(value, dict):
        return cls(value)
    elif isinstance(value, list):
        return [decode_info_value(cls, v) for v in value]
    else:
        expression: Sexp = assemble(value)
        if expression.atom is None:
            return Program(expression)
        else:
            atom: bytes = expression.atom
            typ = type_for_atom(atom)
            if typ == Type.QUOTES:
                return bytes(atom).decode("utf8")
            elif typ == Type.INT:
                return int_from_bytes(atom)
            else:
                return atom
