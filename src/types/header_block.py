from dataclasses import dataclass
from typing import Optional

from src.types.challenge import Challenge
from src.types.header import Header
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class HeaderBlock(Streamable):
    proof_of_space: ProofOfSpace
    proof_of_time: Optional[ProofOfTime]
    challenge: Optional[Challenge]
    header: Header

    @property
    def prev_header_hash(self):
        return self.header.data.prev_header_hash

    @property
    def height(self):
        return self.challenge.height

    @property
    def weight(self):
        return self.challenge.total_weight

    @property
    def header_hash(self):
        return self.header.header_hash


@dataclass(frozen=True)
@streamable
class SmallHeaderBlock(Streamable):
    header: Header
    challenge: Challenge

    @property
    def prev_header_hash(self):
        return self.header.data.prev_header_hash

    @property
    def height(self):
        return self.challenge.height

    @property
    def weight(self):
        return self.challenge.total_weight

    @property
    def header_hash(self):
        return self.header.header_hash
