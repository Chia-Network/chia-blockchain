import logging
import string

import clvm
from typing import Dict, Optional, List, Any, Set
from clvm_tools import binutils
from clvm.EvalError import EvalError
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program, SExp
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.byte_types import hexstr_to_bytes
from src.util.condition_tools import (
    conditions_dict_for_solution,
    hash_key_pairs_for_conditions_dict,
)
from src.util.ints import uint64, uint32
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.block_record import BlockRecord
from src.wallet.cc_wallet.cc_info import CCInfo
from src.wallet.cc_wallet.cc_wallet_puzzles import (
    get_innerpuzzle_from_puzzle,
    cc_generate_eve_spend,
    create_spend_for_auditor,
    create_spend_for_ephemeral,
    cc_make_puzzle,
    get_genesis_from_puzzle,
    cc_make_core,
)
from src.wallet.cc_wallet.ccparent import CCParent
from src.wallet.util.json_util import dict_to_json_str
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet import Wallet
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo
from src.wallet.derivation_record import DerivationRecord
from src.wallet.cc_wallet import cc_wallet_puzzles
from clvm import run_program

# TODO: write tests based on wallet tests
# TODO: {Matt} compatibility based on deriving innerpuzzle from derivation record
# TODO: {Matt} convert this into wallet_state_manager.puzzle_store
# TODO: {Matt} add hooks in WebSocketServer for all UI functions


class CCWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    cc_coin_record: WalletCoinRecord
    cc_info: CCInfo
    standard_wallet: Wallet
    base_puzzle_program: Optional[Program]
    base_inner_puzzle_hash: Optional[bytes32]
    sexp_cache: Optional[Dict[str, SExp]]

    @staticmethod
    async def create_new_cc(
        wallet_state_manager: Any, wallet: Wallet, amount: uint64, name: str = None,
    ):
        self = CCWallet()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.sexp_cache = None
        self.standard_wallet = wallet
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.cc_info = CCInfo(None, [], None)
        info_as_string = bytes(self.cc_info).hex()
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
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.sexp_cache = None
        self.standard_wallet = wallet
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.cc_info = CCInfo(cc_wallet_puzzles.cc_make_core(colour), [], colour)
        info_as_string = bytes(self.cc_info).hex()
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
        self.cc_info = CCInfo.from_bytes(hexstr_to_bytes(self.wallet_info.data))
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.sexp_cache = None
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

    async def coin_added(
        self, coin: Coin, height: int, header_hash: bytes32, removals: List[Coin]
    ):
        """ Notification from wallet state manager that wallet has been received. """
        self.log.info(f"CC wallet has been notified that coin was added")

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
                            CCParent(coin.parent_coin_info, inner_puzzle_hash, coin.amount),
                        )

                return True

        return False

    async def generator_received(
        self, height: uint32, header_hash: bytes32, generator: Program, action_id: int
    ):
        """ Notification that wallet has received a generator it asked for. """
        block: BlockRecord = await self.wallet_state_manager.wallet_store.get_block_record(
            header_hash
        )
        if block.removals is not None:
            parent_found = await self.search_for_parent_info(generator, block.removals)
            if parent_found:
                await self.wallet_state_manager.set_action_done(action_id)

    async def get_new_inner_hash(self) -> bytes32:
        return await self.standard_wallet.get_new_puzzlehash()

    def do_replace(self, sexp, magic, magic_replacement):
        """ Generic way to replace anything inside a SEXP, not used currentyl """
        if sexp.listp():
            return self.do_replace(sexp.first(), magic, magic_replacement).cons(
                self.do_replace(sexp.rest(), magic, magic_replacement)
            )
        if sexp.as_atom() == magic:
            return sexp.to(magic_replacement)
        return sexp

    def specific_replace(self, sexp, magic, magic_replacement):
        """binutil.assemble is slow, using this hack to swap inner_puzzle_hash. """
        if self.sexp_cache is None:
            self.sexp_cache = {}
            n1 = sexp.first()
            n2 = sexp.rest().rest()
            n3 = sexp.rest().first().first()
            n4 = sexp.rest().first().rest().first().first()
            sexp_to_replace = sexp.rest().first().rest().first().rest().first()
            n5 = sexp.rest().first().rest().first().rest().rest()
            n6 = sexp.rest().first().rest().rest()
            self.sexp_cache["n1"] = n1
            self.sexp_cache["n2"] = n2
            self.sexp_cache["n3"] = n3
            self.sexp_cache["n4"] = n4
            self.sexp_cache["sexp_to_replace"] = sexp_to_replace
            self.sexp_cache["n5"] = n5
            self.sexp_cache["n6"] = n6
        else:
            n1 = self.sexp_cache["n1"]
            n2 = self.sexp_cache["n2"]
            n3 = self.sexp_cache["n3"]
            n4 = self.sexp_cache["n4"]
            sexp_to_replace = self.sexp_cache["sexp_to_replace"]
            n5 = self.sexp_cache["n5"]
            n6 = self.sexp_cache["n6"]

        replaced = sexp_to_replace.to(magic_replacement)

        step0 = replaced.cons(n5)
        step1 = n4.cons(step0)
        step2 = step1.cons(n6)
        step3 = n3.cons(step2)
        step5 = step3.cons(n2)
        result = n1.cons(step5)

        return result

    def fast_cc_puzzle(self, inner_puzzle_hash) -> Program:
        new_sexp = self.specific_replace(
            self.base_puzzle_program, self.base_inner_puzzle_hash, inner_puzzle_hash
        )
        program = Program(new_sexp)
        return program

    def puzzle_for_pk(self, pubkey) -> Program:
        inner_puzzle_hash = self.standard_wallet.puzzle_for_pk(
            bytes(pubkey)
        ).get_tree_hash()
        if self.base_puzzle_program is None:
            cc_puzzle: Program = cc_wallet_puzzles.cc_make_puzzle(
                inner_puzzle_hash, self.cc_info.my_core
            )
            self.base_puzzle_program = cc_puzzle
            self.base_inner_puzzle_hash = inner_puzzle_hash
        else:
            cc_puzzle = self.fast_cc_puzzle(inner_puzzle_hash)
        return cc_puzzle

    async def get_new_cc_puzzle_hash(self):
        return (
            await self.wallet_state_manager.get_unused_derivation_record(
                self.wallet_info.id
            )
        ).puzzle_hash

    # Create a new coin of value 0 with a given colour
    async def generate_zero_val_coin(self, send = True, exclude: List[Coin] = None) -> Optional[SpendBundle]:
        if self.cc_info.my_core is None:
            return None
        if exclude is None:
            exclude = []
        coins = await self.standard_wallet.select_coins(1, exclude)
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
        cc_puzzle_hash = cc_puzzle.get_tree_hash()

        spend_bundle = await self.standard_wallet.generate_signed_transaction(
            uint64(0), cc_puzzle_hash, uint64(0), origin_id, coins
        )
        self.log.warning(f"cc_puzzle_hash is {cc_puzzle_hash}")
        eve_coin = Coin(origin_id, cc_puzzle_hash, uint64(0))
        if spend_bundle is None:
            return None

        eve_spend = cc_generate_eve_spend(eve_coin, cc_puzzle)
        full_spend = SpendBundle.aggregate([spend_bundle, eve_spend])

        future_parent = CCParent(
            eve_coin.parent_coin_info, cc_inner, eve_coin.amount
        )
        eve_parent = CCParent(
            origin.parent_coin_info, origin.puzzle_hash, origin.amount
        )

        await self.add_parent(eve_coin.name(), future_parent)
        await self.add_parent(eve_coin.parent_coin_info, eve_parent)

        if send:
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

    async def get_sigs(self, innerpuz: Program, innersol: Program) -> List[BLSSignature]:
        puzzle_hash = innerpuz.get_tree_hash()
        pubkey, private = await self.wallet_state_manager.get_keys(puzzle_hash)
        private = BLSPrivateKey(private)
        sigs: List[BLSSignature] = []
        code_ = [innerpuz, innersol]
        sexp = Program.to(code_)
        error, conditions, cost = conditions_dict_for_solution(sexp)
        if conditions is not None:
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

    async def get_parent_for_coin(self, coin) -> Optional[CCParent]:
        parent_info = None
        for name, ccparent in self.cc_info.parent_info:
            if name == coin.parent_coin_info:
                parent_info = ccparent

        return parent_info

    async def cc_spend(
        self, amount: uint64, to_address: bytes32
    ) -> Optional[SpendBundle]:
        sigs: List[BLSSignature] = []

        # Get coins and calculate amount of change required
        selected_coins: Optional[Set[Coin]] = await self.select_coins(amount)
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
            inner_puzzle.get_tree_hash(),
            auditor.amount,
        )
        list_of_solutions = []

        # auditees should be (primary_input, innerpuzhash, coin_amount, output_amount)
        auditees = [
            (
                auditor.parent_coin_info,
                inner_puzzle.get_tree_hash(),
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
        parent_info = await self.get_parent_for_coin(auditor)
        assert parent_info is not None
        assert self.cc_info.my_core is not None

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
            False,
        )

        main_coin_solution = CoinSolution(
            auditor,
            clvm.to_sexp_f(
                [
                    cc_wallet_puzzles.cc_make_puzzle(
                        inner_puzzle.get_tree_hash(), self.cc_info.my_core,
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
            coin_inner_puzzle = await self.inner_puzzle_for_cc_puzzle(
                coin.puzzle_hash
            )
            innersol = self.standard_wallet.make_solution()
            parent_info = await self.get_parent_for_coin(coin)
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
                                coin_inner_puzzle.get_tree_hash(), self.cc_info.my_core,
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

        await self.wallet_state_manager.add_pending_transaction(
            spend_bundle, self.wallet_info.id
        )

        return spend_bundle

    async def add_parent(self, name: bytes32, parent: Optional[CCParent]):
        self.log.info(f"Adding parent {name}: {parent}")
        current_list = self.cc_info.parent_info.copy()
        current_list.append((name, parent))
        cc_info: CCInfo = CCInfo(
            self.cc_info.my_core, current_list, self.cc_info.my_colour_name,
        )
        await self.save_info(cc_info)

    async def save_info(self, cc_info: CCInfo):
        self.cc_info = cc_info
        current_info = self.wallet_info
        data_str = bytes(cc_info).hex()
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
        # self.add_parent(origin_id, origin_id)
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
        cc_puzzle_hash = cc_puzzle.get_tree_hash()

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

    async def create_spend_bundle_relative_amount(self, cc_amount):
        # If we're losing value then get coloured coins with at least that much value
        # If we're gaining value then our amount doesn't matter
        if cc_amount < 0:
            cc_spends = await self.select_coins(abs(cc_amount))
        else:
            cc_spends = await self.select_coins(1)
        if cc_spends is None:
            return None

        # Calculate output amount given relative difference and sum of actual values
        spend_value = sum([coin.amount for coin in cc_spends])
        cc_amount = spend_value + cc_amount

        # Loop through coins and create solution for innerpuzzle
        list_of_solutions = []
        output_created = None
        sigs = []
        for coin in cc_spends:
            if output_created is None:
                newinnerpuzhash = await self.get_new_inner_hash()
                innersol = self.standard_wallet.make_solution(
                    primaries=[{"puzzlehash": newinnerpuzhash, "amount": cc_amount}]
                )
                output_created = coin
            else:
                innersol = self.standard_wallet.make_solution()
            innerpuz: Program = await self.inner_puzzle_for_cc_puzzle(coin.puzzle_hash)

            parent_info = await self.get_parent_for_coin(coin)
            assert parent_info is not None

            # Use coin info to create solution and add coin and solution to list of CoinSolutions
            solution = cc_wallet_puzzles.cc_make_solution(
                self.cc_info.my_core,
                (
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ),
                coin.amount,
                binutils.disassemble(innerpuz),
                binutils.disassemble(innersol),
                None,
                None,
            )
            list_of_solutions.append(
                CoinSolution(
                    coin,
                    clvm.to_sexp_f(
                        [
                            cc_wallet_puzzles.cc_make_puzzle(
                                innerpuz.get_tree_hash(), self.cc_info.my_core
                            ),
                            solution,
                        ]
                    ),
                )
            )
            sigs = sigs + await self.get_sigs(innerpuz, innersol)

        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)
        return spend_bundle

    # Create an offer spend bundle for chia given an amount of relative change (i.e -400 or 1000)
    # This is to be aggregated together with a coloured coin offer to ensure that the trade happens
    async def create_spend_bundle_relative_chia(self, chia_amount: uint64):
        self.log.error("Not implemented")
        # TODO MATT: Implement
