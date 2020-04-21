from pathlib import Path
from typing import Dict, Optional, Tuple
import logging

import clvm

from src.types.BLSSignature import BLSSignature
from src.types.coin_solution import CoinSolution
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.wallet.cc_wallet import cc_wallet_puzzles
from src.wallet.cc_wallet.cc_wallet import CCWallet
from src.wallet.cc_wallet.cc_wallet_puzzles import create_spend_for_auditor, create_spend_for_ephemeral
from src.wallet.wallet import Wallet
from src.wallet.wallet_state_manager import WalletStateManager
from clvm_tools import binutils


class TradeManager:
    wallet_state_manager: WalletStateManager
    log: logging.Logger

    @staticmethod
    async def create(
            wallet_state_manager: WalletStateManager, path: Path, config: Dict, name: str = None,
    ):
        self = TradeManager()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        return self

    async def create_offer_for_ids(self, offer: Dict[int, int], file_path: str) -> bool:
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
                    return False

                if spend_bundle is None:
                    spend_bundle = new_spend_bundle
                else:
                    spend_bundle = SpendBundle.aggregate([spend_bundle, new_spend_bundle])

            f = open(file_path, "w")
            f.write(bytes(spend_bundle).hex())
            f.close()
            return True
        except Exception as e:
            return False

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
        except Exception as e:
            return False, None, e


    async def respond_to_offer(self, filename) -> bool:
        f = open(filename, "r")
        trade_offer_hex = f.read()
        f.close()
        trade_offer = SpendBundle.from_bytes(bytes.fromhex(trade_offer_hex))

        spend_bundle = None
        coinsols = []  # [] of CoinSolutions
        cc_coinsol_outamounts = dict()
        # spendslist is [] of (coin, parent_info, outputamount, innersol, innerpuzzlehash=None)
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
                    # remove brackets from parent_info
                    parent_info[0] = parent_info[0].replace("(", "")
                    parent_info[2] = parent_info[2].replace(")", "")

                    # Add this coin to the list of auditees for this colour
                    # auditees should be (primary_input, innerpuzhash, coin_amount, output_amount)
                    if colour in auditees:
                        auditees[colour].append(
                            (
                                parent_info,
                                Program(innerpuzzlereveal).get_tree_hash(),
                                coinsol.coin.amount,
                                out_amount,
                            )
                        )
                    else:
                        auditees[colour] = [
                            (
                                parent_info,
                                Program(innerpuzzlereveal).get_tree_hash(),
                                coinsol.coin.amount,
                                out_amount,
                            )
                        ]
                # else:  # Eve spend - currently don't support 0 generation as its not the recipients problem
                #     coinsols.append(coinsol)
            else:  # standard chia coin
                if chia_discrepancy is None:
                    chia_discrepancy = cc_wallet_puzzles.get_output_discrepancy_for_puzzle_and_solution(
                        coinsol.coin, puzzle, solution
                    )
                else:
                    chia_discrepancy += cc_wallet_puzzles.get_output_discrepancy_for_puzzle_and_solution(
                        coinsol.coin, puzzle, solution
                    )
                coinsols.append(coinsol)

        chia_spend_bundle = None
        if chia_discrepancy is not None:
            chia_spend_bundle = await self.wallet_state_manager.main_wallet.create_spend_bundle_relative_chia(
                chia_discrepancy
            )

        # create coloured coin
        for colour in cc_discrepancies.keys():
            coloured_coin = None
            auditor = None
            auditor_innerpuz = None
            auditor_info = None
            auditor_formatted = None

            if cc_discrepancies[colour] < 0:
                my_cc_spends = await wallets[colour].select_coins(
                    abs(cc_discrepancies[colour])
                )
            else:
                my_cc_spends = await wallets[colour].select_coins(1)

            # TODO: if unable to select coins, autogenerate a zero value coin

            if my_cc_spends == set() or my_cc_spends is None:
                return None

            for coloured_coin in my_cc_spends:
                # establish the auditor
                if auditor is None:
                    auditor = coloured_coin
                    if auditor_innerpuz is None:
                        auditor_innerpuz = await wallets[colour].get_innerpuzzle_from_puzzle(
                            auditor.puzzle_hash
                        )
                    auditor_info = (
                        auditor.parent_coin_info,
                        auditor_innerpuz.get_tree_hash(),
                        auditor.amount,
                    )
                    inner_hash = auditor_innerpuz.get_tree_hash()
                    auditor_formatted = f"(0x{auditor.parent_coin_info} 0x{inner_hash} {auditor.amount})"
                    core = cc_wallet_puzzles.cc_make_core(colour)

                # complete the non-auditor CoinSolutions
                else:
                    innersol = self.wallet_state_manager.main_wallet.make_solution(
                        consumed=[auditor.name()]
                    )
                    sig = await wallets[colour].get_sigs_for_innerpuz_with_innersol(
                        wallets[colour].get_innerpuzzle_from_puzzle(
                            coloured_coin.puzzle_hash
                        ),
                        innersol,
                    )
                    aggsig = BLSSignature.aggregate(
                        [BLSSignature.aggregate(sig), aggsig]
                    )
                    # auditees should be (primary_input, innerpuzhash, coin_amount, output_amount)
                    innerpuz = wallets[colour].get_innerpuzzle_from_puzzle(
                        coloured_coin.puzzle_hash
                    )
                    auditees[colour].append(
                        (
                            coloured_coin.parent_coin_info,
                            innerpuz,
                            coloured_coin.amount,
                            0,
                        )
                    )
                    parent_info = await wallets[colour].get_parent_for_coin(auditor)
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
                    coinsols.append(
                        CoinSolution(
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
                    )
                    coinsols.append(
                        cc_wallet_puzzles.create_spend_for_ephemeral(
                            coloured_coin, auditor, 0
                        )
                    )
                    coinsols.append(
                        cc_wallet_puzzles.create_spend_for_auditor(
                            auditor, coloured_coin
                        )
                    )

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
                coinsols.append(
                    cc_wallet_puzzles.create_spend_for_ephemeral(
                        cc_coinsol.coin, auditor, cc_coinsol_out[1]
                    )
                )
                coinsols.append(
                    cc_wallet_puzzles.create_spend_for_auditor(auditor, cc_coinsol.coin)
                )

            # Finish the auditor CoinSolution with new information
            newinnerpuzhash = wallets[colour].get_new_inner_hash()
            outputamount = (
                sum([c.amount for c in my_cc_spends]) + cc_discrepancies[colour]
            )
            innersol = self.wallet_state_manager.main_wallet.make_solution(
                primaries=[{"puzzlehash": newinnerpuzhash, "amount": outputamount}]
            )
            parent_info = wallets[colour].get_parent_for_coin(auditor.parent_coin_info)
            auditees[colour].append(
                (
                    auditor.parent_coin_info,
                    auditor_innerpuz,
                    auditor.amount,
                    outputamount,
                )
            )
            sig = wallets[colour].get_sigs(auditor_innerpuz, innersol)
            aggsig = BLSSignature.aggregate([BLSSignature.aggregate(sig), aggsig])
            solution = cc_wallet_puzzles.cc_make_solution(
                core,
                parent_info,
                auditor.amount,
                binutils.disassemble(auditor_innerpuz),
                binutils.disassemble(innersol),
                auditor_info,
                auditees[colour],
            )
            coinsols.append(
                CoinSolution(
                    auditor,
                    clvm.to_sexp_f(
                        [
                            cc_wallet_puzzles.cc_make_puzzle(
                                auditor_innerpuz.get_tree_hash(), core
                            ),
                            solution,
                        ]
                    ),
                )
            )
            coinsols.append(
                create_spend_for_ephemeral(auditor, auditor, outputamount)
            )
            coinsols.append(create_spend_for_auditor(auditor, auditor))

        # Combine all CoinSolutions into a spend bundle
        if spend_bundle is None:
            spend_bundle = SpendBundle(coinsols, aggsig)
        else:
            spend_bundle = SpendBundle.aggregate(
                [spend_bundle, SpendBundle(coinsols, aggsig)]
            )

        if chia_spend_bundle is not None:
            spend_bundle = SpendBundle.aggregate([spend_bundle, chia_spend_bundle])

        await self.wallet_state_manager.add_pending_transaction(
            spend_bundle,
            self.wallet_state_manager.main_wallet.wallet_info.id
        )

        return True



