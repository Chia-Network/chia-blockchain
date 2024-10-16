from __future__ import annotations

import logging
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from chia_rs import G1Element, G2Element
from typing_extensions import Unpack

from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import VersionedBlob
from chia.wallet.cat_wallet.cat_info import CATCoinData, CRCATInfo
from chia.wallet.cat_wallet.cat_utils import CAT_MOD_HASH, CAT_MOD_HASH_HASH, construct_cat_puzzle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.coin_selection import select_coins
from chia.wallet.conditions import (
    Condition,
    ConditionValidTimes,
    CreateCoinAnnouncement,
    CreatePuzzleAnnouncement,
    UnknownCondition,
    parse_timelock_info,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trading.offer import Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.compute_hints import compute_spend_hints_and_additions
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.query_filter import HashFilter
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_sync_utils import fetch_coin_spend_for_coin_state
from chia.wallet.util.wallet_types import CoinType, WalletType
from chia.wallet.vc_wallet.cr_cat_drivers import (
    CRCAT,
    CRCATMetadata,
    CRCATVersion,
    ProofsChecker,
    construct_cr_layer_hash,
    construct_pending_approval_state,
)
from chia.wallet.vc_wallet.vc_drivers import VerifiedCredential
from chia.wallet.vc_wallet.vc_wallet import VCWallet
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import MetadataTypes, WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import GSTOptionalArgs, WalletProtocol
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager


class CRCATWallet(CATWallet):
    wallet_state_manager: WalletStateManager
    log: logging.Logger
    wallet_info: WalletInfo
    info: CRCATInfo
    standard_wallet: Wallet

    @staticmethod
    def default_wallet_name_for_unknown_cat(limitations_program_hash_hex: str) -> str:
        return f"CAT {limitations_program_hash_hex[:16]}..."

    @property
    def cost_of_single_tx(self) -> int:
        return 78000000  # Estimate measured in testing

    @staticmethod
    async def create_new_cat_wallet(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        cat_tail_info: Dict[str, Any],
        amount: uint64,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        name: Optional[str] = None,
        push: bool = False,
    ) -> CATWallet:  # pragma: no cover
        raise NotImplementedError("create_new_cat_wallet is a legacy method and is not available on CR-CAT wallets")

    @staticmethod
    async def get_or_create_wallet_for_cat(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        limitations_program_hash_hex: str,
        name: Optional[str] = None,
        authorized_providers: Optional[List[bytes32]] = None,
        proofs_checker: Optional[ProofsChecker] = None,
    ) -> CRCATWallet:
        if authorized_providers is None or proofs_checker is None:  # pragma: no cover
            raise ValueError("get_or_create_wallet_for_cat was call on CRCATWallet without proper arguments")
        self = CRCATWallet()
        self.standard_wallet = wallet
        if name is None:
            name = self.default_wallet_name_for_unknown_cat(limitations_program_hash_hex)
        self.log = logging.getLogger(name)

        tail_hash = bytes32.from_hexstr(limitations_program_hash_hex)

        for id, w in wallet_state_manager.wallets.items():
            if w.type() == CRCATWallet.type():
                assert isinstance(w, CRCATWallet)
                if w.get_asset_id() == limitations_program_hash_hex:
                    self.log.warning("Not creating wallet for already existing CR-CAT wallet")
                    return w

        self.wallet_state_manager = wallet_state_manager

        self.info = CRCATInfo(tail_hash, None, authorized_providers, proofs_checker)
        info_as_string = bytes(self.info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(name, WalletType.CRCAT, info_as_string)

        await self.wallet_state_manager.add_new_wallet(self)
        return self

    @classmethod
    async def create_from_puzzle_info(
        cls,
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        puzzle_driver: PuzzleInfo,
        name: Optional[str] = None,
        # We're hinting this as Any for mypy by should explore adding this to the wallet protocol and hinting properly
        potential_subclasses: Dict[AssetType, Any] = {},
    ) -> Any:
        cr_layer: Optional[PuzzleInfo] = puzzle_driver.also()
        if cr_layer is None:  # pragma: no cover
            raise ValueError("create_from_puzzle_info called on CRCATWallet with a non CR-CAT puzzle driver")
        return await cls.get_or_create_wallet_for_cat(
            wallet_state_manager,
            wallet,
            puzzle_driver["tail"].hex(),
            name,
            [bytes32(provider) for provider in cr_layer["authorized_providers"]],
            ProofsChecker.from_program(uncurry_puzzle(cr_layer["proofs_checker"])),
        )

    @staticmethod
    async def create(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        wallet_info: WalletInfo,
    ) -> CRCATWallet:
        self = CRCATWallet()

        self.log = logging.getLogger(__name__)
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.standard_wallet = wallet
        self.info = CRCATInfo.from_bytes(hexstr_to_bytes(self.wallet_info.data))
        return self

    @classmethod
    async def convert_to_cr(
        cls,
        cat_wallet: CATWallet,
        authorized_providers: List[bytes32],
        proofs_checker: ProofsChecker,
    ) -> None:
        replace_self = cls()
        replace_self.standard_wallet = cat_wallet.standard_wallet
        replace_self.log = logging.getLogger(cat_wallet.get_name())
        replace_self.log.info(f"Converting CAT wallet {cat_wallet.id()} to CR-CAT wallet")
        replace_self.wallet_state_manager = cat_wallet.wallet_state_manager
        replace_self.info = CRCATInfo(
            cat_wallet.cat_info.limitations_program_hash, None, authorized_providers, proofs_checker
        )
        await cat_wallet.wallet_state_manager.user_store.update_wallet(
            WalletInfo(
                cat_wallet.id(), cat_wallet.get_name(), uint8(WalletType.CRCAT.value), bytes(replace_self.info).hex()
            )
        )
        updated_wallet_info = await cat_wallet.wallet_state_manager.user_store.get_wallet_by_id(cat_wallet.id())
        assert updated_wallet_info is not None
        replace_self.wallet_info = updated_wallet_info

        cat_wallet.wallet_state_manager.wallets[cat_wallet.id()] = replace_self

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.CRCAT

    def id(self) -> uint32:
        return self.wallet_info.id

    def get_asset_id(self) -> str:
        return self.info.limitations_program_hash.hex()

    async def set_tail_program(self, tail_program: str) -> None:  # pragma: no cover
        raise NotImplementedError("set_tail_program is a legacy method and is not available on CR-CAT wallets")

    async def coin_added(
        self, coin: Coin, height: uint32, peer: WSChiaConnection, coin_data: Optional[CATCoinData]
    ) -> None:
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"CR-CAT wallet has been notified that {coin.name().hex()} was added")
        try:
            coin_state = await self.wallet_state_manager.wallet_node.get_coin_state([coin.parent_coin_info], peer=peer)
            coin_spend = await fetch_coin_spend_for_coin_state(coin_state[0], peer)
            await self.add_crcat_coin(coin_spend, coin, height)
        except Exception as e:
            self.log.debug(f"Exception: {e}, traceback: {traceback.format_exc()}")

    async def add_crcat_coin(self, coin_spend: CoinSpend, coin: Coin, height: uint32) -> None:
        try:
            new_cr_cats: List[CRCAT] = CRCAT.get_next_from_coin_spend(coin_spend)
            hint_dict = {
                id: hc.hint
                for id, hc in compute_spend_hints_and_additions(coin_spend)[0].items()
                if hc.hint is not None
            }
            cr_cat: CRCAT = list(filter(lambda c: c.coin.name() == coin.name(), new_cr_cats))[0]
            if (
                await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
                    cr_cat.inner_puzzle_hash
                )
                is not None
            ):
                self.log.info(f"Found CRCAT coin {coin.name().hex()}")
                is_pending = False
            elif (
                cr_cat.inner_puzzle_hash
                == construct_pending_approval_state(
                    hint_dict[coin.name()],
                    uint64(coin.amount),
                ).get_tree_hash()
            ):
                self.log.info(f"Found pending approval CRCAT coin {coin.name().hex()}")
                is_pending = True
                created_timestamp = await self.wallet_state_manager.wallet_node.get_timestamp_for_height(uint32(height))
                spend_bundle = WalletSpendBundle([coin_spend], G2Element())
                memos = compute_memos(spend_bundle)
                # This will override the tx created in the wallet state manager
                tx_record = TransactionRecord(
                    confirmed_at_height=height,
                    created_at_time=uint64(created_timestamp),
                    to_puzzle_hash=hint_dict[coin.name()],
                    amount=uint64(coin.amount),
                    fee_amount=uint64(0),
                    confirmed=True,
                    sent=uint32(0),
                    spend_bundle=None,
                    additions=[coin],
                    removals=[coin_spend.coin],
                    wallet_id=self.id(),
                    sent_to=[],
                    trade_id=None,
                    type=uint32(TransactionType.INCOMING_CRCAT_PENDING),
                    name=coin.name(),
                    memos=list(memos.items()),
                    valid_times=ConditionValidTimes(),
                )
                await self.wallet_state_manager.tx_store.add_transaction_record(tx_record)
            else:  # pragma: no cover
                self.log.error(f"Unknown CRCAT inner puzzle, coin ID: {coin.name().hex()}")
                return None
            coin_record = WalletCoinRecord(
                coin,
                uint32(height),
                uint32(0),
                False,
                False,
                WalletType.CRCAT,
                self.id(),
                CoinType.CRCAT_PENDING if is_pending else CoinType.CRCAT,
                VersionedBlob(
                    CRCATVersion.V1.value,
                    bytes(
                        CRCATMetadata(
                            cr_cat.lineage_proof, hint_dict[coin.name()] if is_pending else cr_cat.inner_puzzle_hash
                        )
                    ),
                ),
            )
            await self.wallet_state_manager.coin_store.add_coin_record(coin_record)
        except Exception:
            # The parent is not a CAT which means we need to scrub all of its children from our DB
            self.log.error(f"Cannot add CRCAT coin: {traceback.format_exc()}")
            child_coin_records = await self.wallet_state_manager.coin_store.get_coin_records_by_parent_id(
                coin_spend.coin.name()
            )
            if len(child_coin_records) > 0:
                for record in child_coin_records:
                    if record.wallet_id == self.id():  # pragma: no cover
                        await self.wallet_state_manager.coin_store.delete_coin_record(record.coin.name())
                        # We also need to make sure there's no record of the transaction
                        await self.wallet_state_manager.tx_store.delete_transaction_record(record.coin.name())

    def require_derivation_paths(self) -> bool:
        return False

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:  # pragma: no cover
        raise NotImplementedError("puzzle_for_pk is a legacy method and is not available on CR-CAT wallets")

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:  # pragma: no cover
        raise NotImplementedError("puzzle_hash_for_pk is a legacy method and is not available on CR-CAT wallets")

    async def get_new_cat_puzzle_hash(self) -> bytes32:  # pragma: no cover
        raise NotImplementedError("get_new_cat_puzzle_hash is a legacy method and is not available on CR-CAT wallets")

    async def inner_puzzle_for_cat_puzhash(self, cat_hash: bytes32) -> Program:  # pragma: no cover
        raise NotImplementedError(
            "inner_puzzle_for_cat_puzhash is a legacy method and is not available on CR-CAT wallets"
        )

    async def get_cat_spendable_coins(self, records: Optional[Set[WalletCoinRecord]] = None) -> List[WalletCoinRecord]:
        result: List[WalletCoinRecord] = []

        record_list: Set[WalletCoinRecord] = await self.wallet_state_manager.get_spendable_coins_for_wallet(
            self.id(), records
        )

        for record in record_list:
            crcat: CRCAT = self.coin_record_to_crcat(record)
            if crcat.lineage_proof is not None and not crcat.lineage_proof.is_none():
                result.append(record)

        return result

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        if record_list is None:
            record_list = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(
                self.id(), CoinType.CRCAT
            )
        amount: uint128 = uint128(0)
        for record in record_list:
            crcat: CRCAT = self.coin_record_to_crcat(record)
            if crcat.lineage_proof is not None and not crcat.lineage_proof.is_none():
                amount = uint128(amount + record.coin.amount)

        self.log.info(f"Confirmed balance for cat wallet {self.id()} is {amount}")
        return uint128(amount)

    async def get_pending_approval_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        if record_list is None:
            record_list = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(
                self.id(), CoinType.CRCAT_PENDING
            )
        amount: uint128 = uint128(0)
        for record in record_list:
            crcat: CRCAT = self.coin_record_to_crcat(record)
            if crcat.lineage_proof is not None and not crcat.lineage_proof.is_none():
                amount = uint128(amount + record.coin.amount)

        self.log.info(f"Pending approval balance for cat wallet {self.id()} is {amount}")
        return uint128(amount)

    async def convert_puzzle_hash(self, puzzle_hash: bytes32) -> bytes32:
        return puzzle_hash

    @staticmethod
    def get_metadata_from_record(coin_record: WalletCoinRecord) -> CRCATMetadata:
        metadata: MetadataTypes = coin_record.parsed_metadata()
        assert isinstance(metadata, CRCATMetadata)
        return metadata

    def coin_record_to_crcat(self, coin_record: WalletCoinRecord) -> CRCAT:
        if coin_record.coin_type not in {CoinType.CRCAT, CoinType.CRCAT_PENDING}:  # pragma: no cover
            raise ValueError(f"Attempting to spend a non-CRCAT coin: {coin_record.coin.name().hex()}")
        if coin_record.metadata is None:  # pragma: no cover
            raise ValueError(f"Attempting to spend a CRCAT coin without metadata: {coin_record.coin.name().hex()}")
        try:
            metadata: CRCATMetadata = CRCATWallet.get_metadata_from_record(coin_record)
            crcat: CRCAT = CRCAT(
                coin_record.coin,
                self.info.limitations_program_hash,
                metadata.lineage_proof,
                self.info.authorized_providers,
                self.info.proofs_checker.as_program(),
                (
                    construct_pending_approval_state(
                        metadata.inner_puzzle_hash, uint64(coin_record.coin.amount)
                    ).get_tree_hash()
                    if coin_record.coin_type == CoinType.CRCAT_PENDING
                    else metadata.inner_puzzle_hash
                ),
            )
            return crcat
        except Exception as e:  # pragma: no cover
            raise ValueError(f"Error parsing CRCAT metadata: {e}")

    async def get_lineage_proof_for_coin(self, coin: Coin) -> Optional[LineageProof]:  # pragma: no cover
        raise RuntimeError("get_lineage_proof_for_coin is a legacy method and is not available on CR-CAT wallets")

    async def _generate_unsigned_spendbundle(
        self,
        payments: List[Payment],
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        cat_discrepancy: Optional[Tuple[int, Program, Program]] = None,  # (extra_delta, tail_reveal, tail_solution)
        coins: Optional[Set[Coin]] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
        add_authorizations_to_cr_cats: bool = True,
    ) -> WalletSpendBundle:
        if cat_discrepancy is not None:
            extra_delta, tail_reveal, tail_solution = cat_discrepancy
        else:
            extra_delta, tail_reveal, tail_solution = 0, Program.to([]), Program.to([])
        payment_amount: int = sum(p.amount for p in payments)
        starting_amount: int = payment_amount - extra_delta
        if coins is None:
            cat_coins = list(
                await self.select_coins(
                    uint64(starting_amount),
                    action_scope,
                )
            )
        else:
            cat_coins = list(coins)

        cat_coins = sorted(cat_coins, key=Coin.name)  # need determinism because we need definitive origin coin

        selected_cat_amount = sum(c.amount for c in cat_coins)
        assert selected_cat_amount >= starting_amount

        # Figure out if we need to absorb/melt some XCH as part of this
        regular_chia_to_claim: int = 0
        if payment_amount > starting_amount:
            # TODO: The no coverage comment is because minting is broken for both this and the standard CAT wallet
            fee = uint64(fee + payment_amount - starting_amount)  # pragma: no cover
        elif payment_amount < starting_amount:
            regular_chia_to_claim = payment_amount

        need_chia_transaction = (fee > 0 or regular_chia_to_claim > 0) and (fee - regular_chia_to_claim != 0)

        # Calculate standard puzzle solutions
        change = selected_cat_amount - starting_amount
        primaries: List[Payment] = []
        for payment in payments:
            primaries.append(payment)

        if change > 0:
            origin_crcat_record = await self.wallet_state_manager.coin_store.get_coin_record(list(cat_coins)[0].name())
            if origin_crcat_record is None:
                raise RuntimeError("A CR-CAT coin was selected that we don't have a record for")  # pragma: no cover
            origin_crcat = self.coin_record_to_crcat(origin_crcat_record)
            if action_scope.config.tx_config.override(
                reuse_puzhash=(
                    True if not add_authorizations_to_cr_cats else action_scope.config.tx_config.reuse_puzhash
                )
            ).reuse_puzhash:
                change_puzhash = origin_crcat.inner_puzzle_hash
                for payment in payments:
                    if change_puzhash == payment.puzzle_hash and change == payment.amount:
                        # We cannot create two coins has same id, create a new puzhash for the change
                        change_puzhash = await self.get_new_inner_hash()
                        break
            else:
                change_puzhash = await self.get_new_inner_hash()
            primaries.append(Payment(change_puzhash, uint64(change), [change_puzhash]))

        # Find the VC Wallet
        vc_wallet: VCWallet
        for wallet in self.wallet_state_manager.wallets.values():
            if WalletType(wallet.type()) == WalletType.VC:
                assert isinstance(wallet, VCWallet)
                vc_wallet = wallet
                break
        else:
            raise RuntimeError("CR-CATs cannot be spent without an appropriate VC")  # pragma: no cover

        # Loop through the coins we've selected and gather the information we need to spend them
        vc: Optional[VerifiedCredential] = None
        vc_announcements_to_make: List[bytes] = []
        inner_spends: List[Tuple[CRCAT, int, Program, Program]] = []
        first = True
        announcement: CreateCoinAnnouncement
        coin_ids: List[bytes32] = [coin.name() for coin in cat_coins]
        coin_records: List[WalletCoinRecord] = (
            await self.wallet_state_manager.coin_store.get_coin_records(coin_id_filter=HashFilter.include(coin_ids))
        ).records
        assert len(coin_records) == len(cat_coins)
        # sort the coin records to ensure they are in the same order as the CAT coins
        coin_records = [rec for rec in sorted(coin_records, key=lambda rec: coin_ids.index(rec.coin.name()))]
        for coin in coin_records:
            if vc is None:
                vc = await vc_wallet.get_vc_with_provider_in_and_proofs(
                    self.info.authorized_providers, self.info.proofs_checker.flags
                )

            if cat_discrepancy is not None:
                cat_condition = UnknownCondition(
                    opcode=Program.to(51),
                    args=[
                        Program.to(None),
                        Program.to(-113),
                        tail_reveal,
                        tail_solution,
                    ],
                )
                if first:
                    extra_conditions = (*extra_conditions, cat_condition)

            crcat: CRCAT = self.coin_record_to_crcat(coin)
            vc_announcements_to_make.append(crcat.expected_announcement())
            if first:
                announcement = CreateCoinAnnouncement(std_hash(b"".join([c.name() for c in cat_coins])), coin.name())
                if need_chia_transaction:
                    if fee > regular_chia_to_claim:
                        await self.create_tandem_xch_tx(
                            fee,
                            uint64(regular_chia_to_claim),
                            action_scope,
                            extra_conditions=(announcement.corresponding_assertion(),),
                        )
                        innersol = self.standard_wallet.make_solution(
                            primaries=primaries,
                            conditions=(*extra_conditions, announcement),
                        )
                    elif regular_chia_to_claim > fee:
                        xch_announcement = await self.create_tandem_xch_tx(
                            fee,
                            uint64(regular_chia_to_claim),
                            action_scope,
                        )
                        assert xch_announcement is not None
                        innersol = self.standard_wallet.make_solution(
                            primaries=primaries,
                            conditions=(*extra_conditions, xch_announcement, announcement),
                        )
                    else:
                        # TODO: what about when they are equal?
                        raise Exception("Equality not handled")
                else:
                    innersol = self.standard_wallet.make_solution(
                        primaries=primaries,
                        conditions=(*extra_conditions, announcement),
                    )
            else:
                innersol = self.standard_wallet.make_solution(
                    primaries=[],
                    conditions=(announcement.corresponding_assertion(),),
                )
            inner_derivation_record = (
                await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
                    crcat.inner_puzzle_hash
                )
            )
            if inner_derivation_record is None:
                raise RuntimeError(  # pragma: no cover
                    f"CR-CAT {crcat} has an inner puzzle hash {crcat.inner_puzzle_hash} that we don't have the keys for"
                )
            inner_puzzle: Program = self.standard_wallet.puzzle_for_pk(inner_derivation_record.pubkey)
            inner_spends.append(
                (
                    crcat,
                    extra_delta if first else 0,
                    inner_puzzle,
                    innersol,
                )
            )
            first = False

        if vc is None:  # pragma: no cover
            raise RuntimeError("Spending no cat coins is not an appropriate use of _generate_unsigned_spendbundle")
        if vc.proof_hash is None:
            raise RuntimeError("CR-CATs found an appropriate VC but that VC contains no proofs")  # pragma: no cover

        proof_of_inclusions: Program = await vc_wallet.proof_of_inclusions_for_root_and_keys(
            vc.proof_hash, self.info.proofs_checker.flags
        )

        expected_announcements, coin_spends, _ = CRCAT.spend_many(
            inner_spends,
            proof_of_inclusions,
            Program.to(None),  # TODO: With more proofs checkers, this may need to be flexible. For now, it's hardcoded.
            vc.proof_provider,
            vc.launcher_id,
            vc.wrap_inner_with_backdoor().get_tree_hash() if add_authorizations_to_cr_cats else None,
        )
        if add_authorizations_to_cr_cats:
            await vc_wallet.generate_signed_transaction(
                vc.launcher_id,
                action_scope,
                extra_conditions=(
                    *expected_announcements,
                    announcement,
                    *(CreatePuzzleAnnouncement(ann) for ann in vc_announcements_to_make),
                ),
            )

        return WalletSpendBundle(coin_spends, G2Element())

    async def generate_signed_transaction(
        self,
        amounts: List[uint64],
        puzzle_hashes: List[bytes32],
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        memos: Optional[List[List[bytes]]] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> None:
        # (extra_delta, tail_reveal, tail_solution)
        cat_discrepancy: Optional[Tuple[int, Program, Program]] = kwargs.get("cat_discrepancy", None)
        add_authorizations_to_cr_cats: bool = kwargs.get("add_authorizations_to_cr_cats", True)
        if memos is None:
            memos = [[] for _ in range(len(puzzle_hashes))]

        if not (len(memos) == len(puzzle_hashes) == len(amounts)):
            raise ValueError("Memos, puzzle_hashes, and amounts must have the same length")  # pragma: no cover

        payments = []
        for amount, puzhash, memo_list in zip(amounts, puzzle_hashes, memos):
            memos_with_hint: List[bytes] = [puzhash]
            memos_with_hint.extend(memo_list)
            # Force wrap the outgoing coins in the pending state if not going to us
            payments.append(
                Payment(
                    (
                        construct_pending_approval_state(puzhash, amount).get_tree_hash()
                        if puzhash != Offer.ph()
                        and not await self.wallet_state_manager.puzzle_store.puzzle_hash_exists(puzhash)
                        else puzhash
                    ),
                    amount,
                    memos_with_hint,
                )
            )

        spend_bundle = await self._generate_unsigned_spendbundle(
            payments,
            action_scope,
            fee,
            cat_discrepancy=cat_discrepancy,  # (extra_delta, tail_reveal, tail_solution)
            coins=coins,
            extra_conditions=extra_conditions,
            add_authorizations_to_cr_cats=add_authorizations_to_cr_cats,
        )

        async with action_scope.use() as interface:
            other_tx_removals: Set[Coin] = {
                removal for tx in interface.side_effects.transactions for removal in tx.removals
            }
            other_tx_additions: Set[Coin] = {
                addition for tx in interface.side_effects.transactions for addition in tx.additions
            }
            tx_list = [
                TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=payment.puzzle_hash,
                    amount=payment.amount,
                    fee_amount=fee,
                    confirmed=False,
                    sent=uint32(0),
                    spend_bundle=spend_bundle if i == 0 else None,
                    additions=list(set(spend_bundle.additions()) - other_tx_additions) if i == 0 else [],
                    removals=list(set(spend_bundle.removals()) - other_tx_removals) if i == 0 else [],
                    wallet_id=self.id(),
                    sent_to=[],
                    trade_id=None,
                    type=uint32(TransactionType.OUTGOING_TX.value),
                    name=spend_bundle.name() if i == 0 else payment.as_condition().get_tree_hash(),
                    memos=list(compute_memos(spend_bundle).items()),
                    valid_times=parse_timelock_info(extra_conditions),
                )
                for i, payment in enumerate(payments)
            ]

            interface.side_effects.transactions.extend(tx_list)

    async def claim_pending_approval_balance(
        self,
        min_amount_to_claim: uint64,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
        excluded_coin_amounts: Optional[List[uint64]] = None,
        reuse_puzhash: Optional[bool] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        # Select the relevant CR-CAT coins
        crcat_records: Set[WalletCoinRecord] = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(
            self.id(), CoinType.CRCAT_PENDING
        )
        if coins is None:
            if max_coin_amount is None:
                max_coin_amount = uint64(self.wallet_state_manager.constants.MAX_COIN_AMOUNT)
            coins = await select_coins(
                await self.get_pending_approval_balance(),
                action_scope.config.tx_config.coin_selection_config,
                list(crcat_records),
                {},
                self.log,
                uint128(min_amount_to_claim),
            )

        # Select the relevant XCH coins
        if fee > 0:
            chia_coins = await self.standard_wallet.select_coins(
                fee,
                action_scope,
            )
        else:
            chia_coins = set()

        # Select the relevant VC coin
        vc_wallet: VCWallet = await self.wallet_state_manager.get_or_create_vc_wallet()
        vc: Optional[VerifiedCredential] = await vc_wallet.get_vc_with_provider_in_and_proofs(
            self.info.authorized_providers, self.info.proofs_checker.flags
        )
        if vc is None:  # pragma: no cover
            raise RuntimeError(f"No VC exists that can approve spends for CR-CAT wallet {self.id()}")
        if vc.proof_hash is None:
            raise RuntimeError(f"VC {vc.launcher_id} has no proofs to authorize transaction")  # pragma: no cover
        proof_of_inclusions: Program = await vc_wallet.proof_of_inclusions_for_root_and_keys(
            vc.proof_hash, self.info.proofs_checker.flags
        )

        # Generate the bundle nonce
        nonce: bytes32 = Program.to(
            [coin_as_list(c) for c in sorted(coins.union(chia_coins).union({vc.coin}), key=Coin.name)]
        ).get_tree_hash()

        # Make CR-CAT bundle
        crcats_and_puzhashes: List[Tuple[CRCAT, bytes32]] = [
            (crcat, CRCATWallet.get_metadata_from_record(record).inner_puzzle_hash)
            for record in [r for r in crcat_records if r.coin in coins]
            for crcat in [self.coin_record_to_crcat(record)]
        ]
        expected_announcements, coin_spends, _ = CRCAT.spend_many(
            [
                (
                    crcat,
                    0,
                    construct_pending_approval_state(inner_puzhash, uint64(crcat.coin.amount)),
                    Program.to([nonce]),
                )
                for crcat, inner_puzhash in crcats_and_puzhashes
            ],
            proof_of_inclusions,
            Program.to(None),  # TODO: With more proofs checkers, this may need to be flexible. For now, it's hardcoded.
            vc.proof_provider,
            vc.launcher_id,
            vc.wrap_inner_with_backdoor().get_tree_hash(),
        )
        claim_bundle = WalletSpendBundle(coin_spends, G2Element())

        # Make the Fee TX
        if fee > 0:
            await self.create_tandem_xch_tx(
                fee,
                uint64(0),
                action_scope,
                extra_conditions=tuple(expected_announcements),
            )

        # Make the VC TX
        await vc_wallet.generate_signed_transaction(
            vc.launcher_id,
            action_scope,
            extra_conditions=(
                *extra_conditions,
                *expected_announcements,
                CreateCoinAnnouncement(nonce),
                *(CreatePuzzleAnnouncement(crcat.expected_announcement()) for crcat, _ in crcats_and_puzhashes),
            ),
        )

        async with action_scope.use() as interface:
            other_additions: Set[Coin] = {rem for tx in interface.side_effects.transactions for rem in tx.additions}
            other_removals: Set[Coin] = {rem for tx in interface.side_effects.transactions for rem in tx.removals}
            interface.side_effects.transactions.append(
                TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=await self.wallet_state_manager.main_wallet.get_puzzle_hash(False),
                    amount=uint64(sum(c.amount for c in coins)),
                    fee_amount=fee,
                    confirmed=False,
                    sent=uint32(0),
                    spend_bundle=claim_bundle,
                    additions=list(set(claim_bundle.additions()) - other_additions),
                    removals=list(set(claim_bundle.removals()) - other_removals),
                    wallet_id=self.id(),
                    sent_to=[],
                    trade_id=None,
                    type=uint32(TransactionType.INCOMING_TX.value),
                    name=claim_bundle.name(),
                    memos=list(compute_memos(claim_bundle).items()),
                    valid_times=parse_timelock_info(extra_conditions),
                )
            )

    async def match_puzzle_info(self, puzzle_driver: PuzzleInfo) -> bool:
        if (
            AssetType(puzzle_driver.type()) == AssetType.CAT
            and puzzle_driver["tail"] == self.info.limitations_program_hash
        ):
            inner_puzzle_driver: Optional[PuzzleInfo] = puzzle_driver.also()
            if inner_puzzle_driver is None:
                raise ValueError("Malformed puzzle driver passed to CRCATWallet.match_puzzle_info")  # pragma: no cover
            return (
                AssetType(inner_puzzle_driver.type()) == AssetType.CR
                and [bytes32(provider) for provider in inner_puzzle_driver["authorized_providers"]]
                == self.info.authorized_providers
                and ProofsChecker.from_program(uncurry_puzzle(inner_puzzle_driver["proofs_checker"]))
                == self.info.proofs_checker
            )
        return False

    async def get_puzzle_info(self, asset_id: bytes32) -> PuzzleInfo:
        return PuzzleInfo(
            {
                "type": AssetType.CAT.value,
                "tail": "0x" + self.info.limitations_program_hash.hex(),
                "also": {
                    "type": AssetType.CR.value,
                    "authorized_providers": ["0x" + provider.hex() for provider in self.info.authorized_providers],
                    "proofs_checker": self.info.proofs_checker.as_program(),
                },
            }
        )

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        """
        This matches coins that are either CRCATs with the hint as the inner puzzle, or CRCATs in the pending approval
        state that will come to us once claimed.
        """
        authorized_providers_hash: bytes32 = Program.to(self.info.authorized_providers).get_tree_hash()
        proofs_checker_hash: bytes32 = self.info.proofs_checker.as_program().get_tree_hash()
        hint_inner_hash: bytes32 = construct_cr_layer_hash(
            authorized_providers_hash,
            proofs_checker_hash,
            hint,
        )
        if (
            construct_cat_puzzle(
                Program.to(CAT_MOD_HASH),
                self.info.limitations_program_hash,
                hint_inner_hash,
                mod_code_hash=CAT_MOD_HASH_HASH,
            ).get_tree_hash_precalc(hint, CAT_MOD_HASH, CAT_MOD_HASH_HASH, hint_inner_hash)
            == coin.puzzle_hash
        ):
            return True

        pending_approval_inner_hash: bytes32 = construct_cr_layer_hash(
            authorized_providers_hash,
            proofs_checker_hash,
            construct_pending_approval_state(hint, uint64(coin.amount)).get_tree_hash(),
        )
        if (
            construct_cat_puzzle(
                Program.to(CAT_MOD_HASH),
                self.info.limitations_program_hash,
                pending_approval_inner_hash,
                mod_code_hash=CAT_MOD_HASH_HASH,
            ).get_tree_hash_precalc(CAT_MOD_HASH, CAT_MOD_HASH_HASH, pending_approval_inner_hash)
            == coin.puzzle_hash
        ):
            return True
        else:
            return False


if TYPE_CHECKING:
    _dummy: WalletProtocol[CATCoinData] = CRCATWallet()
