from dataclasses import dataclass

from src.util.streamable import streamable, Streamable
from src.wallet.util.wallet_types import WalletType


@dataclass(frozen=True)
@streamable
class WalletInfo(Streamable):
    """
    Wrapper around data that
    """

    id: int
    name: str
    type: WalletType
    data: str
