from __future__ import annotations

from typing import List, Tuple

from chia_rs import CoinSpend

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_protocol import WalletProtocol


class SingletonWallet(WalletProtocol):
    """

    Event:
    A singleton eve coin is detected by the WalletStateManager.
    The WSM does not have a wallet for that launcher_id
    - create_wallet_from_coin is called
    - wallet created in DB
    -


    Event:
    A singleton spend is detected for an existing (WSM detects existing wallet by ____
    - apply_state_transition


    Issues:
        These names ... could be better
        What about multiple Singletons being managed from the same wallet?
        What about coins not following the singleton pattern?



    Generalized inner/outer wallet ideas:
    - detect outer (CAT / Singleton)
    - detect inner (does this coin belong to me)
    - create from spend
    - create new wallet for singleton that already exists (we have not yet received the coin)
    - spending when you don't own the singleton, but you can spend
      - Examples:
    """

    ###################### Class methods ######################################

    # Name: detect_singleton_coin_type ?
    @classmethod
    def coin_is_my_singleton_wallet_type(cls, coin: Coin, inner_puzzle: Program) -> bool:
        """Match the singleton inner puzzle for this type of wallet"""
        ...

    # def register_singleton_inner_puzzle(self) -> Program:
    #    ...

    @classmethod
    def create_wallet_from_coin(
        cls,
        wallet_state_manager: Any,
        standard_wallet: Wallet,
        launcher_coin_id: bytes32,
        block_spends: List[CoinSpend],
        block_height: uint32,
        *,
        name: str = None,
    ) -> SingletonRecord:
        """Create a new wallet from a Singleton we found on the blockchain"""
        ...

    @classmethod
    def create_wallet_spend(cls) -> Tuple[TransactionRecord, bytes32, bytes32]:
        """
        This method creates the launcher spend for a new wallet of this type.
        Used when the wallet is being created locally.
        It DOES NOT create local DB entries. We create a wallet instance only
        when we detect a new launcher_id transaction on-chain.

        returns: (standard_wallet_record, p2_singleton_puzzle_hash, launcher_coin_id)
        """
        ...

    ###########################################################
    async def apply_state_transition(self, new_state: CoinSpend, block_height: uint32) -> bool:
        """Called when a singleton of this wallet is updated / spent"""
        ...

    # Note: we need to add to WalletProtocol
    #   rewind / rollback to height
    #   create from WalletRecord ("create_from_db")
