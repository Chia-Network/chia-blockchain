import logging
import os
import json
import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple, Set, List, Dict

from blspy import G2Element, AugSchemeMPL

from chia.clvm.singleton import SINGLETON_LAUNCHER
from chia.wallet.db_wallet.db_wallet_puzzles import (
    create_host_fullpuz,
    create_offer_fullpuz,
    SINGLETON_LAUNCHER,
    create_host_layer_puzzle,
    create_singleton_fullpuz,
)
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo


@dataclass(frozen=True)
@streamable
class DataLayerInfo(Streamable):
    origin_coin: Optional[Coin]  # Coin ID of this coin is our Singleton ID
    root_hash: bytes32
    parent_info: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): LineageProof}
    current_inner_inner: Optional[Program]  # represents a Program as bytes


class DataLayerWallet:
    MINIMUM_INITIAL_BALANCE = 1

    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    standard_wallet: Wallet
    base_puzzle_program: Optional[bytes]
    base_inner_puzzle_hash: Optional[bytes32]
    wallet_id: int
    """
    interface used by datalayer for interacting with the chain
    """

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.DATA_LAYER)

    def id(self) -> uint32:
        return self.wallet_info.id

    # todo remove
    async def create_data_store(self, name: str = "") -> bytes32:
        tree_id = bytes32.from_bytes(os.urandom(32))
        return tree_id

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        launcher_coin_id: bytes32,
        block_spends: List[CoinSpend],
        block_height: uint32,
        in_transaction: bool,
        name: str = None,
    ):
        """
        This creates a new PoolWallet with only one spend: the launcher spend. The DB MUST be committed after calling
        this method.
        """
        self = DataLayerWallet()
        self.wallet_state_manager = wallet_state_manager

        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "DataLayer wallet", WalletType.DATA_LAYER.value, "", in_transaction=in_transaction
        )
        self.wallet_id = self.wallet_info.id
        self.standard_wallet = wallet
        self.target_state = None
        self.log = logging.getLogger(name if name else __name__)

        launcher_spend: Optional[CoinSpend] = None
        for spend in block_spends:
            if spend.coin.name() == launcher_coin_id:
                launcher_spend = spend
        assert launcher_spend is not None
        self.dl_info = DataLayerInfo(spend.coin, Program.to(0).get_tree_hash(), [], None)
        info_as_string = json.dumps(self.did_info.to_json_dict())
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id, info_as_string, create_puzzle_hashes=False)
        self.wallet_state_manager.set_new_peak_callback(self.wallet_id, self.new_peak)
        return self

    async def create_new_data_layer_wallet_transaction(
        self,
        root_hash: bytes32,
        fee: uint64 = uint64(0),
    ) -> Tuple[TransactionRecord, bytes32]:
        amount = 1

        unspent_records = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.standard_wallet.wallet_id)
        balance = await self.standard_wallet.get_confirmed_balance(unspent_records)
        if balance < DataLayerWallet.MINIMUM_INITIAL_BALANCE:
            raise ValueError("Not enough balance in main wallet .")
        if balance < fee:
            raise ValueError(f"Not enough balance in main wallet to create a managed plotting pool with fee {fee}.")

        spend_bundle, singleton_puzzle_hash, launcher_coin_id = await self.generate_launcher_spend(
            amount, root_hash
        )

        if spend_bundle is None:
            raise ValueError("failed to generate ID for wallet")

        standard_wallet_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=singleton_puzzle_hash,
            amount=uint64(amount),
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
            name=spend_bundle.name(),
        )
        await self.standard_wallet.push_transaction(standard_wallet_record)
        # p2_singleton_puzzle_hash: bytes32 = launcher_id_to_p2_puzzle_hash(
        #     launcher_coin_id, p2_singleton_delay_time, p2_singleton_delayed_ph
        # )
        return standard_wallet_record, launcher_coin_id

    async def generate_launcher_spend(
        self,
        amount: uint64,
        initial_root: bytes32,
    ) -> Tuple[SpendBundle, bytes32, bytes32]:
        """
        Creates the initial singleton, which includes spending an origin coin, the launcher, and creating a singleton
        """

        coins: Set[Coin] = await self.standard_wallet.select_coins(amount)
        if coins is None:
            raise ValueError("Not enough coins to create pool wallet")

        assert len(coins) == 1

        launcher_parent: Coin = coins.copy().pop()
        genesis_launcher_puz: Program = SINGLETON_LAUNCHER
        launcher_coin: Coin = Coin(launcher_parent.name(), genesis_launcher_puz.get_tree_hash(), amount)

        inner_puzzle: Program = await self.standard_wallet.get_new_puzzle()

        full_puzzle: Program = create_host_fullpuz(inner_puzzle, initial_root, launcher_coin.name())
        puzzle_hash: bytes32 = full_puzzle.get_tree_hash()

        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([puzzle_hash, amount, initial_root]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message).name())
        eve_coin = Coin(launcher_coin.name(), full_puzzle.get_tree_hash(), amount)
        future_parent = LineageProof(
            eve_coin.parent_coin_info,
            create_host_layer_puzzle(inner_puzzle, initial_root).get_tree_hash(),
            eve_coin.amount,
        )
        eve_parent = LineageProof(
            launcher_coin.parent_coin_info,
            launcher_coin.puzzle_hash,
            launcher_coin.amount,
        )
        await self.add_parent(eve_coin.parent_coin_info, eve_parent, False)
        await self.add_parent(eve_coin.name(), future_parent, False)
        create_launcher_tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            amount,
            genesis_launcher_puz.get_tree_hash(),
            uint64(0),
            None,
            coins,
            None,
            False,
            announcement_set,
        )
        assert create_launcher_tx_record is not None and create_launcher_tx_record.spend_bundle is not None
        genesis_launcher_solution: Program = Program.to([puzzle_hash, amount, initial_root])
        launcher_cs: CoinSpend = CoinSpend(
            launcher_coin,
            SerializedProgram.from_program(genesis_launcher_puz),
            SerializedProgram.from_program(genesis_launcher_solution),
        )
        launcher_sb: SpendBundle = SpendBundle([launcher_cs], G2Element())
        full_spend: SpendBundle = SpendBundle.aggregate([create_launcher_tx_record.spend_bundle, launcher_sb])
        return full_spend, puzzle_hash, launcher_coin.name()

    async def create_update_state_spend(
        self,
        root_hash: bytes,
    ) -> SpendBundle:
        new_inner_inner_puzzle = await self.standard_wallet.get_new_puzzle()
        new_db_layer_puzzle = create_host_layer_puzzle(new_inner_inner_puzzle, root_hash)
        coins = await self.select_coins(1)
        assert coins is not None and coins != set()
        my_coin = coins.pop()
        primaries = [({"puzzlehash": new_db_layer_puzzle.get_tree_hash(), "amount": my_coin.amount})]
        inner_inner_sol = self.standard_wallet.make_solution(primaries=primaries)
        db_layer_sol = Program.to([0, inner_inner_sol])
        parent_info = await self.get_parent_for_coin(my_coin)
        assert parent_info is not None
        current_full_puz = create_host_fullpuz(
            self.dl_info.current_inner_inner,
            self.dl_info.root_hash,
            self.dl_info.origin_coin.name(),
        )
        full_sol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                my_coin.amount,
                db_layer_sol,
            ]
        )
        future_parent = LineageProof(
            my_coin.name(),
            create_host_layer_puzzle(
                self.dl_info.current_inner_inner,
                self.dl_info.root_hash
            ).get_tree_hash(),
            my_coin.amount,
        )
        await self.add_parent(my_coin.name(), future_parent, False)
        coin_spend = CoinSpend(my_coin, current_full_puz, full_sol)
        sigs = await self.standard_wallet.sign([coin_spend])
        spend_bundle = SpendBundle([coin_spend], sigs)
        new_info = DataLayerInfo(self.dl_info.origin_coin, root_hash, self.did_info.parent_info, new_inner_inner_puzzle)
        await self.save_info(new_info)
        await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_info.id)

        return spend_bundle

    async def create_report_spend(self) -> SpendBundle:
        coins = await self.select_coins(1)
        assert coins is not None and coins != set()
        my_coin = coins.pop()
        # (my_puzhash . my_amount)
        db_layer_sol = Program.to([1, (my_coin.puzzle_hash, my_coin.amount)])
        parent_info = await self.get_parent_for_coin(my_coin)
        assert parent_info is not None
        current_full_puz = create_host_fullpuz(
            self.dl_info.current_inner_inner,
            self.dl_info.root_hash,
            self.dl_info.origin_coin.name(),
        )
        full_sol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                my_coin.amount,
                db_layer_sol,
            ]
        )
        coin_spend = CoinSpend(my_coin, current_full_puz, full_sol)
        spend_bundle = SpendBundle([coin_spend], AugSchemeMPL.aggregate([]))

        return spend_bundle

    async def select_coins(self, amount, exclude: List[Coin] = None) -> Optional[Set[Coin]]:
        """Returns a set of coins that can be used for generating a new transaction."""
        if exclude is None:
            exclude = []

        spendable_amount = await self.get_spendable_balance()
        if amount > spendable_amount:
            self.log.warning(f"Can't select {amount}, from spendable {spendable_amount} for wallet id {self.id()}")
            return None

        self.log.info(f"About to select coins for amount {amount}")
        unspent: List[WalletCoinRecord] = list(
            await self.wallet_state_manager.get_spendable_coins_for_wallet(self.wallet_info.id)
        )
        sum_value = 0
        used_coins: Set = set()

        # Use older coins first
        unspent.sort(key=lambda r: r.confirmed_block_height)

        # Try to use coins from the store, if there isn't enough of "unused"
        # coins use change coins that are not confirmed yet
        unconfirmed_removals: Dict[bytes32, Coin] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.wallet_info.id
        )
        for coinrecord in unspent:
            if sum_value >= amount and len(used_coins) > 0:
                break
            if coinrecord.coin.name() in unconfirmed_removals:
                continue
            if coinrecord.coin in exclude:
                continue
            sum_value += coinrecord.coin.amount
            used_coins.add(coinrecord.coin)

        # This happens when we couldn't use one of the coins because it's already used
        # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
        if sum_value < amount:
            raise ValueError(
                "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
            )

        self.log.info(f"Successfully selected coins: {used_coins}")
        return used_coins

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        inner_inner_puz = await self.standard_wallet.puzzle_for_pk(pubkey)
        innerpuz = create_host_layer_puzzle(
            inner_inner_puz, self.dl_info.current_root
        )
        if self.did_info.origin_coin is not None:
            return create_singleton_fullpuz(self.did_info.origin_coin.name(), innerpuz)
        else:
            return create_singleton_fullpuz(0x00, innerpuz)

    async def get_new_puzzle(self) -> Program:
        return self.puzzle_for_pk(
            bytes((await self.wallet_state_manager.get_unused_derivation_record(self.wallet_info.id)).pubkey)
        )

    async def get_parent_for_coin(self, coin) -> Optional[LineageProof]:
        parent_info = None
        for name, ccparent in self.did_info.parent_info:
            if name == coin.parent_coin_info:
                parent_info = ccparent

        return parent_info

    async def add_parent(self, name: bytes32, parent: Optional[LineageProof], in_transaction: bool):
        self.log.info(f"Adding parent {name}: {parent}")
        current_list = self.did_info.parent_info.copy()
        current_list.append((name, parent))
        dl_info: DataLayerInfo = DataLayerInfo(
            self.did_info.origin_coin,
            self.did_info.backup_ids,
            current_list,
            self.did_info.current_inner,
        )
        await self.save_info(dl_info, in_transaction)

    async def save_info(self, dl_info: DataLayerInfo, in_transaction: bool):
        self.dl_info = dl_info
        current_info = self.wallet_info
        data_str = json.dumps(dl_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info, in_transaction)
