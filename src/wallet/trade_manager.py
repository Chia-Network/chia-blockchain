import time
import traceback
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
from src.util.ints import uint32, uint64
from src.wallet.cc_wallet import cc_wallet_puzzles
from src.wallet.cc_wallet.cc_wallet import CCWallet
from src.wallet.cc_wallet.cc_wallet_puzzles import (
    create_spend_for_auditor,
    create_spend_for_ephemeral,
)
from src.wallet.trade_record import TradeRecord
from src.wallet.trading.trade_status import TradeStatus
from src.wallet.trading.trade_store import TradeStore
from src.wallet.transaction_record import TransactionRecord
from src.wallet.wallet import Wallet
from clvm_tools import binutils

from src.wallet.wallet_coin_record import WalletCoinRecord


class TradeManager:
    wallet_state_manager: Any
    log: logging.Logger
    trade_store: TradeStore

    @staticmethod
    async def create(
        wallet_state_manager: Any, db_connection, name: str = None,
    ):
        self = TradeManager()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.trade_store = await TradeStore.create(db_connection)
        return self

    async def get_offers_with_status(self, status: TradeStatus) -> List[TradeRecord]:
        records = await self.trade_store.get_trade_record_with_status(status)
        return records

    async def get_coins_of_interest(
        self,
    ) -> Tuple[Dict[bytes32, Coin], Dict[bytes32, Coin]]:
        """
        Returns list of coins we want to check if they are included in filter,
        These will include coins that belong to us and coins that that on other side of treade
        """
        all_pending = []
        pending_accept = await self.get_offers_with_status(TradeStatus.PENDING_ACCEPT)
        pending_confirm = await self.get_offers_with_status(TradeStatus.PENDING_CONFIRM)
        pending_cancel = await self.get_offers_with_status(TradeStatus.PENDING_CANCEL)
        all_pending.extend(pending_accept)
        all_pending.extend(pending_confirm)
        all_pending.extend(pending_cancel)
        removals = {}
        additions = {}

        for trade in all_pending:
            for coin in trade.spend_bundle.removals():
                removals[coin.name()] = coin
            for coin in trade.spend_bundle.additions():
                additions[coin.name()] = coin

        return removals, additions

    async def get_trade_by_coin(self, coin: Coin) -> Optional[TradeRecord]:
        all_trades = await self.get_all_trades()
        for trade in all_trades:
            if coin in trade.removals:
                return trade
            if coin in trade.additions:
                return trade
        return None

    async def coins_of_interest_farmed(
        self, removals: List[Coin], additions: List[Coin], index: uint32
    ):
        """
        If both our coins and other coins in trade got removed that means that trade was successfully executed
        If coins from other side of trade got farmed without ours, that means that trade failed because either someone
        else completed trade or other side of trade canceled the trade by doing a spend.
        If our coins got farmed but coins from other side didn't, we successfully canceled trade by spending inputs.
        """
        removal_dict = {}
        addition_dict = {}
        checked: Dict[bytes32, Coin] = {}
        for coin in removals:
            removal_dict[coin.name()] = coin
        for coin in additions:
            addition_dict[coin.name()] = coin

        all_coins = []
        all_coins.extend(removals)
        all_coins.extend(additions)

        for coin in all_coins:
            if coin.name() in checked:
                continue
            trade = await self.get_trade_by_coin(coin)
            if trade is None:
                self.log.error(f"Coin: {Coin}, not in any trade")
                continue

            # Check if all coins that are part of the trade got farmed
            # If coin is missing, trade failed
            failed = False
            for coin in trade.removals:
                if coin.name() not in removal_dict:
                    self.log.error(f"{coin} from trade not removed")
                    failed = True
                checked[coin.name()] = coin
            for coin in trade.additions:
                if coin.name() not in addition_dict:
                    self.log.error(f"{coin} from trade not added")
                    failed = True
                checked[coin.name()] = coin

            if failed is False:
                # Mark this trade as succesfull
                await self.trade_store.set_status(
                    trade.trade_id, TradeStatus.CONFIRMED, index
                )
                self.log.info(
                    f"Trade with id: {trade.trade_id} confirmed at height: {index}"
                )
            else:
                # Either we canceled this trade or this trade failed
                status = TradeStatus(trade.status)
                if status is TradeStatus.PENDING_CANCEL:
                    await self.trade_store.set_status(
                        trade.trade_id, TradeStatus.CANCELED
                    )
                    self.log.info(
                        f"Trade with id: {trade.trade_id} canceled at height: {index}"
                    )
                else:
                    await self.trade_store.set_status(
                        trade.trade_id, TradeStatus.FAILED
                    )
                    self.log.warning(
                        f"Trade with id: {trade.trade_id} failed at height: {index}"
                    )

    async def get_locked_coins(
        self, wallet_id: int = None
    ) -> Dict[bytes32, WalletCoinRecord]:
        """ Returns a dictionary of confirmed coins that are locked by a trade. """
        all_pending = []
        pending_accept = await self.get_offers_with_status(TradeStatus.PENDING_ACCEPT)
        pending_confirm = await self.get_offers_with_status(TradeStatus.PENDING_CONFIRM)
        pending_cancel = await self.get_offers_with_status(TradeStatus.PENDING_CANCEL)
        all_pending.extend(pending_accept)
        all_pending.extend(pending_confirm)
        all_pending.extend(pending_cancel)
        if len(all_pending) == 0:
            return {}

        result = {}
        for trade_offer in all_pending:
            locked = await self.get_locked_coins_in_spend_bundle(
                trade_offer.spend_bundle
            )
            for name, record in locked.items():
                if wallet_id is None or record.wallet_id == wallet_id:
                    result[name] = record

        return result

    async def get_all_trades(self):
        all: List[TradeRecord] = await self.trade_store.get_all_trades()
        return all

    async def get_trade_by_id(self, trade_id: bytes) -> Optional[TradeRecord]:
        record = await self.trade_store.get_trade_record(trade_id)
        return record

    async def get_locked_coins_in_spend_bundle(
        self, bundle: SpendBundle
    ) -> Dict[bytes32, WalletCoinRecord]:
        """ Returns a list of coin records that are used in this SpendBundle"""
        result = {}
        removals = bundle.removals()
        for coin in removals:
            coin_record = await self.wallet_state_manager.wallet_store.get_coin_record_by_coin_id(
                coin.name()
            )
            if coin_record is None:
                continue
            result[coin_record.name()] = coin_record
        return result

    async def cancel_pending_offer(self, trade_id: bytes32):
        await self.trade_store.set_status(trade_id, TradeStatus.CANCELED)

    async def cancel_pending_offer_safely(self, trade_id: bytes32):
        """ This will create a transaction that includes coins that were offered"""
        self.log.info(f"Secure-Cancel pending offer with id trade_id {trade_id.hex()}")
        trade = await self.trade_store.get_trade_record(trade_id)
        if trade is None:
            return None

        all_coins = trade.spend_bundle.removals()

        for coin in all_coins:
            wallet = await self.wallet_state_manager.get_wallet_for_coin(coin.name())

            if wallet is None:
                continue
            new_ph = await wallet.get_new_puzzlehash()
            tx = await wallet.generate_signed_transaction(
                coin.amount, new_ph, 0, coins={coin}
            )
            await self.wallet_state_manager.add_pending_transaction(tx_record=tx)

        await self.trade_store.set_status(trade_id, TradeStatus.PENDING_CANCEL)
        return

    async def save_trade(self, trade: TradeRecord):
        await self.trade_store.add_trade_record(trade)

    async def create_offer_for_ids(
        self, offer: Dict[int, int], file_name: str
    ) -> Tuple[bool, Optional[TradeRecord], Optional[str]]:
        success, trade_offer, error = await self._create_offer_for_ids(offer)

        if success is True and trade_offer is not None:
            self.write_offer_to_disk(Path(file_name), trade_offer)
            await self.save_trade(trade_offer)

        return success, trade_offer, error

    async def _create_offer_for_ids(
        self, offer: Dict[int, int]
    ) -> Tuple[bool, Optional[TradeRecord], Optional[str]]:
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
                    return False, None, "unsupported wallet type"
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

            now = uint64(int(time.time()))
            trade_offer: TradeRecord = TradeRecord(
                confirmed_at_index=uint32(0),
                accepted_at_time=None,
                created_at_time=now,
                my_offer=True,
                sent=uint32(0),
                spend_bundle=spend_bundle,
                additions=spend_bundle.additions(),
                removals=spend_bundle.removals(),
                trade_id=spend_bundle.name(),
                status=uint32(TradeStatus.PENDING_ACCEPT.value),
                sent_to=[],
            )
            return True, trade_offer, None
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Error with creating trade offer: {type(e)}{tb}")
            return False, None, str(e)

    def write_offer_to_disk(self, file_path: Path, offer: TradeRecord):
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
        trade_offer = TradeRecord.from_bytes(bytes.fromhex(trade_offer_hex))
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
        trade_offer: TradeRecord = TradeRecord.from_bytes(
            bytes.fromhex(trade_offer_hex)
        )
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

        now = uint64(int(time.time()))
        trade_record: TradeRecord = TradeRecord(
            confirmed_at_index=uint32(0),
            accepted_at_time=now,
            created_at_time=now,
            my_offer=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            trade_id=spend_bundle.name(),
            status=uint32(TradeStatus.PENDING_CONFIRM.value),
            sent_to=[],
        )

        await self.save_trade(trade_record)

        await self.wallet_state_manager.add_pending_transaction(tx_record)
        for tx in my_tx_records:
            await self.wallet_state_manager.add_transaction(tx)

        return True, None
