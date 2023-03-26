from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from blspy import AugSchemeMPL, G1Element, G2Element
from chia_rs.chia_rs import CoinState

from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.payment import Payment
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    solution_for_conditions,
)
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_wallet.vc_drivers import VerifiedCredential
from chia.wallet.vc_wallet.vc_store import VCRecord, VCStore
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
    standard_wallet: Wallet
    wallet_info: WalletInfo
    store: VCStore

    @staticmethod
    async def create_new_vc_wallet(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        name: Optional[str] = None,
    ) -> VCWallet:
        self = VCWallet()
        self.wallet_state_manager = wallet_state_manager
        self.standard_wallet = wallet
        name = "VCWallet" if name is None else name
        self.log = logging.getLogger(name if name else __name__)
        self.store = wallet_state_manager.vc_store
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(name, uint32(WalletType.VC.value), "")
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id, False)
        return self

    @staticmethod
    async def create(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: Optional[str] = None,
    ) -> VCWallet:
        self = VCWallet()
        self.wallet_state_manager = wallet_state_manager
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else wallet_info.name)
        self.wallet_info = wallet_info
        self.store = wallet_state_manager.vc_store
        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.VC.value)

    def id(self) -> uint32:
        return self.wallet_info.id

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection) -> None:
        """
        An unspent coin has arrived to our wallet. Get the parent spend to construct the current VerifiedCredential
        representation of the coin and add it to the DB if it's the newest version of the singleton.
        """
        wallet_node = self.wallet_state_manager.wallet_node
        coin_states: Optional[List[CoinState]] = await wallet_node.get_coin_state([coin.parent_coin_info], peer=peer)
        if coin_states is None:
            self.log.error(f"Cannot find parent coin of the verified credential coin: {coin.name().hex()}")
            return
        parent_coin = coin_states[0].coin
        cs = await wallet_node.fetch_puzzle_solution(height, parent_coin, peer)
        if cs is None:
            self.log.error(f"Cannot get verified credential coin: {coin.name().hex()} puzzle and solution")
            return
        vc = VerifiedCredential.get_next_from_coin_spend(cs)
        vc_record: VCRecord = VCRecord(vc, height)
        await self.store.add_or_replace_vc_record(vc_record)

    async def get_vc_record_for_launcher_id(self, launcher_id: bytes32) -> VCRecord:
        """
        Go into the store and get the VC Record representing the latest representation of the VC we have on chain.
        """
        vc_record = await self.store.get_vc_record(launcher_id)
        if vc_record is None:
            raise ValueError(f"Verified credential {launcher_id.hex()} doesn't exist.")
        return vc_record

    async def launch_new_vc(
        self,
        provider_did: bytes32,
        inner_puzzle_hash: Optional[bytes32] = None,
        fee: uint64 = uint64(0),
    ) -> Tuple[VCRecord, List[TransactionRecord]]:
        """
        Given the DID ID of a proof provider, mint a brand new VC with an empty slot for proofs.

        Returns the tx records associated with the transaction as well as the expected unconfirmed VCRecord.
        """
        # Check if we own the DID
        found_did = False
        for _, wallet in self.wallet_state_manager.wallets.items():
            if wallet.type() == WalletType.DECENTRALIZED_ID:
                assert isinstance(wallet, DIDWallet)
                if bytes32.fromhex(wallet.get_my_DID()) == provider_did:
                    found_did = True
                    break
        if not found_did:
            raise ValueError(f"You don't own the DID {provider_did.hex()}")
        # Mint VC
        coins = await self.standard_wallet.select_coins(uint64(2) + fee, min_coin_amount=uint64(2) + fee)
        if len(coins) == 0:
            raise ValueError("Cannot find a coin to mint the verified credential.")
        if inner_puzzle_hash is None:
            inner_puzzle_hash = await self.standard_wallet.get_puzzle_hash(new=False)
        original_coin = coins.copy().pop()
        dpuz, coin_spends, vc = VerifiedCredential.launch(
            original_coin,
            provider_did,
            inner_puzzle_hash,
            inner_puzzle_hash,
        )
        solution = solution_for_conditions(dpuz.rest())
        original_puzzle = await self.standard_wallet.puzzle_for_puzzle_hash(original_coin.puzzle_hash)
        coin_spends.append(CoinSpend(original_coin, original_puzzle, solution))
        spend_bundle = await sign_coin_spends(
            coin_spends,
            self.standard_wallet.secret_key_store.secret_key_for_public_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )
        now = uint64(int(time.time()))
        add_list: List[Coin] = list(spend_bundle.additions())
        rem_list: List[Coin] = list(spend_bundle.removals())
        vc_record: VCRecord = VCRecord(vc, uint32(0))
        tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=now,
            to_puzzle_hash=inner_puzzle_hash,
            amount=uint64(1),
            fee_amount=uint64(fee),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=add_list,
            removals=rem_list,
            wallet_id=uint32(1),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
            memos=list(compute_memos(spend_bundle).items()),
        )

        return vc_record, [tx]

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

    async def sign(self, spend_bundle: SpendBundle, puzzle_hashes: Optional[List[bytes32]] = None) -> SpendBundle:
        if puzzle_hashes is None:
            puzzle_hashes = []
        sigs: List[G2Element] = []
        for spend in spend_bundle.coin_spends:
            pks = {}
            for ph in puzzle_hashes:
                keys = await self.wallet_state_manager.get_keys(ph)
                assert keys
                pks[bytes(keys[0])] = private = keys[1]
                synthetic_secret_key = calculate_synthetic_secret_key(private, DEFAULT_HIDDEN_PUZZLE_HASH)
                synthetic_pk = synthetic_secret_key.get_g1()
                pks[bytes(synthetic_pk)] = synthetic_secret_key
            error, conditions, cost = conditions_dict_for_solution(
                spend.puzzle_reveal.to_program(),
                spend.solution.to_program(),
                self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
            )
            if conditions is not None:
                for pk, msg in pkm_pairs_for_conditions_dict(
                    conditions, spend.coin.name(), self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
                ):
                    try:
                        sk = pks.get(pk)
                        if sk:
                            self.log.debug("Found key, signing for pk: %s", pk)
                            sigs.append(AugSchemeMPL.sign(sk, msg))
                        else:
                            self.log.warning("Couldn't find key for: %s", pk)
                    except AssertionError:
                        raise ValueError("This spend bundle cannot be signed by the NFT wallet")

        agg_sig = AugSchemeMPL.aggregate(sigs)
        return SpendBundle.aggregate([spend_bundle, SpendBundle([], agg_sig)])

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
        return self.wallet_info.name
