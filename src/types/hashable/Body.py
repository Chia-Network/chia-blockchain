
from src.util.ints import uint64
from .BLSSignature import BLSSignature
from .Coin import Coin
from .Program import Program
from src.util.streamable import Streamable, streamable


@streamable
class Body(Streamable):
    """
    This structure is pointed to by the Header, and contains everything necessary to determine
    the additions and removals from a block.
    """
    coinbase_signature: BLSSignature
    coinbase_coin: Coin
    fees_coin: Coin
    solution_program: Program
    program_cost: uint64
    aggregated_signature: BLSSignature
