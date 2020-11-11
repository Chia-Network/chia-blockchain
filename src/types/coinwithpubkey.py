from .coin import Coin
from blspy import G1Element


class CoinWithPubkey(Coin):
    """
    This is a coin with information needed by the standard transaction.
    It contains  a pubkey for the secret key used to unlock it.
    CoinWithPubkey is used by the command line tool "chia tx"
    """

    pubkey: G1Element

    def __init__(self, coin: Coin, pubkey: G1Element):
        self.pubkey = pubkey
        super(CoinWithPubkey, self).__init__(
            coin.parent_coin_info, coin.puzzle_hash, coin.amount
        )
