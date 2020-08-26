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
    conditions_dict_for_solution
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
from src.wallet.did_wallet import did_wallet_puzzles
from clvm import run_program
from src.util.hash import std_hash


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
        wallet_state_manager: Any,
        wallet: Wallet,
        amount: int,
        backups_ids: List = [],
        name: str = None,
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
        self.did_info = DIDInfo(None, backups_ids, [], None)
        info_as_string = bytes(self.did_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "DID Wallet", WalletType.DISTRIBUTED_ID, info_as_string
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")

        bal = await self.standard_wallet.get_confirmed_balance()
        if amount > bal:
            raise ValueError("Not enough balance")

        spend_bundle = await self.generate_new_decentralised_id(amount)
        if spend_bundle is None:
            raise ValueError("failed to generate ID for wallet")
        # Change and actual coloured coin
        non_ephemeral_spends: List[Coin] = spend_bundle.not_ephemeral_additions()
        did_coin = None
        for c in non_ephemeral_spends:
            did_coin = c
            break

        if did_coin is None:
            raise ValueError("Internal Error, unable to generate new coloured coin")

        regular_record = TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=did_coin.puzzle_hash,
            amount=uint64(did_coin.amount),
            fee_amount=uint64(0),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_state_manager.main_wallet.wallet_info.id,
            sent_to=[],
        )
        did_record = TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=did_coin.puzzle_hash,
            amount=uint64(did_coin.amount),
            fee_amount=uint64(0),
            incoming=True,
            confirmed=False,
            sent=uint32(10),
            spend_bundle=None,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
        )
        await self.standard_wallet.push_transaction(regular_record)
        await self.standard_wallet.push_transaction(did_record)

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

    async def get_confirmed_balance(self) -> uint64:
        record_list: Set[
            WalletCoinRecord
        ] = await self.wallet_state_manager.wallet_store.get_unspent_coins_for_wallet(
            self.wallet_info.id
        )

        amount: uint64 = uint64(0)
        for record in record_list:
            parent = await self.get_parent_for_coin(record.coin)
            if parent is not None:
                amount = uint64(amount + record.coin.amount)

        self.log.info(f"Confirmed balance for did wallet is {amount}")
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

        self.log.info(f"Unconfirmed balance for did wallet is {result}")
        return uint64(result)

    async def select_coins(
        self, amount, exclude: List[Coin] = None
    ) -> Optional[Set[Coin]]:
        """ Returns a set of coins that can be used for generating a new transaction. """
        async with self.wallet_state_manager.lock:
            if exclude is None:
                exclude = []

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
                if sum >= amount and len(used_coins) > 0:
                    break
                if coinrecord.coin.name() in unconfirmed_removals:
                    continue
                if coinrecord.coin in exclude:
                    continue
                sum += coinrecord.coin.amount
                used_coins.add(coinrecord.coin)
                self.log.info(
                    f"Selected coin: {coinrecord.coin.name()} at height {coinrecord.confirmed_block_index}!"
                )

            # This happens when we couldn't use one of the coins because it's already used
            # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
            unconfirmed_additions = None
            if sum < amount:
                raise ValueError(
                    "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
                )
                unconfirmed_additions = await self.wallet_state_manager.unconfirmed_additions_for_wallet(
                    self.wallet_info.id
                )
                for coin in unconfirmed_additions.values():
                    if sum > amount:
                        break
                    if coin.name() in unconfirmed_removals:
                        continue

                    sum += coin.amount
                    used_coins.add(coin)
                    self.log.info(f"Selected used coin: {coin.name()}")

        if sum >= amount:
            self.log.info(f"Successfully selected coins: {used_coins}")
            return used_coins
        else:
            # This shouldn't happen because of: if amount > self.get_unconfirmed_balance_spendable():
            self.log.error(
                f"Wasn't able to select coins for amount: {amount}"
                f"unspent: {unspent}"
                f"unconfirmed_removals: {unconfirmed_removals}"
                f"unconfirmed_additions: {unconfirmed_additions}"
            )
            return None

    # This will be used in the recovery case where we don't have the parent info already
    async def coin_added(
        self, coin: Coin, height: int, header_hash: bytes32, removals: List[Coin]
    ):
        """ Notification from wallet state manager that wallet has been received. """
        self.log.info("DID wallet has been notified that coin was added")

        search_for_parent: bool = True

        inner_puzzle = await self.inner_puzzle_for_did_puzzle(coin.puzzle_hash)
        future_parent = CCParent(
            coin.parent_coin_info,
            Program(binutils.assemble(inner_puzzle)).get_tree_hash(),
            coin.amount,
        )

        await self.add_parent(coin.name(), future_parent)

        for name, ccparent in self.did_info.parent_info:
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

    # This should basically never be called as we don't want to receive ID coins from somebody else
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
                    if did_wallet_puzzles.check_is_did_puzzle(puzzle_program):
                        puzzle_string = binutils.disassemble(puzzle_program)
                        inner_puzzle_hash = hexstr_to_bytes(
                            did_wallet_puzzles.get_innerpuzzle_from_puzzle(
                                puzzle_string
                            )
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
        innerpuzhash = Program(
            binutils.assemble(
                did_wallet_puzzles.create_innerpuz(pubkey, self.did_info.backup_ids)
            )
        ).get_tree_hash()
        core = self.did_info.my_core
        return Program(
            binutils.assemble(did_wallet_puzzles.create_fullpuz(innerpuzhash, core))
        )

    async def get_new_puzzle(self) -> Program:
        return self.puzzle_for_pk(
            bytes(
                await self.wallet_state_manager.get_unused_derivation_record(
                    self.wallet_info.id
                ).pubkey
            )
        )

    def get_my_ID(self):
        ret = did_wallet_puzzles.get_genesis_from_puzzle(self.did_info.my_core)
        return ret

    # This is used to cash out, or update the id_list
    async def create_spend(self, puzhash):
        coins = await self.select_coins(1)
        coin = coins.pop()
        # innerpuz solution is (mode amount new_puz identity my_puz)
        innersol = f"(0 {coin.amount} 0x{puzhash} 0x{coin.name()} 0x{coin.puzzle_hash})"
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz_str = self.did_info.current_inner
        full_puzzle: str = did_wallet_puzzles.create_fullpuz(
            Program(binutils.assemble(innerpuz_str)).get_tree_hash(),
            self.did_info.my_core,
        )
        parent_info = await self.get_parent_for_coin(coin)

        fullsol = f"(0x{Program(binutils.assemble(self.did_info.my_core)).get_tree_hash()} (0x{parent_info.parent_name} 0x{parent_info.inner_puzzle_hash} {parent_info.amount}) {coin.amount} {innerpuz_str} {innersol})"
        #breakpoint()
        list_of_solutions = [
            CoinSolution(
                coin,
                clvm.to_sexp_f(
                    [
                        Program(binutils.assemble(full_puzzle)),
                        Program(binutils.assemble(fullsol)),
                    ]
                ),
            )
        ]
        # sign for AGG_SIG_ME
        message = std_hash(bytes(puzhash) + bytes(coin.name()))
        pubkey = did_wallet_puzzles.get_pubkey_from_innerpuz(innerpuz_str)
        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
        private = self.wallet_state_manager.private_key.private_child(
            index
        ).get_private_key()
        pk = BLSPrivateKey(private)
        signature = pk.sign(message)
        assert signature.validate([signature.PkMessagePair(pubkey, message)])
        sigs = [signature]
        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)

        did_record = TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=puzhash,
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
        )
        await self.standard_wallet.push_transaction(did_record)
        return spend_bundle

    async def create_attestment(self, identity, newpuz):
        coins = await self.select_coins(1)
        coin = coins.pop()
        # innerpuz solution is (mode amount new_puz identity my_puz)
        innersol = f"(1 {coin.amount} 0x{newpuz} 0x{identity} 0x{coin.puzzle_hash})"
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz_str = self.did_info.current_inner
        full_puzzle: str = did_wallet_puzzles.create_fullpuz(
            Program(binutils.assemble(innerpuz_str)).get_tree_hash(),
            self.did_info.my_core,
        )
        parent_info = await self.get_parent_for_coin(coin)

        fullsol = f"(0x{Program(binutils.assemble(self.did_info.my_core)).get_tree_hash()} (0x{parent_info.parent_name} 0x{parent_info.inner_puzzle_hash} {parent_info.amount}) {coin.amount} {innerpuz_str} {innersol})"
        # breakpoint()
        list_of_solutions = [
            CoinSolution(
                coin,
                clvm.to_sexp_f(
                    [
                        Program(binutils.assemble(full_puzzle)),
                        Program(binutils.assemble(fullsol)),
                    ]
                ),
            )
        ]
        # spend the message coin
        list_of_solutions.append(
            did_wallet_puzzles.create_spend_for_mesasage(coin.name(), identity, newpuz)
        )
        # sign for AGG_SIG_ME
        message = std_hash(bytes(newpuz) + bytes(coin.name()))
        pubkey = did_wallet_puzzles.get_pubkey_from_innerpuz(innerpuz_str)
        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
        private = self.wallet_state_manager.private_key.private_child(
            index
        ).get_private_key()
        pk = BLSPrivateKey(private)
        signature = pk.sign(message)
        assert signature.validate([signature.PkMessagePair(pubkey, message)])
        sigs = [signature]
        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)
        """
        did_record = TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=coin.puzzle_hash,
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
        )
        await self.standard_wallet.push_transaction(did_record)
        """
        return spend_bundle

    async def get_info_for_recovery(self):
        coins = await self.select_coins(1)
        coin = coins.pop()
        parent = coin.parent_coin_info
        innerpuzhash = Program(
            binutils.assemble(self.did_info.current_inner)
        ).get_tree_hash()
        amount = coin.amount
        return f"(0x{parent} 0x{innerpuzhash} {amount})"

    async def recovery_spend(
        self,
        coin,
        puzhash,
        parent_innerpuzhash_amounts_for_recovery_ids,
        spend_bundle=None,
    ):
        # innerpuz solution is (mode amount new_puz identity my_puz parent_innerpuzhash_amounts_for_recovery_ids)
        innersol = f"(2 {coin.amount} 0x{puzhash} 0x{coin.name()} 0x{coin.puzzle_hash} {parent_innerpuzhash_amounts_for_recovery_ids})"
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz_str = self.did_info.current_inner
        full_puzzle: str = did_wallet_puzzles.create_fullpuz(
            Program(binutils.assemble(innerpuz_str)).get_tree_hash(),
            self.did_info.my_core,
        )
        parent_info = await self.get_parent_for_coin(coin)

        fullsol = f"(0x{Program(binutils.assemble(self.did_info.my_core)).get_tree_hash()} (0x{parent_info.parent_name} 0x{parent_info.inner_puzzle_hash} {parent_info.amount}) {coin.amount} {innerpuz_str} {innersol})"
        # breakpoint()
        list_of_solutions = [
            CoinSolution(
                coin,
                clvm.to_sexp_f(
                    [
                        Program(binutils.assemble(full_puzzle)),
                        Program(binutils.assemble(fullsol)),
                    ]
                ),
            )
        ]
        sigs = []
        aggsig = BLSSignature.aggregate(sigs)
        if spend_bundle is None:
            spend_bundle = SpendBundle(list_of_solutions, aggsig)
        else:
            spend_bundle = spend_bundle.aggregate(
                [spend_bundle, SpendBundle(list_of_solutions, aggsig)]
            )

        did_record = TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=puzhash,
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
        )
        await self.standard_wallet.push_transaction(did_record)
        return spend_bundle

    async def get_new_innerpuz(self) -> Program:
        devrec = await self.wallet_state_manager.get_unused_derivation_record(
            self.standard_wallet.wallet_info.id
        )
        pubkey = bytes(devrec.pubkey)
        innerpuzzle = did_wallet_puzzles.create_innerpuz(
            pubkey, self.did_info.backup_ids
        )
        innerpuz = Program(binutils.assemble(innerpuzzle))
        return innerpuz

    async def get_new_inner_hash(self) -> bytes32:
        innerpuz = await self.get_new_innerpuz()
        return innerpuz.get_tree_hash()

    async def get_innerhash_for_pubkey(self, pubkey: bytes):
        innerpuzzle = did_wallet_puzzles.create_innerpuz(
            pubkey, self.did_info.backup_ids
        )
        innerpuz = Program(binutils.assemble(innerpuzzle))
        return innerpuz.get_tree_hash()

    async def inner_puzzle_for_did_puzzle(self, did_hash: bytes32) -> Program:
        record: DerivationRecord = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
            did_hash.hex()
        )
        inner_puzzle: Program = did_wallet_puzzles.create_innerpuz(
            bytes(record.pubkey), self.did_info.backup_ids
        )
        return inner_puzzle

    async def get_parent_for_coin(self, coin) -> Optional[CCParent]:
        parent_info = None
        for name, ccparent in self.did_info.parent_info:
            if name == coin.parent_coin_info:
                parent_info = ccparent

        return parent_info

    async def generate_new_decentralised_id(
        self, amount: uint64
    ) -> Optional[SpendBundle]:

        coins = await self.standard_wallet.select_coins(amount)
        if coins is None:
            return None

        origin = coins.copy().pop()
        origin_id = origin.name()

        did_core = did_wallet_puzzles.create_core(bytes(origin_id))

        did_inner: Program = await self.get_new_innerpuz()
        did_inner_hash = did_inner.get_tree_hash()
        did_puz = did_wallet_puzzles.create_fullpuz(did_inner_hash, did_core)
        did_puzzle_hash = Program(binutils.assemble(did_puz)).get_tree_hash()

        tx_record: Optional[
            TransactionRecord
        ] = await self.standard_wallet.generate_signed_transaction(
            amount, did_puzzle_hash, uint64(0), origin_id, coins
        )
        self.log.warning(f"did_puzzle_hash is {did_puzzle_hash}")
        eve_coin = Coin(origin_id, did_puzzle_hash, amount)
        future_parent = CCParent(
            eve_coin.parent_coin_info, did_inner_hash, eve_coin.amount
        )
        eve_parent = CCParent(
            origin.parent_coin_info, origin.puzzle_hash, origin.amount
        )
        await self.add_parent(eve_coin.parent_coin_info, eve_parent)
        await self.add_parent(eve_coin.name(), future_parent)

        if tx_record is None or tx_record.spend_bundle is None:
            return None

        # Only want to save this information if the transaction is valid
        did_info: DIDInfo = DIDInfo(
            did_core,
            self.did_info.backup_ids,
            self.did_info.parent_info,
            binutils.disassemble(did_inner),
        )
        await self.save_info(did_info)

        eve_spend = await self.generate_eve_spend(
            eve_coin, did_puz, origin_id, did_inner
        )

        full_spend = SpendBundle.aggregate([tx_record.spend_bundle, eve_spend])
        return full_spend

    async def generate_eve_spend(
        self, coin: Coin, full_puzzle: str, origin_id: bytes, innerpuz: Program
    ):
        # innerpuz solution is (mode amount new_puz identity my_puz)
        innersol = f"(0 {coin.amount} 0x{coin.puzzle_hash} 0x{coin.name()} 0x{coin.puzzle_hash})"
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz_str = binutils.disassemble(innerpuz)
        fullsol = f"(0x{Program(binutils.assemble(self.did_info.my_core)).get_tree_hash()} 0x{coin.parent_coin_info} {coin.amount} {innerpuz_str} {innersol})"
        # breakpoint()
        list_of_solutions = [
            CoinSolution(
                coin,
                clvm.to_sexp_f(
                    [
                        Program(binutils.assemble(full_puzzle)),
                        Program(binutils.assemble(fullsol)),
                    ]
                ),
            )
        ]
        # sign for AGG_SIG_ME
        message = std_hash(bytes(coin.puzzle_hash) + bytes(coin.name()))
        pubkey = did_wallet_puzzles.get_pubkey_from_innerpuz(innerpuz_str)
        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
        private = self.wallet_state_manager.private_key.private_child(
            index
        ).get_private_key()
        pk = BLSPrivateKey(private)
        signature = pk.sign(message)
        assert signature.validate([signature.PkMessagePair(pubkey, message)])
        sigs = [signature]
        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)
        return spend_bundle

    async def add_parent(self, name: bytes32, parent: Optional[CCParent]):
        self.log.info(f"Adding parent {name}: {parent}")
        current_list = self.did_info.parent_info.copy()
        current_list.append((name, parent))
        cc_info: DIDInfo = DIDInfo(
            self.did_info.my_core,
            self.did_info.backup_ids,
            current_list,
            self.did_info.current_inner,
        )
        await self.save_info(cc_info)

    async def save_info(self, did_info: DIDInfo):
        self.did_info = did_info
        current_info = self.wallet_info
        data_str = bytes(did_info).hex()
        wallet_info = WalletInfo(
            current_info.id, current_info.name, current_info.type, data_str
        )
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info)
