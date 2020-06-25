import logging
import time

import clvm
from typing import Dict, Optional, List, Any, Set
from clvm_tools import binutils
from clvm.EvalError import EvalError
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.byte_types import hexstr_to_bytes
from src.util.condition_tools import (
    conditions_dict_for_solution,
    hash_key_pairs_for_conditions_dict,
)
from src.util.json_util import dict_to_json_str
from src.util.ints import uint64, uint32
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.block_record import BlockRecord
from src.wallet.did_wallet.did_info import DIDInfo
from src.wallet.cc_wallet.ccparent import CCParent
from src.wallet.transaction_record import TransactionRecord
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet import Wallet
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo
from src.wallet.derivation_record import DerivationRecord
from src.wallet.did_wallet import did_puzzle
from clvm import run_program


class DIDWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    did_info: DIDInfo
    standard_wallet: Wallet
    base_puzzle_program: Optional[bytes]
    base_inner_puzzle_hash: Optional[bytes32]

    @staticmethod
    async def create_new_did_wallet(
        wallet_state_manager: Any, wallet: Wallet, amount: int, backups_ids: List = [], name: str = None,
    ):
        self = DIDWallet()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.did_info = DIDInfo(backups_ids)
        info_as_string = bytes(self.did_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "DID Wallet", WalletType.DISTRIBUTED_ID, info_as_string
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)

        return self

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: str = None,
    ):
        self = DIDWallet()

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.standard_wallet = wallet
        self.did_info = DIDInfo.from_bytes(hexstr_to_bytes(self.wallet_info.data))
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        return self

    async def coin_added(
        self, coin: Coin, height: int, header_hash: bytes32, removals: List[Coin]
    ):
        """ Notification from wallet state manager that wallet has been received. """
        self.log.info("CC wallet has been notified that coin was added")

        search_for_parent: bool = True

        inner_puzzle = await self.inner_puzzle_for_cc_puzzle(coin.puzzle_hash)
        future_parent = CCParent(
            coin.parent_coin_info, inner_puzzle.get_tree_hash(), coin.amount
        )

        await self.add_parent(coin.name(), future_parent)

        for name, ccparent in self.cc_info.parent_info:
            if coin.parent_coin_info == name:
                search_for_parent = False
                break
        # breakpoint()

        if search_for_parent:
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
                name="request_generator",
                wallet_id=self.wallet_info.id,
                type=self.wallet_info.type,
                callback="generator_received",
                done=False,
                data=data_str,
            )

    async def search_for_parent_info(
        self, block_program: Program, removals: List[Coin]
    ) -> bool:

        """
        Returns an error if it's unable to evaluate, otherwise
        returns a list of NPC (coin_name, solved_puzzle_hash, conditions_dict)
        """
        cost_sum = 0
        try:
            cost_run, sexp = run_program(block_program, [])
            cost_sum += cost_run
        except EvalError:
            return False

        for name_solution in sexp.as_iter():
            _ = name_solution.as_python()
            if len(_) != 2:
                return False
            if not isinstance(_[0], bytes) or len(_[0]) != 32:
                return False
            coin_name = bytes32(_[0])
            if not isinstance(_[1], list) or len(_[1]) != 2:
                return False
            puzzle_solution_program = name_solution.rest().first()
            puzzle_program = puzzle_solution_program.first()
            try:
                error, conditions_dict, cost_run = conditions_dict_for_solution(
                    puzzle_solution_program
                )
                cost_sum += cost_run
                if error:
                    return False
            except clvm.EvalError:

                return False
            if conditions_dict is None:
                conditions_dict = {}

            if ConditionOpcode.CREATE_COIN in conditions_dict:
                created_output_conditions = conditions_dict[ConditionOpcode.CREATE_COIN]
            else:
                continue
            for cvp in created_output_conditions:
                result = await self.wallet_state_manager.puzzle_store.wallet_info_for_puzzle_hash(
                    cvp.var1
                )
                if result is None:
                    continue

                wallet_id, wallet_type = result
                if wallet_id != self.wallet_info.id:
                    continue

                coin = None
                for removed in removals:
                    if removed.name() == coin_name:
                        coin = removed
                        break

                if coin is not None:
                    if cc_wallet_puzzles.check_is_cc_puzzle(puzzle_program):
                        puzzle_string = binutils.disassemble(puzzle_program)
                        inner_puzzle_hash = hexstr_to_bytes(
                            get_innerpuzzle_from_puzzle(puzzle_string)
                        )
                        self.log.info(
                            f"parent: {coin_name} inner_puzzle for parent is {inner_puzzle_hash.hex()}"
                        )

                        await self.add_parent(
                            coin_name,
                            CCParent(
                                coin.parent_coin_info, inner_puzzle_hash, coin.amount
                            ),
                        )

                return True

        return False

    async def generator_received(
        self, height: uint32, header_hash: bytes32, generator: Program, action_id: int
    ):
        """ Notification that wallet has received a generator it asked for. """
        block: Optional[
            BlockRecord
        ] = await self.wallet_state_manager.wallet_store.get_block_record(header_hash)
        assert block is not None
        if block.removals is not None:
            parent_found = await self.search_for_parent_info(generator, block.removals)
            if parent_found:
                await self.wallet_state_manager.set_action_done(action_id)

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        innerpuzzle = did_puzzle.create_innerpuz(pubkey, self.did_info.backup_ids)
        core = did_puzzle.create_core()
        return did_puzzle.create_fullpuz(innerpuzzle, core)

    async def get_new_puzzle(self) -> Program:
        return self.puzzle_for_pk(
            bytes(
                self.wallet_state_manager.get_unused_derivation_record(
                    self.wallet_info.id
                ).pubkey
            )
        )

    async def create_spend(self, puzhash, amount):

        return

    async def create_attestment(self):

        return

    async def recovery_spend(self, puzhash, amount):

        return

    async def get_new_inner_hash(self) -> bytes32:

        return did_puzzle.get_new_puzzlehash(
            bytes(
                self.wallet_state_manager.get_unused_derivation_record(
                    self.wallet_info.id
                ).pubkey
            )
        )

    async def inner_puzzle_for_did_puzzle(self, did_hash: bytes32) -> Program:
        record: DerivationRecord = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
            did_hash.hex()
        )
        inner_puzzle: Program = did_puzzle.get_new_puzzlehash(bytes(record.pubkey))
        return inner_puzzle

    async def generate_new_coloured_coin(self, amount: uint64) -> Optional[SpendBundle]:

        coins = await self.standard_wallet.select_coins(amount)
        if coins is None:
            return None

        origin = coins.copy().pop()
        origin_id = origin.name()
        # self.add_parent(origin_id, origin_id)
        did_core = did_puzzle.create_core(origin_id)
        parent_info = {}
        parent_info[origin_id] = (
            origin.parent_coin_info,
            origin.puzzle_hash,
            origin.amount,
        )

        did_info: DIDInfo = DIDInfo(did_core, self.did_info.backup_ids, parent_info)
        await self.save_info(did_info)

        did_inner = await self.get_new_inner_hash()
        did_puz = did_puzzle.create_fullpuz(did_inner, did_core)
        did_puzzle_hash = did_puz.get_tree_hash()

        tx_record: Optional[
            TransactionRecord
        ] = await self.standard_wallet.generate_signed_transaction(
            amount, did_puzzle_hash, uint64(0), origin_id, coins
        )
        self.log.warning(f"did_puzzle_hash is {did_puzzle_hash}")
        eve_coin = Coin(origin_id, did_puzzle_hash, amount)
        if tx_record is None or tx_record.spend_bundle is None:
            return None

        eve_spend = self.generate_eve_spend(eve_coin, did_puzzle, origin_id, did_inner)

        full_spend = SpendBundle.aggregate([tx_record.spend_bundle, eve_spend])
        return full_spend

    def generate_eve_spend(coin: Coin, full_puzzle: Program, origin_id: bytes, innerpuz: Program):
        # innerpuz solution is (mode amount new_innerpuz identity my_puz)
        innersol = f"(0 {coin.amount} 0x{full_puzzle} 0x{coin.name()} )"
        # core solution is (corehash parent_info my_amount puzzle_reveal solution)
        solution = did_puzzle.make_eve_solution(
            coin.parent_coin_info, coin.puzzle_hash, coin.amount
        )
        list_of_solutions = [CoinSolution(coin, clvm.to_sexp_f([full_puzzle, solution]),)]
        aggsig = BLSSignature.aggregate([])
        spend_bundle = SpendBundle(list_of_solutions, aggsig)
        return spend_bundle
