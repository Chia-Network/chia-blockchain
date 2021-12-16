import logging
import os
import json
import time
from dataclasses import dataclass, replace
from typing import Any, Optional, Tuple, Set, List, Dict, Type, TypeVar

from blspy import G2Element, AugSchemeMPL

from chia.consensus.block_record import BlockRecord
from chia.wallet.db_wallet.db_wallet_puzzles import (
    create_host_fullpuz,
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
from chia.util.ints import uint8, uint32, uint64, uint128
from secrets import token_bytes
from chia.util.streamable import Streamable, streamable
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.transaction_record import ItemAndTransactionRecords
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo


@dataclass(frozen=True)
@streamable
class DataLayerInfo(Streamable):
    origin_coin: Optional[Coin]  # Coin ID of this coin is our Singleton ID
    root_hash: bytes32
    # TODO: should this be a dict for quick lookup?
    parent_info: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): LineageProof}
    current_inner_inner: Optional[Program]  # represents a Program as bytes


_T_DataLayerWallet = TypeVar("_T_DataLayerWallet", bound="DataLayerWallet")


class DataLayerWallet:
    MINIMUM_INITIAL_BALANCE = 1

    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    standard_wallet: Wallet
    base_puzzle_program: Optional[bytes]
    base_inner_puzzle_hash: Optional[bytes32]
    wallet_id: int
    tip_coin: Coin
    """
    interface used by datalayer for interacting with the chain
    """

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.DATA_LAYER)

    def id(self) -> uint32:
        return self.wallet_info.id

    @classmethod
    async def create_new_dl_wallet(
        cls: Type[_T_DataLayerWallet],
        wallet_state_manager: Any,
        wallet: Wallet,
        root_hash: Optional[bytes32],
        fee: uint64 = uint64(0),
        name: Optional[str] = None,
    ) -> ItemAndTransactionRecords[_T_DataLayerWallet]:
        """
        This must be called under the wallet state manager lock
        """

        self = cls()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager

        bal = await wallet_state_manager.get_confirmed_balance_for_wallet_already_locked(self.standard_wallet.wallet_id)
        if 1 > bal:
            raise ValueError("Not enough balance")

        if root_hash is None:
            root_hash = Program.to(0).get_tree_hash()

        txs, parents, launcher_coin, inner_inner_puz = await self.generate_launcher_spend(uint64(1), root_hash)

        self.dl_info = DataLayerInfo(launcher_coin, root_hash, parents, inner_inner_puz)
        info_as_string = json.dumps(self.dl_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "DataLayer Wallet", WalletType.DATA_LAYER.value, info_as_string
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = self.wallet_info.id
        assert self.dl_info.origin_coin is not None
        assert self.dl_info.current_inner_inner is not None
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)

        for tx in txs:
            if tx.wallet_id == uint32(0):
                tx = replace(tx, wallet_id=self.wallet_id)
            await self.standard_wallet.push_transaction(tx)

        await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_info.id)
        return ItemAndTransactionRecords(item=self, transaction_records=txs)

    async def generate_launcher_spend(
        self,
        fee: uint64,
        initial_root: bytes32,
    ) -> Tuple[SpendBundle, bytes32, Coin, Program]:
        """
        Creates the initial singleton, which includes spending an origin coin, the launcher, and creating a singleton
        """

        coins: Set[Coin] = await self.standard_wallet.select_coins(1)
        if coins is None:
            raise ValueError("Not enough coins to create pool wallet")

        assert len(coins) == 1

        launcher_parent: Coin = coins.copy().pop()
        genesis_launcher_puz: Program = SINGLETON_LAUNCHER
        launcher_coin: Coin = Coin(launcher_parent.name(), genesis_launcher_puz.get_tree_hash(), uint64(1))

        inner_puzzle: Program = await self.standard_wallet.get_new_puzzle()

        full_puzzle: Program = create_host_fullpuz(inner_puzzle, initial_root, launcher_coin.name())
        puzzle_hash: bytes32 = full_puzzle.get_tree_hash()

        announcement_set: Set[bytes32] = set()
        announcement_message = Program.to([puzzle_hash, 1, initial_root]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message).name())
        eve_coin = Coin(launcher_coin.name(), full_puzzle.get_tree_hash(), uint64(1))
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
        parents: List[Tuple[bytes32, LineageProof]] = []
        parents.append((eve_coin.parent_coin_info, eve_parent))
        parents.append((eve_coin.name(), future_parent))
        self.tip_coin = eve_coin
        create_launcher_tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            amount=1,
            puzzle_hash=genesis_launcher_puz.get_tree_hash(),
            fee=uint64(0),
            origin_id=None,
            coins=coins,
            primaries=None,
            ignore_max_send_amount=False,
            coin_announcements_to_consume=announcement_set,
        )
        assert create_launcher_tx_record is not None and create_launcher_tx_record.spend_bundle is not None
        genesis_launcher_solution: Program = Program.to([puzzle_hash, 1, initial_root])
        launcher_cs: CoinSpend = CoinSpend(
            launcher_coin,
            SerializedProgram.from_program(genesis_launcher_puz),
            SerializedProgram.from_program(genesis_launcher_solution),
        )
        launcher_sb: SpendBundle = SpendBundle([launcher_cs], G2Element())
        full_spend: SpendBundle = SpendBundle.aggregate([create_launcher_tx_record.spend_bundle, launcher_sb])
        # Delete from standard transaction so we don't push duplicate spends
        std_record: TransactionRecord = replace(create_launcher_tx_record, spend_bundle=None)
        # TODO (Standalone merge): Add memos field
        dl_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=bytes32([2]*32),
            amount=uint64(1),
            fee_amount=fee,
            confirmed=False,
            sent=uint32(10),
            spend_bundle=full_spend,
            additions=launcher_sb.additions(),
            removals=launcher_sb.removals(),
            wallet_id=uint32(0),  # This is being called before the wallet is created so we're using a temp ID of 0
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=launcher_sb.name(),
        )
        return [dl_record, std_record], parents, launcher_coin, inner_puzzle

    async def create_update_state_spend(
        self,
        root_hash: bytes32,
    ) -> TransactionRecord:
        new_inner_inner_puzzle = await self.standard_wallet.get_new_puzzle()
        new_db_layer_puzzle = create_host_layer_puzzle(new_inner_inner_puzzle, root_hash)
        primaries = [({"puzzlehash": new_db_layer_puzzle.get_tree_hash(), "amount": self.tip_coin.amount})]
        inner_inner_sol = self.standard_wallet.make_solution(primaries=primaries)
        db_layer_sol = Program.to([0, inner_inner_sol])
        parent_info = await self.get_parent_for_coin(self.tip_coin)
        assert parent_info is not None

        assert self.dl_info.origin_coin is not None
        current_full_puz = create_host_fullpuz(
            self.dl_info.current_inner_inner,
            self.dl_info.root_hash,
            self.dl_info.origin_coin.name(),
        )
        full_sol = Program.to(
            [
                parent_info,
                self.tip_coin.amount,
                db_layer_sol,
            ]
        )
        future_parent = LineageProof(
            self.tip_coin.name(),
            create_host_layer_puzzle(self.dl_info.current_inner_inner, self.dl_info.root_hash).get_tree_hash(),
            self.tip_coin.amount,
        )
        await self.add_parent(self.tip_coin.name(), future_parent, False)
        coin_spend = CoinSpend(
            self.tip_coin, SerializedProgram.from_program(current_full_puz), SerializedProgram.from_program(full_sol)
        )

        spend_bundle = await self.sign(coin_spend)
        new_info = DataLayerInfo(
            origin_coin=self.dl_info.origin_coin,
            root_hash=root_hash,
            parent_info=self.dl_info.parent_info,
            current_inner_inner=new_inner_inner_puzzle,
        )
        await self.save_info(new_info, False)  # todo in_transaction false ?
        next_full_puz = create_host_fullpuz(new_inner_inner_puzzle, root_hash, self.dl_info.origin_coin.name())
        await self.wallet_state_manager.interested_store.add_interested_puzzle_hash(
            next_full_puz.get_tree_hash(), self.wallet_id
        )
        self.tip_coin = Coin(self.tip_coin.name(), next_full_puz.get_tree_hash(), self.tip_coin.amount)
        dl_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=new_db_layer_puzzle.get_tree_hash(),
            amount=uint64(self.tip_coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(10),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=bytes32(token_bytes()),
        )
        await self.standard_wallet.push_transaction(dl_record)
        return dl_record

    async def create_report_spend(self) -> Tuple[SpendBundle, Announcement]:
        # (my_puzhash . my_amount)
        db_layer_sol = Program.to([1, (self.tip_coin.puzzle_hash, self.tip_coin.amount)])
        parent_info = await self.get_parent_for_coin(self.tip_coin)
        assert parent_info is not None
        assert self.dl_info.origin_coin is not None
        current_full_puz = create_host_fullpuz(
            self.dl_info.current_inner_inner,
            self.dl_info.root_hash,
            self.dl_info.origin_coin.name(),
        )
        full_sol = Program.to(
            [
                parent_info,
                self.tip_coin.amount,
                db_layer_sol,
            ]
        )
        coin_spend = CoinSpend(
            self.tip_coin, SerializedProgram.from_program(current_full_puz), SerializedProgram.from_program(full_sol)
        )
        future_parent = LineageProof(
            self.tip_coin.name(),
            create_host_layer_puzzle(self.dl_info.current_inner_inner, self.dl_info.root_hash).get_tree_hash(),
            self.tip_coin.amount,
        )
        await self.add_parent(self.tip_coin.name(), future_parent, False)
        self.tip_coin = Coin(self.tip_coin.name(), self.tip_coin.puzzle_hash, self.tip_coin.amount)
        spend_bundle = SpendBundle([coin_spend], AugSchemeMPL.aggregate([]))

        return spend_bundle, Announcement(self.tip_coin.puzzle_hash, self.dl_info.root_hash)

    async def get_info_for_offer_claim(
        self,
    ) -> Tuple[Program, Optional[Program], bytes32]:
        origin_coin = self.dl_info.origin_coin
        if origin_coin is None:
            raise ValueError("Non-None origin coin required")
        current_full_puz = create_host_fullpuz(
            self.dl_info.current_inner_inner,
            self.dl_info.root_hash,
            origin_coin.name(),
        )
        db_innerpuz_hash = self.dl_info.current_inner_inner
        current_root = self.dl_info.root_hash
        return current_full_puz, db_innerpuz_hash, current_root

    async def select_coins(self, amount: uint64, exclude: List[Coin] = []) -> Optional[Set[Coin]]:
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
        used_coins: Set[Coin] = set()

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
        inner_inner_puz = self.standard_wallet.puzzle_for_pk(pubkey)
        innerpuz = create_host_layer_puzzle(inner_inner_puz, self.dl_info.root_hash)
        if self.dl_info.origin_coin is not None:
            # TODO: Remove ignore when done.
            #       https://github.com/Chia-Network/clvm/pull/102
            #       https://github.com/Chia-Network/clvm/pull/106
            return create_singleton_fullpuz(self.dl_info.origin_coin.name(), innerpuz)  # type: ignore[no-any-return]

        # TODO: Remove ignore when done.
        #       https://github.com/Chia-Network/clvm/pull/102
        #       https://github.com/Chia-Network/clvm/pull/106
        return create_singleton_fullpuz(0x00, innerpuz)  # type: ignore[no-any-return]

    async def get_new_puzzle(self) -> Program:
        return self.puzzle_for_pk(
            bytes((await self.wallet_state_manager.get_unused_derivation_record(self.wallet_info.id)).pubkey)
        )

    async def get_parent_for_coin(self, coin: Coin) -> Optional[List[Any]]:
        parent_info = None
        for name, parent in self.dl_info.parent_info:
            if name == coin.parent_coin_info:
                parent_info = parent

        if parent_info is None:
            # TODO: is it ok to log the coin info
            raise ValueError("Unable to find parent info")

        if self.dl_info.origin_coin is None:
            ret = parent_info.as_list()
        elif parent_info.parent_name == self.dl_info.origin_coin.parent_coin_info:
            ret = [parent_info.parent_name, parent_info.amount]
        else:
            ret = parent_info.as_list()
        return ret

    async def add_parent(self, name: bytes32, parent: Optional[LineageProof], in_transaction: bool) -> None:
        self.log.info(f"Adding parent {name}: {parent}")
        current_list = self.dl_info.parent_info.copy()
        current_list.append((name, parent))
        dl_info: DataLayerInfo = DataLayerInfo(
            self.dl_info.origin_coin,
            self.dl_info.root_hash,
            current_list,
            self.dl_info.current_inner_inner,
        )
        await self.save_info(dl_info, in_transaction)

    async def save_info(self, dl_info: DataLayerInfo, in_transaction: bool) -> None:
        self.dl_info = dl_info
        current_info = self.wallet_info
        data_str = json.dumps(dl_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info, in_transaction)
        return

    async def new_peak(self, peak: BlockRecord) -> None:
        pass

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint64:
        if record_list is None:
            record_list = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.id())

        amount: uint64 = uint64(0)
        for record in record_list:
            parent = await self.get_parent_for_coin(record.coin)
            if parent is not None:
                amount = uint64(amount + record.coin.amount)

        self.log.info(f"Confirmed balance for dl wallet is {amount}")
        return uint64(amount)

    async def get_unconfirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        confirmed = await self.get_confirmed_balance(record_list)
        # TODO: remove ignore after fixing sized bytes type hints
        return await self.wallet_state_manager._get_unconfirmed_balance(  # type: ignore[no-any-return]
            self.id(),
            confirmed,
        )

    async def get_spendable_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        spendable_am = await self.wallet_state_manager.get_confirmed_spendable_balance_for_wallet(
            self.wallet_info.id, unspent_records
        )
        # TODO: remove ignore after fixing sized bytes type hints
        return spendable_am  # type: ignore[no-any-return]

    async def sign(self, coin_spend: CoinSpend) -> SpendBundle:
        return await sign_coin_spends(
            [coin_spend],
            self.standard_wallet.secret_key_store.secret_key_for_public_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )
