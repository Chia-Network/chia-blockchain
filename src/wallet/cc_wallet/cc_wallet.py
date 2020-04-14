import logging
import clvm
import json
from blspy import ExtendedPrivateKey
from dataclasses import dataclass
from secrets import token_bytes
from typing import Dict, Optional, List, Any, Set, Tuple
from clvm_tools import binutils
from src.server.server import ChiaServer
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.condition_opcodes import ConditionOpcode
from src.types.name_puzzle_condition import NPC
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.condition_tools import conditions_dict_for_solution
from src.util.errors import Err
from src.util.ints import uint64, uint32
from src.util.streamable import streamable, Streamable
from src.wallet.cc_wallet.cc_wallet_puzzles import cc_make_solution
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
    inner_puzzle_hash: bytes32
    amount: uint64


@dataclass(frozen=True)
@streamable
class CCInfo(Streamable):
    my_core: Optional[str]  # core is stored as the disassembled string
    my_coloured_coins: Optional[Dict]  #  {coin: innerpuzzle as Program}
    parent_info: Optional[Dict[bytes32, CCParent]]  # {coin.name(): CCParent}
    my_colour_name: Optional[str]


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

        self.cc_info = CCInfo(None, dict(), dict(), dict(), dict(), None, [], dict())
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
        self.update_derivation_todos()

    def get_genesis_from_puzzle(self, puzzle):
        return puzzle[-2687:].split(")")[0]

    def get_genesis_from_core(self, core):
        return core[-2678:].split(")")[0]

    def get_innerpuzzle_from_puzzle(self, puzzle):
        return puzzle[9:75]

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
            response = await self.wallet_state_manager.create_action(
                self,
                name="cc_get_generator",
                wallet_id=self.wallet_info.id,
                type=self.wallet_info.type,
                callback="str",
                done=False,
                data=data_str,
            )
        # TODO: actually fetch parent information

    def get_parent_info(self,
            block_program: Program,
    ) -> Tuple[Optional[Err], List[NPC], uint64]:

        """
        Returns an error if it's unable to evaluate, otherwise
        returns a list of NPC (coin_name, solved_puzzle_hash, conditions_dict)
        """
        cost_sum = 0
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
                info = await self.wallet_state_manager.puzzle_store.wallet_info_for_puzzle_hash(cvp.var1)
                if info is None:
                    continue
                puzstring = binutils.disassemble(puzzle_program)
                innerpuzzle = self.get_innerpuzzle_from_puzzle(puzstring)
                await self.add_parent(coin_name, CCParent(coin.parent_coin_info, innerpuzzle, coin.amount))

            npc_list.append(npc)

        return None, npc_list, uint64(cost_sum)

    async def generator_received(self, generator: Program, action_id: int):
        """ Notification that wallet has received a generator it asked for. """
        result = await self.get_parent_info(generator)
        await self.wallet_state_manager.set_action_done(action_id)

    # Note, if you do this before you have a colour assigned you will need to add the colour
    async def get_new_innerpuzhash(self):
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

            return innerpuzzlehash

    async def update_derivation_todos(self):
        for index in self.cc_info.derivation_todos:
            pk = self.standard_wallet.get_public_key(index)
            innerpuzzlehash = self.standard_wallet.puzzle_for_pk(bytes(pk)).get_hash()
            cc_puzzle = cc_wallet_puzzles.cc_make_puzzle(
                innerpuzzlehash, self.cc_info.my_core
            )
            new_inner_puzzle_record = DerivationRecord(index, innerpuzzlehash.get_hash(), pk, WalletType.COLORED_COIN, self.wallet_info.id)
            new_record = DerivationRecord(index, cc_puzzle.get_hash(), pk, WalletType.COLORED_COIN, self.wallet_info.id)
            await self.wallet_state_manager.puzzle_store.add_derivation_paths([new_inner_puzzle_record, new_record])

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

    async def select_coins(self, amount: uint64) -> Optional[Set[Coin]]:

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
            unspents: List[WalletCoinRecord] = list(
                await self.wallet_state_manager.get_spendable_coins_for_wallet(
                    self.wallet_info.id
                )
            )
            sum = 0
            used_coins: Set = set()

            for unspent in unspents:
                used_coins.add(unspent.coin)
                sum += unspent.amount
                if sum > amount:
                    break

            self.log.info(f"used these coins: {used_coins}")

            return used_coins

    def cc_generate_spends_for_coin_list(self, amount: uint64, puzzle_hash: bytes32) -> Optional[SpendBundle]:

        selected_coins: Optional[List[Coin]] = await self.select_coins(amount)
        if selected_coins is None:
            return None


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

    # Create the spend bundle given a relative amount change (i.e -400 or 1000) and a colour
    def create_spend_bundle_relative_core(self, cc_amount):
        # Coloured Coin processing

        # If we're losing value then get coloured coins with at least that much value
        # If we're gaining value then our amount doesn't matter
        if cc_amount < 0:
            cc_spends = self.select_coins(abs(cc_amount))
        else:
            cc_spends = self.select_coins(1)
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
                newinnerpuzhash = self.get_new_innerpuzhash()
                innersol = self.make_solution(
                    primaries=[{"puzzlehash": newinnerpuzhash, "amount": cc_amount}]
                )
                output_created = coin
            else:
                innersol = self.make_solution(consumed=[output_created.name()])
            if coin in self.cc_info.my_coloured_coins:
                innerpuz = self.cc_info.my_coloured_coins[coin][0]
            # Use coin info to create solution and add coin and solution to list of CoinSolutions
            solution = self.cc_make_solution(
                self.cc_info.my_core,
                self.cc_info.parent_info[coin.parent_coin_info],
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
                        [cc_wallet_puzzles.cc_make_puzzle(innerpuz.get_hash(), self.my_core), solution]
                    ),
                )
            )
            sigs = sigs + self.get_sigs_for_innerpuz_with_innersol(innerpuz, innersol)

        aggsig = BLSSignature.aggregate(sigs)

        return SpendBundle(list_of_solutions, aggsig)

    async def add_parent(self, name: bytes32, parent: CCParent):
        current_dict = self.cc_info.parent_info.copy()
        current_dict[name] = parent
        cc_info: CCInfo = CCInfo(self.cc_info.my_core, self.cc_info.my_coloured_coins, current_dict, self.cc_info.my_colour_name)
        await self.save_info(cc_info)

    async def save_info(self, cc_info: CCInfo):
        self.cc_info = cc_info
        current_info = self.wallet_info
        data_str = json.dumps(cc_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        self.wallet_state_manager.user_store.update_wallet(wallet_info)

    async def generate_new_coloured_coin(
        self, amount: uint64
    ) -> bool:

        coins = await self.standard_wallet.select_coins(amount)
        if coins is None:
            return False

        origin = coins.copy().pop()
        origin_id = origin.name()

        cc_core = cc_wallet_puzzles.cc_make_core(origin_id)
        parent_info = {}
        parent_info[origin_id] = (origin.parent_coin_info, origin.puzzle_hash, origin.amount)

        cc_info: CCInfo = CCInfo(bytes(cc_core).hex(), None, None, origin_id.hex())
        await self.save_info(cc_info)

        cc_inner = self.get_new_innerpuzhash()
        cc_puzzle = cc_wallet_puzzles.cc_make_puzzle(cc_inner, cc_core)
        cc_puzzle_hash = cc_puzzle.get_hash()

        spend_bundle = await self.standard_wallet.generate_signed_transaction(
            amount, cc_puzzle_hash, uint64(0), origin_id, coins
        )

        eve_coin = Coin(origin_id, cc_puzzle_hash, amount)
        if spend_bundle is None:
            return False
        eve_spend = await self.cc_generate_eve_spend(eve_coin, origin_id, cc_puzzle)

        full_spend = SpendBundle.aggregate([spend_bundle, eve_spend])
        await self.standard_wallet.push_transaction(full_spend)

        return True

    async def cc_generate_eve_spend(self, coin: Coin, genesis_id: bytes32, full_puzzle: Program):
        list_of_solutions = []

        innersol = "()"
        solution = cc_make_solution(
            "()",
            genesis_id,
            coin.amount,
            f"0x{coin.puzzle_hash}",
            binutils.disassemble(innersol),
            None,
            None,
        )
        list_of_solutions.append(
            CoinSolution(coin, clvm.to_sexp_f([full_puzzle, solution,]),)
        )
        aggsig = BLSSignature.aggregate([])
        spend_bundle = SpendBundle(list_of_solutions, aggsig)
        return spend_bundle
