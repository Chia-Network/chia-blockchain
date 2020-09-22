from __future__ import annotations
import logging
import time

from typing import Dict, Optional, List, Any, Set
from blspy import G2Element, AugSchemeMPL
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.byte_types import hexstr_to_bytes
from src.util.condition_tools import (
    conditions_dict_for_solution,
    pkm_pairs_for_conditions_dict,
)
from src.util.json_util import dict_to_json_str
from src.util.ints import uint64, uint32
from src.wallet.block_record import BlockRecord
from src.wallet.cc_wallet.cc_info import CCInfo
from src.wallet.transaction_record import TransactionRecord
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet import Wallet
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo
from src.wallet.derivation_record import DerivationRecord
from src.wallet.cc_wallet.cc_utils import (
    SpendableCC,
    cc_puzzle_hash_for_inner_puzzle_hash,
    cc_puzzle_for_inner_puzzle,
    spend_bundle_for_spendable_ccs,
    get_lineage_proof_from_coin_and_puz,
    uncurry_cc,
    CC_MOD,
)
from src.wallet.puzzles.genesis_by_coin_id_with_0 import (
    create_genesis_or_zero_coin_checker,
    lineage_proof_for_genesis,
    genesis_coin_id_for_genesis_coin_checker,
)
from dataclasses import replace


class CCWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    cc_coin_record: WalletCoinRecord
    cc_info: CCInfo
    standard_wallet: Wallet
    base_puzzle_program: Optional[bytes]
    base_inner_puzzle_hash: Optional[bytes32]

    @staticmethod
    async def create_new_cc(
        wallet_state_manager: Any,
        wallet: Wallet,
        amount: uint64,
        name: str = None,
    ):
        self = CCWallet()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.cc_info = CCInfo(None, [])
        info_as_string = bytes(self.cc_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "CC Wallet", WalletType.COLOURED_COIN.value, info_as_string
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")

        try:
            spend_bundle = await self.generate_new_coloured_coin(amount)
        except Exception:
            await wallet_state_manager.user_store.delete_wallet(self.wallet_info.id)
            raise

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)

        # Change and actual coloured coin
        non_ephemeral_spends: List[Coin] = spend_bundle.not_ephemeral_additions()
        cc_coin = None
        puzzle_store = self.wallet_state_manager.puzzle_store

        for c in non_ephemeral_spends:
            info = await puzzle_store.wallet_info_for_puzzle_hash(c.puzzle_hash)
            if info is None:
                raise ValueError("Internal Error")
            id, wallet_type = info
            if id == self.wallet_info.id:
                cc_coin = c

        if cc_coin is None:
            raise ValueError("Internal Error, unable to generate new coloured coin")

        regular_record = TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=cc_coin.puzzle_hash,
            amount=uint64(cc_coin.amount),
            fee_amount=uint64(0),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_state_manager.main_wallet.wallet_info.id,
            sent_to=[],
            trade_id=None,
        )
        cc_record = TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=cc_coin.puzzle_hash,
            amount=uint64(cc_coin.amount),
            fee_amount=uint64(0),
            incoming=True,
            confirmed=False,
            sent=uint32(10),
            spend_bundle=None,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
        )
        await self.standard_wallet.push_transaction(regular_record)
        await self.standard_wallet.push_transaction(cc_record)
        return self

    @staticmethod
    async def create_wallet_for_cc(
        wallet_state_manager: Any,
        wallet: Wallet,
        genesis_checker_hex: str,
        name: str = None,
    ) -> CCWallet:

        self = CCWallet()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.cc_info = CCInfo(
            Program.from_bytes(bytes.fromhex(genesis_checker_hex)), []
        )
        info_as_string = bytes(self.cc_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "CC Wallet", WalletType.COLOURED_COIN.value, info_as_string
        )
        if self.wallet_info is None:
            raise Exception("wallet_info is None")

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
        return self

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: str = None,
    ) -> CCWallet:
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
        return self

    async def get_confirmed_balance(self) -> uint64:
        record_list: Set[
            WalletCoinRecord
        ] = await self.wallet_state_manager.wallet_store.get_unspent_coins_for_wallet(
            self.wallet_info.id
        )

        amount: uint64 = uint64(0)
        for record in record_list:
            lineage = await self.get_lineage_proof_for_coin(record.coin)
            if lineage is not None:
                amount = uint64(amount + record.coin.amount)

        self.log.info(
            f"Confirmed balance for cc wallet {self.wallet_info.id} is {amount}"
        )
        return uint64(amount)

    async def get_unconfirmed_balance(self) -> uint64:
        confirmed = await self.get_confirmed_balance()
        unconfirmed_tx: List[
            TransactionRecord
        ] = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
            self.wallet_info.id
        )
        addition_amount = 0
        removal_amount = 0

        for record in unconfirmed_tx:
            if record.incoming:
                addition_amount += record.amount
            else:
                removal_amount += record.amount

        result = confirmed - removal_amount + addition_amount

        self.log.info(
            f"Unconfirmed balance for cc wallet {self.wallet_info.id} is {result}"
        )
        return uint64(result)

    async def get_name(self):
        return self.wallet_info.name

    async def set_name(self, new_name: str):
        new_info = replace(self.wallet_info, name=new_name)
        self.wallet_info = new_info
        await self.wallet_state_manager.user_store.update_wallet(self.wallet_info)

    def get_colour(self) -> str:
        assert self.cc_info.my_genesis_checker is not None
        return bytes(self.cc_info.my_genesis_checker).hex()

    async def coin_added(
        self, coin: Coin, height: int, header_hash: bytes32, removals: List[Coin]
    ):
        """ Notification from wallet state manager that wallet has been received. """
        self.log.info(f"CC wallet has been notified that {coin} was added")

        search_for_parent: bool = True

        inner_puzzle = await self.inner_puzzle_for_cc_puzhash(coin.puzzle_hash)
        lineage_proof = Program.to(
            (1, [coin.parent_coin_info, inner_puzzle.get_tree_hash(), coin.amount])
        )
        await self.add_lineage(coin.name(), lineage_proof)

        for name, lineage_proofs in self.cc_info.lineage_proofs:
            if coin.parent_coin_info == name:
                search_for_parent = False
                break

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
            cost_run, sexp = block_program.run_with_cost([])
            cost_sum += cost_run
        except Program.EvalError:
            return False

        parents = []

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
            except Program.EvalError:

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
                    r = uncurry_cc(puzzle_program)
                    if r is not None:
                        mod_hash, genesis_coin_checker, inner_puzzle = r
                        self.log.info(
                            f"parent: {coin_name} inner_puzzle for parent is {inner_puzzle}"
                        )
                        lineage_proof = get_lineage_proof_from_coin_and_puz(
                            coin, puzzle_program
                        )
                        parents.append(lineage_proof)
                        await self.add_lineage(coin_name, lineage_proof)

        return len(parents) > 0

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
            self.log.info(f"search_for_parent_info returned {parent_found}")
            if parent_found:
                await self.wallet_state_manager.set_action_done(action_id)

    async def get_new_inner_hash(self) -> bytes32:
        return await self.standard_wallet.get_new_puzzlehash()

    async def get_new_inner_puzzle(self) -> Program:
        return await self.standard_wallet.get_new_puzzle()

    async def get_new_puzzlehash(self) -> bytes32:
        return await self.standard_wallet.get_new_puzzlehash()

    def puzzle_for_pk(self, pubkey) -> Program:
        inner_puzzle = self.standard_wallet.puzzle_for_pk(bytes(pubkey))
        cc_puzzle: Program = cc_puzzle_for_inner_puzzle(
            CC_MOD, self.cc_info.my_genesis_checker, inner_puzzle
        )
        self.base_puzzle_program = bytes(cc_puzzle)
        self.base_inner_puzzle_hash = inner_puzzle.get_tree_hash()
        return cc_puzzle

    async def get_new_cc_puzzle_hash(self):
        return (
            await self.wallet_state_manager.get_unused_derivation_record(
                self.wallet_info.id
            )
        ).puzzle_hash

    # Create a new coin of value 0 with a given colour
    async def generate_zero_val_coin(
        self, send=True, exclude: List[Coin] = None
    ) -> SpendBundle:
        if self.cc_info.my_genesis_checker is None:
            raise ValueError("My genesis checker is None")
        if exclude is None:
            exclude = []
        coins = await self.standard_wallet.select_coins(0, exclude)

        assert coins != set()

        origin = coins.copy().pop()
        origin_id = origin.name()

        cc_inner = await self.get_new_inner_hash()
        cc_puzzle_hash: Program = cc_puzzle_hash_for_inner_puzzle_hash(
            CC_MOD, self.cc_info.my_genesis_checker, cc_inner
        )

        tx: TransactionRecord = await self.standard_wallet.generate_signed_transaction(
            uint64(0), cc_puzzle_hash, uint64(0), origin_id, coins
        )
        assert tx.spend_bundle is not None
        full_spend: SpendBundle = tx.spend_bundle
        self.log.info(f"Generate zero val coin: cc_puzzle_hash is {cc_puzzle_hash}")

        # generate eve coin so we can add future lineage_proofs even if we don't eve spend
        eve_coin = Coin(origin_id, cc_puzzle_hash, uint64(0))

        await self.add_lineage(
            eve_coin.name(),
            Program.to(
                (
                    1,
                    [eve_coin.parent_coin_info, cc_inner, eve_coin.amount],
                )
            ),
        )
        await self.add_lineage(
            eve_coin.parent_coin_info, Program.to((0, [origin.as_list(), 1]))
        )

        if send:
            regular_record = TransactionRecord(
                confirmed_at_index=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=cc_puzzle_hash,
                amount=uint64(0),
                fee_amount=uint64(0),
                incoming=False,
                confirmed=False,
                sent=uint32(10),
                spend_bundle=full_spend,
                additions=full_spend.additions(),
                removals=full_spend.removals(),
                wallet_id=uint32(1),
                sent_to=[],
                trade_id=None,
            )
            cc_record = TransactionRecord(
                confirmed_at_index=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=cc_puzzle_hash,
                amount=uint64(0),
                fee_amount=uint64(0),
                incoming=True,
                confirmed=False,
                sent=uint32(0),
                spend_bundle=full_spend,
                additions=full_spend.additions(),
                removals=full_spend.removals(),
                wallet_id=self.wallet_info.id,
                sent_to=[],
                trade_id=None,
            )
            await self.wallet_state_manager.add_transaction(regular_record)
            await self.wallet_state_manager.add_pending_transaction(cc_record)

        return full_spend

    async def get_spendable_balance(self) -> uint64:
        coins = await self.get_cc_spendable_coins()
        amount = 0
        for record in coins:
            amount += record.coin.amount

        return uint64(amount)

    async def get_pending_change_balance(self) -> uint64:
        unconfirmed_tx = (
            await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
                self.wallet_info.id
            )
        )
        addition_amount = 0

        for record in unconfirmed_tx:
            our_spend = False
            for coin in record.removals:
                # Don't count eve spend as change
                if coin.parent_coin_info.hex() == self.get_colour():
                    continue
                if await self.wallet_state_manager.does_coin_belong_to_wallet(
                    coin, self.wallet_info.id
                ):
                    our_spend = True
                    break

            if our_spend is not True:
                continue

            for coin in record.additions:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(
                    coin, self.wallet_info.id
                ):
                    addition_amount += coin.amount

        return uint64(addition_amount)

    async def get_cc_spendable_coins(self) -> List[WalletCoinRecord]:
        result: List[WalletCoinRecord] = []

        record_list: Set[
            WalletCoinRecord
        ] = await self.wallet_state_manager.get_spendable_coins_for_wallet(
            self.wallet_info.id
        )

        for record in record_list:
            lineage = await self.get_lineage_proof_for_coin(record.coin)
            if lineage is not None:
                result.append(record)

        return result

    async def select_coins(self, amount: uint64) -> Set[Coin]:
        """ Returns a set of coins that can be used for generating a new transaction. """
        async with self.wallet_state_manager.lock:
            spendable_am = await self.get_confirmed_balance()

            if amount > spendable_am:
                error_msg = f"Can't select amount higher than our spendable balance {amount}, spendable {spendable_am}"
                self.log.warning(error_msg)
                raise ValueError(error_msg)

            self.log.info(f"About to select coins for amount {amount}")
            spendable: List[WalletCoinRecord] = await self.get_cc_spendable_coins()

            sum = 0
            used_coins: Set = set()

            # Use older coins first
            spendable.sort(key=lambda r: r.confirmed_block_index)

            # Try to use coins from the store, if there isn't enough of "unused"
            # coins use change coins that are not confirmed yet
            unconfirmed_removals: Dict[
                bytes32, Coin
            ] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
                self.wallet_info.id
            )
            for coinrecord in spendable:
                if sum >= amount and len(used_coins) > 0:
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

    async def get_sigs(self, innerpuz: Program, innersol: Program) -> List[G2Element]:
        puzzle_hash = innerpuz.get_tree_hash()
        pubkey, private = await self.wallet_state_manager.get_keys(puzzle_hash)
        sigs: List[G2Element] = []
        code_ = [innerpuz, innersol]
        sexp = Program.to(code_)
        error, conditions, cost = conditions_dict_for_solution(sexp)
        if conditions is not None:
            for _, msg in pkm_pairs_for_conditions_dict(conditions):
                signature = AugSchemeMPL.sign(private, msg)
                sigs.append(signature)
        return sigs

    async def inner_puzzle_for_cc_puzhash(self, cc_hash: bytes32) -> Program:
        record: DerivationRecord = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
            cc_hash.hex()
        )
        inner_puzzle: Program = self.standard_wallet.puzzle_for_pk(bytes(record.pubkey))
        return inner_puzzle

    async def get_lineage_proof_for_coin(self, coin) -> Optional[Program]:
        for name, proof in self.cc_info.lineage_proofs:
            if name == coin.parent_coin_info:
                return proof
        return None

    async def generate_signed_transaction(
        self,
        amounts: List[uint64],
        puzzle_hashes: List[bytes32],
        fee: uint64 = uint64(0),
        origin_id: bytes32 = None,
        coins: Set[Coin] = None,
    ) -> TransactionRecord:
        sigs: List[G2Element] = []

        # Get coins and calculate amount of change required
        outgoing_amount = uint64(sum(amounts))

        if coins is None:
            selected_coins: Set[Coin] = await self.select_coins(
                uint64(outgoing_amount + fee)
            )
        else:
            selected_coins = coins

        total_amount = sum([x.amount for x in selected_coins])
        change = total_amount - outgoing_amount - fee
        primaries = []
        for amount, puzzle_hash in zip(amounts, puzzle_hashes):
            primaries.append({"puzzlehash": puzzle_hash, "amount": amount})

        if change > 0:
            changepuzzlehash = await self.get_new_inner_hash()
            primaries.append({"puzzlehash": changepuzzlehash, "amount": change})

        if fee > 0:
            innersol = self.standard_wallet.make_solution(primaries=primaries, fee=fee)
        else:
            innersol = self.standard_wallet.make_solution(primaries=primaries)

        coin = selected_coins.pop()
        inner_puzzle = await self.inner_puzzle_for_cc_puzhash(coin.puzzle_hash)

        if self.cc_info.my_genesis_checker is None:
            raise ValueError("My genesis checker is None")

        genesis_id = genesis_coin_id_for_genesis_coin_checker(
            self.cc_info.my_genesis_checker
        )
        innersol_list = [innersol]

        sigs = sigs + await self.get_sigs(inner_puzzle, innersol)
        lineage_proof = await self.get_lineage_proof_for_coin(coin)
        assert lineage_proof is not None
        spendable_cc_list = [SpendableCC(coin, genesis_id, inner_puzzle, lineage_proof)]
        assert self.cc_info.my_genesis_checker is not None

        for coin in selected_coins:
            coin_inner_puzzle = await self.inner_puzzle_for_cc_puzhash(coin.puzzle_hash)
            innersol = self.standard_wallet.make_solution()
            innersol_list.append(innersol)
            sigs = sigs + await self.get_sigs(coin_inner_puzzle, innersol)
        spend_bundle = spend_bundle_for_spendable_ccs(
            CC_MOD,
            self.cc_info.my_genesis_checker,
            spendable_cc_list,
            innersol_list,
            sigs,
        )
        # TODO add support for array in stored records
        return TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=puzzle_hashes[0],
            amount=uint64(outgoing_amount),
            fee_amount=uint64(0),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
        )

    async def add_lineage(self, name: bytes32, lineage: Optional[Program]):
        self.log.info(f"Adding parent {name}: {lineage}")
        current_list = self.cc_info.lineage_proofs.copy()
        current_list.append((name, lineage))
        cc_info: CCInfo = CCInfo(self.cc_info.my_genesis_checker, current_list)
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

    async def generate_new_coloured_coin(self, amount: uint64) -> SpendBundle:
        coins = await self.standard_wallet.select_coins(amount)

        origin = coins.copy().pop()
        origin_id = origin.name()

        cc_inner_hash = await self.get_new_inner_hash()
        await self.add_lineage(origin_id, Program.to((0, [origin.as_list(), 0])))
        genesis_coin_checker = create_genesis_or_zero_coin_checker(origin_id)

        minted_cc_puzzle_hash = cc_puzzle_hash_for_inner_puzzle_hash(
            CC_MOD, genesis_coin_checker, cc_inner_hash
        )

        tx_record: TransactionRecord = (
            await self.standard_wallet.generate_signed_transaction(
                amount, minted_cc_puzzle_hash, uint64(0), origin_id, coins
            )
        )
        assert tx_record.spend_bundle is not None

        lineage_proof: Optional[Program] = lineage_proof_for_genesis(origin)
        lineage_proofs = [(origin_id, lineage_proof)]
        cc_info: CCInfo = CCInfo(genesis_coin_checker, lineage_proofs)
        await self.save_info(cc_info)
        return tx_record.spend_bundle

    async def create_spend_bundle_relative_amount(
        self, cc_amount, zero_coin: Coin = None
    ) -> Optional[SpendBundle]:
        # If we're losing value then get coloured coins with at least that much value
        # If we're gaining value then our amount doesn't matter
        if cc_amount < 0:
            cc_spends = await self.select_coins(abs(cc_amount))
        else:
            if zero_coin is None:
                return None
            cc_spends = set()
            cc_spends.add(zero_coin)

        if cc_spends is None:
            return None

        # Calculate output amount given relative difference and sum of actual values
        spend_value = sum([coin.amount for coin in cc_spends])
        cc_amount = spend_value + cc_amount

        # Loop through coins and create solution for innerpuzzle
        list_of_solutions = []
        output_created = None
        sigs: List[G2Element] = []
        for coin in cc_spends:
            if output_created is None:
                newinnerpuzhash = await self.get_new_inner_hash()
                innersol = self.standard_wallet.make_solution(
                    primaries=[{"puzzlehash": newinnerpuzhash, "amount": cc_amount}]
                )
                output_created = coin
            else:
                innersol = self.standard_wallet.make_solution(
                    consumed=[output_created.name()]
                )
            innerpuz: Program = await self.inner_puzzle_for_cc_puzhash(coin.puzzle_hash)
            sigs = sigs + await self.get_sigs(innerpuz, innersol)
            lineage_proof = await self.get_lineage_proof_for_coin(coin)
            puzzle_reveal = cc_puzzle_for_inner_puzzle(
                CC_MOD, self.cc_info.my_genesis_checker, innerpuz
            )
            # Use coin info to create solution and add coin and solution to list of CoinSolutions
            solution = [
                innersol,
                coin.as_list(),
                lineage_proof,
                None,
                None,
                None,
                None,
                None,
            ]
            full_solution = Program.to([puzzle_reveal, solution])

            list_of_solutions.append(CoinSolution(coin, full_solution))

        aggsig = AugSchemeMPL.aggregate(sigs)
        return SpendBundle(list_of_solutions, aggsig)
