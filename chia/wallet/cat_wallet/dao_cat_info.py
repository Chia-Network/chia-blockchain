from typing import List
from chia.types.blockchain_format.program import Program
from chia.util.ints import uint64
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32


class LockedCoinInfo:
    coin: Coin
    inner_puzzle: Program
    active_proposal_votes: List[bytes32]


class DAOCATInfo:
    current_innerpuzzes: List[Program]
    dao_wallet_id: uint64
    locked_coins: List[LockedCoinInfo]
