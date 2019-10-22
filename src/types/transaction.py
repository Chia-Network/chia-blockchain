from src.util.streamable import streamable, Streamable
from dataclasses import dataclass


@dataclass(frozen=True)
@streamable
class Transaction(Streamable):
    pass
