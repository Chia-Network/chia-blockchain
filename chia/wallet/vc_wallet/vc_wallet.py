from __future__ import annotations

import logging

from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from blspy import G1Element

from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.wallet.announcement import Announcement
from chia.wallet.payment import Payment
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_drivers import VerifiedCredential
from chia.wallet.vc_wallet.vc_store import VCStore, VCRecord
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager


class VCWallet:
    # WalletStateManager is only imported for type hinting thus leaving pylint
    # unable to process this
    wallet_state_manager: WalletStateManager  # pylint: disable=used-before-assignment
    log: logging.Logger
    _id: uint32
    name: str
    store: VCStore

    @staticmethod
    async def create(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: Optional[str] = None,
    ) -> VCWallet:
        self = VCWallet()

        self.wallet_state_manager = wallet_state_manager
        self.log = logging.getLogger(__name__)
        self._id = wallet_info.id
        self.name = "VCWallet" if name is None else name
        self.store = await VCStore.create(wallet_state_manager.db_wrapper)

        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.VC.value)

    def id(self) -> uint32:
        return self._id

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection) -> None:
        """
        An unspent coin has arrived to our wallet. Get the parent spend to construct the current VerifiedCredential
        representation of the coin and add it to the DB if it's the newest version of the singleton.
        """
        # TODO - VCWallet: Implement this
        ...

    async def get_vc_record_for_launcher_id(self, launcher_id: bytes32) -> VCRecord:  # type: ignore[empty-body]
        """
        Go into the store and get the VC Record representing the latest representation of the VC we have on chain.
        """
        # TODO - VCWallet: Implement this
        ...

    async def launch_new_vc(  # type: ignore[empty-body]
        self, provider_did: bytes32, fee: uint64 = uint64(0)
    ) -> Tuple[VCRecord, List[TransactionRecord]]:
        """
        Given the DID ID of a proof provider, mint a brand new VC with an empty slot for proofs.

        Returns the tx records associated with the transaction as well as the expected unconfirmed VCRecord.
        """
        ...

    async def generate_signed_transaction(  # type: ignore[empty-body]
        self,
        payments: List[Payment],
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,  # must be pre-selected
        vc_coin: Optional[VerifiedCredential] = None,  # must match selected coin
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
        coin_announcements_to_make: Optional[Set[bytes]] = None,
        puzzle_announcements_to_make: Optional[Set[bytes]] = None,
        ignore_max_send_amount: bool = False,
        new_proof_hash: Optional[bytes32] = None,  # Requires that this key posesses the DID to update the specified VC
        trade_prices_list: Optional[Program] = None,
    ) -> List[TransactionRecord]:
        """
        Entry point for two standard actions:
         - Cycle the singleton and make an announcement authorizing something
         - Update the hash of the proofs contained within the VC (new_proof_hash is not None)

        Returns a 1 - 3 TransactionRecord objects depending on whether or not there's a fee and whether or not there's
        a DID announcement involved.
        """
        # TODO - VCWallet: Implement this
        ...

    async def select_coins(
        self,
        amount: uint64,
        exclude: Optional[List[Coin]] = None,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
        excluded_coin_amounts: Optional[List[uint64]] = None,
    ) -> Set[Coin]:
        raise RuntimeError("NFTWallet does not support select_coins()")

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """The VC wallet doesn't really have a balance."""
        return uint128(0)

    async def get_unconfirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """The VC wallet doesn't really have a balance."""
        return uint128(0)

    async def get_spendable_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """The VC wallet doesn't really have a balance."""
        return uint128(0)

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)

    async def get_max_send_amount(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        """This is the confirmed balance, which we set to 0 as the VC wallet doesn't have one."""
        return uint128(0)

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise RuntimeError("VCWallet does not support puzzle_hash_for_pk")

    def require_derivation_paths(self) -> bool:
        return False

    def get_name(self) -> str:
        return self.name
