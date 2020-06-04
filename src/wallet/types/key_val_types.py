from dataclasses import dataclass
from typing import List

from src.types.spend_bundle import SpendBundle
from src.util.streamable import streamable, Streamable


@dataclass(frozen=True)
@streamable
class Trades(Streamable):
    trades: List[SpendBundle]
