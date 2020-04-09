from dataclasses import dataclass

from src.util.streamable import streamable, Streamable
from src.wallet.util.wallet_types import WalletType
from src.util.ints import uint32


@dataclass(frozen=True)
@streamable
class WalletInfo(Streamable):
    """
    # TODO(straya): describe
    """

    id: uint32
    name: str
    type: WalletType
    data: str
