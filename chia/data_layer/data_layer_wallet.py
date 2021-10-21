import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple, Set, List

from blspy import G2Element

from chia.clvm.singleton import SINGLETON_LAUNCHER
from chia.pools.pool_puzzles import create_full_puzzle
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo


@dataclass(frozen=True)
@streamable
class DataLayerInfo(Streamable):
    origin_coin: Optional[Coin]  # Coin ID of this coin is our DID
    root_hash: bytes
    # num_of_backup_ids_needed: uint64
    # parent_info: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): LineageProof}
    # current_inner: Optional[Program]  # represents a Program as bytes
    # temp_coin: Optional[Coin]  # partially recovered wallet uses these to hold info
    # temp_puzhash: Optional[bytes32]
    # temp_pubkey: Optional[bytes]
    # sent_recovery_transaction: bool


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
        await self.wallet_state_manager.pool_store.add_spend(self.wallet_id, launcher_spend, block_height)
        await self.update_pool_config(True)

        p2_puzzle_hash: bytes32 = (await self.get_current_state()).p2_singleton_puzzle_hash
        await self.wallet_state_manager.interested_store.add_interested_puzzle_hash(
            p2_puzzle_hash, self.wallet_id, True
        )

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id, create_puzzle_hashes=False)
        self.wallet_state_manager.set_new_peak_callback(self.wallet_id, self.new_peak)
        return self

    @staticmethod
    async def create_new_data_layer_wallet_transaction(
        wallet_state_manager: Any,
        main_wallet: Wallet,
        root_hash: bytes,
        fee: uint64 = uint64(0),
    ) -> Tuple[TransactionRecord, bytes32]:
        amount = 1
        standard_wallet = main_wallet

        unspent_records = await wallet_state_manager.coin_store.get_unspent_coins_for_wallet(standard_wallet.wallet_id)
        balance = await standard_wallet.get_confirmed_balance(unspent_records)
        if balance < DataLayerWallet.MINIMUM_INITIAL_BALANCE:
            raise ValueError("Not enough balance in main wallet .")
        if balance < fee:
            raise ValueError("Not enough balance in main wallet to create a managed plotting pool with fee {fee}.")

        spend_bundle, singleton_puzzle_hash, launcher_coin_id = await DataLayerWallet.generate_launcher_spend(
            standard_wallet, amount, root_hash
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
            wallet_id=wallet_state_manager.main_wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
        )
        await standard_wallet.push_transaction(standard_wallet_record)
        # p2_singleton_puzzle_hash: bytes32 = launcher_id_to_p2_puzzle_hash(
        #     launcher_coin_id, p2_singleton_delay_time, p2_singleton_delayed_ph
        # )
        return standard_wallet_record, launcher_coin_id

    @staticmethod
    async def generate_launcher_spend(
        standard_wallet: Wallet,
        amount: uint64,
        initial_target_state: bytes32,
    ) -> Tuple[SpendBundle, bytes32, bytes32]:
        """
        Creates the initial singleton, which includes spending an origin coin, the launcher, and creating a singleton
        """

        coins: Set[Coin] = await standard_wallet.select_coins(amount)
        if coins is None:
            raise ValueError("Not enough coins to create pool wallet")

        assert len(coins) == 1

        launcher_parent: Coin = coins.copy().pop()
        genesis_launcher_puz: Program = SINGLETON_LAUNCHER
        launcher_coin: Coin = Coin(launcher_parent.name(), genesis_launcher_puz.get_tree_hash(), amount)

        puzzle: Program = create_data_layer_inner_puzzle()
        full_puzzle: Program = create_full_puzzle(puzzle, launcher_id=launcher_coin.name())
        puzzle_hash: bytes32 = full_puzzle.get_tree_hash()

        # announcement_set: Set[Announcement] = set()
        # announcement_message = Program.to([puzzle_hash, amount, initial_target_state]).get_tree_hash()
        # announcement_set.add(Announcement(launcher_coin.name(), announcement_message).name())

        create_launcher_tx_record: Optional[TransactionRecord] = await standard_wallet.generate_signed_transaction(
            amount,
            genesis_launcher_puz.get_tree_hash(),
            uint64(0),
            None,
            coins,
            None,
            False,
            None,
        )
        assert create_launcher_tx_record is not None and create_launcher_tx_record.spend_bundle is not None
        genesis_launcher_solution: Program = Program.to([puzzle_hash, amount, initial_target_state])
        launcher_cs: CoinSpend = CoinSpend(
            launcher_coin,
            SerializedProgram.from_program(genesis_launcher_puz),
            SerializedProgram.from_program(genesis_launcher_solution),
        )
        launcher_sb: SpendBundle = SpendBundle([launcher_cs], G2Element())
        full_spend: SpendBundle = SpendBundle.aggregate([create_launcher_tx_record.spend_bundle, launcher_sb])
        return full_spend, puzzle_hash, launcher_coin.name()

    @staticmethod
    async def update_state_transition(
        wallet_state_manager: Any,
        main_wallet: Wallet,
        root_hash: bytes,
    ):
        return None

    async def get_current_state(self) -> DataLayerInfo:
        # history: List[Tuple[uint32, CoinSpend]] = await self.get_spend_history()
        # all_spends: List[CoinSpend] = [cs for _, cs in history]
        #
        # # We must have at least the launcher spend
        # assert len(all_spends) >= 1
        #
        # launcher_coin: Coin = all_spends[0].coin
        # delayed_seconds, delayed_puzhash = get_delayed_puz_info_from_launcher_spend(all_spends[0])
        # tip_singleton_coin: Optional[Coin] = get_most_recent_singleton_coin_from_coin_spend(all_spends[-1])
        # launcher_id: bytes32 = launcher_coin.name()
        # p2_singleton_puzzle_hash = launcher_id_to_p2_puzzle_hash(launcher_id, delayed_seconds, delayed_puzhash)
        # assert tip_singleton_coin is not None
        #
        # curr_spend_i = len(all_spends) - 1
        # pool_state: Optional[PoolState] = None
        # last_singleton_spend_height = uint32(0)
        # while pool_state is None:
        #     full_spend: CoinSpend = all_spends[curr_spend_i]
        #     pool_state = solution_to_pool_state(full_spend)
        #     last_singleton_spend_height = uint32(history[curr_spend_i][0])
        #     curr_spend_i -= 1
        #
        # assert pool_state is not None
        # current_inner = pool_state_to_inner_puzzle(
        #     pool_state,
        #     launcher_coin.name(),
        #     self.wallet_state_manager.constants.GENESIS_CHALLENGE,
        #     delayed_seconds,
        #     delayed_puzhash,
        # )
        return DataLayerInfo(origin_coin=None, root_hash=b"")


def create_data_layer_inner_puzzle():
    # todo implement
    return Program.to(b"")
