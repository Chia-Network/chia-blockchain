from dataclasses import dataclass

from src.util.streamable import streamable, Streamable
from src.wallet.util.wallet_types import WalletType
from src.util.ints import uint32


@dataclass(frozen=True)
@streamable
class WalletInfo(Streamable):
    """
    This object represents the wallet data as it is stored in DB.
    ID: Main wallet (Standard) is stored at index 1, every wallet created after done has auto incremented id.
    Name: can be a user provided or default generated name. (can be modified)
    Type: is specified during wallet creation and should never be changed.
    Data: this filed is intended to be used for storing any wallet specific information required for it.
    (RL wallet stores origin_id, admin/user pubkey, rate limit, etc.)
    This data should be json encoded string.
    """

    id: uint32
    name: str
    type: WalletType
    data: str
