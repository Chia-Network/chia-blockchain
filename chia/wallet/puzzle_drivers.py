from clvm.casts import int_from_bytes
from clvm_tools.binutils import assemble, type_for_atom
from dataclasses import dataclass
from ir.Type import Type
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class PuzzleInfo:
    info: Dict[str, Any]

    def __post_init__(self) -> None:
        if "type" not in self.info:
            raise ValueError("A type is required to initialize a puzzle driver")

    def __getitem__(self, item: str) -> Any:
        value = self.info[decode_info_value(PuzzleInfo, item)]
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
        value = self.info[decode_info_value(Solver, item)]
        return decode_info_value(Solver, value)


def decode_info_value(cls: Any, value: Any) -> Any:
    if isinstance(value, dict):
        return cls(value)
    elif isinstance(value, list):
        return [decode_info_value(cls, v) for v in value]
    else:
        atom: bytes = assemble(value).as_atom()  # type: ignore
        typ = type_for_atom(atom)
        if typ == Type.QUOTES:
            return bytes(atom).decode("utf8")
        elif typ == Type.INT:
            return int_from_bytes(atom)
        else:
            return atom
