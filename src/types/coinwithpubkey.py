"""CoinWithPubkey is a coin assumed to be using the standard puzzle, and its pubkey"""

from dataclasses import dataclass
from blspy import G1Element
from .coin import Coin

@dataclass(frozen=True)
class CoinWithPubkey(Coin):
    """
    This is a coin with information needed by the standard transaction.
    It contains  a pubkey for the secret key used to unlock it.
    CoinWithPubkey is used by the command line tool "chia tx"
    """

    pubkey: G1Element
