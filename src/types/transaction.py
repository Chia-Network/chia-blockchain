from dataclasses import dataclass

from src.types.hashable.SpendBundle import SpendBundle
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class Transaction(Streamable):
    sb: SpendBundle

