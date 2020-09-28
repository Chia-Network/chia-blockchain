import logging

# RLWallet is subclass of Wallet
from dataclasses import dataclass
import time
from secrets import token_bytes
from typing import Optional, List, Tuple, Any

import json
from blspy import PrivateKey, AugSchemeMPL, G1Element
from clvm_tools import binutils
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.byte_types import hexstr_to_bytes
from src.util.ints import uint8, uint64, uint32
from src.util.streamable import streamable, Streamable
from src.wallet.rl_wallet.rl_wallet_puzzles import (
    rl_puzzle_for_pk,
    rl_make_aggregation_puzzle,
    rl_make_aggregation_solution,
    rl_make_solution_mode_2,
    make_clawback_solution,
    solution_for_rl,
)
from src.wallet.transaction_record import TransactionRecord
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet import Wallet
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo
from src.wallet.derivation_record import DerivationRecord
from src.wallet.derive_keys import master_sk_to_wallet_sk


@dataclass(frozen=True)
@streamable
class RLInfo(Streamable):
    type: str
    admin_pubkey: Optional[bytes]
    user_pubkey: Optional[bytes]
    limit: Optional[uint64]
    interval: Optional[uint64]
    rl_origin: Optional[Coin]
    rl_origin_id: Optional[bytes32]
    rl_puzzle_hash: Optional[bytes32]
    initialized: bool


class RLWallet:
    wallet_state_manager: Any
    wallet_info: WalletInfo
    rl_coin_record: Optional[WalletCoinRecord]
    rl_info: RLInfo
    main_wallet: Wallet
    private_key: PrivateKey
    log: logging.Logger

    @staticmethod
    async def create_rl_admin(
        wallet_state_manager: Any,
    ):
        unused: Optional[
            uint32
        ] = await wallet_state_manager.puzzle_store.get_unused_derivation_path()
        if unused is None:
            await wallet_state_manager.create_more_puzzle_hashes()
        unused = await wallet_state_manager.puzzle_store.get_unused_derivation_path()
        assert unused is not None

        private_key = master_sk_to_wallet_sk(wallet_state_manager.private_key, unused)
        pubkey_bytes: bytes = bytes(private_key.get_g1())

        rl_info = RLInfo(
            "admin", pubkey_bytes, None, None, None, None, None, None, False
        )
        info_as_string = json.dumps(rl_info.to_json_dict())
        wallet_info: Optional[
            WalletInfo
        ] = await wallet_state_manager.user_store.create_wallet(
            "RL Admin", WalletType.RATE_LIMITED, info_as_string
        )
        if wallet_info is None:
            raise Exception("wallet_info is None")

        await wallet_state_manager.puzzle_store.add_derivation_paths(
            [
                DerivationRecord(
                    unused,
                    token_bytes(),
                    pubkey_bytes,
                    WalletType.RATE_LIMITED,
                    wallet_info.id,
                )
            ]
        )
        await wallet_state_manager.puzzle_store.set_used_up_to(unused)

        self = await RLWallet.create(wallet_state_manager, wallet_info)
        await wallet_state_manager.add_new_wallet(self, self.id())
        return self

    @staticmethod
    async def create_rl_user(
        wallet_state_manager: Any,
    ):
        async with wallet_state_manager.puzzle_store.lock:
            unused: Optional[
                uint32
            ] = await wallet_state_manager.puzzle_store.get_unused_derivation_path()
            if unused is None:
                await wallet_state_manager.create_more_puzzle_hashes()
            unused = (
                await wallet_state_manager.puzzle_store.get_unused_derivation_path()
            )
            assert unused is not None

            private_key = wallet_state_manager.private_key

            pubkey_bytes: bytes = bytes(
                master_sk_to_wallet_sk(private_key, unused).get_g1()
            )

            rl_info = RLInfo(
                "user", None, pubkey_bytes, None, None, None, None, None, False
            )
            info_as_string = json.dumps(rl_info.to_json_dict())
            await wallet_state_manager.user_store.create_wallet(
                "RL User", WalletType.RATE_LIMITED, info_as_string
            )
            wallet_info = await wallet_state_manager.user_store.get_last_wallet()
            if wallet_info is None:
                raise Exception("wallet_info is None")

            self = await RLWallet.create(wallet_state_manager, wallet_info)

            await wallet_state_manager.puzzle_store.add_derivation_paths(
                [
                    DerivationRecord(
                        unused,
                        token_bytes(),
                        pubkey_bytes,
                        WalletType.RATE_LIMITED,
                        wallet_info.id,
                    )
                ]
            )
            await wallet_state_manager.puzzle_store.set_used_up_to(unused)

            await wallet_state_manager.add_new_wallet(self, self.id())
            return self

    @staticmethod
    async def create(wallet_state_manager: Any, info: WalletInfo):
        self = RLWallet()

        self.private_key = wallet_state_manager.private_key

        self.wallet_state_manager = wallet_state_manager

        self.wallet_info = info
        self.rl_info = RLInfo.from_json_dict(json.loads(info.data))
        self.main_wallet = wallet_state_manager.main_wallet
        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.RATE_LIMITED)

    def id(self):
        return self.wallet_info.id

    async def admin_create_coin(
        self, interval: uint64, limit: uint64, user_pubkey: str, amount: uint64, fee: uint64
    ) -> bool:
        coins = await self.wallet_state_manager.main_wallet.select_coins(amount)
        if coins is None:
            return False

        origin = coins.copy().pop()
        origin_id = origin.name()

        user_pubkey_bytes = hexstr_to_bytes(user_pubkey)

        assert self.rl_info.admin_pubkey is not None

        rl_puzzle = rl_puzzle_for_pk(
            pubkey=user_pubkey_bytes,
            rate_amount=limit,
            interval_time=interval,
            origin_id=origin_id,
            clawback_pk=self.rl_info.admin_pubkey,
        )

        rl_puzzle_hash = rl_puzzle.get_tree_hash()
        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(
            G1Element.from_bytes(self.rl_info.admin_pubkey)
        )

        assert index is not None
        record = DerivationRecord(
            index,
            rl_puzzle_hash,
            self.rl_info.admin_pubkey,
            WalletType.RATE_LIMITED,
            self.id(),
        )
        await self.wallet_state_manager.puzzle_store.add_derivation_paths([record])

        spend_bundle = await self.main_wallet.generate_signed_transaction(
            amount, rl_puzzle_hash, fee, origin_id, coins
        )
        if spend_bundle is None:
            return False

        await self.main_wallet.push_transaction(spend_bundle)
        new_rl_info = RLInfo(
            "admin",
            self.rl_info.admin_pubkey,
            user_pubkey_bytes,
            limit,
            interval,
            origin,
            origin.name(),
            rl_puzzle_hash,
            True,
        )

        data_str = json.dumps(new_rl_info.to_json_dict())
        new_wallet_info = WalletInfo(
            self.id(), self.wallet_info.name, self.type(), data_str
        )
        await self.wallet_state_manager.user_store.update_wallet(new_wallet_info)
        await self.wallet_state_manager.add_new_wallet(self, self.id())
        self.wallet_info = new_wallet_info
        self.rl_info = new_rl_info

        return True

    async def set_user_info(
        self,
        interval: uint64,
        limit: uint64,
        origin_parent_id: str,
        origin_puzzle_hash: str,
        origin_amount: uint64,
        admin_pubkey: str,
    ) -> None:
        admin_pubkey_bytes = hexstr_to_bytes(admin_pubkey)

        assert self.rl_info.user_pubkey is not None
        origin = Coin(
            hexstr_to_bytes(origin_parent_id),
            hexstr_to_bytes(origin_puzzle_hash),
            origin_amount,
        )
        rl_puzzle = rl_puzzle_for_pk(
            pubkey=self.rl_info.user_pubkey,
            rate_amount=limit,
            interval_time=interval,
            origin_id=origin.name(),
            clawback_pk=admin_pubkey_bytes,
        )

        rl_puzzle_hash = rl_puzzle.get_tree_hash()

        new_rl_info = RLInfo(
            "user",
            admin_pubkey_bytes,
            self.rl_info.user_pubkey,
            limit,
            interval,
            origin,
            origin.name(),
            rl_puzzle_hash,
            True,
        )
        rl_puzzle_hash = rl_puzzle.get_tree_hash()
        if await self.wallet_state_manager.puzzle_store.puzzle_hash_exists(
            rl_puzzle_hash
        ):
            raise ValueError(
                "Cannot create multiple Rate Limited wallets under the same keys. This will change in a future release."
            )
        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(
            G1Element.from_bytes(self.rl_info.user_pubkey)
        )
        assert index is not None
        record = DerivationRecord(
            index,
            rl_puzzle_hash,
            self.rl_info.user_pubkey,
            WalletType.RATE_LIMITED,
            self.id(),
        )

        aggregation_puzzlehash = self.rl_get_aggregation_puzzlehash(
            new_rl_info.rl_puzzle_hash
        )
        record2 = DerivationRecord(
            index + 1,
            aggregation_puzzlehash,
            self.rl_info.user_pubkey,
            WalletType.RATE_LIMITED,
            self.id(),
        )
        await self.wallet_state_manager.puzzle_store.add_derivation_paths(
            [record, record2]
        )
        self.wallet_state_manager.set_coin_with_puzzlehash_created_callback(
            aggregation_puzzlehash, self.aggregate_this_coin
        )

        data_str = json.dumps(new_rl_info.to_json_dict())
        new_wallet_info = WalletInfo(
            self.id(), self.wallet_info.name, self.type(), data_str
        )
        await self.wallet_state_manager.user_store.update_wallet(new_wallet_info)
        await self.wallet_state_manager.add_new_wallet(self, self.id())
        self.wallet_info = new_wallet_info
        self.rl_info = new_rl_info

    async def aggregate_this_coin(self, coin: Coin):
        spend_bundle = await self.rl_generate_signed_aggregation_transaction(
            self.rl_info, coin, await self._get_rl_parent(), await self._get_rl_coin()
        )

        rl_coin = await self._get_rl_coin()
        puzzle_hash = rl_coin.puzzle_hash if rl_coin is not None else None
        tx_record = TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=puzzle_hash,
            amount=uint64(0),
            fee_amount=uint64(0),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
        )

        await self.push_transaction(tx_record)

    async def rl_available_balance(self) -> uint64:
        self.rl_coin_record = await self._get_rl_coin_record()
        if self.rl_coin_record is None:
            return uint64(0)
        lca_header_hash = self.wallet_state_manager.lca
        lca = self.wallet_state_manager.block_records[lca_header_hash]
        height = lca.height
        assert self.rl_info.limit is not None
        unlocked = int(
            (
                (height - self.rl_coin_record.confirmed_block_index)
                / self.rl_info.interval
            )
            * int(self.rl_info.limit)
        )
        total_amount = self.rl_coin_record.coin.amount
        available_amount = min(unlocked, total_amount)
        return uint64(available_amount)

    async def get_confirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_confirmed_balance_for_wallet(
            self.id()
        )

    async def get_unconfirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_unconfirmed_balance(self.id())

    async def get_frozen_amount(self) -> uint64:
        return await self.wallet_state_manager.get_frozen_balance(self.id())

    async def get_spendable_balance(self) -> uint64:
        spendable_am = (
            await self.wallet_state_manager.get_confirmed_spendable_balance_for_wallet(
                self.id()
            )
        )
        return spendable_am

    async def get_pending_change_balance(self) -> uint64:
        unconfirmed_tx = (
            await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
                self.id()
            )
        )
        addition_amount = 0

        for record in unconfirmed_tx:
            our_spend = False
            for coin in record.removals:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(
                    coin, self.id()
                ):
                    our_spend = True
                    break

            if our_spend is not True:
                continue

            for coin in record.additions:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(
                    coin, self.id()
                ):
                    addition_amount += coin.amount

        return uint64(addition_amount)

    def get_new_puzzle(self) -> Program:
        if (
            self.rl_info.limit is None
            or self.rl_info.interval is None
            or self.rl_info.user_pubkey is None
            or self.rl_info.admin_pubkey is None
            or self.rl_info.rl_origin_id is None
        ):
            raise ValueError("One or more of the RL info fields is None")
        return rl_puzzle_for_pk(
            pubkey=self.rl_info.user_pubkey,
            rate_amount=self.rl_info.limit,
            interval_time=self.rl_info.interval,
            origin_id=self.rl_info.rl_origin_id,
            clawback_pk=self.rl_info.admin_pubkey,
        )

    def get_new_puzzlehash(self) -> bytes32:
        return self.get_new_puzzle().get_tree_hash()

    async def can_generate_rl_puzzle_hash(self, hash) -> bool:
        return await self.wallet_state_manager.puzzle_store.puzzle_hash_exists(hash)

    def puzzle_for_pk(self, pk) -> Optional[Program]:
        if self.rl_info.initialized is False:
            return None
        if (
            self.rl_info.limit is None
            or self.rl_info.interval is None
            or self.rl_info.user_pubkey is None
            or self.rl_info.admin_pubkey is None
            or self.rl_info.rl_origin_id is None
        ):
            return None
        return rl_puzzle_for_pk(
            pubkey=self.rl_info.user_pubkey,
            rate_amount=self.rl_info.limit,
            interval_time=self.rl_info.interval,
            origin_id=self.rl_info.rl_origin_id,
            clawback_pk=self.rl_info.admin_pubkey,
        )

    async def get_keys(self, puzzle_hash: bytes32) -> Tuple[G1Element, PrivateKey]:
        """
        Returns keys for puzzle_hash.
        """
        index_for_puzzlehash = await self.wallet_state_manager.puzzle_store.index_for_puzzle_hash_and_wallet(
            puzzle_hash, self.id()
        )
        if index_for_puzzlehash is None:
            raise ValueError(f"index_for_puzzlehash is None ph {puzzle_hash}")
        private = master_sk_to_wallet_sk(self.private_key, index_for_puzzlehash)
        pubkey = private.get_g1()
        return pubkey, private

    async def get_keys_pk(self, clawback_pubkey: bytes):
        """
        Return keys for pubkey
        """
        index_for_pubkey = (
            await self.wallet_state_manager.puzzle_store.index_for_pubkey(
                G1Element.from_bytes(clawback_pubkey)
            )
        )
        if index_for_pubkey is None:
            raise ValueError(f"index_for_pubkey is None pk {clawback_pubkey.hex()}")
        private = master_sk_to_wallet_sk(self.private_key, index_for_pubkey)
        pubkey = private.get_g1()

        return pubkey, private

    async def _get_rl_coin(self) -> Optional[Coin]:
        rl_coins = await self.wallet_state_manager.wallet_store.get_coin_records_by_puzzle_hash(
            self.rl_info.rl_puzzle_hash
        )
        for coin_record in rl_coins:
            if coin_record.spent is False:
                return coin_record.coin

        return None

    async def _get_rl_coin_record(self) -> Optional[WalletCoinRecord]:
        rl_coins = await self.wallet_state_manager.wallet_store.get_coin_records_by_puzzle_hash(
            self.rl_info.rl_puzzle_hash
        )
        for coin_record in rl_coins:
            if coin_record.spent is False:
                return coin_record

        return None

    async def _get_rl_parent(self) -> Optional[Coin]:
        self.rl_coin_record = await self._get_rl_coin_record()
        if not self.rl_coin_record:
            return None
        rl_parent_id = self.rl_coin_record.coin.parent_coin_info
        if rl_parent_id == self.rl_info.rl_origin_id:
            return self.rl_info.rl_origin
        rl_parent = (
            await self.wallet_state_manager.wallet_store.get_coin_record_by_coin_id(
                rl_parent_id
            )
        )
        if rl_parent is None:
            return None

        return rl_parent.coin

    async def rl_generate_unsigned_transaction(self, to_puzzlehash, amount, fee):
        spends = []
        coin = self.rl_coin_record.coin
        puzzle_hash = coin.puzzle_hash
        pubkey = self.rl_info.user_pubkey
        rl_parent: Optional[Coin] = await self._get_rl_parent()
        if rl_parent is None:
            raise ValueError("No RL parent coin")

        puzzle = rl_puzzle_for_pk(
            bytes(pubkey),
            self.rl_info.limit,
            self.rl_info.interval,
            self.rl_info.rl_origin_id,
            self.rl_info.admin_pubkey,
        )

        solution = solution_for_rl(
            coin.parent_coin_info,
            puzzle_hash,
            coin.amount,
            to_puzzlehash,
            amount,
            rl_parent.parent_coin_info,
            rl_parent.amount,
            self.rl_info.interval,
            self.rl_info.limit,
            fee
        )

        spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    async def generate_signed_transaction(
        self, amount, to_puzzle_hash, fee: uint64 = uint64(0)
    ) -> TransactionRecord:
        self.rl_coin_record = await self._get_rl_coin_record()
        if not self.rl_coin_record:
            raise ValueError("No unspent coin (zero balance)")
        if amount > self.rl_coin_record.coin.amount:
            raise ValueError(
                f"Coin value not sufficient: {amount} > {self.rl_coin_record.coin.amount}"
            )
        transaction = await self.rl_generate_unsigned_transaction(
            to_puzzle_hash, amount, fee
        )
        spend_bundle = await self.rl_sign_transaction(transaction)

        return TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=to_puzzle_hash,
            amount=uint64(amount),
            fee_amount=uint64(0),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
        )

    async def rl_sign_transaction(
        self, spends: List[Tuple[Program, CoinSolution]]
    ) -> SpendBundle:
        sigs = []
        for puzzle, solution in spends:
            pubkey, secretkey = await self.get_keys(solution.coin.puzzle_hash)
            signature = AugSchemeMPL.sign(
                secretkey, Program(solution.solution).get_tree_hash()
            )
            sigs.append(signature)

        aggsig = AugSchemeMPL.aggregate(sigs)

        solution_list: List[CoinSolution] = []
        for puzzle, coin_solution in spends:
            solution_list.append(
                CoinSolution(
                    coin_solution.coin, Program.to([puzzle, coin_solution.solution])
                )
            )

        return SpendBundle(solution_list, aggsig)

    def generate_unsigned_clawback_transaction(
        self, clawback_coin: Coin, clawback_puzzle_hash: bytes32
    ):
        if (
            self.rl_info.limit is None
            or self.rl_info.interval is None
            or self.rl_info.user_pubkey is None
            or self.rl_info.admin_pubkey is None
        ):
            raise ValueError("One ore more of the elements of rl_info is None")
        spends = []
        coin = clawback_coin
        if self.rl_info.rl_origin is None:
            raise ValueError("Origin not initialized")
        puzzle = rl_puzzle_for_pk(
            self.rl_info.user_pubkey,
            self.rl_info.limit,
            self.rl_info.interval,
            self.rl_info.rl_origin.name(),
            self.rl_info.admin_pubkey,
        )
        solution = make_clawback_solution(clawback_puzzle_hash, clawback_coin.amount)
        spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    async def sign_clawback_transaction(
        self, spends: List[Tuple[Program, CoinSolution]], clawback_pubkey
    ) -> SpendBundle:
        sigs = []
        for puzzle, solution in spends:
            pubkey, secretkey = await self.get_keys_pk(clawback_pubkey)
            signature = AugSchemeMPL.sign(
                secretkey, Program(solution.solution).get_tree_hash()
            )
            sigs.append(signature)
        aggsig = AugSchemeMPL.aggregate(sigs)
        solution_list = []
        for puzzle, coin_solution in spends:
            solution_list.append(
                CoinSolution(
                    coin_solution.coin, Program.to([puzzle, coin_solution.solution])
                )
            )

        return SpendBundle(solution_list, aggsig)

    async def clawback_rl_coin(self, clawback_puzzle_hash: bytes32) -> SpendBundle:
        rl_coin = await self._get_rl_coin()
        if rl_coin is None:
            raise ValueError("rl_coin is None")
        transaction = self.generate_unsigned_clawback_transaction(
            rl_coin, clawback_puzzle_hash
        )
        return await self.sign_clawback_transaction(
            transaction, self.rl_info.admin_pubkey
        )

    async def clawback_rl_coin_transaction(self) -> TransactionRecord:
        to_puzzle_hash = await self.main_wallet.get_new_puzzlehash()
        spend_bundle = await self.clawback_rl_coin(to_puzzle_hash)

        return TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=to_puzzle_hash,
            amount=uint64(0),
            fee_amount=uint64(0),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
        )

    # This is for using the AC locked coin and aggregating it into wallet - must happen in same block as RL Mode 2
    async def rl_generate_signed_aggregation_transaction(
        self, rl_info, consolidating_coin, rl_parent, rl_coin
    ):
        if (
            rl_info.limit is None
            or rl_info.interval is None
            or rl_info.user_pubkey is None
            or rl_info.admin_pubkey is None
        ):
            raise ValueError("One or more of the elements of rl_info is None")
        if self.rl_coin_record is None:
            raise ValueError("Rl coin record is None")

        list_of_coinsolutions = []
        self.rl_coin_record = await self._get_rl_coin_record()
        pubkey, secretkey = await self.get_keys(self.rl_coin_record.coin.puzzle_hash)
        # Spend wallet coin
        puzzle = rl_puzzle_for_pk(
            rl_info.user_pubkey,
            rl_info.limit,
            rl_info.interval,
            rl_info.rl_origin_id,
            rl_info.admin_pubkey,
        )

        solution = rl_make_solution_mode_2(
            rl_coin.puzzle_hash,
            consolidating_coin.parent_coin_info,
            consolidating_coin.puzzle_hash,
            consolidating_coin.amount,
            rl_coin.parent_coin_info,
            rl_coin.amount,
            rl_parent.amount,
            rl_parent.parent_coin_info,
        )
        signature = AugSchemeMPL.sign(secretkey, solution.get_tree_hash())
        rl_spend = CoinSolution(
            self.rl_coin_record.coin, Program.to([puzzle, solution])
        )

        list_of_coinsolutions.append(rl_spend)

        # Spend consolidating coin
        puzzle = rl_make_aggregation_puzzle(self.rl_coin_record.coin.puzzle_hash)
        solution = rl_make_aggregation_solution(
            consolidating_coin.name(),
            self.rl_coin_record.coin.parent_coin_info,
            self.rl_coin_record.coin.amount,
        )
        agg_spend = CoinSolution(consolidating_coin, Program.to([puzzle, solution]))

        list_of_coinsolutions.append(agg_spend)
        # Spend lock
        puzstring = f"(r (c (q 0x{consolidating_coin.name().hex()}) (q ())))"

        puzzle = Program(binutils.assemble(puzstring))
        solution = Program(binutils.assemble("()"))

        ephemeral = CoinSolution(
            Coin(self.rl_coin_record.coin.name(), puzzle.get_tree_hash(), uint64(0)),
            Program.to([puzzle, solution]),
        )
        list_of_coinsolutions.append(ephemeral)

        aggsig = AugSchemeMPL.aggregate([signature])

        return SpendBundle(list_of_coinsolutions, aggsig)

    def rl_get_aggregation_puzzlehash(self, wallet_puzzle):
        puzzle_hash = rl_make_aggregation_puzzle(wallet_puzzle).get_tree_hash()

        return puzzle_hash

    async def rl_add_funds(self, amount, puzzle_hash):
        spend_bundle = await self.main_wallet.generate_signed_transaction(
            amount, puzzle_hash, uint64(0)
        )
        if spend_bundle is None:
            return False

        await self.main_wallet.push_transaction(spend_bundle)

    async def push_transaction(self, tx: TransactionRecord) -> None:
        """ Use this API to send transactions. """
        await self.wallet_state_manager.add_pending_transaction(tx)
