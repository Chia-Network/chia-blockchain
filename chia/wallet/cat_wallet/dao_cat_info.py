from typing import List, Optional
from chia.types.blockchain_format.program import Program
from chia.util.ints import uint64
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from dataclasses import dataclass
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class LockedCoinInfo(Streamable):
    coin: Coin
    inner_puzzle: Program
    previous_votes: List[Optional[bytes32]]


@streamable
@dataclass(frozen=True)
class DAOCATInfo(Streamable):
    dao_wallet_id: uint64
    free_cat_wallet_id: uint64
    limitations_program_hash: bytes32
    my_tail: Optional[Program]  # this is the program
    locked_coins: List[LockedCoinInfo]
