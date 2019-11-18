from dataclasses import dataclass

from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class Transaction(Streamable):
    pass
