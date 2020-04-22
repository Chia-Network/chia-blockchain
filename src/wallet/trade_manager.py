from pathlib import Path
from typing import Dict, Optional, Tuple, List
import logging

import clvm

from src.types.BLSSignature import BLSSignature, ZERO96
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.util.byte_types import hexstr_to_bytes
from src.wallet.cc_wallet import cc_wallet_puzzles
from src.wallet.cc_wallet.cc_wallet import CCWallet
from src.wallet.cc_wallet.cc_wallet_puzzles import create_spend_for_auditor, create_spend_for_ephemeral, \
    get_innerpuzzle_from_puzzle
from src.wallet.wallet import Wallet
from src.wallet.wallet_state_manager import WalletStateManager
from clvm_tools import binutils


class TradeManager:
    wallet_state_manager: WalletStateManager
    log: logging.Logger

    @staticmethod
    async def create(
            wallet_state_manager: WalletStateManager, name: str = None,
    ):
        self = TradeManager()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        return self

    async def create_offer_for_ids(self, offer: Dict[int, int], file_path: str) -> Tuple[bool, Optional[SpendBundle]]:
        """
        Offer is dictionary of wallet ids and amount
        """
        spend_bundle = None
        try:
            for id in offer.keys():
                amount = offer[id]
                wallet_id = int(id)
                wallet = self.wallet_state_manager.wallets[wallet_id]
                if isinstance(wallet, CCWallet):
                    new_spend_bundle = await wallet.create_spend_bundle_relative_amount(amount)
                elif isinstance(wallet, Wallet):
                    new_spend_bundle = await wallet.create_spend_bundle_relative_chia(
                        amount
                    )
                else:
                    return False, None

                if spend_bundle is None:
                    spend_bundle = new_spend_bundle
                else:
                    spend_bundle = SpendBundle.aggregate([spend_bundle, new_spend_bundle])

            return True, spend_bundle
        except Exception as e:
            return False, None

    def write_offer_to_disk(self, file_name, offer: SpendBundle):
        f = open(file_name, "w")
        f.write(bytes(offer).hex())
        f.close()

    async def get_discrepancies_for_offer(self, filename) -> Tuple[bool, Optional[Dict], Optional[Exception]]:
        try:
            cc_discrepancies = dict()
            wallets = dict()
            f = open(filename, "r")
            trade_offer_hex = f.read()
            f.close()
            trade_offer = SpendBundle.from_bytes(bytes.fromhex(trade_offer_hex))
            for coinsol in trade_offer.coin_solutions:
                puzzle = coinsol.solution.first()
                solution = coinsol.solution.rest().first()

                # work out the deficits between coin amount and expected output for each
                if cc_wallet_puzzles.check_is_cc_puzzle(puzzle):
                    colour = cc_wallet_puzzles.get_genesis_from_puzzle(
                        binutils.disassemble(puzzle)
                    )
                    if colour not in wallets:
                        wallets[
                            colour
                        ] = await self.wallet_state_manager.get_wallet_for_colour(
                            colour
                        )
                    parent_info = binutils.disassemble(solution.rest().first()).split(" ")
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
                    if None in cc_discrepancies:
                        cc_discrepancies[None] += (
                            coinsol.coin.amount
                            - cc_wallet_puzzles.get_output_amount_for_puzzle_and_solution(
                                puzzle, solution
                            )
                        )
                    else:
                        cc_discrepancies[None] = (
                            coinsol.coin.amount
                            - cc_wallet_puzzles.get_output_amount_for_puzzle_and_solution(
                                puzzle, solution
                            )
                        )
            return True, cc_discrepancies, None
        except Exception as e:
            return False, None, e

    async def get_inner_puzzle_for_puzzle_hash(self, puzzle_hash) -> Optional[Program]:
        info = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(puzzle_hash.hex())
        assert info is not None
        puzzle = self.wallet_state_manager.main_wallet.puzzle_for_pk(bytes(info.pubkey))
        return puzzle

    async def respond_to_offer(self, filename) -> bool:
        f = open(filename, "r")
        trade_offer_hex = f.read()
        f.close()
        trade_offer = SpendBundle.from_bytes(bytes.fromhex(trade_offer_hex))

        coinsols = []  # [] of CoinSolutions
        cc_coinsol_outamounts = dict()
        auditees = dict()  # used for generating auditor solution, key is colour
        aggsig = trade_offer.aggregated_signature
        cc_discrepancies = dict()
        chia_discrepancy = None
        wallets = dict()  # colour to wallet dict

        for coinsol in trade_offer.coin_solutions:
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
                # standard chia coin
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
                chia_discrepancy
            )

        zero_spend_list: List[SpendBundle] = []
        # create coloured coin
        for colour in cc_discrepancies.keys():
            auditor = None
            auditor_inner_puzzle = None
            auditor_info = None
            auditor_formatted = None

            if cc_discrepancies[colour] < 0:
                my_cc_spends = await wallets[colour].select_coins(
                    abs(cc_discrepancies[colour])
                )
            else:
                if chia_spend_bundle is None:
                    to_exclude = []
                else:
                    to_exclude = chia_spend_bundle.removals()
                zero_spend_bundle: SpendBundle = await wallets[colour].generate_zero_val_coin(False, to_exclude)
                zero_spend_list.append(zero_spend_bundle)

                additions = zero_spend_bundle.additions()
                removals = zero_spend_bundle.removals()
                my_cc_spends = set()
                for add in additions:
                    if add not in removals and add.amount == 0:
                        my_cc_spends.add(add)

            # TODO: if unable to select coins, autogenerate a zero value coin
            if my_cc_spends == set() or my_cc_spends is None:
                return False

            for coloured_coin in my_cc_spends:
                # establish the auditor
                if auditor is None:
                    auditor = coloured_coin
                    auditor_inner_puzzle = await self.get_inner_puzzle_for_puzzle_hash(auditor.puzzle_hash)
                    inner_hash = auditor_inner_puzzle.get_tree_hash()

                    auditor_info = (
                        auditor.parent_coin_info,
                        inner_hash,
                        auditor.amount,
                    )
                    auditor_formatted = f"(0x{auditor.parent_coin_info} 0x{inner_hash} {auditor.amount})"
                    core = cc_wallet_puzzles.cc_make_core(colour)
                    parent_info = await wallets[colour].get_parent_for_coin(auditor)
                # complete the non-auditor CoinSolutions
                else:
                    innersol = self.wallet_state_manager.main_wallet.make_solution(
                        consumed=[auditor.name()]
                    )
                    sig = await wallets[colour].get_sigs_for_innerpuz_with_innersol(
                        await self.get_inner_puzzle_for_puzzle_hash(
                            coloured_coin.puzzle_hash
                        ),
                        innersol,
                    )
                    aggsig = BLSSignature.aggregate(
                        [BLSSignature.aggregate(sig), aggsig]
                    )
                    # auditees should be (primary_input, innerpuzhash, coin_amount, output_amount)
                    innerpuz = await self.get_inner_puzzle_for_puzzle_hash(
                        coloured_coin.puzzle_hash
                    )
                    auditees[colour].append(
                        (
                            coloured_coin.parent_coin_info,
                            innerpuz.get_tree_hash(),
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
                        binutils.disassemble(innerpuz),
                        binutils.disassemble(innersol),
                        auditor_info,
                        None,
                    )
                    coin_spend = CoinSolution(
                            coloured_coin,
                            clvm.to_sexp_f(
                                [
                                    cc_wallet_puzzles.cc_make_puzzle(
                                        innerpuz.get_tree_hash(), core,
                                    ),
                                    solution,
                                ]
                            ),
                        )
                    coinsols.append(coin_spend)

                    eph = cc_wallet_puzzles.create_spend_for_ephemeral(
                        coloured_coin, auditor, 0
                    )
                    coinsols.append(eph)

                    aud = cc_wallet_puzzles.create_spend_for_auditor(
                            auditor, coloured_coin
                        )
                    coinsols.append(aud)

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

                aud = cc_wallet_puzzles.create_spend_for_auditor(auditor, cc_coinsol.coin)
                coinsols.append(aud)

            # Finish the auditor CoinSolution with new information
            newinnerpuzhash = await wallets[colour].get_new_inner_hash()
            outputamount = (
                sum([c.amount for c in my_cc_spends]) + cc_discrepancies[colour]
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


        if chia_spend_bundle is not None:
            spend_bundle = SpendBundle.aggregate([spend_bundle, chia_spend_bundle])

        if zero_spend_list is not None:
            zero_spend_list.append(spend_bundle)
            spend_bundle = SpendBundle.aggregate(zero_spend_list)

        await self.wallet_state_manager.add_pending_transaction(
            spend_bundle,
            self.wallet_state_manager.main_wallet.wallet_info.id
        )

        return True
