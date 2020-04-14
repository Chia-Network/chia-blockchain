import logging
import clvm
import json

from blspy import ExtendedPrivateKey
from dataclasses import dataclass
from secrets import token_bytes
from typing import Dict, Optional, List, Any, Set
from clvm_tools import binutils
from src.server.server import ChiaServer
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32
from src.util.streamable import streamable, Streamable
from src.wallet.util.json_util import dict_to_json_str
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet import Wallet
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo
from src.wallet.derivation_record import DerivationRecord
from src.wallet.cc_wallet import cc_wallet_puzzles


@dataclass(frozen=True)
@streamable
class CCInfo(Streamable):
    my_core: Optional[str]  # core is stored as the disassembled string
    my_coloured_coins: Optional[Dict]  #  {coin: innerpuzzle as Program}
    eve_coloured_coins: Optional[Dict]
    parent_info: Optional[
        Dict
    ]  # {coin.name(): (parent_coin_info, puzzle_hash, coin.amount)}
    puzzle_cache: Optional[Dict]  # {"innerpuz"+"core": puzzle}
    my_colour_name: Optional[str]

    # TODO: {Matt} compatibility based on deriving innerpuzzle from derivation record
    # TODO: {Matt} convert this into wallet_state_manager.puzzle_store
    # TODO: {Matt} add hooks in WebSocketServer for all UI functions
    my_cc_puzhashes: Optional[Dict]  # {cc_puzhash: (innerpuzzle, core)}


class CCWallet:
    config: Dict
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    cc_coin_record: WalletCoinRecord
    cc_info: CCInfo
    standard_wallet: Wallet

    @staticmethod
    async def create_new_cc(
        config: Dict, wallet_state_manager: Any, wallet: Wallet, name: str = None,
    ):
        self = CCWallet()
        self.config = config
        self.standard_wallet = wallet
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.cc_info = CCInfo(None, dict(), dict(), dict(), dict(), None, dict())
        info_as_string = json.dumps(self.cc_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "CC Wallet", WalletType.COLOURED_COIN, info_as_string
        )
        if self.wallet_info is None:
            raise

        return self

    @staticmethod
    async def create(
        config: Dict,
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: str = None,
    ):
        self = CCWallet()
        self.config = config
        self.key_config = key_config

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.standard_wallet = wallet
        self.cc_info = CCInfo.from_json_dict(json.loads(wallet_info.data))
        return self

    async def get_name(self):
        return self.cc_info.my_colour_name

    async def set_name(self, new_name: str):
        self.cc_info.my_colour_name = new_name

    async def set_core(self, core: str):
        self.cc_info.my_core = core

    async def coin_added(self, coin: Coin, height: int, header_hash: bytes32):
        """ Notification from wallet state manager that wallet has been received. """
        self.log.info(f"CC wallet has been notified that coin was added")

        search_for_parent = set()
        self.cc_info.my_coloured_coins[coin] = (
            self.cc_info.my_cc_puzhashes[coin.puzzle_hash][0],
        )

        self.cc_info.parent_info[coin.name()] = (
            coin.parent_coin_info,
            self.my_coloured_coins[coin].get_hash(),
            coin.amount,
        )
        if coin.parent_coin_info not in self.cc_info.parent_info:
            search_for_parent.add(coin)

        # TODO (MATT): Pass this info only for headers you want generator for
        if len(search_for_parent) >= 1:
            data: Dict[str, Any] = {
                "data": {
                    "action_data": {
                        "api_name": "request_generator",
                        "height": height,
                        "header_hash": header_hash,
                    }
                }
            }

            data_str = dict_to_json_str(data)
            await self.wallet_state_manager.create_action(
                self,
                name="cc_get_generator",
                wallet_id=self.wallet_info.id,
                type=self.wallet_info.type,
                callback="str",
                done=False,
                data=data_str,
            )

    async def generator_received(self, generator: Program, action_id: int):
        """ Notification that wallet has received a generator it asked for. """

        await self.wallet_state_manager.set_action_done(action_id)

    async def get_new_ccpuzzlehash(self):
        async with self.wallet_state_manager.puzzle_store.lock:
            max = await self.wallet_state_manager.puzzle_store.get_last_derivation_path()
            max_pk = self.standard_wallet.get_public_key(max)
            innerpuzzlehash = self.standard_wallet.puzzle_for_pk(bytes(max_pk)).get_hash()

            cc_puzzle = cc_wallet_puzzles.cc_make_puzzle(
                innerpuzzlehash, self.cc_info.my_core
            )
            new_inner_puzzle_record = DerivationRecord(max, innerpuzzlehash.get_hash(), max_pk, WalletType.COLORED_COIN, self.wallet_info.id)
            new_record = DerivationRecord(max, cc_puzzle.get_hash(), max_pk, WalletType.COLORED_COIN, self.wallet_info.id)
            await self.wallet_state_manager.puzzle_store.add_derivation_paths([new_inner_puzzle_record, new_record])

    # Create a new coin of value 0 with a given colour
    async def cc_create_zero_val_for_core(self, core):
        innerpuz = self.wallet.get_new_puzzle()
        newpuzzle = cc_wallet_puzzles.cc_make_puzzle(innerpuz.get_hash(), core)
        self.cc_info.my_cc_puzhashes[newpuzzle.get_hash()] = (innerpuz, core)
        coin = self.wallet.select_coins(1).pop()
        primaries = [{"puzzlehash": newpuzzle.get_hash(), "amount": 0}]
        # put all of coin's actual value into a new coin
        changepuzzlehash = self.wallet.get_new_puzzlehash()
        primaries.append({"puzzlehash": changepuzzlehash, "amount": coin.amount})

        # add change coin into temp_utxo set
        self.cc_info.temp_utxos.add(Coin(coin, changepuzzlehash, coin.amount))
        solution = self.wallet.make_solution(primaries=primaries)
        pubkey, secretkey = self.wallet.get_keys(coin.puzzle_hash)
        puzzle = self.wallet.puzzle_for_pk(pubkey)
        spend_bundle = self.sign_transaction([(puzzle, CoinSolution(coin, solution))])

        # Eve spend so that the coin is automatically ready to be spent
        coin = Coin(coin, newpuzzle.get_hash(), 0)
        solution = cc_wallet_puzzles.cc_make_solution(
            core,
            coin.parent_coin_info,
            coin.amount,
            binutils.disassemble(innerpuz),
            "((q ()) ())",
            None,
            None,
        )
        eve_spend = SpendBundle(
            [CoinSolution(coin, clvm.to_sexp_f([newpuzzle, solution]))],
            BLSSignature.aggregate([]),
        )
        spend_bundle = spend_bundle.aggregate([spend_bundle, eve_spend])
        self.cc_info.parent_info[coin.name()] = (
            coin.parent_coin_info,
            coin.puzzle_hash,
            coin.amount,
        )
        self.cc_info.eve_coloured_coins[Coin(coin, coin.puzzle_hash, 0)] = (
            innerpuz,
            core,
        )
        return spend_bundle

    # Given a list of coloured coins, their parent_info, outputamount, and innersol, create spends
    def cc_generate_spends_for_coin_list(self, spendslist, sigs=[]):
        # spendslist is [] of (coin, parent_info, outputamount, innersol)
        auditor = spendslist[0][0]
        core = self.cc_info.my_core
        auditor_info = (
            auditor.parent_coin_info,
            self.cc_info.my_coloured_coins[auditor].get_hash(),
            auditor.amount,
        )
        list_of_solutions = []

        # first coin becomes the auditor special case
        spend = spendslist[0]
        coin = spend[0]
        innerpuz = binutils.disassemble(self.cc_info.my_coloured_coins[coin])
        innersol = spend[3]
        parent_info = spend[1]
        solution = cc_wallet_puzzles.cc_make_solution(
            core,
            parent_info,
            coin.amount,
            innerpuz,
            binutils.disassemble(innersol),
            auditor_info,
            spendslist,
        )
        list_of_solutions.append(
            CoinSolution(
                coin,
                clvm.to_sexp_f(
                    [
                        cc_wallet_puzzles.cc_make_puzzle(
                            self.cc_info.my_coloured_coins[coin].get_hash(), core
                        ),
                        solution,
                    ]
                ),
            )
        )
        list_of_solutions.append(
            self.create_spend_for_ephemeral(coin, auditor, spend[2])
        )
        list_of_solutions.append(self.create_spend_for_auditor(auditor, coin))

        # loop through remaining spends, treating them as aggregatees
        for spend in spendslist[1:]:
            coin = spend[0]
            innerpuz = binutils.disassemble(self.cc_info.my_coloured_coins[coin])
            innersol = spend[3]
            parent_info = spend[1]
            solution = cc_wallet_puzzles.cc_make_solution(
                core,
                parent_info,
                coin.amount,
                innerpuz,
                binutils.disassemble(innersol),
                auditor_info,
                None,
            )
            list_of_solutions.append(
                CoinSolution(
                    coin,
                    clvm.to_sexp_f(
                        [
                            cc_wallet_puzzles.cc_make_puzzle(
                                self.cc_info.my_coloured_coins[coin].get_hash(), core
                            ),
                            solution,
                        ]
                    ),
                )
            )
            list_of_solutions.append(
                self.create_spend_for_ephemeral(coin, auditor, spend[2])
            )
            list_of_solutions.append(self.create_spend_for_auditor(auditor, coin))

        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)
        return spend_bundle

    # Make sure that a generated E lock is spent in the spendbundle
    def create_spend_for_ephemeral(self, parent_of_e, auditor_coin, spend_amount):
        puzstring = (
            f"(r (r (c (q 0x{auditor_coin.name()}) (c (q {spend_amount}) (q ())))))"
        )
        puzzle = Program(binutils.assemble(puzstring))
        coin = Coin(parent_of_e, puzzle.get_hash(), 0)
        solution = Program(binutils.assemble("()"))
        coinsol = CoinSolution(coin, clvm.to_sexp_f([puzzle, solution]))
        return coinsol

    # Make sure that a generated A lock is spent in the spendbundle
    def create_spend_for_auditor(self, parent_of_a, auditee):
        puzstring = f"(r (c (q 0x{auditee.name()}) (q ())))"
        puzzle = Program(binutils.assemble(puzstring))
        coin = Coin(parent_of_a, puzzle.get_hash(), 0)
        solution = Program(binutils.assemble("()"))
        coinsol = CoinSolution(coin, clvm.to_sexp_f([puzzle, solution]))
        return coinsol
