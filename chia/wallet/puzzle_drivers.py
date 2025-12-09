from __future__ import annotations

from typing import Any

from clvm.SExp import SExp
from clvm_tools.binutils import assemble, type_for_atom
from ir.Type import Type
from typing_extensions import Self

from chia.types.blockchain_format.program import Program
from chia.util.casts import int_from_bytes

"""
The following two classes act as wrapper classes around dictionaries of strings.
Values in the dictionary are assumed to be strings in CLVM format (0x for bytes, etc.)
When you access a value in the dictionary, it will be deserialized to a str, int, bytes, or Program appropriately.
"""


class PuzzleInfo:
    """
    There are two 'magic' keys in a PuzzleInfo object:
      - 'type' must be an included key (for easy lookup of drivers)
      - 'also' gets its own method as it's the supported way to do recursion of PuzzleInfos
    """

    info: dict[str, Any]

    def __init__(self, info: dict[str, Any]) -> None:
        self.info = info
        self.__post_init__()

    def __post_init__(self) -> None:
        if "type" not in self.info:
            raise ValueError("A type is required to initialize a puzzle driver")

    def __getitem__(self, item: str) -> Any:
        value = self.info[item]
        return decode_info_value(PuzzleInfo, value)

    def __eq__(self, other: object) -> bool:
        for key, value in self.info.items():
            try:
                if self[key] != other[key]:  # type: ignore
                    return False
            except Exception:
                return False
        return True

    def __contains__(self, item: str) -> bool:
        if item in self.info:
            return True
        else:
            return False

    def type(self) -> str:
        return str(self.info["type"])

    def also(self) -> PuzzleInfo | None:
        if "also" in self.info:
            return PuzzleInfo(self.info["also"])
        else:
            return None

    def check_type(self, types: list[str]) -> bool:
        if types == []:
            if self.also() is None:
                return True
            else:
                return False
        elif self.type() == types[0]:
            types.pop(0)
            if self.also():
                return self.also().check_type(types)  # type: ignore
            else:
                return self.check_type(types)
        else:
            return False

    # Methods to make this a valid Streamable member
    # Should not be being serialized as bytes
    stream = None
    parse = None

    def to_json_dict(self) -> dict[str, Any]:
        return self.info

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> Self:
        return cls(json_dict)


class Solver:
    info: dict[str, Any]

    def __init__(self, info: dict[str, Any]) -> None:
        self.info = info

    def __getitem__(self, item: str) -> Any:
        value = self.info[item]
        return decode_info_value(Solver, value)

    def __eq__(self, other: object) -> bool:
        for key, value in self.info.items():
            try:
                if self[key] != other[key]:  # type: ignore
                    return False
            except Exception:
                return False
        return True

    # Methods to make this a valid Streamable member
    stream = None
    parse = None

    def to_json_dict(self) -> dict[str, Any]:
        return self.info

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> Self:
        return cls(json_dict)


def decode_info_value(cls: Any, value: Any) -> Any:
    if isinstance(value, dict):
        return cls(value)
    elif isinstance(value, list):
        return [decode_info_value(cls, v) for v in value]
    elif isinstance(value, Program) and value.atom is None:
        return value
    else:
        if value in {"()", ""}:  # special case
            return Program.to([])
        expression: SExp = assemble(value)
        if expression.atom is None:
            return Program(expression)
        else:
            atom: bytes = expression.atom
            typ = type_for_atom(atom)
            if typ == Type.QUOTES and value[0:2] != "0x":
                return bytes(atom).decode("utf8")
            elif typ == Type.INT:
                return int_from_bytes(atom)
            else:
                return atom
