from dataclasses import dataclass
from typing import Optional

from src.util.streamable import streamable, Streamable
from src.wallet.util.wallet_types import WalletType
from src.util.ints import uint32


@dataclass(frozen=True)
@streamable
class WalletAction(Streamable):
    """
    This object represents the wallet action as it is stored in the database.

    Purpose:
    Some wallets require wallet node to perform a certain action when event happens.
    For Example, coloured coin wallet needs to fetch solutions once it receives a coin.
    In order to be safe from losing connection, closing the app, etc, those actions need to be persisted.

    id: auto-incremented for every added action
    name: Specified by the wallet
    Wallet_id: ID of the wallet that created this action
    type: Type of the wallet that created this action
    wallet_callback: Name of the callback function in the wallet that created this action, if specified it will
    get called when action has been performed.
    done: Indicates if the action has been performed
    data: JSON encoded string containing any data wallet or a wallet_node needs for this specific action.
    """

    id: uint32
    name: str
    wallet_id: int
    type: WalletType
    wallet_callback: Optional[str]
    done: bool
    data: str
