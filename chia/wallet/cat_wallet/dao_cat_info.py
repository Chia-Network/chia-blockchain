from typing import List, Optional
from chia.types.blockchain_format.program import Program
from chia.util.ints import uint64
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32


class LockedCoinInfo:
    coin: Coin
    inner_puzzle: Program
    active_proposal_votes: List[bytes32]


class DAOCATInfo:
    dao_wallet_id: uint64
    free_cat_wallet_id: uint64
    limitations_program_hash: bytes32
    my_tail: Optional[Program]  # this is the program
    locked_coins: List[LockedCoinInfo]
