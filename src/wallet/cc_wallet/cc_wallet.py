import logging
import clvm
import json
from blspy import ExtendedPrivateKey
from dataclasses import dataclass
from secrets import token_bytes
from typing import Dict, Optional, List, Any, Set, Tuple
from clvm_tools import binutils
from src.server.server import ChiaServer
from clvm.EvalError import EvalError
from src.types.BLSSignature import BLSSignature, ZERO96
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.condition_opcodes import ConditionOpcode
from src.types.condition_var_pair import ConditionVarPair
from src.types.name_puzzle_condition import NPC
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.condition_tools import (
    conditions_dict_for_solution,
    conditions_by_opcode,
    conditions_for_solution,
    hash_key_pairs_for_conditions_dict,
)
from src.util.errors import Err
from src.util.ints import uint64, uint32
from src.util.streamable import streamable, Streamable
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.cc_wallet.cc_wallet_puzzles import (
    cc_make_solution,
    get_innerpuzzle_from_puzzle,
    cc_generate_eve_spend,
    create_spend_for_auditor,
    create_spend_for_ephemeral,
)
from src.wallet.util.json_util import dict_to_json_str
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet import Wallet
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo
from src.wallet.derivation_record import DerivationRecord
from src.wallet.cc_wallet import cc_wallet_puzzles


# TODO: write tests based on wallet tests
# TODO: {Matt} compatibility based on deriving innerpuzzle from derivation record
# TODO: {Matt} convert this into wallet_state_manager.puzzle_store
# TODO: {Matt} add hooks in WebSocketServer for all UI functions


@dataclass(frozen=True)
@streamable
class CCParent(Streamable):
    parent_name: bytes32
    inner_puzzle_hash: Optional[bytes32]
    amount: uint64


@dataclass(frozen=True)
@streamable
class CCInfo(Streamable):
    my_core: Optional[str]  # core is stored as the disassembled string
    parent_info: List[Tuple[bytes32, CCParent]]  # {coin.name(): CCParent}
    my_colour_name: Optional[str]


class CCWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    cc_coin_record: WalletCoinRecord
    cc_info: CCInfo
    standard_wallet: Wallet

    @staticmethod
    async def create_new_cc(
        wallet_state_manager: Any, wallet: Wallet, amount: uint64, name: str = None,
    ):
        self = CCWallet()
        self.standard_wallet = wallet
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.cc_info = CCInfo(None, [], None)
        info_as_string = json.dumps(self.cc_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "CC Wallet", WalletType.COLOURED_COIN, info_as_string
        )
        if self.wallet_info is None:
            raise

        spend_bundle = await self.generate_new_coloured_coin(amount)
        if spend_bundle is None:
            raise

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
        await self.standard_wallet.push_transaction(spend_bundle)

        return self

    @staticmethod
    async def create_wallet_for_cc(
        wallet_state_manager: Any, wallet: Wallet, colour: str, name: str = None
    ):

        self = CCWallet()
        self.standard_wallet = wallet
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.cc_info = CCInfo(cc_wallet_puzzles.cc_make_core(colour), [], colour)
        info_as_string = json.dumps(self.cc_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "CC Wallet", WalletType.COLOURED_COIN, info_as_string
        )
        if self.wallet_info is None:
            raise

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
        return self

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: str = None,
    ):
        self = CCWallet()

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.standard_wallet = wallet
        self.cc_info = CCInfo.from_json_dict(json.loads(wallet_info.data))
        return self

    async def get_confirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_confirmed_balance_for_wallet(
            self.wallet_info.id
        )

    async def get_unconfirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_unconfirmed_balance(
            self.wallet_info.id
        )

    async def get_name(self):
        return self.cc_info.my_colour_name

    async def set_name(self, new_name: str):
        cc_info: CCInfo = CCInfo(
            self.cc_info.my_core, self.cc_info.parent_info, new_name,
        )
        await self.save_info(cc_info)

    async def get_colour(self):
        colour = cc_wallet_puzzles.get_genesis_from_core(self.cc_info.my_core)
        return colour

    async def coin_added(self, coin: Coin, height: int, header_hash: bytes32, removals: List[Coin]):
        """ Notification from wallet state manager that wallet has been received. """
        self.log.info(f"CC wallet has been notified that coin was added")

        search_for_parent: bool = True

        inner_puzzle = await self.inner_puzzle_for_cc_puzzle(coin.puzzle_hash)
        future_parent = CCParent(
            coin.parent_coin_info, inner_puzzle.get_hash(), coin.amount
        )
        self.log.info(f"Adding parent {coin.name()}: {future_parent}")
        await self.add_parent(coin.name(), future_parent)

        for name, ccparent in self.cc_info.parent_info:
            if coin.parent_coin_info == name:
                search_for_parent = False
                break
        # breakpoint()

        if search_for_parent:
            for removed in removals:
                if removed.name() == coin.parent_coin_info:
                    parent = CCParent(
                        removed.parent_coin_info, None, removed.amount
                    )
                    await self.add_parent(coin.parent_coin_info, parent)

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
                name="cc_get_generator",
                wallet_id=self.wallet_info.id,
                type=self.wallet_info.type,
                callback="str",
                done=False,
                data=data_str,
            )

    async def get_parent_info(
        self, block_program: Program,
    ) -> Tuple[Optional[Err], List[NPC], uint64]:

        """
        Returns an error if it's unable to evaluate, otherwise
        returns a list of NPC (coin_name, solved_puzzle_hash, conditions_dict)
        """
        cost_sum = 0
        self.log.info(f"Searching for parent info in block program: {block_program   }")
        breakpoint()
        try:
            cost_run, sexp = run_program(block_program, [])
            cost_sum += cost_run
        except EvalError:
            return Err.INVALID_COIN_SOLUTION, [], uint64(0)

        npc_list = []
        for name_solution in sexp.as_iter():
            _ = name_solution.as_python()
            if len(_) != 2:
                return Err.INVALID_COIN_SOLUTION, [], uint64(cost_sum)
            if not isinstance(_[0], bytes) or len(_[0]) != 32:
                return Err.INVALID_COIN_SOLUTION, [], uint64(cost_sum)
            coin_name = bytes32(_[0])
            if not isinstance(_[1], list) or len(_[1]) != 2:
                return Err.INVALID_COIN_SOLUTION, [], uint64(cost_sum)
            puzzle_solution_program = name_solution.rest().first()
            puzzle_program = puzzle_solution_program.first()
            puzzle_hash = Program(puzzle_program).get_hash()
            try:
                error, conditions_dict, cost_run = conditions_dict_for_solution(
                    puzzle_solution_program
                )
                cost_sum += cost_run
                if error:
                    return error, [], uint64(cost_sum)
            except clvm.EvalError:
                return Err.INVALID_COIN_SOLUTION, [], uint64(cost_sum)
            if conditions_dict is None:
                conditions_dict = {}
            npc: NPC = NPC(coin_name, puzzle_hash, conditions_dict)

            created_output_conditions = conditions_dict[ConditionOpcode.CREATE_COIN]
            for cvp in created_output_conditions:
                info = await self.wallet_state_manager.puzzle_store.wallet_info_for_puzzle_hash(
                    cvp.var1
                )
                if info is None:
                    continue
                puzstring = binutils.disassemble(puzzle_program)
                innerpuzzle = get_innerpuzzle_from_puzzle(puzstring)
                await self.add_parent(
                    coin_name, CCParent(coin.parent_coin_info, innerpuzzle, coin.amount)
                )

            npc_list.append(npc)

        return None, npc_list, uint64(cost_sum)

    async def generator_received(self, generator: Program, action_id: int):
        """ Notification that wallet has received a generator it asked for. """
        self.log.info(f"Generator received: {generator}")
        await self.get_parent_info(generator)
        await self.wallet_state_manager.set_action_done(action_id)

    async def get_new_inner_hash(self) -> bytes32:
        return await self.standard_wallet.get_new_puzzlehash()

    def puzzle_for_pk(self, pubkey) -> Program:
        inner_puzzle_hash = self.standard_wallet.puzzle_for_pk(bytes(pubkey)).get_hash()
        cc_puzzle: Program = cc_wallet_puzzles.cc_make_puzzle(
            inner_puzzle_hash, self.cc_info.my_core
        )
        return cc_puzzle

    async def get_new_cc_puzzle_hash(self):
        return (
            await self.wallet_state_manager.get_unused_derivation_record(
                self.wallet_info.id
            )
        ).puzzle_hash

    # Create a new coin of value 0 with a given colour
    async def generate_zero_val_coin(self) -> Optional[SpendBundle]:
        if self.cc_info.my_core is None:
            return
        coins = await self.standard_wallet.select_coins(1)
        if coins is None:
            return None

        origin = coins.copy().pop()
        origin_id = origin.name()

        parent_info = {}
        parent_info[origin_id] = (
            origin.parent_coin_info,
            origin.puzzle_hash,
            origin.amount,
        )

        cc_inner = await self.get_new_inner_hash()
        cc_puzzle = cc_wallet_puzzles.cc_make_puzzle(cc_inner, self.cc_info.my_core)
        cc_puzzle_hash = cc_puzzle.get_hash()

        spend_bundle = await self.standard_wallet.generate_signed_transaction(
            0, cc_puzzle_hash, uint64(0), origin_id, coins
        )
        self.log.warning(f"cc_puzzle_hash is {cc_puzzle_hash}")
        eve_coin = Coin(origin_id, cc_puzzle_hash, 0)
        if spend_bundle is None:
            return None

        eve_spend = cc_generate_eve_spend(eve_coin, cc_puzzle)
        full_spend = SpendBundle.aggregate([spend_bundle, eve_spend])
        await self.standard_wallet.push_transaction(full_spend)
        return full_spend

    async def select_coins(self, amount: uint64) -> Optional[Set[Coin]]:
        """ Returns a set of coins that can be used for generating a new transaction. """
        async with self.wallet_state_manager.lock:
            spendable_am = await self.wallet_state_manager.get_unconfirmed_spendable_for_wallet(
                self.wallet_info.id
            )

            if amount > spendable_am:
                self.log.warning(
                    f"Can't select amount higher than our spendable balance {amount}, spendable {spendable_am}"
                )
                return None

            self.log.info(f"About to select coins for amount {amount}")
            unspent: List[WalletCoinRecord] = list(
                await self.wallet_state_manager.get_spendable_coins_for_wallet(
                    self.wallet_info.id
                )
            )
            sum = 0
            used_coins: Set = set()

            # Use older coins first
            unspent.sort(key=lambda r: r.confirmed_block_index)

            # Try to use coins from the store, if there isn't enough of "unused"
            # coins use change coins that are not confirmed yet
            unconfirmed_removals: Dict[
                bytes32, Coin
            ] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
                self.wallet_info.id
            )
            for coinrecord in unspent:
                if sum >= amount:
                    break
                if coinrecord.coin.name() in unconfirmed_removals:
                    continue
                sum += coinrecord.coin.amount
                used_coins.add(coinrecord.coin)
                self.log.info(
                    f"Selected coin: {coinrecord.coin.name()} at height {coinrecord.confirmed_block_index}!"
                )

            # This happens when we couldn't use one of the coins because it's already used
            # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
            if sum < amount:
                raise ValueError(
                    "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
                )

            self.log.info(f"Successfully selected coins: {used_coins}")
            return used_coins

    async def get_sigs(self, innerpuz: Program, innersol: Program):
        puzzle_hash = innerpuz.get_hash()
        pubkey, private = await self.wallet_state_manager.get_keys(puzzle_hash)
        private = BLSPrivateKey(private)
        sigs = []
        code_ = [innerpuz, innersol]
        sexp = Program.to(code_)
        error, conditions, cost = conditions_dict_for_solution(sexp)
        for _ in hash_key_pairs_for_conditions_dict(conditions):
            signature = private.sign(_.message_hash)
            sigs.append(signature)
        return sigs

    async def inner_puzzle_for_cc_puzzle(self, cc_hash: bytes32) -> Program:
        record: DerivationRecord = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
            cc_hash.hex()
        )
        inner_puzzle: Program = self.standard_wallet.puzzle_for_pk(bytes(record.pubkey))
        return inner_puzzle

    async def cc_spend(
        self, amount: uint64, to_address: bytes32
    ) -> Optional[SpendBundle]:
        sigs = []

        # Get coins and calculate amount of change required
        selected_coins: Optional[List[Coin]] = await self.select_coins(amount)
        if selected_coins is None:
            return None

        total_amount = sum([x.amount for x in selected_coins])
        change = total_amount - amount

        # first coin becomes the auditor special case
        auditor = selected_coins.pop()
        puzzle_hash = auditor.puzzle_hash
        inner_puzzle: Program = await self.inner_puzzle_for_cc_puzzle(puzzle_hash)

        auditor_info = (
            auditor.parent_coin_info,
            inner_puzzle.get_hash(),
            auditor.amount,
        )
        list_of_solutions = []

        # auditees should be (primary_input, innerpuzhash, coin_amount, output_amount)
        auditees = [
            (
                auditor.parent_coin_info,
                inner_puzzle.get_hash(),
                auditor.amount,
                total_amount,
            )
        ]
        for coin in selected_coins:
            coin_inner_puzzle: Program = await self.inner_puzzle_for_cc_puzzle(
                coin.puzzle_hash
            )
            auditees.append(
                (coin.parent_coin_info, coin_inner_puzzle[coin], coin.amount, 0,)
            )

        primaries = [{"puzzlehash": to_address, "amount": amount}]
        if change > 0:
            changepuzzlehash = await self.get_new_inner_hash()
            primaries.append({"puzzlehash": changepuzzlehash, "amount": change})

        innersol = self.standard_wallet.make_solution(primaries=primaries)
        sigs = sigs + await self.get_sigs(inner_puzzle, innersol)
        parent_info = None

        for name, ccparent in self.cc_info.parent_info:
            if name == auditor.parent_coin_info:
                parent_info = ccparent

        assert parent_info is not None
        assert parent_info.inner_puzzle_hash is not None

        solution = cc_wallet_puzzles.cc_make_solution(
            self.cc_info.my_core,
            (
                parent_info.parent_name,
                parent_info.inner_puzzle_hash,
                parent_info.amount,
            ),
            auditor.amount,
            binutils.disassemble(inner_puzzle),
            binutils.disassemble(innersol),
            auditor_info,
            auditees,
        )

        main_coin_solution = CoinSolution(
            auditor,
            clvm.to_sexp_f(
                [
                    cc_wallet_puzzles.cc_make_puzzle(
                        inner_puzzle.get_hash(), self.cc_info.my_core,
                    ),
                    solution,
                ]
            ),
        )
        list_of_solutions.append(main_coin_solution)
        # main = SpendBundle([main_coin_solution], ZERO96)

        ephemeral_coin_solution = create_spend_for_ephemeral(
            auditor, auditor, total_amount
        )
        list_of_solutions.append(ephemeral_coin_solution)
        # eph = SpendBundle([ephemeral_coin_solution], ZERO96)

        auditor_coin_colution = create_spend_for_auditor(auditor, auditor)
        list_of_solutions.append(auditor_coin_colution)
        # aud = SpendBundle([auditor_coin_colution], ZERO96)

        # loop through remaining spends, treating them as aggregatees
        for coin in selected_coins:
            coin_inner_puzzle: Program = await self.inner_puzzle_for_cc_puzzle(
                coin.puzzle_hash
            )
            innersol = self.standard_wallet.make_solution()
            parent_info = None
            for name, ccparent in self.cc_info.parent_info:
                if name == auditor.parent_coin_info:
                    parent_info = ccparent
            assert parent_info is not None
            sigs = sigs + await self.get_sigs(coin_inner_puzzle, innersol)

            solution = cc_wallet_puzzles.cc_make_solution(
                self.cc_info.my_core,
                (
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ),
                coin.amount,
                binutils.disassemble(coin_inner_puzzle),
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
                                coin_inner_puzzle.get_hash(), self.cc_info.my_core,
                            ),
                            solution,
                        ]
                    ),
                )
            )
            list_of_solutions.append(create_spend_for_ephemeral(coin, auditor, 0))
            list_of_solutions.append(create_spend_for_auditor(auditor, coin))

        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)
        await self.standard_wallet.push_transaction(spend_bundle)

        return spend_bundle

    async def add_parent(self, name: bytes32, parent: CCParent):
        current_list: List[Tuple[bytes32, CCParent]] = self.cc_info.parent_info.copy()
        current_list.append((name, parent))
        cc_info: CCInfo = CCInfo(
            self.cc_info.my_core, current_list, self.cc_info.my_colour_name,
        )
        await self.save_info(cc_info)

    async def save_info(self, cc_info: CCInfo):
        self.cc_info = cc_info
        current_info = self.wallet_info
        data_str = dict_to_json_str(cc_info.to_json_dict())
        wallet_info = WalletInfo(
            current_info.id, current_info.name, current_info.type, data_str
        )
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info)

    async def generate_new_coloured_coin(self, amount: uint64) -> Optional[SpendBundle]:

        coins = await self.standard_wallet.select_coins(amount)
        if coins is None:
            return None

        origin = coins.copy().pop()
        origin_id = origin.name()

        cc_core = cc_wallet_puzzles.cc_make_core(origin_id)
        parent_info = {}
        parent_info[origin_id] = (
            origin.parent_coin_info,
            origin.puzzle_hash,
            origin.amount,
        )

        cc_info: CCInfo = CCInfo(cc_core, [], origin_id.hex())
        await self.save_info(cc_info)

        cc_inner = await self.get_new_inner_hash()
        cc_puzzle = cc_wallet_puzzles.cc_make_puzzle(cc_inner, cc_core)
        cc_puzzle_hash = cc_puzzle.get_hash()

        spend_bundle = await self.standard_wallet.generate_signed_transaction(
            amount, cc_puzzle_hash, uint64(0), origin_id, coins
        )
        self.log.warning(f"cc_puzzle_hash is {cc_puzzle_hash}")
        eve_coin = Coin(origin_id, cc_puzzle_hash, amount)
        if spend_bundle is None:
            return None

        eve_spend = cc_generate_eve_spend(eve_coin, cc_puzzle)

        full_spend = SpendBundle.aggregate([spend_bundle, eve_spend])
        return full_spend
