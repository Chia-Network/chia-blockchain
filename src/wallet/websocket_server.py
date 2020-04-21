import asyncio
import json
import logging
import signal
import time
import traceback
import clvm

from typing import Any, Dict, List, Optional, Tuple

import websockets

from src.types.peer_info import PeerInfo
from src.util.byte_types import hexstr_to_bytes
from src.wallet.cc_wallet.cc_wallet_puzzles import create_spend_for_auditor, create_spend_for_ephemeral
from src.wallet.util.json_util import dict_to_json_str

try:
    import uvloop
except ImportError:
    uvloop = None

from src.server.outbound_message import NodeType, OutboundMessage, Message, Delivery
from src.server.server import ChiaServer
from src.simulator.simulator_constants import test_constants
from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.util.config import load_config_cli, load_config
from src.util.ints import uint64
from src.util.logging import initialize_logging
from src.wallet.rl_wallet.rl_wallet import RLWallet
from src.wallet.cc_wallet.cc_wallet import CCWallet
from src.wallet.wallet import Wallet
from src.wallet.cc_wallet import cc_wallet_puzzles
from src.wallet.wallet_info import WalletInfo
from src.wallet.wallet_node import WalletNode
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.setproctitle import setproctitle
from clvm_tools import binutils
from src.types.spend_bundle import SpendBundle
from src.types.program import Program
from src.types.BLSSignature import BLSSignature
from src.types.coin_solution import CoinSolution

# Timeout for response from wallet/full node for sending a transaction
TIMEOUT = 30


def format_response(command: str, response_data: Dict[str, Any]):
    """
    Formats the response into standard format used between renderer.js and here
    """
    response = {"command": command, "data": response_data}

    json_str = dict_to_json_str(response)
    return json_str


class WebSocketServer:
    def __init__(self, wallet_node: WalletNode, log):
        self.wallet_node: WalletNode = wallet_node
        self.websocket = None
        self.log = log

    async def get_next_puzzle_hash(self, websocket, request, response_api):
        """
        Returns a new puzzlehash
        """

        wallet_id = int(request["wallet_id"])
        wallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        puzzlehash = (await wallet.get_new_puzzlehash()).hex()

        data = {
            "puzzlehash": puzzlehash,
        }

        await websocket.send(format_response(response_api, data))

    async def send_transaction(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        try:
            tx = await wallet.generate_signed_transaction_dict(request)
        except BaseException as e:
            data = {
                "status": "FAILED",
                "reason": f"Failed to generate signed transaction {e}",
            }
            return await websocket.send(format_response(response_api, data))

        if tx is None:
            data = {
                "status": "FAILED",
                "reason": "Failed to generate signed transaction",
            }
            return await websocket.send(format_response(response_api, data))
        try:
            await wallet.push_transaction(tx)
        except BaseException as e:
            data = {
                "status": "FAILED",
                "reason": f"Failed to push transaction {e}",
            }
            return await websocket.send(format_response(response_api, data))
        self.log.error(tx)
        sent = False
        start = time.time()
        while time.time() - start < TIMEOUT:
            sent_to: List[
                Tuple[str, MempoolInclusionStatus, Optional[str]]
            ] = await self.wallet_node.wallet_state_manager.get_transaction_status(
                tx.name()
            )

            if len(sent_to) == 0:
                await asyncio.sleep(0.1)
                continue
            status, err = sent_to[0][1], sent_to[0][2]
            if status == MempoolInclusionStatus.SUCCESS:
                data = {"status": "SUCCESS"}
                sent = True
                break
            elif status == MempoolInclusionStatus.PENDING:
                assert err is not None
                data = {"status": "PENDING", "reason": err}
                sent = True
                break
            elif status == MempoolInclusionStatus.FAILED:
                assert err is not None
                data = {"status": "FAILED", "reason": err}
                sent = True
                break
        if not sent:
            data = {
                "status": "FAILED",
                "reason": "Timed out. Transaction may or may not have been sent.",
            }

        return await websocket.send(format_response(response_api, data))

    async def server_ready(self, websocket, response_api):
        response = {"success": True}
        await websocket.send(format_response(response_api, response))

    async def get_transactions(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        transactions = await self.wallet_node.wallet_state_manager.get_all_transactions(
            wallet_id
        )

        response = {"success": True, "txs": transactions}
        await websocket.send(format_response(response_api, response))

    async def farm_block(self, websocket, request, response_api):
        puzzle_hash = bytes.fromhex(request["puzzle_hash"])
        request = FarmNewBlockProtocol(puzzle_hash)
        msg = OutboundMessage(
            NodeType.FULL_NODE, Message("farm_new_block", request), Delivery.BROADCAST,
        )

        self.wallet_node.server.push_message(msg)

    async def get_wallet_balance(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        balance = await wallet.get_confirmed_balance()
        pending_balance = await wallet.get_unconfirmed_balance()

        response = {
            "wallet_id": wallet_id,
            "success": True,
            "confirmed_wallet_balance": balance,
            "unconfirmed_wallet_balance": pending_balance,
        }

        await websocket.send(format_response(response_api, response))

    async def get_sync_status(self, websocket, response_api):
        syncing = self.wallet_node.wallet_state_manager.sync_mode

        response = {"syncing": syncing}

        await websocket.send(format_response(response_api, response))

    async def get_height_info(self, websocket, response_api):
        lca = self.wallet_node.wallet_state_manager.lca
        height = self.wallet_node.wallet_state_manager.block_records[lca].height

        response = {"height": height}

        await websocket.send(format_response(response_api, response))

    async def get_connection_info(self, websocket, response_api):
        connections = (
            self.wallet_node.server.global_connections.get_full_node_peerinfos()
        )

        response = {"connections": connections}

        await websocket.send(format_response(response_api, response))

    async def create_new_wallet(self, websocket, request, response_api):
        config, key_config, wallet_state_manager, main_wallet = self.get_wallet_config()
        if request["wallet_type"] == "rl_wallet":
            if request["mode"] == "admin":
                rl_admin: RLWallet = await RLWallet.create_rl_admin(
                    config, key_config, wallet_state_manager, main_wallet
                )
                self.wallet_node.wallet_state_manager.wallets[
                    rl_admin.wallet_info.id
                ] = rl_admin
                response = {"success": True, "type": "rl_wallet"}
                return await websocket.send(format_response(response_api, response))
            elif request["mode"] == "user":
                rl_user: RLWallet = await RLWallet.create_rl_user(
                    config, key_config, wallet_state_manager, main_wallet
                )
                self.wallet_node.wallet_state_manager.wallets[
                    rl_user.wallet_info.id
                ] = rl_user
                response = {"success": True, "type": "rl_wallet"}
                return await websocket.send(format_response(response_api, response))
        elif request["wallet_type"] == "cc_wallet":
            if request["mode"] == "new":
                cc_wallet: CCWallet = await CCWallet.create_new_cc(
                    wallet_state_manager, main_wallet, request["amount"]
                )
                response = {"success": True, "type": cc_wallet.wallet_info.type.name}
                return await websocket.send(format_response(response_api, response))
            elif request["mode"] == "existing":
                cc_wallet: CCWallet = await CCWallet.create_wallet_for_cc(
                    wallet_state_manager, main_wallet, request["colour"]
                )
                response = {"success": True, "type": cc_wallet.wallet_info.type.name}
                return await websocket.send(format_response(response_api, response))

        response = {"success": False}
        return await websocket.send(format_response(response_api, response))

    def get_wallet_config(self):
        return (
            self.wallet_node.config,
            self.wallet_node.key_config,
            self.wallet_node.wallet_state_manager,
            self.wallet_node.wallet_state_manager.main_wallet,
        )

    async def get_wallets(self, websocket, response_api):
        wallets: List[
            WalletInfo
        ] = await self.wallet_node.wallet_state_manager.get_all_wallets()

        response = {"wallets": wallets}

        return await websocket.send(format_response(response_api, response))

    async def rl_set_admin_info(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet: RLWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        user_pubkey = request["user_pubkey"]
        limit = uint64(int(request["limit"]))
        interval = uint64(int(request["interval"]))
        amount = uint64(int(request["amount"]))

        success = await wallet.admin_create_coin(interval, limit, user_pubkey, amount)

        response = {"success": success}

        return await websocket.send(format_response(response_api, response))

    async def rl_set_user_info(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet: RLWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        admin_pubkey = request["admin_pubkey"]
        limit = uint64(int(request["limit"]))
        interval = uint64(int(request["interval"]))
        origin_id = request["origin_id"]

        success = await wallet.set_user_info(interval, limit, origin_id, admin_pubkey)

        response = {"success": success}

        return await websocket.send(format_response(response_api, response))

    async def cc_set_name(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        success = await wallet.set_name(str(request["name"]))
        response = {"success": success}
        return await websocket.send(format_response(response_api, response))

    async def cc_get_name(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        name: str = await wallet.get_name()
        response = {"name": name}
        return await websocket.send(format_response(response_api, response))

    async def cc_generate_zero_val(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        try:
            tx = await wallet.generate_zero_val_coin()
        except BaseException as e:
            data = {
                "status": "FAILED",
                "reason": f"{e}",
            }
            return await websocket.send(format_response(response_api, data))

        if tx is None:
            data = {
                "status": "FAILED",
                "reason": "Failed to generate signed transaction",
            }
            return await websocket.send(format_response(response_api, data))
        self.log.error(tx)
        sent = False
        start = time.time()
        while time.time() - start < TIMEOUT:
            sent_to: List[
                Tuple[str, MempoolInclusionStatus, Optional[str]]
            ] = await self.wallet_node.wallet_state_manager.get_transaction_status(
                tx.name()
            )

            if len(sent_to) == 0:
                await asyncio.sleep(0.1)
                continue
            status, err = sent_to[0][1], sent_to[0][2]
            if status == MempoolInclusionStatus.SUCCESS:
                data = {"status": "SUCCESS"}
                sent = True
                break
            elif status == MempoolInclusionStatus.PENDING:
                assert err is not None
                data = {"status": "PENDING", "reason": err}
                sent = True
                break
            elif status == MempoolInclusionStatus.FAILED:
                assert err is not None
                data = {"status": "FAILED", "reason": err}
                sent = True
                break
        if not sent:
            data = {
                "status": "FAILED",
                "reason": "Timed out. Transaction may or may not have been sent.",
            }
        return await websocket.send(format_response(response_api, data))

    async def cc_spend(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        puzzle_hash = hexstr_to_bytes(request["innerpuzhash"])
        try:
            tx = await wallet.cc_spend(request["amount"], puzzle_hash)
        except BaseException as e:
            data = {
                "status": "FAILED",
                "reason": f"{e}",
            }
            return await websocket.send(format_response(response_api, data))

        if tx is None:
            data = {
                "status": "FAILED",
                "reason": "Failed to generate signed transaction",
            }
            return await websocket.send(format_response(response_api, data))

        self.log.error(tx)
        sent = False
        start = time.time()
        while time.time() - start < TIMEOUT:
            sent_to: List[
                Tuple[str, MempoolInclusionStatus, Optional[str]]
            ] = await self.wallet_node.wallet_state_manager.get_transaction_status(
                tx.name()
            )

            if len(sent_to) == 0:
                await asyncio.sleep(0.1)
                continue
            status, err = sent_to[0][1], sent_to[0][2]
            if status == MempoolInclusionStatus.SUCCESS:
                data = {"status": "SUCCESS"}
                sent = True
                break
            elif status == MempoolInclusionStatus.PENDING:
                assert err is not None
                data = {"status": "PENDING", "reason": err}
                sent = True
                break
            elif status == MempoolInclusionStatus.FAILED:
                assert err is not None
                data = {"status": "FAILED", "reason": err}
                sent = True
                break
        if not sent:
            data = {
                "status": "FAILED",
                "reason": "Timed out. Transaction may or may not have been sent.",
            }

        return await websocket.send(format_response(response_api, data))

    async def cc_get_new_innerpuzzlehash(self, websocket, request, response_api):

        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        innerpuz: str = await wallet.get_new_inner_hash()
        response = {"innerpuz": innerpuz.hex()}
        return await websocket.send(format_response(response_api, response))

    async def cc_get_colour(self, websocket, request, response_api):
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        colour: str = await wallet.get_colour()
        response = {
            "colour": colour,
            "wallet_id": wallet_id}
        return await websocket.send(format_response(response_api, response))

    async def create_offer_for_ids(self, websocket, request, response_api):
        # request["ids"] = {1: 100, 2: -50, 4: 20}
        spend_bundle = None
        try:
            for id in request["ids"].keys():
                amount = request["ids"][id]
                wallet_id = int(id)
                wallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
                if isinstance(wallet, CCWallet):
                    new_spend_bundle = await wallet.create_spend_bundle_relative_amount(amount)
                elif isinstance(wallet, Wallet):
                    new_spend_bundle = await wallet.create_spend_bundle_relative_chia(
                        amount
                    )
                if spend_bundle is None:
                    spend_bundle = new_spend_bundle
                else:
                    spend_bundle = SpendBundle.aggregate([spend_bundle, new_spend_bundle])
            f = open(request["filename"], "w")
            f.write(bytes(spend_bundle).hex())
            f.close()
            response = {"success": True}
        except Exception:
            response = {"success": False}
        return await websocket.send(format_response(response_api, response))

    async def get_discrepancies_for_offer(self, websocket, request, response_api):
        cc_discrepancies = dict()
        wallets = dict()
        f = open(request["filename"], "r")
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
                    ] = await self.wallet_node.wallet_state_manager.get_wallet_for_colour(
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
        response = {"discrepancies": cc_discrepancies}
        return await websocket.send(format_response(response_api, response))

    async def respond_to_offer(self, websocket, request, response_api):
        f = open(request["filename"], "r")
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
                        ] = await self.wallet_node.wallet_state_manager.get_wallet_for_colour(
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
            chia_spend_bundle = await self.wallet_node.wallet_state_manager.main_wallet.create_spend_bundle_relative_chia(
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
                    innersol = self.wallet_node.wallet_state_manager.main_wallet.make_solution(
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
            innersol = self.wallet_node.wallet_state_manager.main_wallet.make_solution(
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

        await self.wallet_node.wallet_state_manager.add_pending_transaction(
            spend_bundle,
            self.wallet_node.wallet_state_manager.main_wallet.wallet_info.id,
        )
        return

    async def safe_handle(self, websocket, path):
        try:
            await self.handle_message(websocket, path)
        except (BaseException, websockets.exceptions.ConnectionClosedError) as e:
            if isinstance(e, websockets.exceptions.ConnectionClosedError):
                tb = traceback.format_exc()
                self.log.warning(f"ConnectionClosedError. Closing websocket. {tb}")
                await websocket.close()
            else:
                tb = traceback.format_exc()
                self.log.error(f"Error while handling message: {tb}")

    async def handle_message(self, websocket, path):
        """
        This function gets called when new message is received via websocket.
        """

        async for message in websocket:
            decoded = json.loads(message)
            command = decoded["command"]
            data = None
            if "data" in decoded:
                data = decoded["data"]
            if command == "start_server":
                self.websocket = websocket
                await self.server_ready(websocket, command)
            elif command == "get_wallet_balance":
                await self.get_wallet_balance(websocket, data, command)
            elif command == "send_transaction":
                await self.send_transaction(websocket, data, command)
            elif command == "get_next_puzzle_hash":
                await self.get_next_puzzle_hash(websocket, data, command)
            elif command == "get_transactions":
                await self.get_transactions(websocket, data, command)
            elif command == "farm_block":
                await self.farm_block(websocket, data, command)
            elif command == "get_sync_status":
                await self.get_sync_status(websocket, command)
            elif command == "get_height_info":
                await self.get_height_info(websocket, command)
            elif command == "get_connection_info":
                await self.get_connection_info(websocket, command)
            elif command == "create_new_wallet":
                await self.create_new_wallet(websocket, data, command)
            elif command == "get_wallets":
                await self.get_wallets(websocket, command)
            elif command == "rl_set_admin_info":
                await self.rl_set_admin_info(websocket, data, command)
            elif command == "rl_set_user_info":
                await self.rl_set_user_info(websocket, data, command)
            elif command == "cc_set_name":
                await self.cc_set_name(websocket, data, command)
            elif command == "cc_get_name":
                await self.cc_get_name(websocket, data, command)
            elif command == "cc_generate_zero_val":
                await self.cc_generate_zero_val(websocket, data, command)
            elif command == "cc_spend":
                await self.cc_spend(websocket, data, command)
            elif command == "cc_get_innerpuzzlehash":
                await self.cc_get_new_innerpuzzlehash(websocket, data, command)
            elif command == "cc_get_colour":
                await self.cc_get_colour(websocket, data, command)
            elif command == "create_offer":
                await self.create_offer_for_colours(websocket, data, command)
            elif command == "create_offer_for_ids":
                await self.create_offer_for_ids(websocket, data, command)
            elif command == "get_discrepancies_for_offer":
                await self.get_discrepancies_for_offer(websocket, data, command)
            elif command == "respond_to_offer":
                await self.respond_to_offer(websocket, data, command)
            else:
                response = {"error": f"unknown_command {command}"}
                await websocket.send(dict_to_json_str(response))

    async def notify_ui_that_state_changed(self, state: str):
        data = {
            "state": state,
        }
        if self.websocket is not None:
            try:
                await self.websocket.send(format_response("state_changed", data))
            except (BaseException, websockets.exceptions.ConnectionClosedError) as e:
                try:
                    self.log.warning(f"Caught exception {type(e)}, closing websocket")
                    await self.websocket.close()
                except BrokenPipeError:
                    pass
                finally:
                    self.websocket = None

    def state_changed_callback(self, state: str):
        if self.websocket is None:
            return
        asyncio.create_task(self.notify_ui_that_state_changed(state))


async def start_websocket_server():
    """
    Starts WalletNode, WebSocketServer, and ChiaServer
    """

    root_path = DEFAULT_ROOT_PATH

    config = load_config_cli(root_path, "config.yaml", "wallet")
    initialize_logging("Wallet %(name)-25s", config["logging"], root_path)
    log = logging.getLogger(__name__)

    try:
        key_config = load_config(DEFAULT_ROOT_PATH, "keys.yaml")
    except FileNotFoundError:
        raise RuntimeError("Keys not generated. Run `chia generate keys`")
    if config["testing"] is True:
        log.info(f"Testing")
        config["database_path"] = "test_db_wallet.db"
        wallet_node = await WalletNode.create(
            config, key_config, override_constants=test_constants
        )
    else:
        log.info(f"Not Testing")
        wallet_node = await WalletNode.create(config, key_config)
    setproctitle("chia-wallet")
    handler = WebSocketServer(wallet_node, log)
    wallet_node.wallet_state_manager.set_callback(handler.state_changed_callback)

    net_config = load_config(root_path, "config.yaml")
    ping_interval = net_config.get("ping_interval")
    network_id = net_config.get("network_id")
    assert ping_interval is not None
    assert network_id is not None

    log.info(f"Starting wallet server on port {config['port']}.")
    server = ChiaServer(
        config["port"], wallet_node, NodeType.WALLET, ping_interval, network_id, DEFAULT_ROOT_PATH, config
    )
    wallet_node.set_server(server)

    if "full_node_peer" in config:
        full_node_peer = PeerInfo(
            config["full_node_peer"]["host"], config["full_node_peer"]["port"]
        )

        log.info(f"Connecting to full node peer at {full_node_peer}")
        server.global_connections.peers.add(full_node_peer)
        _ = await server.start_client(full_node_peer, None)

    log.info("Starting websocket server.")
    websocket_server = await websockets.serve(
        handler.safe_handle, "localhost", config["rpc_port"]
    )
    log.info(f"Started websocket server at port {config['rpc_port']}.")

    def master_close_cb():
        websocket_server.close()
        server.close_all()
        wallet_node._shutdown()

    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, master_close_cb)
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, master_close_cb)
    except NotImplementedError:
        log.info("signal handlers unsupported")

    if config["testing"] is False:
        wallet_node._start_bg_tasks()

    await server.await_closed()
    await websocket_server.wait_closed()
    await wallet_node.wallet_state_manager.close_all_stores()
    log.info("Wallet fully closed")


def main():
    if uvloop is not None:
        uvloop.install()
    asyncio.run(start_websocket_server())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        log = logging.getLogger(__name__)
        log.error(f"Error in wallet. {tb}")
        raise
