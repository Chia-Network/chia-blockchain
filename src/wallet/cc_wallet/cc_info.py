from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.types.program import Program
from src.types.sized_bytes import bytes32
from src.util.streamable import streamable, Streamable
from src.wallet.cc_wallet import cc_wallet_puzzles
from src.wallet.cc_wallet.ccparent import CCParent


@dataclass(frozen=True)
@streamable
class CCInfo(Streamable):
    parent_info: List[Tuple[bytes32, Optional[CCParent]]]  # {coin.name(): CCParent}
    my_colour_name: str

    def puzzle_for_inner_puzzle(self, inner_puzzle: Program) -> Program:
        genesis_id = bytes.fromhex(self.my_colour_name) if self.my_colour_name else 0
        return cc_wallet_puzzles.puzzle_for_inner_puzzle(inner_puzzle, genesis_id)

    def genesis_id(self):
        return self.my_colour_name
