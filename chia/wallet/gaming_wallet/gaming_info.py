from dataclasses import dataclass
from chia.util import streamable
from chia.util.streamable import Streamable
from chia.types.blockchain_format.program import Program
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16
from chia_rs import CoinState
from chia.types.blockchain_format.coin import Coin


@streamable
@dataclass(frozen=True)
class GamingInfo(Streamable):
    game_coins: [Coin]

@streamable
@dataclass(frozen=True)
class GamingCoinData(Streamable):
    p2_puzzle: Program
    recovery_list_hash: bytes32 | None
    num_verification: uint16
    singleton_struct: Program
    metadata: Program
    inner_puzzle: Program | None
    coin_state: CoinState