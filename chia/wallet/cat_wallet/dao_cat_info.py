from typing import List
from chia.types.blockchain_format.program import Program
from chia.util.ints import uint64


class DAOCATInfo:
    current_innerpuzzes: List[Program]
    dao_wallet_id: uint64
