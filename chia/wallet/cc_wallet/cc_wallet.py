from __future__ import annotations

import logging
import time
from dataclasses import replace
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Set

from blspy import AugSchemeMPL, G2Element

from chia.consensus.cost_calculator import calculate_cost_of_program, NPCResult
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.protocols.wallet_protocol import PuzzleSolutionResponse
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.json_util import dict_to_json_str
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.block_record import HeaderBlockRecord
from chia.wallet.cc_wallet.cc_info import CCInfo
from chia.wallet.cc_wallet.cc_utils import (
    CC_MOD,
    SpendableCC,
    construct_cc_puzzle,
    spend_bundle_for_spendable_ccs,
    get_cat_truths,
    match_cat_puzzle,
)
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.puzzles.genesis_checkers import GenesisById, ALL_LIMITATIONS_PROGRAMS
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
)
from chia.wallet.puzzles.singleton_top_layer import (
    adapt_inner_to_singleton,
    adapt_inner_puzzle_hash_to_singleton,
    remove_singleton_truth_wrapper,
)
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo


class CCWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    cc_coin_record: WalletCoinRecord
    cc_info: CCInfo
    standard_wallet: Wallet
    cost_of_single_tx: Optional[int]

    @staticmethod
    async def create_new_cc_wallet(
        wallet_state_manager: Any,
        wallet: Wallet,
        cat_tail_info: Dict,
        amount: uint64,
    ):
        self = CCWallet()
        self.cost_of_single_tx = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(__name__)
        std_wallet_id = self.standard_wallet.wallet_id
        bal = await wallet_state_manager.get_confirmed_balance_for_wallet_already_locked(std_wallet_id)
        if amount > bal:
            raise ValueError("Not enough balance")
        self.wallet_state_manager = wallet_state_manager

        self.cc_info = CCInfo(None, [])
        info_as_string = bytes(self.cc_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "CAT Wallet", WalletType.COLOURED_COIN, info_as_string
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")

        try:
            spend_bundle = await ALL_LIMITATIONS_PROGRAMS[cat_tail_info["identifier"]].generate_issuance_bundle(
                self,
                cat_tail_info,
                amount,
            )
        except Exception:
            await wallet_state_manager.user_store.delete_wallet(self.id(), False)
            raise
        if spend_bundle is None:
            await wallet_state_manager.user_store.delete_wallet(self.id())
            raise ValueError("Failed to create spend.")

        await self.wallet_state_manager.add_new_wallet(self, self.id())

        # Change and actual coloured coin
        non_ephemeral_coins: List[Coin] = spend_bundle.not_ephemeral_additions()
        cc_coin = None
        puzzle_store = self.wallet_state_manager.puzzle_store
        for c in non_ephemeral_coins:
            info = await puzzle_store.wallet_info_for_puzzle_hash(c.puzzle_hash)
            if info is None:
                raise ValueError("Internal Error")
            id, wallet_type = info
            if id == self.id():
                cc_coin = c

        if cc_coin is None:
            raise ValueError("Internal Error, unable to generate new coloured coin")

        regular_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=cc_coin.puzzle_hash,
            amount=uint64(cc_coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_state_manager.main_wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=token_bytes(),
        )
        cc_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=cc_coin.puzzle_hash,
            amount=uint64(cc_coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(10),
            spend_bundle=None,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=token_bytes(),
        )
        await self.standard_wallet.push_transaction(regular_record)
        await self.standard_wallet.push_transaction(cc_record)
        return self

    @staticmethod
    async def create_wallet_for_cc(
        wallet_state_manager: Any,
        wallet: Wallet,
        genesis_checker_hex: str,
    ) -> CCWallet:
        self = CCWallet()
        self.cost_of_single_tx = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.cc_info = CCInfo(Program.fromhex(genesis_checker_hex), [])
        info_as_string = bytes(self.cc_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "CC Wallet", WalletType.COLOURED_COIN, info_as_string
        )
        if self.wallet_info is None:
            raise Exception("wallet_info is None")

        await self.wallet_state_manager.add_new_wallet(self, self.id())
        return self

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
    ) -> CCWallet:
        self = CCWallet()

        self.log = logging.getLogger(__name__)

        self.cost_of_single_tx = None
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.standard_wallet = wallet
        self.cc_info = CCInfo.from_bytes(hexstr_to_bytes(self.wallet_info.data))
        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.COLOURED_COIN)

    def id(self) -> uint32:
        return self.wallet_info.id

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint64:
        if record_list is None:
            record_list = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.id())

        amount: uint64 = uint64(0)
        for record in record_list:
            lineage = await self.get_lineage_proof_for_coin(record.coin)
            if lineage is not None:
                amount = uint64(amount + record.coin.amount)

        self.log.info(f"Confirmed balance for cc wallet {self.id()} is {amount}")
        return uint64(amount)

    async def get_unconfirmed_balance(self, unspent_records=None) -> uint128:
        confirmed = await self.get_confirmed_balance(unspent_records)
        unconfirmed_tx: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
            self.id()
        )
        addition_amount = 0
        removal_amount = 0

        for record in unconfirmed_tx:
            if TransactionType(record.type) is TransactionType.INCOMING_TX:
                addition_amount += record.amount
            else:
                removal_amount += record.amount

        result = confirmed - removal_amount + addition_amount

        self.log.info(f"Unconfirmed balance for cc wallet {self.id()} is {result}")
        return uint128(result)

    async def get_max_send_amount(self, records=None):
        spendable: List[WalletCoinRecord] = list(
            await self.wallet_state_manager.get_spendable_coins_for_wallet(self.id(), records)
        )
        if len(spendable) == 0:
            return 0
        spendable.sort(reverse=True, key=lambda record: record.coin.amount)
        if self.cost_of_single_tx is None:
            coin = spendable[0].coin
            tx = await self.generate_signed_transaction(
                [coin.amount], [coin.puzzle_hash], coins={coin}, ignore_max_send_amount=True
            )
            program: BlockGenerator = simple_solution_generator(tx.spend_bundle)
            # npc contains names of the coins removed, puzzle_hashes and their spend conditions
            result: NPCResult = get_name_puzzle_conditions(
                program,
                self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
                cost_per_byte=self.wallet_state_manager.constants.COST_PER_BYTE,
                safe_mode=True,
                rust_checker=True,
            )
            cost_result: uint64 = calculate_cost_of_program(
                program.program, result, self.wallet_state_manager.constants.COST_PER_BYTE
            )
            self.cost_of_single_tx = cost_result
            self.log.info(f"Cost of a single tx for CAT wallet: {self.cost_of_single_tx}")

        max_cost = self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM / 2  # avoid full block TXs
        current_cost = 0
        total_amount = 0
        total_coin_count = 0

        for record in spendable:
            current_cost += self.cost_of_single_tx
            total_amount += record.coin.amount
            total_coin_count += 1
            if current_cost + self.cost_of_single_tx > max_cost:
                break

        return total_amount

    async def get_name(self):
        return self.wallet_info.name

    async def set_name(self, new_name: str):
        new_info = replace(self.wallet_info, name=new_name)
        self.wallet_info = new_info
        await self.wallet_state_manager.user_store.update_wallet(self.wallet_info, False)

    def get_colour(self) -> str:
        assert self.cc_info.my_genesis_checker is not None
        return bytes(self.cc_info.my_genesis_checker).hex()

    async def coin_added(self, coin: Coin, height: uint32):
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"CC wallet has been notified that {coin} was added")
        search_for_parent: bool = True

        inner_puzzle = await self.inner_puzzle_for_cc_puzhash(coin.puzzle_hash)
        lineage_proof = LineageProof(coin.parent_coin_info, inner_puzzle.get_tree_hash(), coin.amount)
        await self.add_lineage(coin.name(), lineage_proof, True)

        for name, lineage_proofs in self.cc_info.lineage_proofs:
            if coin.parent_coin_info == name:
                search_for_parent = False
                break

        if search_for_parent:
            data: Dict[str, Any] = {
                "data": {
                    "action_data": {
                        "api_name": "request_puzzle_solution",
                        "height": height,
                        "coin_name": coin.parent_coin_info,
                        "received_coin": coin.name(),
                    }
                }
            }

            data_str = dict_to_json_str(data)
            await self.wallet_state_manager.create_action(
                name="request_puzzle_solution",
                wallet_id=self.id(),
                wallet_type=self.type(),
                callback="puzzle_solution_received",
                done=False,
                data=data_str,
                in_transaction=True,
            )

    async def puzzle_solution_received(self, response: PuzzleSolutionResponse, action_id: int):
        coin_name = response.coin_name
        height = response.height
        puzzle: Program = response.puzzle
        matched, curried_args = match_cat_puzzle(puzzle)
        header_hash = self.wallet_state_manager.blockchain.height_to_hash(height)
        block: Optional[
            HeaderBlockRecord
        ] = await self.wallet_state_manager.blockchain.block_store.get_header_block_record(header_hash)
        if block is None:
            return None

        removals = block.removals
        parent_coin = None
        for coin in removals:
            if coin.name() == coin_name:
                parent_coin = coin
        if parent_coin is None:
            raise ValueError("Error in finding parent")

        if matched:
            mod_hash, genesis_coin_checker_hash, inner_puzzle = curried_args
            self.log.info(f"parent: {coin_name} inner_puzzle for parent is {inner_puzzle}")
            await self.add_lineage(
                coin_name, LineageProof(parent_coin.parent_coin_info, inner_puzzle.get_tree_hash(), parent_coin.amount)
            )
        else:
            # await self.add_lineage(coin_name, LineageProof())
            # The comment above is what it should be when we have some way of
            # identifying that this is a coin with a TAIL we can spend, and not some spoof
            pass
        await self.wallet_state_manager.action_store.action_done(action_id)

    async def get_new_inner_hash(self) -> bytes32:
        puzzle = adapt_inner_to_singleton(await self.standard_wallet.get_new_puzzle())
        return puzzle.get_tree_hash()

    async def get_new_inner_puzzle(self) -> Program:
        return adapt_inner_to_singleton(await self.standard_wallet.get_new_puzzle())

    async def get_new_puzzlehash(self) -> bytes32:
        return adapt_inner_puzzle_hash_to_singleton(await self.standard_wallet.get_new_puzzlehash())

    def puzzle_for_pk(self, pubkey) -> Program:
        inner_puzzle = adapt_inner_to_singleton(self.standard_wallet.puzzle_for_pk(bytes(pubkey)))
        if self.cc_info.my_genesis_checker is None:
            raise ValueError("My genesis checker is None")
        cc_puzzle: Program = construct_cc_puzzle(CC_MOD, self.cc_info.my_genesis_checker, inner_puzzle)
        return cc_puzzle

    async def get_new_cc_puzzle_hash(self):
        return (await self.wallet_state_manager.get_unused_derivation_record(self.id())).puzzle_hash

    # Create a new coin of value 0 with a given colour
    async def generate_zero_val_coin(self, send=True, exclude: List[Coin] = None) -> SpendBundle:
        if self.cc_info.my_genesis_checker is None:
            raise ValueError("My genesis checker is None")
        if exclude is None:
            exclude = []
        coins = await self.standard_wallet.select_coins(0, exclude)

        assert coins != set()

        origin = coins.copy().pop()
        origin_id = origin.name()

        cc_inner = await self.get_new_inner_puzzle()
        cc_puzzle_hash: Program = construct_cc_puzzle(CC_MOD, self.cc_info.my_genesis_checker, cc_inner).get_tree_hash()

        tx: TransactionRecord = await self.standard_wallet.generate_signed_transaction(
            uint64(0), cc_puzzle_hash, uint64(0), origin_id, coins
        )
        assert tx.spend_bundle is not None
        full_spend: SpendBundle = tx.spend_bundle
        self.log.info(f"Generate zero val coin: cc_puzzle_hash is {cc_puzzle_hash}")

        # generate eve coin so we can add future lineage_proofs even if we don't eve spend
        eve_coin = Coin(origin_id, cc_puzzle_hash, uint64(0))

        await self.add_lineage(
            eve_coin.name(), LineageProof(eve_coin.parent_coin_info, cc_inner.get_tree_hash(), eve_coin.amount)
        )
        await self.add_lineage(eve_coin.parent_coin_info, LineageProof())

        if send:
            regular_record = TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=cc_puzzle_hash,
                amount=uint64(0),
                fee_amount=uint64(0),
                confirmed=False,
                sent=uint32(10),
                spend_bundle=full_spend,
                additions=full_spend.additions(),
                removals=full_spend.removals(),
                wallet_id=uint32(1),
                sent_to=[],
                trade_id=None,
                type=uint32(TransactionType.INCOMING_TX.value),
                name=token_bytes(),
            )
            cc_record = TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=cc_puzzle_hash,
                amount=uint64(0),
                fee_amount=uint64(0),
                confirmed=False,
                sent=uint32(0),
                spend_bundle=full_spend,
                additions=full_spend.additions(),
                removals=full_spend.removals(),
                wallet_id=self.id(),
                sent_to=[],
                trade_id=None,
                type=uint32(TransactionType.INCOMING_TX.value),
                name=full_spend.name(),
            )
            await self.wallet_state_manager.add_transaction(regular_record)
            await self.wallet_state_manager.add_pending_transaction(cc_record)

        return full_spend

    async def get_spendable_balance(self, records=None) -> uint64:
        coins = await self.get_cc_spendable_coins(records)
        amount = 0
        for record in coins:
            amount += record.coin.amount

        return uint64(amount)

    async def get_pending_change_balance(self) -> uint64:
        unconfirmed_tx = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(self.id())
        addition_amount = 0
        for record in unconfirmed_tx:
            if not record.is_in_mempool():
                continue
            our_spend = False
            for coin in record.removals:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(coin, self.id()):
                    our_spend = True
                    break

            if our_spend is not True:
                continue

            for coin in record.additions:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(coin, self.id()):
                    addition_amount += coin.amount

        return uint64(addition_amount)

    async def get_cc_spendable_coins(self, records=None) -> List[WalletCoinRecord]:
        result: List[WalletCoinRecord] = []

        record_list: Set[WalletCoinRecord] = await self.wallet_state_manager.get_spendable_coins_for_wallet(
            self.id(), records
        )

        for record in record_list:
            lineage = await self.get_lineage_proof_for_coin(record.coin)
            if lineage is not None:
                result.append(record)

        return result

    async def select_coins(self, amount: uint64) -> Set[Coin]:
        """
        Returns a set of coins that can be used for generating a new transaction.
        Note: Must be called under wallet state manager lock
        """

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
        spendable.sort(key=lambda r: r.confirmed_block_height)

        # Try to use coins from the store, if there isn't enough of "unused"
        # coins use change coins that are not confirmed yet
        unconfirmed_removals: Dict[bytes32, Coin] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.id()
        )
        for coinrecord in spendable:
            if sum >= amount and len(used_coins) > 0:
                break
            if coinrecord.coin.name() in unconfirmed_removals:
                continue
            sum += coinrecord.coin.amount
            used_coins.add(coinrecord.coin)
            self.log.info(f"Selected coin: {coinrecord.coin.name()} at height {coinrecord.confirmed_block_height}!")

        # This happens when we couldn't use one of the coins because it's already used
        # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
        if sum < amount:
            raise ValueError(
                "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
            )

        self.log.info(f"Successfully selected coins: {used_coins}")
        return used_coins

    async def get_sigs(self, innerpuz: Program, innersol: Program, coin_name: bytes32) -> List[G2Element]:
        puzzle_hash = remove_singleton_truth_wrapper(innerpuz).get_tree_hash()
        pubkey, private = await self.wallet_state_manager.get_keys(puzzle_hash)
        synthetic_secret_key = calculate_synthetic_secret_key(private, DEFAULT_HIDDEN_PUZZLE_HASH)
        sigs: List[G2Element] = []
        error, conditions, cost = conditions_dict_for_solution(
            innerpuz, innersol, self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM
        )
        if conditions is not None:
            for _, msg in pkm_pairs_for_conditions_dict(
                conditions, coin_name, self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
            ):
                signature = AugSchemeMPL.sign(synthetic_secret_key, msg)
                sigs.append(signature)
        return sigs

    async def inner_puzzle_for_cc_puzhash(self, cc_hash: bytes32) -> Program:
        record: DerivationRecord = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
            cc_hash.hex()
        )
        inner_puzzle: Program = adapt_inner_to_singleton(self.standard_wallet.puzzle_for_pk(bytes(record.pubkey)))
        return inner_puzzle

    async def get_lineage_proof_for_coin(self, coin) -> Optional[LineageProof]:
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
        ignore_max_send_amount: bool = False,
        memos: Optional[List[Optional[bytes]]] = None,
    ) -> TransactionRecord:
        if memos is None:
            memos = [None for _ in range(len(puzzle_hashes))]

        if not (len(memos) == len(puzzle_hashes) == len(amounts)):
            raise ValueError("Memos, puzzle_hashes, and amounts must have the same length")

        # Get coins and calculate amount of change required
        outgoing_amount = uint64(sum(amounts))
        total_outgoing = outgoing_amount + fee

        if not ignore_max_send_amount:
            max_send = await self.get_max_send_amount()
            if total_outgoing > max_send:
                raise ValueError(f"Can't send more than {max_send} in a single transaction")

        if coins is None:
            selected_coins: Set[Coin] = await self.select_coins(uint64(total_outgoing))
        else:
            selected_coins = coins

        total_amount = sum([x.amount for x in selected_coins])
        change = total_amount - total_outgoing
        primaries = []
        for amount, puzzle_hash, memo in zip(amounts, puzzle_hashes, memos):
            primaries.append({"puzzlehash": puzzle_hash, "amount": amount, "memo": memo})

        if change > 0:
            changepuzzlehash = await self.get_new_inner_hash()
            primaries.append({"puzzlehash": changepuzzlehash, "amount": change})

        coin = list(selected_coins)[0]
        inner_puzzle = await self.inner_puzzle_for_cc_puzhash(coin.puzzle_hash)

        if self.cc_info.my_genesis_checker is None:
            raise ValueError("My genesis checker is None")

        uncurried_mod, curried_args = self.cc_info.my_genesis_checker.uncurry()
        _, args = GenesisById.match(uncurried_mod, curried_args)  # Static TAIL
        genesis_id = args[0].as_python()

        spendable_cc_list = []
        innersol_list = []
        sigs: List[G2Element] = []
        first = True
        for coin in selected_coins:
            coin_inner_puzzle = await self.inner_puzzle_for_cc_puzhash(coin.puzzle_hash)
            if first:
                first = False
                if fee > 0:
                    innersol = self.standard_wallet.make_solution(primaries=primaries, fee=fee)
                else:
                    innersol = self.standard_wallet.make_solution(primaries=primaries)
            else:
                innersol = self.standard_wallet.make_solution()
            innersol_list.append(innersol)
            lineage_proof = await self.get_lineage_proof_for_coin(coin)
            assert lineage_proof is not None
            new_spendable_cc = SpendableCC(coin, genesis_id, inner_puzzle, lineage_proof.to_program())
            spendable_cc_list.append(new_spendable_cc)
            limitations_reveal = Program.to([]) if lineage_proof == LineageProof() else self.cc_info.my_genesis_checker
            truths = get_cat_truths(new_spendable_cc, limitations_reveal, GenesisById.solve([], {}))  # Static TAIL
            sigs = sigs + (await self.get_sigs(coin_inner_puzzle, truths.cons(innersol), coin.name()))

        spend_bundle = spend_bundle_for_spendable_ccs(
            CC_MOD,
            self.cc_info.my_genesis_checker,
            spendable_cc_list,
            innersol_list,
            sigs,
        )

        # TODO add support for array in stored records
        return TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=puzzle_hashes[0],
            amount=uint64(outgoing_amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
        )

    async def add_lineage(self, name: bytes32, lineage: Optional[LineageProof], in_transaction=False):
        self.log.info(f"Adding parent {name}: {lineage}")
        current_list = self.cc_info.lineage_proofs.copy()
        current_list.append((name, lineage))
        cc_info: CCInfo = CCInfo(self.cc_info.my_genesis_checker, current_list)
        await self.save_info(cc_info, in_transaction)

    async def save_info(self, cc_info: CCInfo, in_transaction):
        self.cc_info = cc_info
        current_info = self.wallet_info
        data_str = bytes(cc_info).hex()
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info, in_transaction)

    async def create_spend_bundle_relative_amount(self, cc_amount, zero_coin: Coin = None) -> Optional[SpendBundle]:
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
                innersol = self.standard_wallet.make_solution(consumed=[output_created.name()])
            innerpuz: Program = await self.inner_puzzle_for_cc_puzhash(coin.puzzle_hash)
            sigs = sigs + await self.get_sigs(innerpuz, innersol, coin.name())
            lineage_proof = await self.get_lineage_proof_for_coin(coin)
            if self.cc_info.my_genesis_checker is None:
                raise ValueError("My genesis checker is None")
            puzzle_reveal = construct_cc_puzzle(CC_MOD, self.cc_info.my_genesis_checker, innerpuz)
            # Use coin info to create solution and add coin and solution to list of CoinSpends
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
            list_of_solutions.append(CoinSpend(coin, puzzle_reveal, Program.to(solution)))

        aggsig = AugSchemeMPL.aggregate(sigs)
        return SpendBundle(list_of_solutions, aggsig)
