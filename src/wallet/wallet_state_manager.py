import base64
import json
import time
from pathlib import Path

from typing import Dict, Optional, List, Set, Tuple, Callable, Any
import logging
import asyncio

import aiosqlite
from chiabip158 import PyBIP158
from blspy import PrivateKey, G1Element, AugSchemeMPL
from cryptography.fernet import Fernet

from src.consensus.constants import ConsensusConstants
from src.types.coin import Coin
from src.types.sized_bytes import bytes32
from src.types.full_block import FullBlock
from src.types.challenge import Challenge
from src.types.header_block import HeaderBlock
from src.util.byte_types import hexstr_to_bytes
from src.util.ints import uint32, uint64
from src.util.hash import std_hash
from src.wallet.cc_wallet.cc_wallet import CCWallet
from src.wallet.key_val_store import KeyValStore
from src.wallet.settings.user_settings import UserSettings
from src.wallet.rl_wallet.rl_wallet import RLWallet
from src.wallet.trade_manager import TradeManager
from src.wallet.transaction_record import TransactionRecord
from src.wallet.block_record import BlockRecord
from src.wallet.util.backup_utils import open_backup_file
from src.wallet.wallet_action import WalletAction
from src.wallet.wallet_action_store import WalletActionStore
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo, WalletInfoBackup
from src.wallet.wallet_puzzle_store import WalletPuzzleStore
from src.wallet.wallet_store import WalletStore
from src.wallet.wallet_transaction_store import WalletTransactionStore
from src.full_node.blockchain import ReceiveBlockResult
from src.consensus.pot_iterations import calculate_iterations_quality
from src.util.significant_bits import truncate_to_significant_bits
from src.wallet.wallet_user_store import WalletUserStore
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.util.errors import Err
from src.wallet.wallet import Wallet
from src.types.program import Program
from src.wallet.derivation_record import DerivationRecord
from src.wallet.util.wallet_types import WalletType
from src.consensus.find_fork_point import find_fork_point_in_chain
from src.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_backup_sk
from src import __version__


class WalletStateManager:
    constants: ConsensusConstants
    config: Dict
    wallet_store: WalletStore
    tx_store: WalletTransactionStore
    puzzle_store: WalletPuzzleStore
    user_store: WalletUserStore
    action_store: WalletActionStore
    basic_store: KeyValStore
    # Map from header hash to BlockRecord
    block_records: Dict[bytes32, BlockRecord]
    # Specifies the LCA path
    height_to_hash: Dict[uint32, bytes32]
    # Map from previous header hash, to new work difficulty
    difficulty_resets_prev: Dict[bytes32, uint64]
    # Header hash of tip (least common ancestor)
    lca: Optional[bytes32]
    start_index: int

    # Makes sure only one asyncio thread is changing the blockchain state at one time
    lock: asyncio.Lock

    log: logging.Logger

    # TODO Don't allow user to send tx until wallet is synced
    sync_mode: bool
    genesis: FullBlock

    state_changed_callback: Optional[Callable]
    pending_tx_callback: Optional[Callable]
    db_path: Path
    db_connection: aiosqlite.Connection

    main_wallet: Wallet
    wallets: Dict[uint32, Any]
    private_key: PrivateKey

    trade_manager: TradeManager
    generate_count: int
    user_settings: UserSettings

    @staticmethod
    async def create(
        private_key: PrivateKey,
        config: Dict,
        db_path: Path,
        constants: ConsensusConstants,
        name: str = None,
        testing: bool = False,
    ):
        self = WalletStateManager()
        self.config = config
        self.constants = constants

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)
        self.lock = asyncio.Lock()

        self.db_connection = await aiosqlite.connect(db_path)
        self.wallet_store = await WalletStore.create(self.db_connection)
        self.tx_store = await WalletTransactionStore.create(self.db_connection)
        self.puzzle_store = await WalletPuzzleStore.create(self.db_connection)
        self.user_store = await WalletUserStore.create(self.db_connection)
        self.action_store = await WalletActionStore.create(self.db_connection)
        self.basic_store = await KeyValStore.create(self.db_connection)
        self.trade_manager = await TradeManager.create(self, self.db_connection)

        self.user_settings = await UserSettings.create(self.basic_store)
        self.lca = None
        self.sync_mode = False
        self.height_to_hash = {}
        self.block_records = await self.wallet_store.get_lca_path()
        genesis = FullBlock.from_bytes(self.constants.GENESIS_BLOCK)
        self.genesis = genesis
        self.state_changed_callback = None
        self.pending_tx_callback = None
        self.difficulty_resets_prev = {}
        self.db_path = db_path
        if testing is True:
            self.generate_count = 10
        else:
            self.generate_count = 100
        main_wallet_info = await self.user_store.get_wallet_by_id(1)
        assert main_wallet_info is not None

        self.private_key = private_key

        self.main_wallet = await Wallet.create(self, main_wallet_info)

        self.wallets = {}
        self.wallets[main_wallet_info.id] = self.main_wallet

        for wallet_info in await self.get_all_wallets():
            # self.log.info(f"wallet_info {wallet_info}")
            if wallet_info.type == WalletType.STANDARD_WALLET.value:
                if wallet_info.id == 1:
                    continue
                wallet = await Wallet.create(config, wallet_info)
                self.wallets[wallet_info.id] = wallet
            elif wallet_info.type == WalletType.COLOURED_COIN.value:
                wallet = await CCWallet.create(self, self.main_wallet, wallet_info,)
                self.wallets[wallet_info.id] = wallet
            elif wallet_info.type == WalletType.RATE_LIMITED.value:
                wallet = await RLWallet.create(self, wallet_info)
                self.wallets[wallet_info.id] = wallet

        async with self.puzzle_store.lock:
            index = await self.puzzle_store.get_last_derivation_path()
            if index is None or index < self.config["initial_num_public_keys"]:
                await self.create_more_puzzle_hashes(from_zero=True)

        if len(self.block_records) > 0:
            # Initializes the state based on the DB block records
            # Header hash with the highest weight
            self.lca = max(
                (item[1].weight, item[0]) for item in self.block_records.items()
            )[1]
            for key, value in self.block_records.items():
                self.height_to_hash[value.height] = value.header_hash

            # Checks genesis block is the same in config, as in DB
            assert self.block_records[genesis.header_hash].height == 0
            assert self.block_records[genesis.header_hash].weight == genesis.weight
        else:
            # Loads the genesis block if there are no blocks
            genesis_challenge = Challenge(
                genesis.proof_of_space.challenge_hash,
                std_hash(
                    genesis.proof_of_space.get_hash()
                    + genesis.proof_of_time.output.get_hash()
                ),
                None,
            )
            genesis_hb = HeaderBlock(
                genesis.proof_of_space,
                genesis.proof_of_time,
                genesis_challenge,
                genesis.header,
            )
            await self.receive_block(
                BlockRecord(
                    genesis.header_hash,
                    genesis.prev_header_hash,
                    uint32(0),
                    genesis.weight,
                    genesis.additions(),
                    [],
                    genesis_hb.header.data.total_iters,
                    genesis_challenge.get_hash(),
                ),
                genesis_hb,
            )

        return self

    def get_derivation_index(self, pubkey: G1Element, max_depth: int = 1000) -> int:
        for i in range(0, max_depth):
            derived = self.get_public_key(uint32(i))
            if derived == pubkey:
                return i
        return -1

    def get_public_key(self, index: uint32) -> G1Element:
        return master_sk_to_wallet_sk(self.private_key, index).get_g1()

    async def load_wallets(self):
        for wallet_info in await self.get_all_wallets():
            if wallet_info.id in self.wallets:
                continue
            if wallet_info.type == WalletType.STANDARD_WALLET.value:
                if wallet_info.id == 1:
                    continue
                wallet = await Wallet.create(self.config, wallet_info)
                self.wallets[wallet_info.id] = wallet
            elif wallet_info.type == WalletType.COLOURED_COIN.value:
                wallet = await CCWallet.create(self, self.main_wallet, wallet_info,)
                self.wallets[wallet_info.id] = wallet

    async def get_keys(self, hash: bytes32) -> Optional[Tuple[G1Element, PrivateKey]]:
        index_for_puzzlehash = await self.puzzle_store.index_for_puzzle_hash(hash)
        if index_for_puzzlehash is None:
            raise ValueError(f"No key for this puzzlehash {hash})")
        private = master_sk_to_wallet_sk(self.private_key, index_for_puzzlehash)
        pubkey = private.get_g1()
        return pubkey, private

    async def create_more_puzzle_hashes(self, from_zero: bool = False):
        """
        For all wallets in the user store, generates the first few puzzle hashes so
        that we can restore the wallet from only the private keys.
        """
        targets = list(self.wallets.keys())

        unused: Optional[uint32] = await self.puzzle_store.get_unused_derivation_path()
        if unused is None:
            # This handles the case where the database has entries but they have all been used
            unused = await self.puzzle_store.get_last_derivation_path()
            if unused is None:
                # This handles the case where the database is empty
                unused = uint32(0)

        to_generate = self.config["initial_num_public_keys"]

        for wallet_id in targets:
            target_wallet = self.wallets[wallet_id]

            last: Optional[
                uint32
            ] = await self.puzzle_store.get_last_derivation_path_for_wallet(wallet_id)

            start_index = 0
            derivation_paths: List[DerivationRecord] = []

            if last is not None:
                start_index = last + 1

            # If the key was replaced (from_zero=True), we should generate the puzzle hashes for the new key
            if from_zero:
                start_index = 0

            for index in range(start_index, unused + to_generate):
                if (
                    WalletType(target_wallet.wallet_info.type)
                    == WalletType.RATE_LIMITED
                ):
                    if target_wallet.rl_info.initialized is False:
                        break
                    type = target_wallet.rl_info.type
                    if type == "user":
                        rl_pubkey = G1Element.from_bytes(
                            target_wallet.rl_info.user_pubkey
                        )
                    else:
                        rl_pubkey = G1Element.from_bytes(
                            target_wallet.rl_info.admin_pubkey
                        )
                    rl_puzzle: Program = target_wallet.puzzle_for_pk(rl_pubkey)
                    puzzle_hash: bytes32 = rl_puzzle.get_tree_hash()

                    rl_index = self.get_derivation_index(rl_pubkey)
                    if rl_index == -1:
                        break

                    derivation_paths.append(
                        DerivationRecord(
                            uint32(rl_index),
                            puzzle_hash,
                            rl_pubkey,
                            target_wallet.wallet_info.type,
                            uint32(target_wallet.wallet_info.id),
                        )
                    )
                    break

                pubkey: G1Element = self.get_public_key(uint32(index))
                puzzle: Program = target_wallet.puzzle_for_pk(bytes(pubkey))
                if puzzle is None:
                    self.log.warning(
                        f"Unable to create puzzles with wallet {target_wallet}"
                    )
                    break
                puzzlehash: bytes32 = puzzle.get_tree_hash()
                self.log.info(
                    f"Puzzle at index {index} wallet ID {wallet_id} puzzle hash {puzzlehash.hex()}"
                )
                derivation_paths.append(
                    DerivationRecord(
                        uint32(index),
                        puzzlehash,
                        pubkey,
                        target_wallet.wallet_info.type,
                        uint32(target_wallet.wallet_info.id),
                    )
                )

            await self.puzzle_store.add_derivation_paths(derivation_paths)
        if unused > 0:
            await self.puzzle_store.set_used_up_to(uint32(unused - 1))

    async def get_unused_derivation_record(self, wallet_id: uint32) -> DerivationRecord:
        """
        Creates a puzzle hash for the given wallet, and then makes more puzzle hashes
        for every wallet to ensure we always have more in the database. Never reusue the
        same public key more than once (for privacy).
        """
        async with self.puzzle_store.lock:
            # If we have no unused public keys, we will create new ones
            unused: Optional[
                uint32
            ] = await self.puzzle_store.get_unused_derivation_path()
            if unused is None:
                await self.create_more_puzzle_hashes()

            # Now we must have unused public keys
            unused = await self.puzzle_store.get_unused_derivation_path()
            assert unused is not None
            record: Optional[
                DerivationRecord
            ] = await self.puzzle_store.get_derivation_record(unused, wallet_id)
            assert record is not None

            # Set this key to used so we never use it again
            await self.puzzle_store.set_used_up_to(record.index)

            # Create more puzzle hashes / keys
            await self.create_more_puzzle_hashes()
            return record

    def set_callback(self, callback: Callable):
        """
        Callback to be called when the state of the wallet changes.
        """
        self.state_changed_callback = callback

    def set_pending_callback(self, callback: Callable):
        """
        Callback to be called when new pending transaction enters the store
        """
        self.pending_tx_callback = callback

    def state_changed(self, state: str, wallet_id: int = None, data_object={}):
        """
        Calls the callback if it's present.
        """
        if self.state_changed_callback is None:
            return
        self.state_changed_callback(state, wallet_id, data_object)

    def tx_pending_changed(self):
        """
        Notifies the wallet node that there's new tx pending
        """
        if self.pending_tx_callback is None:
            return

        self.pending_tx_callback()

    def set_sync_mode(self, mode: bool):
        """
        Sets the sync mode. This changes the behavior of the wallet node.
        """
        self.sync_mode = mode
        self.state_changed("sync_changed")

    async def get_confirmed_spendable_balance_for_wallet(
        self, wallet_id: int
    ) -> uint64:
        """
        Returns the balance amount of all coins that are spendable.
        """
        spendable: Set[WalletCoinRecord] = await self.get_spendable_coins_for_wallet(
            wallet_id
        )

        amount: uint64 = uint64(0)

        for record in spendable:
            amount = uint64(amount + record.coin.amount)

        return uint64(amount)

    async def does_coin_belong_to_wallet(self, coin: Coin, wallet_id: int) -> bool:
        """
        Returns true if we have the key for this coin.
        """
        info = await self.puzzle_store.wallet_info_for_puzzle_hash(coin.puzzle_hash)

        if info is None:
            return False

        coin_wallet_id, wallet_type = info
        if wallet_id == coin_wallet_id:
            return True

        return False

    async def get_confirmed_balance_for_wallet(self, wallet_id: int) -> uint64:
        """
        Returns the confirmed balance, including coinbase rewards that are not spendable.
        """
        record_list: Set[
            WalletCoinRecord
        ] = await self.wallet_store.get_unspent_coins_for_wallet(wallet_id)
        amount: uint64 = uint64(0)

        for record in record_list:
            amount = uint64(amount + record.coin.amount)
        self.log.info(f"Confirmed balance amount is {amount}")
        return uint64(amount)

    async def get_unconfirmed_balance(self, wallet_id) -> uint64:
        """
        Returns the balance, including coinbase rewards that are not spendable, and unconfirmed
        transactions.
        """
        confirmed = await self.get_confirmed_balance_for_wallet(wallet_id)
        unconfirmed_tx: List[
            TransactionRecord
        ] = await self.tx_store.get_unconfirmed_for_wallet(wallet_id)
        removal_amount = 0

        for record in unconfirmed_tx:

            removal_amount += record.amount
            removal_amount += record.fee_amount

        result = confirmed - removal_amount
        return uint64(result)

    async def get_frozen_balance(self, wallet_id: int) -> uint64:
        current_index = self.block_records[self.lca].height

        coinbase_freeze_period = self.constants.COINBASE_FREEZE_PERIOD

        valid_index = current_index - coinbase_freeze_period

        not_frozen: Set[
            WalletCoinRecord
        ] = await self.wallet_store.get_spendable_for_index(valid_index, wallet_id)
        all_records: Set[
            WalletCoinRecord
        ] = await self.wallet_store.get_spendable_for_index(current_index, wallet_id)
        sum_not_frozen = sum(
            record.coin.amount for record in not_frozen if record.coinbase
        )
        sum_all_records = sum(
            record.coin.amount for record in all_records if record.coinbase
        )
        return uint64(sum_all_records - sum_not_frozen)

    async def unconfirmed_additions_for_wallet(
        self, wallet_id: int
    ) -> Dict[bytes32, Coin]:
        """
        Returns change coins for the wallet_id.
        (Unconfirmed addition transactions that have not been confirmed yet.)
        """
        additions: Dict[bytes32, Coin] = {}
        unconfirmed_tx = await self.tx_store.get_unconfirmed_for_wallet(wallet_id)
        for record in unconfirmed_tx:
            for coin in record.additions:
                if await self.is_addition_relevant(coin):
                    additions[coin.name()] = coin
        return additions

    async def unconfirmed_removals_for_wallet(
        self, wallet_id: int
    ) -> Dict[bytes32, Coin]:
        """
        Returns new removals transactions that have not been confirmed yet.
        """
        removals: Dict[bytes32, Coin] = {}
        unconfirmed_tx = await self.tx_store.get_unconfirmed_for_wallet(wallet_id)
        for record in unconfirmed_tx:
            for coin in record.removals:
                removals[coin.name()] = coin
        return removals

    async def coins_of_interest_received(
        self, removals: List[Coin], additions: List[Coin], height: uint32
    ):
        trade_additions = await self.coins_of_interest_added(additions, height)
        trade_removals = await self.coins_of_interest_removed(removals, height)
        if len(trade_additions) > 0 or len(trade_removals) > 0:
            await self.trade_manager.coins_of_interest_farmed(
                trade_removals, trade_additions, height
            )

    async def coins_of_interest_added(
        self, coins: List[Coin], height: uint32
    ) -> List[Coin]:
        (
            trade_removals,
            trade_additions,
        ) = await self.trade_manager.get_coins_of_interest()
        trade_adds: List[Coin] = []
        for coin in coins:
            if coin.name() in trade_additions:
                trade_adds.append(coin)

            is_coinbase = False

            if (
                bytes32((height).to_bytes(32, "big")) == coin.parent_coin_info
                or std_hash(std_hash(height)) == coin.parent_coin_info
            ):
                is_coinbase = True

            info = await self.puzzle_store.wallet_info_for_puzzle_hash(coin.puzzle_hash)
            if info is not None:
                wallet_id, wallet_type = info
                await self.coin_added(
                    coin, height, is_coinbase, uint32(wallet_id), wallet_type
                )

        return trade_adds

    async def coins_of_interest_removed(
        self, coins: List[Coin], height: uint32
    ) -> List[Coin]:
        "This get's called when coins of our interest are spent on chain"
        (
            trade_removals,
            trade_additions,
        ) = await self.trade_manager.get_coins_of_interest()

        # Keep track of trade coins that are removed
        trade_coin_removed: List[Coin] = []

        for coin in coins:
            self.log.info(f"Coin removed: {coin.name()}")
            record = await self.wallet_store.get_coin_record_by_coin_id(coin.name())
            if coin.name() in trade_removals:
                self.log.info(f"Coin:{coin.name()} is part of trade")
                trade_coin_removed.append(coin)
            if record is None:
                self.log.info(f"Coin:{coin.name()} NO RECORD")
                continue
            self.log.info(f"Coin:{coin.name()} Setting removed")
            await self.coin_removed(coin, height, record.wallet_id)

        return trade_coin_removed

    async def coin_removed(self, coin: Coin, index: uint32, wallet_id: int):
        """
        Called when coin gets spent
        """

        await self.wallet_store.set_spent(coin.name(), index)

        unconfirmed_record: List[
            TransactionRecord
        ] = await self.tx_store.unconfirmed_with_removal_coin(coin.name())
        for unconfirmed in unconfirmed_record:
            await self.tx_store.set_confirmed(unconfirmed.name(), index)

        self.state_changed("coin_removed", wallet_id)

    async def coin_added(
        self,
        coin: Coin,
        index: uint32,
        coinbase: bool,
        wallet_id: uint32,
        wallet_type: WalletType,
    ):
        """
        Adding coin to DB
        """
        if coinbase:
            now = uint64(int(time.time()))
            tx_record = TransactionRecord(
                confirmed_at_index=uint32(index),
                created_at_time=now,
                to_puzzle_hash=coin.puzzle_hash,
                amount=coin.amount,
                fee_amount=uint64(0),
                incoming=True,
                confirmed=True,
                sent=uint32(0),
                spend_bundle=None,
                additions=[coin],
                removals=[],
                wallet_id=wallet_id,
                sent_to=[],
                trade_id=None,
            )
            await self.tx_store.add_transaction_record(tx_record)
        else:
            records = await self.tx_store.tx_with_addition_coin(coin.name(), wallet_id)

            if len(records) > 0:
                # This is the change from this transaction
                for record in records:
                    if record.confirmed is False:
                        await self.tx_store.set_confirmed(record.name(), index)
            else:
                now = uint64(int(time.time()))
                tx_record = TransactionRecord(
                    confirmed_at_index=uint32(index),
                    created_at_time=now,
                    to_puzzle_hash=coin.puzzle_hash,
                    amount=coin.amount,
                    fee_amount=uint64(0),
                    incoming=True,
                    confirmed=True,
                    sent=uint32(0),
                    spend_bundle=None,
                    additions=[coin],
                    removals=[],
                    wallet_id=wallet_id,
                    sent_to=[],
                    trade_id=None,
                )
                if coin.amount > 0:
                    await self.tx_store.add_transaction_record(tx_record)

        coin_record: WalletCoinRecord = WalletCoinRecord(
            coin, index, uint32(0), False, coinbase, wallet_type, wallet_id
        )
        await self.wallet_store.add_coin_record(coin_record)

        if wallet_type == WalletType.COLOURED_COIN:
            wallet: CCWallet = self.wallets[wallet_id]
            header_hash: bytes32 = self.height_to_hash[index]
            block: Optional[BlockRecord] = await self.wallet_store.get_block_record(
                header_hash
            )
            assert block is not None
            assert block.removals is not None
            await wallet.coin_added(coin, index, header_hash, block.removals)

        self.state_changed("coin_added", wallet_id)

    async def add_pending_transaction(self, tx_record: TransactionRecord):
        """
        Called from wallet before new transaction is sent to the full_node
        """

        # Wallet node will use this queue to retry sending this transaction until full nodes receives it
        await self.tx_store.add_transaction_record(tx_record)
        self.tx_pending_changed()
        self.state_changed("pending_transaction", tx_record.wallet_id)

    async def add_transaction(self, tx_record: TransactionRecord):
        """
        Called from wallet to add transaction that is not being set to full_node
        """
        await self.tx_store.add_transaction_record(tx_record)
        self.state_changed("pending_transaction", tx_record.wallet_id)

    async def remove_from_queue(
        self,
        spendbundle_id: bytes32,
        name: str,
        send_status: MempoolInclusionStatus,
        error: Optional[Err],
    ):
        """
        Full node received our transaction, no need to keep it in queue anymore
        """
        updated = await self.tx_store.increment_sent(
            spendbundle_id, name, send_status, error
        )
        if updated:
            tx: Optional[TransactionRecord] = await self.get_transaction(spendbundle_id)
            if tx is not None:
                self.state_changed("tx_update", tx.wallet_id, {"transaction": tx})

    async def get_send_queue(self) -> List[TransactionRecord]:
        """
        Wallet Node uses this to retry sending transactions
        """
        records = await self.tx_store.get_not_sent()
        return records

    async def get_all_transactions(self, wallet_id: int) -> List[TransactionRecord]:
        """
        Retrieves all confirmed and pending transactions
        """
        records = await self.tx_store.get_all_transactions(wallet_id)
        return records

    async def get_transaction(self, tx_id: bytes32) -> Optional[TransactionRecord]:
        return await self.tx_store.get_transaction_record(tx_id)

    def find_fork_point_alternate_chain(self, alternate_chain: List[bytes32]) -> uint32:
        """
        Takes in an alternate blockchain (headers), and compares it to self. Returns the last header
        where both blockchains are equal. Used for syncing.
        """
        lca: BlockRecord = self.block_records[self.lca]

        if lca.height >= len(alternate_chain) - 1:
            raise ValueError("Alternate chain is shorter")
        low: uint32 = uint32(0)
        high = lca.height
        while low + 1 < high:
            mid = uint32((low + high) // 2)
            if self.height_to_hash[uint32(mid)] != alternate_chain[mid]:
                high = mid
            else:
                low = mid
        if low == high and low == 0:
            assert self.height_to_hash[uint32(0)] == alternate_chain[0]
            return uint32(0)
        assert low + 1 == high
        if self.height_to_hash[uint32(low)] == alternate_chain[low]:
            if self.height_to_hash[uint32(high)] == alternate_chain[high]:
                return high
            else:
                return low
        elif low > 0:
            assert self.height_to_hash[uint32(low - 1)] == alternate_chain[low - 1]
            return uint32(low - 1)
        else:
            raise ValueError("Invalid genesis block")

    async def receive_block(
        self, block: BlockRecord, header_block: Optional[HeaderBlock] = None,
    ) -> ReceiveBlockResult:
        """
        Adds a new block to the blockchain. It doesn't have to be a new tip, can also be an orphan,
        but it must be connected to the blockchain. If a header block is specified, the full header
        and proofs will be validated. Otherwise, the block is added without validation (for use in
        fast sync). If validation succeeds, block is adedd to DB. If it's a new TIP, transactions are
        reorged accordingly.
        """
        assert block.additions is not None
        assert block.removals is not None

        async with self.lock:
            if block.header_hash in self.block_records:
                return ReceiveBlockResult.ALREADY_HAVE_BLOCK

            if block.prev_header_hash not in self.block_records and block.height != 0:
                return ReceiveBlockResult.DISCONNECTED_BLOCK

            if header_block is not None:
                if not await self.validate_header_block(block, header_block):
                    return ReceiveBlockResult.INVALID_BLOCK
                if (
                    (block.height + 1) % self.constants.DIFFICULTY_EPOCH
                    == self.constants.DIFFICULTY_DELAY
                ):
                    assert header_block.challenge.new_work_difficulty is not None
                    self.difficulty_resets_prev[
                        block.header_hash
                    ] = header_block.challenge.new_work_difficulty

            if (block.height + 1) % self.constants.DIFFICULTY_EPOCH == 0:
                assert block.total_iters is not None

            # Block is valid, so add it to the blockchain
            self.block_records[block.header_hash] = block
            await self.wallet_store.add_block_record(block, False)

            # If one of these new additions is ours, generate more puzzle hashes
            phs: List[bytes32] = [addition.puzzle_hash for addition in block.additions]
            block_includes_our_tx: bool = await self.puzzle_store.one_of_puzzle_hashes_exists(
                phs
            )
            if block_includes_our_tx:
                async with self.puzzle_store.lock:
                    for addition in block.additions:
                        record = await self.puzzle_store.get_derivation_record_for_puzzle_hash(
                            addition.puzzle_hash.hex()
                        )
                        if record is None:
                            continue
                        index = record.index
                        await self.puzzle_store.set_used_up_to(index)
                    await self.create_more_puzzle_hashes()

            # Genesis case
            if self.lca is None:
                assert block.height == 0
                await self.wallet_store.add_block_to_path(block.header_hash)
                self.lca = block.header_hash
                await self.coins_of_interest_received(
                    block.removals, block.additions, block.height
                )
                self.height_to_hash[uint32(0)] = block.header_hash
                return ReceiveBlockResult.ADDED_TO_HEAD

            # Not genesis, updated LCA
            if block.weight > self.block_records[self.lca].weight:

                fork_h = find_fork_point_in_chain(
                    self.block_records, self.block_records[self.lca], block
                )
                await self.reorg_rollback(fork_h)

                # Add blocks between fork point and new lca
                fork_hash = self.height_to_hash[fork_h]
                blocks_to_add: List[BlockRecord] = []
                tip_hash: bytes32 = block.header_hash
                while True:
                    if tip_hash == fork_hash or tip_hash == self.genesis.header_hash:
                        break
                    block_record: BlockRecord = self.block_records[tip_hash]
                    blocks_to_add.append(block_record)
                    tip_hash = block_record.prev_header_hash
                blocks_to_add.reverse()

                for path_block in blocks_to_add:
                    self.height_to_hash[path_block.height] = path_block.header_hash
                    await self.wallet_store.add_block_to_path(path_block.header_hash)
                    assert (
                        path_block.additions is not None
                        and path_block.removals is not None
                    )
                    await self.coins_of_interest_received(
                        path_block.removals, path_block.additions, path_block.height
                    )
                self.lca = block.header_hash
                self.state_changed("new_block")
                return ReceiveBlockResult.ADDED_TO_HEAD

            return ReceiveBlockResult.ADDED_AS_ORPHAN

    def get_min_iters(self, block_record: BlockRecord) -> uint64:
        """
        Returns the min_iters value, which is calculated every epoch. This requires looking
        up the epoch barrier blocks, and taking 10% of the total iterations in the previous
        epoch.
        """
        curr = block_record
        if (
            curr.height
            < self.constants.DIFFICULTY_EPOCH + self.constants.DIFFICULTY_DELAY
        ):
            return self.constants.MIN_ITERS_STARTING
        if (
            curr.height % self.constants.DIFFICULTY_EPOCH
            < self.constants.DIFFICULTY_DELAY
        ):
            # First few blocks of epoch (using old difficulty and min_iters)
            height2 = (
                curr.height
                - (curr.height % self.constants.DIFFICULTY_EPOCH)
                - self.constants.DIFFICULTY_EPOCH
                - 1
            )
        else:
            # The rest of the blocks of epoch (using new difficulty and min iters)
            height2 = curr.height - (curr.height % self.constants.DIFFICULTY_EPOCH) - 1
        height1 = height2 - self.constants.DIFFICULTY_EPOCH
        assert height2 > 0

        iters1: Optional[uint64] = uint64(0)
        iters2: Optional[uint64] = None
        while curr.height > height1 and curr.height > 0:
            if curr.height == height2:
                iters2 = curr.total_iters
            curr = self.block_records[curr.prev_header_hash]
        if height1 > -1:  # For height of -1, total iters is 0
            iters1 = curr.total_iters
        assert iters1 is not None
        assert iters2 is not None
        min_iters_precise = uint64(
            (iters2 - iters1)
            // (self.constants.DIFFICULTY_EPOCH * self.constants.MIN_ITERS_PROPORTION)
        )
        # Truncates to only 12 bits plus 0s. This prevents grinding attacks.
        return uint64(
            truncate_to_significant_bits(
                min_iters_precise, self.constants.SIGNIFICANT_BITS
            )
        )

    async def validate_header_block(
        self, br: BlockRecord, header_block: HeaderBlock
    ) -> bool:
        """
        Fully validates a header block. This requires the ancestors to be present in the blockchain.
        This method also validates that the header block is consistent with the block record.
        """
        # POS challenge hash == POT challenge hash == Challenge prev challenge hash
        if (
            header_block.proof_of_space.challenge_hash
            != header_block.proof_of_time.challenge_hash
        ):
            return False
        if (
            header_block.proof_of_space.challenge_hash
            != header_block.challenge.prev_challenge_hash
        ):
            return False

        if br.height > 0:
            prev_br = self.block_records[br.prev_header_hash]
            # If prev header block, check prev header block hash matches
            if prev_br.new_challenge_hash is not None:
                if (
                    header_block.proof_of_space.challenge_hash
                    != prev_br.new_challenge_hash
                ):
                    return False

        # Validate PoS and get quality
        quality_str: Optional[
            bytes32
        ] = header_block.proof_of_space.verify_and_get_quality_string(
            self.constants.NUMBER_ZERO_BITS_CHALLENGE_SIG
        )
        if quality_str is None:
            return False

        difficulty: uint64
        min_iters: uint64 = self.get_min_iters(br)
        prev_block: Optional[BlockRecord]
        if (
            br.height % self.constants.DIFFICULTY_EPOCH
            != self.constants.DIFFICULTY_DELAY
        ):
            # Only allow difficulty changes once per epoch
            if br.height > 1:
                prev_block = self.block_records[br.prev_header_hash]
                assert prev_block is not None
                prev_prev_block = self.block_records[prev_block.prev_header_hash]
                assert prev_prev_block is not None
                difficulty = uint64(br.weight - prev_block.weight)
                assert difficulty == prev_block.weight - prev_prev_block.weight
            elif br.height == 1:
                prev_block = self.block_records[br.prev_header_hash]
                assert prev_block is not None
                difficulty = uint64(br.weight - prev_block.weight)
                assert difficulty == prev_block.weight
            else:
                difficulty = uint64(br.weight)
                assert difficulty == self.constants.DIFFICULTY_STARTING
        else:
            # This is a difficulty change, so check whether it's within the allowed range.
            # (But don't check whether it's the right amount).
            prev_block = self.block_records[br.prev_header_hash]
            assert prev_block is not None
            prev_prev_block = self.block_records[prev_block.prev_header_hash]
            assert prev_prev_block is not None
            difficulty = uint64(br.weight - prev_block.weight)
            prev_difficulty = uint64(prev_block.weight - prev_prev_block.weight)

            # Ensures the challenge for this block is valid (contains correct diff reset)
            if prev_block.header_hash in self.difficulty_resets_prev:
                if self.difficulty_resets_prev[prev_block.header_hash] != difficulty:
                    return False

            max_diff = uint64(
                truncate_to_significant_bits(
                    prev_difficulty * self.constants.DIFFICULTY_FACTOR,
                    self.constants.SIGNIFICANT_BITS,
                )
            )
            min_diff = uint64(
                truncate_to_significant_bits(
                    prev_difficulty // self.constants.DIFFICULTY_FACTOR,
                    self.constants.SIGNIFICANT_BITS,
                )
            )

            if difficulty < min_diff or difficulty > max_diff:
                return False

        number_of_iters: uint64 = calculate_iterations_quality(
            quality_str, header_block.proof_of_space.size, difficulty, min_iters,
        )

        if header_block.proof_of_time is None:
            return False

        if number_of_iters != header_block.proof_of_time.number_of_iterations:
            return False

        # Check PoT
        if not header_block.proof_of_time.is_valid(
            self.constants.DISCRIMINANT_SIZE_BITS
        ):
            return False

        # Validate challenge
        proofs_hash = std_hash(
            header_block.proof_of_space.get_hash()
            + header_block.proof_of_time.output.get_hash()
        )
        if proofs_hash != header_block.challenge.proofs_hash:
            return False
        # Note that we are not validating the work difficulty reset (since we don't know the
        # next block yet. When we process the next block, we will check that it matches).

        # Validate header:
        if header_block.header.header_hash != br.header_hash:
            return False
        if header_block.header.prev_header_hash != br.prev_header_hash:
            return False
        if header_block.height != br.height:
            return False
        if header_block.weight != br.weight:
            return False
        if br.height > 0:
            assert prev_block is not None
            if prev_block.weight + difficulty != br.weight:
                return False
            if prev_block.total_iters is not None and br.total_iters is not None:
                if prev_block.total_iters + number_of_iters != br.total_iters:
                    return False
            if prev_block.height + 1 != br.height:
                return False
        else:
            if br.weight != difficulty:
                return False
            if br.total_iters != number_of_iters:
                return False

        # Check that block is not far in the future
        if (
            header_block.header.data.timestamp
            > time.time() + self.constants.MAX_FUTURE_TIME
        ):
            return False

        # Check header pos hash
        if (
            header_block.proof_of_space.get_hash()
            != header_block.header.data.proof_of_space_hash
        ):
            return False

        return True

    def validate_select_proofs(
        self,
        all_proof_hashes: List[Tuple[bytes32, Optional[uint64], Optional[uint64]]],
        heights: List[uint32],
        cached_blocks: Dict[bytes32, Tuple[BlockRecord, HeaderBlock, Optional[bytes]]],
        potential_header_hashes: Dict[uint32, bytes32],
    ) -> bool:
        """
        Given a full list of proof hashes (hash of pospace and time, along with difficulty resets), this function
        checks that the proofs at the passed in heights are correct. This is used to validate the weight of a chain,
        by probabilisticly sampling a few blocks, and only validating these. Cached blocks and potential header hashes
        contains the actual data for the header blocks to validate. This method also requires the previous block for
        each height to be present, to ensure an attacker can't grind on the challenge hash.
        """

        for height in heights:
            prev_height = uint32(height - 1)
            # Get previous header block
            prev_hh = potential_header_hashes[prev_height]
            _, prev_header_block, _ = cached_blocks[prev_hh]

            # Validate proof hash of previous header block
            if (
                std_hash(
                    prev_header_block.proof_of_space.get_hash()
                    + prev_header_block.proof_of_time.output.get_hash()
                )
                != all_proof_hashes[prev_height][0]
            ):
                return False

            # Calculate challenge hash (with difficulty)
            if (
                prev_header_block.challenge.prev_challenge_hash
                != prev_header_block.proof_of_space.challenge_hash
            ):
                return False
            if (
                prev_header_block.challenge.prev_challenge_hash
                != prev_header_block.proof_of_time.challenge_hash
            ):
                return False
            if (
                prev_header_block.challenge.proofs_hash
                != all_proof_hashes[prev_height][0]
            ):
                return False
            if (
                height % self.constants.DIFFICULTY_EPOCH
                == self.constants.DIFFICULTY_DELAY
            ):
                diff_change = all_proof_hashes[height][1]
                assert diff_change is not None
                if prev_header_block.challenge.new_work_difficulty != diff_change:
                    return False
            else:
                if prev_header_block.challenge.new_work_difficulty is not None:
                    return False
            challenge_hash = prev_header_block.challenge.get_hash()

            # Get header block
            hh = potential_header_hashes[height]
            _, header_block, _ = cached_blocks[hh]

            # Validate challenge hash is == pospace challenge hash
            if challenge_hash != header_block.proof_of_space.challenge_hash:
                return False
            # Validate challenge hash is == potime challenge hash
            if challenge_hash != header_block.proof_of_time.challenge_hash:
                return False
            # Validate proof hash
            if (
                std_hash(
                    header_block.proof_of_space.get_hash()
                    + header_block.proof_of_time.output.get_hash()
                )
                != all_proof_hashes[height][0]
            ):
                return False

            # Get difficulty
            if (
                height % self.constants.DIFFICULTY_EPOCH
                < self.constants.DIFFICULTY_DELAY
            ):
                diff_height = (
                    height
                    - (height % self.constants.DIFFICULTY_EPOCH)
                    - (
                        self.constants.DIFFICULTY_EPOCH
                        - self.constants.DIFFICULTY_DELAY
                    )
                )
            else:
                diff_height = (
                    height
                    - (height % self.constants.DIFFICULTY_EPOCH)
                    + self.constants.DIFFICULTY_DELAY
                )

            difficulty = all_proof_hashes[diff_height][1]
            assert difficulty is not None

            # Validate pospace to get iters
            quality_str = header_block.proof_of_space.verify_and_get_quality_string(
                self.constants.NUMBER_ZERO_BITS_CHALLENGE_SIG
            )
            assert quality_str is not None

            if (
                height
                < self.constants.DIFFICULTY_EPOCH + self.constants.DIFFICULTY_DELAY
            ):
                min_iters = self.constants.MIN_ITERS_STARTING
            else:
                if (
                    height % self.constants.DIFFICULTY_EPOCH
                    < self.constants.DIFFICULTY_DELAY
                ):
                    height2 = (
                        height
                        - (height % self.constants.DIFFICULTY_EPOCH)
                        - self.constants.DIFFICULTY_EPOCH
                        - 1
                    )
                else:
                    height2 = height - (height % self.constants.DIFFICULTY_EPOCH) - 1

                height1 = height2 - self.constants.DIFFICULTY_EPOCH
                if height1 == -1:
                    iters1: Optional[uint64] = uint64(0)
                else:
                    iters1 = all_proof_hashes[height1][2]
                iters2 = all_proof_hashes[height2][2]
                assert iters1 is not None
                assert iters2 is not None

                min_iters = uint64(
                    (iters2 - iters1)
                    // (
                        self.constants.DIFFICULTY_EPOCH
                        * self.constants.MIN_ITERS_PROPORTION
                    )
                )

            number_of_iters: uint64 = calculate_iterations_quality(
                quality_str, header_block.proof_of_space.size, difficulty, min_iters,
            )

            # Validate potime
            if number_of_iters != header_block.proof_of_time.number_of_iterations:
                return False

            if not header_block.proof_of_time.is_valid(
                self.constants.DISCRIMINANT_SIZE_BITS
            ):
                return False

        return True

    async def get_filter_additions_removals(
        self, new_block: BlockRecord, transactions_filter: bytes
    ) -> Tuple[List[bytes32], List[bytes32]]:
        """ Returns a list of our coin ids, and a list of puzzle_hashes that positively match with provided filter. """
        assert new_block.prev_header_hash in self.block_records

        tx_filter = PyBIP158([b for b in transactions_filter])

        # Find fork point
        fork_h: uint32 = find_fork_point_in_chain(
            self.block_records, self.block_records[self.lca], new_block
        )

        # Get all unspent coins
        my_coin_records_lca: Set[
            WalletCoinRecord
        ] = await self.wallet_store.get_unspent_coins_at_height(uint32(fork_h))

        # Filter coins up to and including fork point
        unspent_coin_names: Set[bytes32] = set()
        for coin in my_coin_records_lca:
            if coin.confirmed_block_index <= fork_h:
                unspent_coin_names.add(coin.name())

        # Get all blocks after fork point up to but not including this block
        curr: BlockRecord = self.block_records[new_block.prev_header_hash]
        reorg_blocks: List[BlockRecord] = []
        while curr.height > fork_h:
            reorg_blocks.append(curr)
            curr = self.block_records[curr.prev_header_hash]
        reorg_blocks.reverse()

        # For each block, process additions to get all Coins, then process removals to get unspent coins
        for reorg_block in reorg_blocks:
            assert (
                reorg_block.additions is not None and reorg_block.removals is not None
            )
            for addition in reorg_block.additions:
                unspent_coin_names.add(addition.name())
            for removal in reorg_block.removals:
                record = await self.puzzle_store.get_derivation_record_for_puzzle_hash(
                    removal.puzzle_hash
                )
                if record is None:
                    continue
                unspent_coin_names.remove(removal)

        if new_block.additions is not None:
            for addition in new_block.additions:
                unspent_coin_names.add(addition.name())

        my_puzzle_hashes = await self.puzzle_store.get_all_puzzle_hashes()

        removals_of_interest: bytes32 = []
        additions_of_interest: bytes32 = []

        (
            trade_removals,
            trade_additions,
        ) = await self.trade_manager.get_coins_of_interest()
        for name, trade_coin in trade_removals.items():
            if tx_filter.Match(bytearray(trade_coin.name())):
                removals_of_interest.append(trade_coin.name())

        for name, trade_coin in trade_additions.items():
            if tx_filter.Match(bytearray(trade_coin.puzzle_hash)):
                additions_of_interest.append(trade_coin.puzzle_hash)

        for coin_name in unspent_coin_names:
            if tx_filter.Match(bytearray(coin_name)):
                removals_of_interest.append(coin_name)

        for puzzle_hash in my_puzzle_hashes:
            if tx_filter.Match(bytearray(puzzle_hash)):
                additions_of_interest.append(puzzle_hash)

        return (additions_of_interest, removals_of_interest)

    async def get_relevant_additions(self, additions: List[Coin]) -> List[Coin]:
        """ Returns the list of coins that are relevant to us.(We can spend them) """

        result: List[Coin] = []
        my_puzzle_hashes: Set[bytes32] = await self.puzzle_store.get_all_puzzle_hashes()

        for coin in additions:
            if coin.puzzle_hash in my_puzzle_hashes:
                result.append(coin)

        return result

    async def is_addition_relevant(self, addition: Coin):
        """
        Check whether we care about a new addition (puzzle_hash). Returns true if we
        control this puzzle hash.
        """
        result = await self.puzzle_store.puzzle_hash_exists(addition.puzzle_hash)
        return result

    async def get_wallet_for_coin(self, coin_id: bytes32) -> Any:
        coin_record = await self.wallet_store.get_coin_record(coin_id)
        if coin_record is None:
            return None
        wallet_id = uint32(coin_record.wallet_id)
        wallet = self.wallets[wallet_id]
        return wallet

    async def get_relevant_removals(self, removals: List[Coin]) -> List[Coin]:
        """ Returns a list of our unspent coins that are in the passed list. """

        result: List[Coin] = []
        wallet_coin_records = await self.wallet_store.get_unspent_coins_at_height()
        my_coins: Dict[bytes32, Coin] = {
            r.coin.name(): r.coin for r in list(wallet_coin_records)
        }

        for coin in removals:
            if coin.name() in my_coins:
                result.append(coin)

        return result

    async def reorg_rollback(self, index: uint32):
        """
        Rolls back and updates the coin_store and transaction store. It's possible this height
        is the tip, or even beyond the tip.
        """
        await self.wallet_store.rollback_lca_to_block(index)

        reorged: List[TransactionRecord] = await self.tx_store.get_transaction_above(
            index
        )
        await self.tx_store.rollback_to_block(index)

        await self.retry_sending_after_reorg(reorged)

    async def retry_sending_after_reorg(self, records: List[TransactionRecord]):
        """
        Retries sending spend_bundle to the Full_Node, after confirmed tx
        get's excluded from chain because of the reorg.
        """
        if len(records) == 0:
            return

        for record in records:
            await self.tx_store.set_not_sent(record.name())

        self.tx_pending_changed()

    async def close_all_stores(self):
        async with self.lock:
            await self.db_connection.close()

    async def clear_all_stores(self):
        async with self.lock:
            await self.wallet_store._clear_database()
            await self.tx_store._clear_database()
            await self.puzzle_store._clear_database()
            await self.user_store._clear_database()
            await self.basic_store._clear_database()

    def unlink_db(self):
        Path(self.db_path).unlink()

    async def get_all_wallets(self) -> List[WalletInfo]:
        return await self.user_store.get_all_wallets()

    async def create_wallet_backup(self, file_path: Path):
        all_wallets = await self.get_all_wallets()
        for wallet in all_wallets:
            if wallet.id == 1:
                all_wallets.remove(wallet)
                break

        backup_pk = master_sk_to_backup_sk(self.private_key)
        now = uint64(int(time.time()))
        wallet_backup = WalletInfoBackup(all_wallets)

        backup: Dict[str, Any] = {}

        data = wallet_backup.to_json_dict()
        data["version"] = __version__
        data["fingerprint"] = self.private_key.get_g1().get_fingerprint()
        data["timestamp"] = now
        key_base_64 = base64.b64encode(bytes(backup_pk))
        f = Fernet(key_base_64)
        data_bytes = json.dumps(data).encode()
        encrypted = f.encrypt(data_bytes)

        meta_data: Dict[str, Any] = {}
        meta_data["timestamp"] = now
        meta_data["pubkey"] = bytes(backup_pk.get_g1()).hex()

        meta_data_bytes = json.dumps(meta_data).encode()
        signature = bytes(
            AugSchemeMPL.sign(
                backup_pk, std_hash(encrypted) + std_hash(meta_data_bytes)
            )
        ).hex()

        backup["data"] = encrypted.decode()
        backup["meta_data"] = meta_data
        backup["signature"] = signature

        backup_file_text = json.dumps(backup)
        file_path.write_text(backup_file_text)

    async def import_backup_info(self, file_path):
        json_dict = open_backup_file(file_path, self.private_key)
        wallet_list_json = json_dict["data"]["wallet_list"]

        for wallet_info in wallet_list_json:
            await self.user_store.create_wallet(
                wallet_info["name"],
                wallet_info["type"],
                wallet_info["data"],
                wallet_info["id"],
            )

        await self.load_wallets()
        await self.user_settings.user_imported_backup()

    async def get_wallet_for_colour(self, colour):
        for wallet_id in self.wallets:
            wallet = self.wallets[wallet_id]
            if wallet.wallet_info.type == WalletType.COLOURED_COIN.value:
                if bytes(wallet.cc_info.my_genesis_checker).hex() == colour:
                    return wallet
        return None

    async def add_new_wallet(self, wallet: Any, id: int):
        self.wallets[uint32(id)] = wallet
        await self.create_more_puzzle_hashes()

    async def get_spendable_coins_for_wallet(
        self, wallet_id: int
    ) -> Set[WalletCoinRecord]:
        if self.lca is None:
            return set()

        current_index = self.block_records[self.lca].height

        coinbase_freeze_period = self.constants.COINBASE_FREEZE_PERIOD

        if current_index <= coinbase_freeze_period:
            return set()

        valid_index = current_index - coinbase_freeze_period

        records = await self.wallet_store.get_spendable_for_index(
            valid_index, wallet_id
        )

        # Coins that are currently part of a transaction
        unconfirmed_tx: List[
            TransactionRecord
        ] = await self.tx_store.get_unconfirmed_for_wallet(wallet_id)
        removal_dict: Dict[bytes32, Coin] = {}
        for tx in unconfirmed_tx:
            for coin in tx.removals:
                # TODO, "if" might not be necessary once unconfirmed tx doesn't contain coins for other wallets
                if await self.does_coin_belong_to_wallet(coin, wallet_id):
                    removal_dict[coin.name()] = coin

        # Coins that are part of the trade
        offer_locked_coins: Dict[
            bytes32, WalletCoinRecord
        ] = await self.trade_manager.get_locked_coins()

        filtered = set()
        for record in records:
            if record.coin.name() in offer_locked_coins:
                continue
            if record.coin.name() in removal_dict:
                continue
            filtered.add(record)

        return filtered

    async def create_action(
        self,
        name: str,
        wallet_id: int,
        type: int,
        callback: str,
        done: bool,
        data: str,
    ):
        await self.action_store.create_action(
            name, wallet_id, type, callback, done, data
        )
        self.tx_pending_changed()

    async def set_action_done(self, action_id: int):
        await self.action_store.action_done(action_id)

    async def generator_received(
        self, height: uint32, header_hash: uint32, program: Program
    ):

        actions: List[WalletAction] = await self.action_store.get_all_pending_actions()
        for action in actions:
            data = json.loads(action.data)
            action_data = data["data"]["action_data"]
            if action.name == "request_generator":
                stored_header_hash = bytes32(
                    hexstr_to_bytes(action_data["header_hash"])
                )
                stored_height = uint32(action_data["height"])
                if stored_header_hash == header_hash and stored_height == height:
                    if action.done:
                        return
                    wallet = self.wallets[uint32(action.wallet_id)]
                    callback_str = action.wallet_callback
                    if callback_str is not None:
                        callback = getattr(wallet, callback_str)
                        await callback(height, header_hash, program, action.id)
