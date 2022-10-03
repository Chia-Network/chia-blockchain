from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import final, Type, TypeVar

from chia.cmds.units import units
from chia.util.ints import uint64

_T_Mojos = TypeVar("_T_Mojos", bound="Mojos")


@dataclass
@final
class Mojos:
    """
    XCH conversion: 1 Chia = 1 Trillion Mojos
    """

    mojos: uint64

    def __init__(self, mojos: uint64):
        self.mojos = mojos

    @classmethod
    def from_chia(cls: Type[_T_Mojos], chia_amount: int) -> Mojos:
        xch = Decimal(chia_amount)
        mojos = uint64(int(xch * units["chia"]))
        return cls(mojos)
