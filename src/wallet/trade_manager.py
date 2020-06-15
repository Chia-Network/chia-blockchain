import time
from pathlib import Path
from secrets import token_bytes
from typing import Dict, Optional, Tuple, List, Any
import logging

import clvm

from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.program import Program
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.util.byte_types import hexstr_to_bytes
from src.util.ints import uint32, uint64
from src.wallet.cc_wallet import cc_wallet_puzzles
from src.wallet.cc_wallet.cc_wallet import CCWallet
from src.wallet.cc_wallet.cc_wallet_puzzles import (
    create_spend_for_auditor,
    create_spend_for_ephemeral,
)
from src.wallet.trade_record import TradeRecord, TradeOffer
from src.wallet.transaction_record import TransactionRecord
from src.wallet.types.key_val_types import PendingOffers, AcceptedOffers
from src.wallet.wallet import Wallet
from clvm_tools import binutils

from src.wallet.wallet_coin_record import WalletCoinRecord

PENDING_OFFERS = "pending_offers"
ACCEPTED_OFFERS = "accepted_offers"


class TradeManager:
    wallet_state_manager: Any
    log: logging.Logger
    locked_coin: Optional[Dict[bytes32, Coin]]
    pending_offer_cache: Optional[List[TradeOffer]]
    accepted_offer_cache: Optional[List[TradeRecord]]

    @staticmethod
    async def create(
        wallet_state_manager: Any, name: str = None,
    ):
        self = TradeManager()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.pending_offer_cache = None
        self.accepted_offer_cache = None
        return self

    async def get_pending_offers(self) -> List[TradeOffer]:
        if self.pending_offer_cache is not None:
            return self.pending_offer_cache.copy()
        current_trades_hex = await self.wallet_state_manager.basic_store.get(
            PENDING_OFFERS
        )
        if current_trades_hex is None:
            return []
        pending = PendingOffers.from_bytes(hexstr_to_bytes(current_trades_hex))
        return pending.trades

    async def get_accepted_offers(self) -> List[TradeRecord]:
        if self.accepted_offer_cache is not None:
            return self.accepted_offer_cache.copy()
        accepted_offers_hex = await self.wallet_state_manager.basic_store.get(
            ACCEPTED_OFFERS
        )
        if accepted_offers_hex is None:
            return []
        accepted = AcceptedOffers.from_bytes((hexstr_to_bytes(accepted_offers_hex)))
        return accepted.trades

    async def get_locked_coins(self, wallet_id: int = None) -> Dict[bytes32, Coin]:
        """ Returns a dictionary of confirmed coins that are locked by a trade. """
        current_trades = await self.get_pending_offers()
        if current_trades is None:
            return {}

        result = {}
        for trade_offer in current_trades:
            spend_bundle = trade_offer.spend_bundle
            removals = spend_bundle.removals()

            for coin in removals:
                record: Optional[
                    WalletCoinRecord
                ] = await self.wallet_state_manager.wallet_store.get_coin_record_by_coin_id(
                    coin.name()
                )
                if record is None:
                    continue
                if wallet_id is None or wallet_id == record.wallet_id:
                    result[coin.name()] = coin

        return result

    async def cancel_pending_offer(self, trade_id: bytes32):
        self.log.info(f"Cancel pending offer with id trade_id {trade_id.hex()}")
        offers: List[TradeOffer] = await self.get_pending_offers()
        filtered_offers: List[TradeOffer] = []
        for offer in offers:
            if offer.trade_id != trade_id:
                filtered_offers.append(offer)

        to_store = PendingOffers(filtered_offers)
        await self.wallet_state_manager.basic_store.set(PENDING_OFFERS, to_store)

    async def cancel_pending_offer_safely(self, trade_id: bytes32):
        """ This will create a transaction that includes coins that were offered"""
        self.log.info(f"Secure-Cancel pending offer with id trade_id {trade_id.hex()}")
        offers: List[TradeOffer] = await self.get_pending_offers()
        to_cancel: Optional[TradeOffer] = None
        for offer in offers:
            if offer.trade_id == trade_id:
                to_cancel = offer
                break
        if to_cancel is None:
            return

        all_coins = to_cancel.spend_bundle.additions()
        all_coins.extend(to_cancel.spend_bundle.removals())

        for coin in all_coins:
            wallet = self.wallet_state_manager.get_wallet_for_coin(coin)
            if wallet is None:
                continue
            new_ph = await wallet.get_new_puzzlehash()
            tx = wallet.generate_signed_transaction(
                coin.amount, new_ph, 0, coins={coin}
            )
            await self.wallet_state_manager.add_pending_transaction(tx_record=tx)
        return

    async def add_pending_offer(self, trade_offer: TradeOffer):
        pending_offers: List[TradeOffer] = await self.get_pending_offers()
        pending_offers.append(trade_offer)
        to_store = PendingOffers(pending_offers)
        await self.wallet_state_manager.basic_store.set(PENDING_OFFERS, to_store)
        self.pending_offer_cache = pending_offers

    async def add_accepted_offer(self, accepted: TradeRecord):
        accepted_offers = await self.get_accepted_offers()
        accepted_offers.append(accepted)
        to_store = AcceptedOffers(accepted_offers)
        await self.wallet_state_manager.basic_store.set(ACCEPTED_OFFERS, to_store)
        self.accepted_offer_cache = accepted_offers

    async def create_offer_for_ids(
        self, offer: Dict[int, int], file_name: str
    ) -> Tuple[bool, Optional[TradeOffer], Optional[str]]:
        success, trade_offer, error = await self._create_offer_for_ids(offer)

        if success is True and trade_offer is not None:
            self.write_offer_to_disk(Path(file_name), trade_offer)
            await self.add_pending_offer(trade_offer)

        return success, trade_offer, error

    async def _create_offer_for_ids(
        self, offer: Dict[int, int]
    ) -> Tuple[bool, Optional[TradeOffer], Optional[str]]:
        """
        Offer is dictionary of wallet ids and amount
        """
        spend_bundle = None
        try:
            for id in offer.keys():
                amount = offer[id]
                wallet_id = uint32(int(id))
                wallet = self.wallet_state_manager.wallets[wallet_id]
                if isinstance(wallet, CCWallet):
                    balance = await wallet.get_confirmed_balance()
                    if balance < abs(amount) and amount < 0:
                        raise Exception(f"insufficient funds in wallet {wallet_id}")
                    if balance == 0 and amount > 0:
                        if spend_bundle is None:
                            to_exclude: List[Coin] = []
                        else:
                            to_exclude = spend_bundle.removals()
                        zero_spend_bundle: Optional[
                            SpendBundle
                        ] = await wallet.generate_zero_val_coin(False, to_exclude)

                        if zero_spend_bundle is None:
                            raise Exception(
                                "Failed to generate offer. Zero value coin not created."
                            )
                        if spend_bundle is None:
                            spend_bundle = zero_spend_bundle
                        else:
                            spend_bundle = SpendBundle.aggregate(
                                [spend_bundle, zero_spend_bundle]
                            )

                        additions = zero_spend_bundle.additions()
                        removals = zero_spend_bundle.removals()
                        zero_val_coin: Optional[Coin] = None
                        for add in additions:
                            if add not in removals and add.amount == 0:
                                zero_val_coin = add

                        new_spend_bundle = await wallet.create_spend_bundle_relative_amount(
                            amount, zero_val_coin
                        )
                    else:
                        new_spend_bundle = await wallet.create_spend_bundle_relative_amount(
                            amount
                        )
                elif isinstance(wallet, Wallet):
                    if spend_bundle is None:
                        to_exclude = []
                    else:
                        to_exclude = spend_bundle.removals()
                    new_spend_bundle = await wallet.create_spend_bundle_relative_chia(
                        amount, to_exclude
                    )
                else:
                    return False, None, "unssuported wallet type"
                if new_spend_bundle.removals() == [] or new_spend_bundle is None:
                    raise Exception(f"Wallet {id} was unable to create offer.")
                if spend_bundle is None:
                    spend_bundle = new_spend_bundle
                else:
                    spend_bundle = SpendBundle.aggregate(
                        [spend_bundle, new_spend_bundle]
                    )

            if spend_bundle is None:
                return False, None, None

            trade_offer = TradeOffer(
                created_at_time=uint64(int(time.time())),
                spend_bundle=spend_bundle,
                trade_id=spend_bundle.name(),
            )
            return True, trade_offer, None
        except Exception as e:
            return False, None, str(e)

    def write_offer_to_disk(self, file_path: Path, offer: TradeOffer):
        if offer is not None:
            file_path.write_text(bytes(offer).hex())

    async def get_discrepancies_for_spend_bundle(
        self, trade_offer: SpendBundle
    ) -> Tuple[bool, Optional[Dict], Optional[Exception]]:
        try:
            cc_discrepancies: Dict[bytes32, int] = dict()
            for coinsol in trade_offer.coin_solutions:
                puzzle = coinsol.solution.first()
                solution = coinsol.solution.rest().first()

                # work out the deficits between coin amount and expected output for each
                if cc_wallet_puzzles.check_is_cc_puzzle(puzzle):
                    parent_info = binutils.disassemble(solution.rest().first()).split(
                        " "
                    )
                    if len(parent_info) > 1:
                        colour = cc_wallet_puzzles.get_genesis_from_puzzle(
                            binutils.disassemble(puzzle)
                        )
                        # get puzzle and solution
                        innerpuzzlereveal = solution.rest().rest().rest().first()
                        innersol = solution.rest().rest().rest().rest().first()
                        # Get output amounts by running innerpuzzle and solution
                        out_amount = cc_wallet_puzzles.get_output_amount_for_puzzle_and_solution(
                            innerpuzzlereveal, innersol
                        )
                        # add discrepancy to dict of discrepancies
                        if colour in cc_discrepancies:
                            cc_discrepancies[colour] += coinsol.coin.amount - out_amount
                        else:
                            cc_discrepancies[colour] = coinsol.coin.amount - out_amount
                else:  # standard chia coin
                    coin_amount = coinsol.coin.amount
                    out_amount = cc_wallet_puzzles.get_output_amount_for_puzzle_and_solution(
                        puzzle, solution
                    )
                    diff = coin_amount - out_amount
                    if "chia" in cc_discrepancies:
                        cc_discrepancies["chia"] = cc_discrepancies["chia"] + diff
                    else:
                        cc_discrepancies["chia"] = diff

            return True, cc_discrepancies, None
        except Exception as e:
            return False, None, e

    async def get_discrepancies_for_offer(
        self, file_path: Path
    ) -> Tuple[bool, Optional[Dict], Optional[Exception]]:
        self.log.info(f"trade offer: {file_path}")
        trade_offer_hex = file_path.read_text()
        trade_offer = TradeOffer.from_bytes(bytes.fromhex(trade_offer_hex))
        return await self.get_discrepancies_for_spend_bundle(trade_offer.spend_bundle)

    async def get_inner_puzzle_for_puzzle_hash(self, puzzle_hash) -> Optional[Program]:
        info = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
            puzzle_hash.hex()
        )
        assert info is not None
        puzzle = self.wallet_state_manager.main_wallet.puzzle_for_pk(bytes(info.pubkey))
        return puzzle

    async def maybe_create_wallets_for_offer(self, file_path: Path) -> bool:
        success, result, error = await self.get_discrepancies_for_offer(file_path)
        if not success or result is None:
            return False

        for key, value in result.items():
            wsm = self.wallet_state_manager
            wallet: Wallet = wsm.main_wallet
            if key == "chia":
                continue
            self.log.info(f"value is {key}")
            exists = await wsm.get_wallet_for_colour(key)
            if exists is not None:
                continue

            await CCWallet.create_wallet_for_cc(wsm, wallet, key)

        return True

    async def respond_to_offer(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        has_wallets = await self.maybe_create_wallets_for_offer(file_path)
        if not has_wallets:
            return False, "Unknown Error"
        trade_offer_hex = file_path.read_text()
        trade_offer: TradeOffer = TradeOffer.from_bytes(bytes.fromhex(trade_offer_hex))
        offer_spend_bundle = trade_offer.spend_bundle

        coinsols = []  # [] of CoinSolutions
        cc_coinsol_outamounts: Dict[bytes32, List[Tuple[Any, int]]] = dict()
        # Used for generating auditor solution, key is colour
        auditees: Dict[bytes32, List[Tuple[bytes32, bytes32, Any, int]]] = dict()
        aggsig = offer_spend_bundle.aggregated_signature
        cc_discrepancies: Dict[bytes32, int] = dict()
        chia_discrepancy = None
        wallets: Dict[bytes32, Any] = dict()  # colour to wallet dict

        for coinsol in offer_spend_bundle.coin_solutions:
            puzzle = coinsol.solution.first()
            solution = coinsol.solution.rest().first()

            # work out the deficits between coin amount and expected output for each
            if cc_wallet_puzzles.check_is_cc_puzzle(puzzle):
                parent_info = binutils.disassemble(solution.rest().first()).split(" ")

                if len(parent_info) > 1:
                    # Calculate output amounts
                    colour = cc_wallet_puzzles.get_genesis_from_puzzle(
                        binutils.disassemble(puzzle)
                    )
                    if colour not in wallets:
                        wallets[
                            colour
                        ] = await self.wallet_state_manager.get_wallet_for_colour(
                            colour
                        )
                    unspent = await self.wallet_state_manager.get_spendable_coins_for_wallet(
                        wallets[colour].wallet_info.id
                    )
                    if coinsol.coin in [record.coin for record in unspent]:
                        return False, "can't respond to own offer"
                    innerpuzzlereveal = solution.rest().rest().rest().first()
                    innersol = solution.rest().rest().rest().rest().first()
                    out_amount = cc_wallet_puzzles.get_output_amount_for_puzzle_and_solution(
                        innerpuzzlereveal, innersol
                    )

                    if colour in cc_discrepancies:
                        cc_discrepancies[colour] += coinsol.coin.amount - out_amount
                    else:
                        cc_discrepancies[colour] = coinsol.coin.amount - out_amount
                    # Store coinsol and output amount for later
                    if colour in cc_coinsol_outamounts:
                        cc_coinsol_outamounts[colour].append((coinsol, out_amount))
                    else:
                        cc_coinsol_outamounts[colour] = [(coinsol, out_amount)]

                    # auditees should be (primary_input, innerpuzhash, coin_amount, output_amount)
                    if colour in auditees:
                        auditees[colour].append(
                            (
                                coinsol.coin.parent_coin_info,
                                Program(innerpuzzlereveal).get_tree_hash(),
                                coinsol.coin.amount,
                                out_amount,
                            )
                        )
                    else:
                        auditees[colour] = [
                            (
                                coinsol.coin.parent_coin_info,
                                Program(innerpuzzlereveal).get_tree_hash(),
                                coinsol.coin.amount,
                                out_amount,
                            )
                        ]
                else:
                    coinsols.append(coinsol)
            else:
                # standard chia coin
                unspent = await self.wallet_state_manager.get_spendable_coins_for_wallet(
                    1
                )
                if coinsol.coin in [record.coin for record in unspent]:
                    return False, "can't respond to own offer"
                if chia_discrepancy is None:
                    chia_discrepancy = cc_wallet_puzzles.get_output_discrepancy_for_puzzle_and_solution(
                        coinsol.coin, puzzle, solution
                    )
                else:
                    chia_discrepancy += cc_wallet_puzzles.get_output_discrepancy_for_puzzle_and_solution(
                        coinsol.coin, puzzle, solution
                    )
                coinsols.append(coinsol)

        chia_spend_bundle: Optional[SpendBundle] = None
        if chia_discrepancy is not None:
            chia_spend_bundle = await self.wallet_state_manager.main_wallet.create_spend_bundle_relative_chia(
                chia_discrepancy, []
            )

        zero_spend_list: List[SpendBundle] = []
        # create coloured coin
        self.log.info(cc_discrepancies)
        for colour in cc_discrepancies.keys():
            if cc_discrepancies[colour] < 0:
                my_cc_spends = await wallets[colour].select_coins(
                    abs(cc_discrepancies[colour])
                )
            else:
                if chia_spend_bundle is None:
                    to_exclude: List = []
                else:
                    to_exclude = chia_spend_bundle.removals()
                my_cc_spends = await wallets[colour].select_coins(0)
                if my_cc_spends is None or my_cc_spends == set():
                    zero_spend_bundle: SpendBundle = await wallets[
                        colour
                    ].generate_zero_val_coin(False, to_exclude)
                    if zero_spend_bundle is None:
                        return (
                            False,
                            "Unable to generate zero value coin. Confirm that you have chia available",
                        )
                    zero_spend_list.append(zero_spend_bundle)

                    additions = zero_spend_bundle.additions()
                    removals = zero_spend_bundle.removals()
                    my_cc_spends = set()
                    for add in additions:
                        if add not in removals and add.amount == 0:
                            my_cc_spends.add(add)

            if my_cc_spends == set() or my_cc_spends is None:
                return False, "insufficient funds"

            auditor = my_cc_spends.pop()
            auditor_inner_puzzle = await self.get_inner_puzzle_for_puzzle_hash(
                auditor.puzzle_hash
            )
            assert auditor_inner_puzzle is not None
            inner_hash = auditor_inner_puzzle.get_tree_hash()

            auditor_info = (
                auditor.parent_coin_info,
                inner_hash,
                auditor.amount,
            )
            auditor_formatted = (
                f"(0x{auditor.parent_coin_info} 0x{inner_hash} {auditor.amount})"
            )
            core = cc_wallet_puzzles.cc_make_core(colour)
            parent_info = await wallets[colour].get_parent_for_coin(auditor)

            for coloured_coin in my_cc_spends:
                inner_solution = self.wallet_state_manager.main_wallet.make_solution(
                    consumed=[auditor.name()]
                )
                sig = await wallets[colour].get_sigs_for_innerpuz_with_innersol(
                    await self.get_inner_puzzle_for_puzzle_hash(
                        coloured_coin.puzzle_hash
                    ),
                    inner_solution,
                )
                aggsig = BLSSignature.aggregate([BLSSignature.aggregate(sig), aggsig])
                inner_puzzle = await self.get_inner_puzzle_for_puzzle_hash(
                    coloured_coin.puzzle_hash
                )
                assert inner_puzzle is not None
                # auditees should be (primary_input, innerpuzhash, coin_amount, output_amount)
                auditees[colour].append(
                    (
                        coloured_coin.parent_coin_info,
                        inner_puzzle.get_tree_hash(),
                        coloured_coin.amount,
                        0,
                    )
                )

                solution = cc_wallet_puzzles.cc_make_solution(
                    core,
                    (
                        parent_info.parent_name,
                        parent_info.inner_puzzle_hash,
                        parent_info.amount,
                    ),
                    coloured_coin.amount,
                    binutils.disassemble(inner_puzzle),
                    binutils.disassemble(inner_solution),
                    auditor_info,
                    None,
                )
                coin_spend = CoinSolution(
                    coloured_coin,
                    clvm.to_sexp_f(
                        [
                            cc_wallet_puzzles.cc_make_puzzle(
                                inner_puzzle.get_tree_hash(), core,
                            ),
                            solution,
                        ]
                    ),
                )
                coinsols.append(coin_spend)

                ephemeral = cc_wallet_puzzles.create_spend_for_ephemeral(
                    coloured_coin, auditor, 0
                )
                coinsols.append(ephemeral)

                auditor = cc_wallet_puzzles.create_spend_for_auditor(
                    auditor, coloured_coin
                )
                coinsols.append(auditor)

            # Tweak the offer's solution to include the new auditor
            for cc_coinsol_out in cc_coinsol_outamounts[colour]:
                cc_coinsol = cc_coinsol_out[0]
                offer_sol = binutils.disassemble(cc_coinsol.solution)
                # auditor is (primary_input, innerpuzzlehash, amount)
                offer_sol = offer_sol.replace(
                    "))) ()) () ()))", f"))) ()) {auditor_formatted} ()))"
                )
                new_coinsol = CoinSolution(
                    cc_coinsol.coin, binutils.assemble(offer_sol)
                )
                coinsols.append(new_coinsol)

                eph = cc_wallet_puzzles.create_spend_for_ephemeral(
                    cc_coinsol.coin, auditor, cc_coinsol_out[1]
                )
                coinsols.append(eph)

                aud = cc_wallet_puzzles.create_spend_for_auditor(
                    auditor, cc_coinsol.coin
                )
                coinsols.append(aud)

            # Finish the auditor CoinSolution with new information
            newinnerpuzhash = await wallets[colour].get_new_inner_hash()
            outputamount = (
                sum([c.amount for c in my_cc_spends])
                + cc_discrepancies[colour]
                + auditor.amount
            )
            innersol = self.wallet_state_manager.main_wallet.make_solution(
                primaries=[{"puzzlehash": newinnerpuzhash, "amount": outputamount}]
            )
            parent_info = await wallets[colour].get_parent_for_coin(auditor)

            auditees[colour].append(
                (
                    auditor.parent_coin_info,
                    auditor_inner_puzzle.get_tree_hash(),
                    auditor.amount,
                    outputamount,
                )
            )

            sig = await wallets[colour].get_sigs(auditor_inner_puzzle, innersol)
            aggsig = BLSSignature.aggregate([BLSSignature.aggregate(sig), aggsig])

            solution = cc_wallet_puzzles.cc_make_solution(
                core,
                (
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ),
                auditor.amount,
                binutils.disassemble(auditor_inner_puzzle),
                binutils.disassemble(innersol),
                auditor_info,
                auditees[colour],
            )

            cs = CoinSolution(
                auditor,
                clvm.to_sexp_f(
                    [
                        cc_wallet_puzzles.cc_make_puzzle(
                            auditor_inner_puzzle.get_tree_hash(), core
                        ),
                        solution,
                    ]
                ),
            )
            coinsols.append(cs)

            cs_eph = create_spend_for_ephemeral(auditor, auditor, outputamount)
            coinsols.append(cs_eph)

            cs_aud = create_spend_for_auditor(auditor, auditor)
            coinsols.append(cs_aud)

        spend_bundle = SpendBundle(coinsols, aggsig)
        my_tx_records = []

        if zero_spend_list is not None:
            zero_spend_list.append(spend_bundle)
            spend_bundle = SpendBundle.aggregate(zero_spend_list)

        # Add transaction history hor this trade
        if chia_spend_bundle is not None:
            spend_bundle = SpendBundle.aggregate([spend_bundle, chia_spend_bundle])
            if chia_discrepancy < 0:
                tx_record = TransactionRecord(
                    confirmed_at_index=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=token_bytes(),
                    amount=uint64(abs(chia_discrepancy)),
                    fee_amount=uint64(0),
                    incoming=False,
                    confirmed=False,
                    sent=uint32(10),
                    spend_bundle=chia_spend_bundle,
                    additions=chia_spend_bundle.additions(),
                    removals=chia_spend_bundle.removals(),
                    wallet_id=uint32(1),
                    sent_to=[],
                    trade_id=spend_bundle.name(),
                )
            else:
                tx_record = TransactionRecord(
                    confirmed_at_index=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=token_bytes(),
                    amount=uint64(abs(chia_discrepancy)),
                    fee_amount=uint64(0),
                    incoming=True,
                    confirmed=False,
                    sent=uint32(10),
                    spend_bundle=chia_spend_bundle,
                    additions=chia_spend_bundle.additions(),
                    removals=chia_spend_bundle.removals(),
                    wallet_id=uint32(1),
                    sent_to=[],
                    trade_id=spend_bundle.name(),
                )
            my_tx_records.append(tx_record)

        for colour, amount in cc_discrepancies.items():
            wallet = wallets[colour]
            if chia_discrepancy > 0:
                tx_record = TransactionRecord(
                    confirmed_at_index=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=token_bytes(),
                    amount=uint64(abs(amount)),
                    fee_amount=uint64(0),
                    incoming=False,
                    confirmed=False,
                    sent=uint32(10),
                    spend_bundle=spend_bundle,
                    additions=spend_bundle.additions(),
                    removals=spend_bundle.removals(),
                    wallet_id=wallet.wallet_info.id,
                    sent_to=[],
                    trade_id=spend_bundle.name(),
                )
            else:
                tx_record = TransactionRecord(
                    confirmed_at_index=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=token_bytes(),
                    amount=uint64(abs(amount)),
                    fee_amount=uint64(0),
                    incoming=True,
                    confirmed=False,
                    sent=uint32(10),
                    spend_bundle=spend_bundle,
                    additions=spend_bundle.additions(),
                    removals=spend_bundle.removals(),
                    wallet_id=wallet.wallet_info.id,
                    sent_to=[],
                    trade_id=spend_bundle.name(),
                )
            my_tx_records.append(tx_record)

        tx_record = TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=token_bytes(),
            amount=uint64(0),
            fee_amount=uint64(0),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=uint32(0),
            sent_to=[],
            trade_id=spend_bundle.name(),
        )

        trade_record = TradeRecord(
            confirmed_at_index=uint32(0),
            accepted_at_time=uint64(int(time.time())),
            created_at_time=trade_offer.created_at_time,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            trade_id=spend_bundle.name(),
            sent_to=[],
        )

        await self.add_accepted_offer(trade_record)

        await self.wallet_state_manager.add_pending_transaction(tx_record)
        for tx in my_tx_records:
            await self.wallet_state_manager.add_transaction(tx)

        return True, None
