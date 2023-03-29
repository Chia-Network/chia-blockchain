from __future__ import annotations

import dataclasses
import logging
import time
import traceback
from secrets import token_bytes
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from blspy import AugSchemeMPL, G1Element, G2Element

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_info import CATInfo, LegacyCATInfo
from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    match_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.cat_wallet.lineage_store import CATLineageStore
from chia.wallet.coin_selection import select_coins
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
)
from chia.wallet.puzzles.tails import ALL_LIMITATIONS_PROGRAMS
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.curry_and_treehash import calculate_hash_of_quoted_mod_hash, curry_and_treehash
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import AmountWithPuzzlehash, WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager


class CRCATWallet(CATWallet):
    wallet_state_manager: WalletStateManager
    log: logging.Logger
    wallet_info: WalletInfo
    tail_hash: bytes32
    standard_wallet: Wallet
    cost_of_single_tx: int
    cr_cat_store: CRCATStore

    @staticmethod
    def default_wallet_name_for_unknown_cat(limitations_program_hash_hex: str) -> str:
        return f"CAT {limitations_program_hash_hex[:16]}..."

    @staticmethod
    async def create_new_cat_wallet(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        cat_tail_info: Dict[str, Any],
        amount: uint64,
        name: Optional[str] = None,
    ) -> "CATWallet":
        raise NotImplementedError("create_new_cat_wallet is a legacy method and is not available on CR-CAT wallets")

    @staticmethod
    async def get_or_create_wallet_for_cat(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        limitations_program_hash_hex: str,
        authorized_providers: List[bytes32],
        proofs_checker: ProofsChecker,
        name: Optional[str] = None,
    ) -> CRCATWallet:
        self = CRCATWallet()
        self.cost_of_single_tx = 78000000  # Measured in testing
        self.standard_wallet = wallet
        self.log = logging.getLogger(__name__)
        self.authorized_providers = authorized_providers
        self.proofs_checker = proofs_checker

        self.tail_hash = bytes32.from_hexstr(limitations_program_hash_hex)
        limitations_program_hash_hex = self.tail_hash.hex()

        for id, w in wallet_state_manager.wallets.items():
            if w.type() == CRCATWallet.type():
                assert isinstance(w, CRCATWallet)
                if w.get_asset_id() == limitations_program_hash_hex:
                    self.log.warning("Not creating wallet for already existing CR-CAT wallet")
                    return w

        self.wallet_state_manager = wallet_state_manager
        if limitations_program_hash_hex in wallet_state_manager.default_cats:
            cat_info = wallet_state_manager.default_cats[limitations_program_hash_hex]
            name = cat_info["name"]
        elif name is None:
            name = self.default_wallet_name_for_unknown_cat(limitations_program_hash_hex)

        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name,
            WalletType.CRCAT,
            limitations_program_hash_hex,
        )

        self.cr_cat_store = wallet_state_manager.cr_cat_store

        await self.wallet_state_manager.add_new_wallet(self)
        return self

    @classmethod
    async def create_from_puzzle_info(
        cls,
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        puzzle_driver: PuzzleInfo,
        name: Optional[str] = None,
    ) -> CRCATWallet:
        cr_layer: PuzzleInfo = puzzle_driver.also()
        return await cls.get_or_create_wallet_for_cat(
            wallet_state_manager,
            wallet,
            puzzle_driver["tail"].hex(),
            [bytes32(provider) for provider in cr_layer["authorized_providers"]],
            ProofsChecker.from_program(cr_layer["proofs_checker"]),
            name,
        )

    @staticmethod
    async def create(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        wallet_info: WalletInfo,
    ) -> CRCATWallet:
        self = CRCATWallet()

        self.log = logging.getLogger(__name__)
        self.cost_of_single_tx = 78000000
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.tail_hash = bytes32.from_hexstr(wallet_info.data)
        self.standard_wallet = wallet
        self.cr_cat_store = wallet_state_manager.cr_cat_store
        self.authorized_providers = self.cr_cat_store.get_authorized_providers_for_tail(self.tail_hash)
        self.proofs_checker = self.cr_cat_store.get_proofs_checker_for_tail(self.tail_hash)

        return self

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.CRCAT

    def get_asset_id(self) -> str:
        return self.tail_hash.hex()

    async def set_tail_program(self, tail_program: str) -> None:
        raise NotImplementedError("set_tail_program is a legacy method and is not available on CR-CAT wallets")

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection) -> None:
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"CR-CAT wallet has been notified that {coin.name().hex()} was added")

        lineage = await self.get_lineage_proof_for_coin(coin)
        if lineage is None:
            try:
                coin_state = await self.wallet_state_manager.wallet_node.get_coin_state(
                    [coin.parent_coin_info], peer=peer
                )
                coin_spend = await self.wallet_state_manager.wallet_node.fetch_puzzle_solution(
                    coin_state[0].spent_height, coin_state[0].coin, peer
                )
                await self.puzzle_solution_received(coin_spend, parent_coin=coin_state[0].coin)
            except Exception as e:
                self.log.debug(f"Exception: {e}, traceback: {traceback.format_exc()}")

    async def puzzle_solution_received(self, coin_spend: CoinSpend, parent_coin: Coin) -> None:
        try:
            new_cr_cats: List[CRCAT] = CRCAT.get_next_from_coin_spend(coin_spend)
        except Exception:
            # The parent is not a CAT which means we need to scrub all of its children from our DB
            child_coin_records = await self.wallet_state_manager.coin_store.get_coin_records_by_parent_id(coin_spend.coin.name())
            if len(child_coin_records) > 0:
                for record in child_coin_records:
                    if record.wallet_id == self.id():
                        await self.wallet_state_manager.coin_store.delete_coin_record(record.coin.name())
                        # We also need to make sure there's no record of the transaction
                        await self.wallet_state_manager.tx_store.delete_transaction_record(record.coin.name())

        for cr_cat in new_crcats:
            if self.wallet_state_manager.puzzle_store.puzzle_hash_exists(cr_cat.inner_puzzle_hash):
                await self.cr_cat_store.add_cr_cat(cr_cat)

    def require_derivation_paths(self) -> bool:
        return False

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        raise NotImplementedError("puzzle_for_pk is a legacy method and is not available on CR-CAT wallets")

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise NotImplementedError("puzzle_hash_for_pk is a legacy method and is not available on CR-CAT wallets")

    async def get_new_cat_puzzle_hash(self) -> bytes32:
        raise NotImplementedError("get_new_cat_puzzle_hash is a legacy method and is not available on CR-CAT wallets")

    async def sign(self, spend_bundle: SpendBundle) -> SpendBundle:
        raise NotImplementedError("get_new_cat_puzzle_hash is a legacy method and is not available on CR-CAT wallets")

    async def inner_puzzle_for_cat_puzhash(self, cat_hash: bytes32) -> Program:
        raise NotImplementedError(
            "inner_puzzle_for_cat_puzhash is a legacy method and is not available on CR-CAT wallets"
        )

    async def convert_puzzle_hash(self, puzzle_hash: bytes32) -> bytes32:
        return puzzle_hash

    async def get_lineage_proof_for_coin(self, coin: Coin) -> Optional[LineageProof]:
        return await self.cr_cat_store.get_lineage_proof(coin.parent_coin_info)

    async def generate_unsigned_spendbundle(
        self,
        payments: List[Payment],
        fee: uint64 = uint64(0),
        cat_discrepancy: Optional[Tuple[int, Program, Program]] = None,  # (extra_delta, tail_reveal, tail_solution)
        coins: Optional[Set[Coin]] = None,
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
        exclude_coin_amounts: Optional[List[uint64]] = None,
        exclude_coins: Optional[Set[Coin]] = None,
        reuse_puzhash: Optional[bool] = None,
        verified_credential: Optional[VerifiedCredential] = None,
        proof_file: Optional[Any] = None,  # type to be determined
    ) -> Tuple[SpendBundle, Optional[TransactionRecord]]:
        if coin_announcements_to_consume is not None:
            coin_announcements_bytes: Optional[Set[bytes32]] = {a.name() for a in coin_announcements_to_consume}
        else:
            coin_announcements_bytes = None

        if puzzle_announcements_to_consume is not None:
            puzzle_announcements_bytes: Optional[Set[bytes32]] = {a.name() for a in puzzle_announcements_to_consume}
        else:
            puzzle_announcements_bytes = None

        if cat_discrepancy is not None:
            extra_delta, tail_reveal, tail_solution = cat_discrepancy
        else:
            extra_delta, tail_reveal, tail_solution = 0, Program.to([]), Program.to([])
        payment_amount: int = sum([p.amount for p in payments])
        starting_amount: int = payment_amount - extra_delta
        if reuse_puzhash is None:
            reuse_puzhash_config = self.wallet_state_manager.config.get("reuse_public_key_for_change", None)
            if reuse_puzhash_config is None:
                reuse_puzhash = False
            else:
                reuse_puzhash = reuse_puzhash_config.get(
                    str(self.wallet_state_manager.wallet_node.logged_in_fingerprint), False
                )
        if coins is None:
            if exclude_coins is None:
                exclude_coins = set()
            cat_coins = await self.select_coins(
                uint64(starting_amount),
                exclude=list(exclude_coins),
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_amounts=exclude_coin_amounts,
            )
        elif exclude_coins is not None:
            raise ValueError("Can't exclude coins when also specifically including coins")
        else:
            cat_coins = coins

        selected_cat_amount = sum([c.amount for c in cat_coins])
        assert selected_cat_amount >= starting_amount

        # Figure out if we need to absorb/melt some XCH as part of this
        regular_chia_to_claim: int = 0
        if payment_amount > starting_amount:
            fee = uint64(fee + payment_amount - starting_amount)
        elif payment_amount < starting_amount:
            regular_chia_to_claim = payment_amount

        need_chia_transaction = (fee > 0 or regular_chia_to_claim > 0) and (fee - regular_chia_to_claim != 0)

        # Calculate standard puzzle solutions
        change = selected_cat_amount - starting_amount
        primaries: List[AmountWithPuzzlehash] = []
        for payment in payments:
            primaries.append({"puzzlehash": payment.puzzle_hash, "amount": payment.amount, "memos": payment.memos})

        if change > 0:
            derivation_record = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
                list(cat_coins)[0].puzzle_hash
            )
            if derivation_record is not None and reuse_puzhash:
                change_puzhash = self.standard_wallet.puzzle_hash_for_pk(derivation_record.pubkey)
                for payment in payments:
                    if change_puzhash == payment.puzzle_hash and change == payment.amount:
                        # We cannot create two coins has same id, create a new puzhash for the change
                        change_puzhash = await self.get_new_inner_hash()
                        break
            else:
                change_puzhash = await self.get_new_inner_hash()
            primaries.append({"puzzlehash": change_puzhash, "amount": uint64(change), "memos": []})

        # Loop through the coins we've selected and gather the information we need to spend them
        spendable_cat_list = []
        chia_tx = None
        first = True
        announcement: Announcement
        for coin in cat_coins:
            if first:
                first = False
                announcement = Announcement(coin.name(), std_hash(b"".join([c.name() for c in cat_coins])))
                if need_chia_transaction:
                    if fee > regular_chia_to_claim:
                        chia_tx, _ = await self.create_tandem_xch_tx(
                            fee,
                            uint64(regular_chia_to_claim),
                            announcement_to_assert=announcement,
                            min_coin_amount=min_coin_amount,
                            max_coin_amount=max_coin_amount,
                            exclude_coin_amounts=exclude_coin_amounts,
                            reuse_puzhash=reuse_puzhash,
                        )
                        innersol = self.standard_wallet.make_solution(
                            primaries=primaries,
                            coin_announcements={announcement.message},
                            coin_announcements_to_assert=coin_announcements_bytes,
                            puzzle_announcements_to_assert=puzzle_announcements_bytes,
                        )
                    elif regular_chia_to_claim > fee:
                        chia_tx, _ = await self.create_tandem_xch_tx(
                            fee,
                            uint64(regular_chia_to_claim),
                            min_coin_amount=min_coin_amount,
                            max_coin_amount=max_coin_amount,
                            exclude_coin_amounts=exclude_coin_amounts,
                            reuse_puzhash=reuse_puzhash,
                        )
                        innersol = self.standard_wallet.make_solution(
                            primaries=primaries,
                            coin_announcements={announcement.message},
                            coin_announcements_to_assert={announcement.name()},
                        )
                else:
                    innersol = self.standard_wallet.make_solution(
                        primaries=primaries,
                        coin_announcements={announcement.message},
                        coin_announcements_to_assert=coin_announcements_bytes,
                        puzzle_announcements_to_assert=puzzle_announcements_bytes,
                    )
            else:
                innersol = self.standard_wallet.make_solution(
                    primaries=[],
                    coin_announcements_to_assert={announcement.name()},
                )
            if cat_discrepancy is not None:
                # TODO: This line is a hack, make_solution should allow us to pass extra conditions to it
                innersol = Program.to(
                    [[], (1, Program.to([51, None, -113, tail_reveal, tail_solution]).cons(innersol.at("rfr"))), []]
                )
            inner_puzzle = await self.inner_puzzle_for_cat_puzhash(coin.puzzle_hash)
            lineage_proof = await self.get_lineage_proof_for_coin(coin)
            assert lineage_proof is not None
            new_spendable_cat = SpendableCAT(
                coin,
                self.cat_info.limitations_program_hash,
                inner_puzzle,
                innersol,
                limitations_solution=tail_solution,
                extra_delta=extra_delta,
                lineage_proof=lineage_proof,
                limitations_program_reveal=tail_reveal,
            )
            spendable_cat_list.append(new_spendable_cat)

        cat_spend_bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, spendable_cat_list)
        chia_spend_bundle = SpendBundle([], G2Element())
        if chia_tx is not None and chia_tx.spend_bundle is not None:
            chia_spend_bundle = chia_tx.spend_bundle

        return (
            SpendBundle.aggregate(
                [
                    cat_spend_bundle,
                    chia_spend_bundle,
                ]
            ),
            chia_tx,
        )

    async def generate_signed_transaction(
        self,
        amounts: List[uint64],
        puzzle_hashes: List[bytes32],
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        ignore_max_send_amount: bool = False,
        memos: Optional[List[List[bytes]]] = None,
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
        exclude_coin_amounts: Optional[List[uint64]] = None,
        exclude_cat_coins: Optional[Set[Coin]] = None,
        cat_discrepancy: Optional[Tuple[int, Program, Program]] = None,  # (extra_delta, tail_reveal, tail_solution)
        reuse_puzhash: Optional[bool] = None,
        verified_credential: Optional[VerifiedCredential] = None,
        proof_file: Optional[Any] = None,  # type to be determined
    ) -> List[TransactionRecord]:
        if memos is None:
            memos = [[] for _ in range(len(puzzle_hashes))]

        if not (len(memos) == len(puzzle_hashes) == len(amounts)):
            raise ValueError("Memos, puzzle_hashes, and amounts must have the same length")

        payments = []
        for amount, puzhash, memo_list in zip(amounts, puzzle_hashes, memos):
            memos_with_hint: List[bytes] = [puzhash]
            memos_with_hint.extend(memo_list)
            payments.append(Payment(puzhash, amount, memos_with_hint))

        payment_sum = sum([p.amount for p in payments])
        if not ignore_max_send_amount:
            max_send = await self.get_max_send_amount()
            if payment_sum > max_send:
                raise ValueError(f"Can't send more than {max_send} mojos in a single transaction")
        signing_hints, unsigned_spend_bundle, chia_tx = await self.generate_unsigned_spendbundle(
            payments,
            fee,
            cat_discrepancy=cat_discrepancy,  # (extra_delta, tail_reveal, tail_solution)
            coins=coins,
            coin_announcements_to_consume=coin_announcements_to_consume,
            puzzle_announcements_to_consume=puzzle_announcements_to_consume,
            min_coin_amount=min_coin_amount,
            max_coin_amount=max_coin_amount,
            exclude_coin_amounts=exclude_coin_amounts,
            exclude_coins=exclude_cat_coins,
            reuse_puzhash=reuse_puzhash,
            verified_credential=verified_credential,
            proof_file=proof_file,
        )

        # TODO: sign the thing

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
                additions=spend_bundle.additions() if i == 0 else None,
                removals=spend_bundle.removals() if i == 0 else None,
                wallet_id=self.id(),
                sent_to=[],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=spend_bundle.name(),
                memos=payment.memos,
            )
            for i, payment in enumerate(payments)
        ]

        if chia_tx is not None:
            tx_list.append(dataclasses.replace(chia_tx, spend_bundle=None))

        return tx_list

    async def match_puzzle_info(self, puzzle_driver: PuzzleInfo) -> bool:
        if AssetType(puzzle_driver.type()) == AssetType.CAT and puzzle_driver["tail"] == self.tail_hash:
            inner_puzzle_driver: PuzzleInfo = puzzle_driver.also()
            return (
                AssetType(inner_puzzle_driver.type()) == AssetType.CR
                and [bytes32(provider) for provider in cr_layer["authorized_providers"]]
                and ProofsChecker.from_program(cr_layer["proofs_checker"]) == self.proofs_checker
            )

    async def get_puzzle_info(self, asset_id: bytes32) -> PuzzleInfo:
        return PuzzleInfo(
            {
                "type": AssetType.CAT.value,
                "tail": "0x" + self.tail_hash,
                "also": {
                    "type": AssetType.CR.value,
                    "authorized_providers": ["0x" + provider.hex() for provider in self.authorized_providers],
                    "proofs_checker": self.proofs_checker.as_program(),
                }
            }
        )


if TYPE_CHECKING:
    from chia.wallet.wallet_protocol import WalletProtocol

    _dummy: WalletProtocol = CATWallet()
