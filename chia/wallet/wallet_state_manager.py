import aiosqlite
import asyncio
import json
import logging
import multiprocessing.context
import time
from collections import defaultdict
from pathlib import Path
from secrets import token_bytes
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

from blspy import G1Element, PrivateKey

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.coinbase import farmer_parent_id, pool_parent_id
from chia.consensus.constants import ConsensusConstants
from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.data_layer.dl_wallet_store import DataLayerStore
from chia.pools.pool_puzzles import SINGLETON_LAUNCHER_HASH, solution_to_pool_state
from chia.pools.pool_wallet import PoolWallet
from chia.protocols import wallet_protocol
from chia.protocols.wallet_protocol import CoinState
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.full_block import FullBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.bech32m import encode_puzzle_hash
from chia.util.db_synchronous import db_synchronous_on
from chia.util.db_wrapper import DBWrapper2
from chia.util.errors import Err
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.lru_cache import LRUCache
from chia.util.path import path_from_root
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_utils import construct_cat_puzzle, match_cat_puzzle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import (
    master_sk_to_wallet_sk,
    master_sk_to_wallet_sk_unhardened,
    master_sk_to_wallet_sk_intermediate,
    _derive_path,
    master_sk_to_wallet_sk_unhardened_intermediate,
    _derive_path_unhardened,
)
from chia.wallet.wallet_protocol import WalletProtocol
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.did_wallet.did_wallet_puzzles import DID_INNERPUZ_MOD, create_fullpuz, match_did_puzzle
from chia.wallet.key_val_store import KeyValStore
from chia.wallet.nft_wallet.nft_info import NFTWalletInfo
from chia.wallet.nft_wallet.nft_puzzles import get_metadata_and_phs, get_new_owner_did
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.notification_manager import NotificationManager
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.puzzles.cat_loader import CAT_MOD, CAT_MOD_HASH
from chia.wallet.settings.user_settings import UserSettings
from chia.wallet.trade_manager import TradeManager
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.compute_hints import compute_coin_hints
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_sync_utils import last_change_height_cs, PeerRequestException
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_blockchain import WalletBlockchain
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_coin_store import WalletCoinStore
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_interested_store import WalletInterestedStore
from chia.wallet.wallet_nft_store import WalletNftStore
from chia.wallet.wallet_pool_store import WalletPoolStore
from chia.wallet.wallet_puzzle_store import WalletPuzzleStore
from chia.wallet.wallet_retry_store import WalletRetryStore
from chia.wallet.wallet_transaction_store import WalletTransactionStore
from chia.wallet.wallet_user_store import WalletUserStore
from chia.wallet.uncurried_puzzle import uncurry_puzzle


class WalletStateManager:
    constants: ConsensusConstants
    config: Dict
    tx_store: WalletTransactionStore
    puzzle_store: WalletPuzzleStore
    user_store: WalletUserStore
    nft_store: WalletNftStore
    basic_store: KeyValStore

    start_index: int

    # Makes sure only one asyncio thread is changing the blockchain state at one time
    lock: asyncio.Lock

    log: logging.Logger

    # TODO Don't allow user to send tx until wallet is synced
    sync_mode: bool
    sync_target: uint32
    genesis: FullBlock

    state_changed_callback: Optional[Callable]
    pending_tx_callback: Optional[Callable]
    puzzle_hash_created_callbacks: Dict = defaultdict(lambda *x: None)
    db_path: Path
    db_wrapper: DBWrapper2

    main_wallet: Wallet
    wallets: Dict[uint32, WalletProtocol]
    private_key: PrivateKey

    trade_manager: TradeManager
    notification_manager: NotificationManager
    new_wallet: bool
    user_settings: UserSettings
    blockchain: WalletBlockchain
    coin_store: WalletCoinStore
    interested_store: WalletInterestedStore
    retry_store: WalletRetryStore
    multiprocessing_context: multiprocessing.context.BaseContext
    server: ChiaServer
    root_path: Path
    wallet_node: Any
    pool_store: WalletPoolStore
    dl_store: DataLayerStore
    default_cats: Dict[str, Any]
    asset_to_wallet_map: Dict[AssetType, Any]
    initial_num_public_keys: int

    @staticmethod
    async def create(
        private_key: PrivateKey,
        config: Dict,
        db_path: Path,
        constants: ConsensusConstants,
        server: ChiaServer,
        root_path: Path,
        wallet_node,
        name: str = None,
    ):
        self = WalletStateManager()
        self.new_wallet = False
        self.config = config
        self.constants = constants
        self.server = server
        self.root_path = root_path
        self.log = logging.getLogger(name if name else __name__)
        self.lock = asyncio.Lock()
        self.log.debug(f"Starting in db path: {db_path}")

        sql_log_path: Optional[Path] = None
        if self.config.get("log_sqlite_cmds", False):
            sql_log_path = path_from_root(self.root_path, "log/wallet_sql.log")
            self.log.info(f"logging SQL commands to {sql_log_path}")

        self.db_wrapper = await DBWrapper2.create(
            database=db_path,
            reader_count=self.config.get("db_readers", 4),
            log_path=sql_log_path,
            synchronous=db_synchronous_on(self.config.get("db_sync", "auto")),
        )

        self.initial_num_public_keys = config["initial_num_public_keys"]
        min_num_public_keys = 425
        if not config.get("testing", False) and self.initial_num_public_keys < min_num_public_keys:
            self.initial_num_public_keys = min_num_public_keys

        self.coin_store = await WalletCoinStore.create(self.db_wrapper)
        self.tx_store = await WalletTransactionStore.create(self.db_wrapper)
        self.puzzle_store = await WalletPuzzleStore.create(self.db_wrapper)
        self.user_store = await WalletUserStore.create(self.db_wrapper)
        self.nft_store = await WalletNftStore.create(self.db_wrapper)
        self.basic_store = await KeyValStore.create(self.db_wrapper)
        self.trade_manager = await TradeManager.create(self, self.db_wrapper)
        self.notification_manager = await NotificationManager.create(self, self.db_wrapper)
        self.user_settings = await UserSettings.create(self.basic_store)
        self.pool_store = await WalletPoolStore.create(self.db_wrapper)
        self.dl_store = await DataLayerStore.create(self.db_wrapper)
        self.interested_store = await WalletInterestedStore.create(self.db_wrapper)
        self.retry_store = await WalletRetryStore.create(self.db_wrapper)
        self.default_cats = DEFAULT_CATS

        self.wallet_node = wallet_node
        self.sync_mode = False
        self.sync_target = uint32(0)
        self.blockchain = await WalletBlockchain.create(self.basic_store, self.constants)
        self.state_changed_callback = None
        self.pending_tx_callback = None
        self.db_path = db_path

        main_wallet_info = await self.user_store.get_wallet_by_id(1)
        assert main_wallet_info is not None

        self.private_key = private_key
        self.main_wallet = await Wallet.create(self, main_wallet_info)

        self.wallets = {main_wallet_info.id: self.main_wallet}

        self.asset_to_wallet_map = {
            AssetType.CAT: CATWallet,
        }

        wallet = None
        for wallet_info in await self.get_all_wallet_info_entries():
            if wallet_info.type == WalletType.STANDARD_WALLET:
                if wallet_info.id == 1:
                    continue
                wallet = await Wallet.create(self, wallet_info)
            elif wallet_info.type == WalletType.CAT:
                wallet = await CATWallet.create(
                    self,
                    self.main_wallet,
                    wallet_info,
                )
            elif wallet_info.type == WalletType.DECENTRALIZED_ID:
                wallet = await DIDWallet.create(
                    self,
                    self.main_wallet,
                    wallet_info,
                )
            elif wallet_info.type == WalletType.NFT:
                wallet = await NFTWallet.create(
                    self,
                    self.main_wallet,
                    wallet_info,
                )
            elif wallet_info.type == WalletType.POOLING_WALLET:
                wallet = await PoolWallet.create_from_db(
                    self,
                    self.main_wallet,
                    wallet_info,
                )
            elif wallet_info.type == WalletType.DATA_LAYER:
                wallet = await DataLayerWallet.create(
                    self,
                    self.main_wallet,
                    wallet_info,
                )
            if wallet is not None:
                self.wallets[wallet_info.id] = wallet

        return self

    def get_public_key(self, index: uint32) -> G1Element:
        return master_sk_to_wallet_sk(self.private_key, index).get_g1()

    def get_public_key_unhardened(self, index: uint32) -> G1Element:
        return master_sk_to_wallet_sk_unhardened(self.private_key, index).get_g1()

    async def get_keys(self, puzzle_hash: bytes32) -> Optional[Tuple[G1Element, PrivateKey]]:
        record = await self.puzzle_store.record_for_puzzle_hash(puzzle_hash)
        if record is None:
            raise ValueError(f"No key for this puzzlehash {puzzle_hash})")
        if record.hardened:
            private = master_sk_to_wallet_sk(self.private_key, record.index)
            pubkey = private.get_g1()
            return pubkey, private
        private = master_sk_to_wallet_sk_unhardened(self.private_key, record.index)
        pubkey = private.get_g1()
        return pubkey, private

    async def create_more_puzzle_hashes(
        self,
        from_zero: bool = False,
        in_transaction=False,
        mark_existing_as_used=True,
        up_to_index: Optional[uint32] = None,
        num_additional_phs: Optional[int] = None,
    ):
        """
        For all wallets in the user store, generates the first few puzzle hashes so
        that we can restore the wallet from only the private keys.
        """
        targets = list(self.wallets.keys())
        self.log.debug("Target wallets to generate puzzle hashes for: %s", repr(targets))
        unused: Optional[uint32] = (
            uint32(up_to_index + 1) if up_to_index is not None else await self.puzzle_store.get_unused_derivation_path()
        )
        if unused is None:
            # This handles the case where the database has entries but they have all been used
            unused = await self.puzzle_store.get_last_derivation_path()
            self.log.debug("Tried finding unused: %s", unused)
            if unused is None:
                # This handles the case where the database is empty
                unused = uint32(0)

        self.log.debug(f"Requested to generate puzzle hashes to at least index {unused}")
        start_t = time.time()
        to_generate = num_additional_phs if num_additional_phs is not None else self.initial_num_public_keys
        new_paths: bool = False

        for wallet_id in targets:
            target_wallet = self.wallets[wallet_id]
            if not target_wallet.require_derivation_paths():
                self.log.debug("Skipping wallet %s as no derivation paths required", wallet_id)
                continue
            last: Optional[uint32] = await self.puzzle_store.get_last_derivation_path_for_wallet(wallet_id)
            self.log.debug(
                "Fetched last record for wallet %r:  %s (from_zero=%r, unused=%r)", wallet_id, last, from_zero, unused
            )
            start_index = 0
            derivation_paths: List[DerivationRecord] = []

            if last is not None:
                start_index = last + 1

            # If the key was replaced (from_zero=True), we should generate the puzzle hashes for the new key
            if from_zero:
                start_index = 0
            last_index = unused + to_generate
            if start_index >= last_index:
                self.log.debug(f"Nothing to create for for wallet_id: {wallet_id}, index: {start_index}")
            else:
                creating_msg = (
                    f"Creating puzzle hashes from {start_index} to {last_index - 1} for wallet_id: {wallet_id}"
                )
                self.log.info(f"Start: {creating_msg}")
                intermediate_sk = master_sk_to_wallet_sk_intermediate(self.private_key)
                intermediate_sk_un = master_sk_to_wallet_sk_unhardened_intermediate(self.private_key)
                for index in range(start_index, last_index):
                    if WalletType(target_wallet.type()) == WalletType.POOLING_WALLET:
                        continue

                    # Hardened
                    pubkey: G1Element = _derive_path(intermediate_sk, [index]).get_g1()
                    puzzlehash: Optional[bytes32] = target_wallet.puzzle_hash_for_pk(pubkey)
                    if puzzlehash is None:
                        self.log.error(f"Unable to create puzzles with wallet {target_wallet}")
                        break
                    self.log.debug(f"Puzzle at index {index} wallet ID {wallet_id} puzzle hash {puzzlehash.hex()}")
                    new_paths = True
                    derivation_paths.append(
                        DerivationRecord(
                            uint32(index),
                            puzzlehash,
                            pubkey,
                            WalletType(target_wallet.type()),
                            uint32(target_wallet.id()),
                            True,
                        )
                    )
                    # Unhardened
                    pubkey_unhardened: G1Element = _derive_path_unhardened(intermediate_sk_un, [index]).get_g1()
                    puzzlehash_unhardened: Optional[bytes32] = target_wallet.puzzle_hash_for_pk(pubkey_unhardened)
                    if puzzlehash_unhardened is None:
                        self.log.error(f"Unable to create puzzles with wallet {target_wallet}")
                        break
                    self.log.debug(
                        f"Puzzle at index {index} wallet ID {wallet_id} puzzle hash {puzzlehash_unhardened.hex()}"
                    )
                    # We await sleep here to allow an asyncio context switch (since the other parts of this loop do
                    # not have await and therefore block). This can prevent networking layer from responding to ping.
                    await asyncio.sleep(0)
                    derivation_paths.append(
                        DerivationRecord(
                            uint32(index),
                            puzzlehash_unhardened,
                            pubkey_unhardened,
                            WalletType(target_wallet.type()),
                            uint32(target_wallet.id()),
                            False,
                        )
                    )
                self.log.info(f"Done: {creating_msg} Time: {time.time() - start_t} seconds")
            await self.puzzle_store.add_derivation_paths(derivation_paths)
            await self.add_interested_puzzle_hashes(
                [record.puzzle_hash for record in derivation_paths],
                [record.wallet_id for record in derivation_paths],
            )
            if len(derivation_paths) > 0:
                self.state_changed("new_derivation_index", data_object={"index": derivation_paths[-1].index})
        # By default, we'll mark previously generated unused puzzle hashes as used if we have new paths
        if mark_existing_as_used and unused > 0 and new_paths:
            self.log.info(f"Updating last used derivation index: {unused - 1}")
            await self.puzzle_store.set_used_up_to(uint32(unused - 1))

    async def update_wallet_puzzle_hashes(self, wallet_id):
        derivation_paths: List[DerivationRecord] = []
        target_wallet = self.wallets[wallet_id]
        last: Optional[uint32] = await self.puzzle_store.get_last_derivation_path_for_wallet(wallet_id)
        unused: Optional[uint32] = await self.puzzle_store.get_unused_derivation_path()
        if unused is None:
            # This handles the case where the database has entries but they have all been used
            unused = await self.puzzle_store.get_last_derivation_path()
            if unused is None:
                # This handles the case where the database is empty
                unused = uint32(0)
        if last is not None:
            for index in range(unused, last):
                # Since DID are not released yet we can assume they are only using unhardened keys derivation
                pubkey: G1Element = self.get_public_key_unhardened(uint32(index))
                puzzlehash: Optional[bytes32] = target_wallet.puzzle_hash_for_pk(pubkey)
                self.log.info(f"Generating public key at index {index} puzzle hash {puzzlehash.hex()}")
                derivation_paths.append(
                    DerivationRecord(
                        uint32(index),
                        puzzlehash,
                        pubkey,
                        target_wallet.wallet_info.type,
                        uint32(target_wallet.wallet_info.id),
                        False,
                    )
                )
            await self.puzzle_store.add_derivation_paths(derivation_paths)

    async def get_unused_derivation_record(self, wallet_id: uint32, *, hardened=False) -> DerivationRecord:
        """
        Creates a puzzle hash for the given wallet, and then makes more puzzle hashes
        for every wallet to ensure we always have more in the database. Never reusue the
        same public key more than once (for privacy).
        """
        async with self.puzzle_store.lock:
            # If we have no unused public keys, we will create new ones
            unused: Optional[uint32] = await self.puzzle_store.get_unused_derivation_path()
            if unused is None:
                self.log.debug("No unused paths, generate more ")
                await self.create_more_puzzle_hashes()
                # Now we must have unused public keys
                unused = await self.puzzle_store.get_unused_derivation_path()
                assert unused is not None

            self.log.debug("Fetching derivation record for: %s %s %s", unused, wallet_id, hardened)
            record: Optional[DerivationRecord] = await self.puzzle_store.get_derivation_record(
                unused, wallet_id, hardened
            )
            assert record is not None

            # Set this key to used so we never use it again
            await self.puzzle_store.set_used_up_to(record.index)

            # Create more puzzle hashes / keys
            await self.create_more_puzzle_hashes()
            return record

    async def get_current_derivation_record_for_wallet(self, wallet_id: uint32) -> Optional[DerivationRecord]:
        async with self.puzzle_store.lock:
            # If we have no unused public keys, we will create new ones
            current: Optional[DerivationRecord] = await self.puzzle_store.get_current_derivation_record_for_wallet(
                wallet_id
            )
            return current

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

    def set_coin_with_puzzlehash_created_callback(self, puzzlehash: bytes32, callback: Callable):
        """
        Callback to be called when new coin is seen with specified puzzlehash
        """
        self.puzzle_hash_created_callbacks[puzzlehash] = callback

    async def puzzle_hash_created(self, coin: Coin):
        callback = self.puzzle_hash_created_callbacks[coin.puzzle_hash]
        if callback is None:
            return None
        await callback(coin)

    def state_changed(self, state: str, wallet_id: Optional[int] = None, data_object: Optional[Dict[str, Any]] = None):
        """
        Calls the callback if it's present.
        """
        if self.state_changed_callback is None:
            return None
        change_data: Dict[str, Any] = {"state": state}
        if wallet_id is not None:
            change_data["wallet_id"] = wallet_id
        if data_object is not None:
            change_data["additional_data"] = data_object
        self.state_changed_callback(state, change_data)

    def tx_pending_changed(self) -> None:
        """
        Notifies the wallet node that there's new tx pending
        """
        if self.pending_tx_callback is None:
            return None

        self.pending_tx_callback()

    async def synced(self):
        if len(self.server.get_connections(NodeType.FULL_NODE)) == 0:
            return False

        latest = await self.blockchain.get_peak_block()
        if latest is None:
            return False

        if "simulator" in self.config.get("selected_network"):
            return True  # sim is always synced if we have a genesis block.

        if latest.height - await self.blockchain.get_finished_sync_up_to() > 1:
            return False

        latest_timestamp = self.blockchain.get_latest_timestamp()
        has_pending_queue_items = self.wallet_node.new_peak_queue.has_pending_data_process_items()

        if latest_timestamp > int(time.time()) - 5 * 60 and not has_pending_queue_items:
            return True
        return False

    def set_sync_mode(self, mode: bool, sync_height: uint32 = uint32(0)):
        """
        Sets the sync mode. This changes the behavior of the wallet node.
        """
        self.sync_mode = mode
        self.sync_target = sync_height
        self.state_changed("sync_changed")

    async def get_confirmed_spendable_balance_for_wallet(self, wallet_id: int, unspent_records=None) -> uint128:
        """
        Returns the balance amount of all coins that are spendable.
        """

        spendable: Set[WalletCoinRecord] = await self.get_spendable_coins_for_wallet(wallet_id, unspent_records)

        spendable_amount: uint128 = uint128(0)
        for record in spendable:
            spendable_amount = uint128(spendable_amount + record.coin.amount)

        return spendable_amount

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

    async def get_confirmed_balance_for_wallet(
        self,
        wallet_id: int,
        unspent_coin_records: Optional[Set[WalletCoinRecord]] = None,
    ) -> uint128:
        """
        Returns the confirmed balance, including coinbase rewards that are not spendable.
        """
        # lock only if unspent_coin_records is None
        if unspent_coin_records is None:
            unspent_coin_records = await self.coin_store.get_unspent_coins_for_wallet(wallet_id)
        return uint128(sum(cr.coin.amount for cr in unspent_coin_records))

    async def get_unconfirmed_balance(
        self, wallet_id: int, unspent_coin_records: Optional[Set[WalletCoinRecord]] = None
    ) -> uint128:
        """
        Returns the balance, including coinbase rewards that are not spendable, and unconfirmed
        transactions.
        """
        # This API should change so that get_balance_from_coin_records is called for Set[WalletCoinRecord]
        # and this method is called only for the unspent_coin_records==None case.
        if unspent_coin_records is None:
            unspent_coin_records = await self.coin_store.get_unspent_coins_for_wallet(wallet_id)

        unconfirmed_tx: List[TransactionRecord] = await self.tx_store.get_unconfirmed_for_wallet(wallet_id)
        all_unspent_coins: Set[Coin] = {cr.coin for cr in unspent_coin_records}

        for record in unconfirmed_tx:
            for addition in record.additions:
                # This change or a self transaction
                if await self.does_coin_belong_to_wallet(addition, wallet_id):
                    all_unspent_coins.add(addition)

            for removal in record.removals:
                if await self.does_coin_belong_to_wallet(removal, wallet_id) and removal in all_unspent_coins:
                    all_unspent_coins.remove(removal)

        return uint128(sum(coin.amount for coin in all_unspent_coins))

    async def unconfirmed_removals_for_wallet(self, wallet_id: int) -> Dict[bytes32, Coin]:
        """
        Returns new removals transactions that have not been confirmed yet.
        """
        removals: Dict[bytes32, Coin] = {}
        unconfirmed_tx = await self.tx_store.get_unconfirmed_for_wallet(wallet_id)
        for record in unconfirmed_tx:
            for coin in record.removals:
                removals[coin.name()] = coin
        return removals

    async def determine_coin_type(
        self, peer: WSChiaConnection, coin_state: CoinState, fork_height: Optional[uint32]
    ) -> Tuple[Optional[uint32], Optional[WalletType]]:
        if coin_state.created_height is not None and (
            self.is_pool_reward(uint32(coin_state.created_height), coin_state.coin)
            or self.is_farmer_reward(uint32(coin_state.created_height), coin_state.coin)
        ):
            return None, None

        response: List[CoinState] = await self.wallet_node.get_coin_state(
            [coin_state.coin.parent_coin_info], peer=peer, fork_height=fork_height
        )
        if len(response) == 0:
            self.log.warning(f"Could not find a parent coin with ID: {coin_state.coin.parent_coin_info}")
            return None, None
        parent_coin_state = response[0]
        assert parent_coin_state.spent_height == coin_state.created_height

        coin_spend: Optional[CoinSpend] = await self.wallet_node.fetch_puzzle_solution(
            parent_coin_state.spent_height, parent_coin_state.coin, peer
        )
        if coin_spend is None:
            return None, None

        puzzle = Program.from_bytes(bytes(coin_spend.puzzle_reveal))

        uncurried = uncurry_puzzle(puzzle)

        # Check if the coin is a CAT
        cat_curried_args = match_cat_puzzle(uncurried)
        if cat_curried_args is not None:
            return await self.handle_cat(cat_curried_args, parent_coin_state, coin_state, coin_spend)

        # Check if the coin is a NFT
        #                                                        hint
        # First spend where 1 mojo coin -> Singleton launcher -> NFT -> NFT
        uncurried_nft = UncurriedNFT.uncurry(uncurried.mod, uncurried.args)
        if uncurried_nft is not None:
            return await self.handle_nft(coin_spend, uncurried_nft, parent_coin_state)

        # Check if the coin is a DID
        did_curried_args = match_did_puzzle(uncurried.mod, uncurried.args)
        if did_curried_args is not None:
            return await self.handle_did(did_curried_args, parent_coin_state, coin_state, coin_spend, peer)

        await self.notification_manager.potentially_add_new_notification(coin_state, coin_spend)

        return None, None

    async def filter_spam(self, new_coin_state: List[CoinState]) -> List[CoinState]:
        xch_spam_amount = self.config.get("xch_spam_amount", 1000000)

        # No need to filter anything if the filter is set to 1 or 0 mojos
        if xch_spam_amount <= 1:
            return new_coin_state

        spam_filter_after_n_txs = self.config.get("spam_filter_after_n_txs", 200)
        small_unspent_count = await self.coin_store.count_small_unspent(xch_spam_amount)

        # if small_unspent_count > spam_filter_after_n_txs:
        filtered_cs: List[CoinState] = []
        is_standard_wallet_phs: Set[bytes32] = set()

        for cs in new_coin_state:
            # Only apply filter to new coins being sent to our wallet, that are very small
            if (
                cs.created_height is not None
                and cs.spent_height is None
                and cs.coin.amount < xch_spam_amount
                and (cs.coin.puzzle_hash in is_standard_wallet_phs or await self.is_standard_wallet_tx(cs))
            ):
                is_standard_wallet_phs.add(cs.coin.puzzle_hash)
                if small_unspent_count < spam_filter_after_n_txs:
                    filtered_cs.append(cs)
                small_unspent_count += 1
            else:
                filtered_cs.append(cs)
        return filtered_cs

    async def is_standard_wallet_tx(self, coin_state: CoinState) -> bool:
        wallet_info: Optional[Tuple[uint32, WalletType]] = await self.get_wallet_id_for_puzzle_hash(
            coin_state.coin.puzzle_hash
        )
        if wallet_info is not None and wallet_info[1] == WalletType.STANDARD_WALLET:
            return True
        return False

    async def handle_cat(
        self,
        curried_args: Iterator[Program],
        parent_coin_state: CoinState,
        coin_state: CoinState,
        coin_spend: CoinSpend,
    ) -> Tuple[Optional[uint32], Optional[WalletType]]:
        """
        Handle the new coin when it is a CAT
        :param curried_args: Curried arg of the CAT mod
        :param parent_coin_state: Parent coin state
        :param coin_state: Current coin state
        :param coin_spend: New coin spend
        :return: Wallet ID & Wallet Type
        """
        wallet_id = None
        wallet_type = None
        mod_hash, tail_hash, inner_puzzle = curried_args

        hint_list = compute_coin_hints(coin_spend)
        derivation_record = None
        for hint in hint_list:
            derivation_record = await self.puzzle_store.get_derivation_record_for_puzzle_hash(bytes32(hint))
            if derivation_record is not None:
                break

        if derivation_record is None:
            self.log.info(f"Received state for the coin that doesn't belong to us {coin_state}")
        else:
            our_inner_puzzle: Program = self.main_wallet.puzzle_for_pk(derivation_record.pubkey)
            asset_id: bytes32 = bytes32(bytes(tail_hash)[1:])
            cat_puzzle = construct_cat_puzzle(CAT_MOD, asset_id, our_inner_puzzle, CAT_MOD_HASH)
            if cat_puzzle.get_tree_hash() != coin_state.coin.puzzle_hash:
                return None, None
            if bytes(tail_hash).hex()[2:] in self.default_cats or self.config.get(
                "automatically_add_unknown_cats", False
            ):
                cat_wallet = await CATWallet.create_wallet_for_cat(self, self.main_wallet, bytes(tail_hash).hex()[2:])
                wallet_id = cat_wallet.id()
                wallet_type = WalletType(cat_wallet.type())
                self.state_changed("wallet_created")
            else:
                # Found unacknowledged CAT, save it in the database.
                await self.interested_store.add_unacknowledged_token(
                    asset_id,
                    CATWallet.default_wallet_name_for_unknown_cat(asset_id.hex()),
                    None if parent_coin_state.spent_height is None else uint32(parent_coin_state.spent_height),
                    parent_coin_state.coin.puzzle_hash,
                )
                self.state_changed("added_stray_cat")
        return wallet_id, wallet_type

    async def handle_did(
        self,
        curried_args: Iterator[Program],
        parent_coin_state: CoinState,
        coin_state: CoinState,
        coin_spend: CoinSpend,
        peer: WSChiaConnection,
    ) -> Tuple[Optional[uint32], Optional[WalletType]]:
        """
        Handle the new coin when it is a DID
        :param curried_args: Curried arg of the DID mod
        :param parent_coin_state: Parent coin state
        :param coin_state: Current coin state
        :param coin_spend: New coin spend
        :return: Wallet ID & Wallet Type
        """
        wallet_id = None
        wallet_type = None
        p2_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata = curried_args
        inner_puzzle_hash = p2_puzzle.get_tree_hash()
        self.log.info(f"parent: {parent_coin_state.coin.name()} inner_puzzle_hash for parent is {inner_puzzle_hash}")

        hint_list = compute_coin_hints(coin_spend)
        derivation_record = None
        for hint in hint_list:
            derivation_record = await self.puzzle_store.get_derivation_record_for_puzzle_hash(bytes32(hint))
            if derivation_record is not None:
                break

        if derivation_record is None:
            self.log.info(f"Received state for the coin that doesn't belong to us {coin_state}")
        else:
            our_inner_puzzle: Program = self.main_wallet.puzzle_for_pk(derivation_record.pubkey)

            launch_id: bytes32 = bytes32(bytes(singleton_struct.rest().first())[1:])
            self.log.info(f"Found DID, launch_id {launch_id}.")
            did_puzzle = DID_INNERPUZ_MOD.curry(
                our_inner_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata
            )
            full_puzzle = create_fullpuz(did_puzzle, launch_id)
            did_puzzle_empty_recovery = DID_INNERPUZ_MOD.curry(
                our_inner_puzzle, Program.to([]).get_tree_hash(), uint64(0), singleton_struct, metadata
            )
            full_puzzle_empty_recovery = create_fullpuz(did_puzzle_empty_recovery, launch_id)
            if full_puzzle.get_tree_hash() != coin_state.coin.puzzle_hash:
                if full_puzzle_empty_recovery.get_tree_hash() == coin_state.coin.puzzle_hash:
                    did_puzzle = did_puzzle_empty_recovery
                    self.log.info("DID recovery list was reset by the previous owner.")
                else:
                    self.log.error("DID puzzle hash doesn't match, please check curried parameters.")
                    return None, None
            # Create DID wallet
            response: List[CoinState] = await self.wallet_node.get_coin_state([launch_id], peer=peer)
            if len(response) == 0:
                self.log.warning(f"Could not find the launch coin with ID: {launch_id}")
                return None, None
            launch_coin: CoinState = response[0]
            origin_coin = launch_coin.coin

            for wallet in self.wallets.values():
                if wallet.type() == WalletType.DECENTRALIZED_ID:
                    assert isinstance(wallet, DIDWallet)
                    assert wallet.did_info.origin_coin is not None
                    if origin_coin.name() == wallet.did_info.origin_coin.name():
                        return wallet.id(), WalletType(wallet.type())
            did_wallet = await DIDWallet.create_new_did_wallet_from_coin_spend(
                self,
                self.main_wallet,
                launch_coin.coin,
                did_puzzle,
                coin_spend,
                f"DID {encode_puzzle_hash(launch_id, AddressType.DID.hrp(self.config))}",
            )
            wallet_id = did_wallet.id()
            wallet_type = WalletType(did_wallet.type())
            self.state_changed("wallet_created", wallet_id, {"did_id": did_wallet.get_my_DID()})
        return wallet_id, wallet_type

    async def get_minter_did(self, launcher_coin: Coin, peer: WSChiaConnection) -> Optional[bytes32]:
        # Get minter DID
        eve_coin = (await self.wallet_node.fetch_children(launcher_coin.name(), peer=peer))[0]
        eve_coin_spend: CoinSpend = await self.wallet_node.fetch_puzzle_solution(
            eve_coin.spent_height, eve_coin.coin, peer
        )
        eve_full_puzzle: Program = Program.from_bytes(bytes(eve_coin_spend.puzzle_reveal))
        eve_uncurried_nft: Optional[UncurriedNFT] = UncurriedNFT.uncurry(*eve_full_puzzle.uncurry())
        if eve_uncurried_nft is None:
            raise ValueError("Couldn't get minter DID for NFT")
        if not eve_uncurried_nft.supports_did:
            return None
        minter_did = get_new_owner_did(eve_uncurried_nft, eve_coin_spend.solution.to_program())
        if minter_did == b"":
            minter_did = None
        if minter_did is None:
            # Check if the NFT is a bulk minting
            launcher_parent: List[CoinState] = await self.wallet_node.get_coin_state(
                [launcher_coin.parent_coin_info], peer=peer
            )
            assert (
                launcher_parent is not None
                and len(launcher_parent) == 1
                and launcher_parent[0].spent_height is not None
            )
            did_coin: List[CoinState] = await self.wallet_node.get_coin_state(
                [launcher_parent[0].coin.parent_coin_info], peer=peer
            )
            assert did_coin is not None and len(did_coin) == 1 and did_coin[0].spent_height is not None
            did_spend: CoinSpend = await self.wallet_node.fetch_puzzle_solution(
                did_coin[0].spent_height, did_coin[0].coin, peer
            )
            puzzle = Program.from_bytes(bytes(did_spend.puzzle_reveal))
            uncurried = uncurry_puzzle(puzzle)
            did_curried_args = match_did_puzzle(uncurried.mod, uncurried.args)
            if did_curried_args is not None:
                p2_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata = did_curried_args
                minter_did = bytes32(bytes(singleton_struct.rest().first())[1:])
        return minter_did

    async def handle_nft(
        self, coin_spend: CoinSpend, uncurried_nft: UncurriedNFT, parent_coin_state: CoinState
    ) -> Tuple[Optional[uint32], Optional[WalletType]]:
        """
        Handle the new coin when it is a NFT
        :param coin_spend: New coin spend
        :param uncurried_nft: Uncurried NFT
        :param parent_coin_state: Parent coin state
        :return: Wallet ID & Wallet Type
        """
        wallet_id = None
        wallet_type = None
        # DID ID determines which NFT wallet should process the NFT
        new_did_id = None
        old_did_id = None
        # P2 puzzle hash determines if we should ignore the NFT
        old_p2_puzhash = uncurried_nft.p2_puzzle.get_tree_hash()
        metadata, new_p2_puzhash = get_metadata_and_phs(
            uncurried_nft,
            coin_spend.solution,
        )
        if uncurried_nft.supports_did:
            new_did_id = get_new_owner_did(uncurried_nft, coin_spend.solution.to_program())
            old_did_id = uncurried_nft.owner_did
            if new_did_id is None:
                new_did_id = old_did_id
            if new_did_id == b"":
                new_did_id = None
        self.log.debug(
            "Handling NFT: %s， old DID:%s, new DID:%s, old P2:%s, new P2:%s",
            coin_spend,
            old_did_id,
            new_did_id,
            old_p2_puzhash,
            new_p2_puzhash,
        )
        new_derivation_record: Optional[
            DerivationRecord
        ] = await self.puzzle_store.get_derivation_record_for_puzzle_hash(new_p2_puzhash)
        old_derivation_record: Optional[
            DerivationRecord
        ] = await self.puzzle_store.get_derivation_record_for_puzzle_hash(old_p2_puzhash)
        if new_derivation_record is None and old_derivation_record is None:
            self.log.debug(
                "Cannot find a P2 puzzle hash for NFT:%s, this NFT belongs to others.",
                uncurried_nft.singleton_launcher_id.hex(),
            )
            return wallet_id, wallet_type
        for wallet_info in await self.get_all_wallet_info_entries(wallet_type=WalletType.NFT):
            nft_wallet_info: NFTWalletInfo = NFTWalletInfo.from_json_dict(json.loads(wallet_info.data))
            if nft_wallet_info.did_id == old_did_id:
                self.log.info(
                    "Removing old NFT, NFT_ID:%s, DID_ID:%s",
                    uncurried_nft.singleton_launcher_id.hex(),
                    old_did_id,
                )
                nft_wallet: WalletProtocol = self.wallets[wallet_info.id]
                assert isinstance(nft_wallet, NFTWallet)
                if parent_coin_state.spent_height is not None:
                    await nft_wallet.remove_coin(coin_spend.coin, uint32(parent_coin_state.spent_height))
                    num = await nft_wallet.get_current_nfts()
                    if len(num) == 0 and nft_wallet.did_id is not None and new_did_id != old_did_id:
                        self.log.info(f"No NFT, deleting wallet {nft_wallet.did_id.hex()} ...")
                        await self.user_store.delete_wallet(nft_wallet.wallet_info.id)
                        self.wallets.pop(nft_wallet.wallet_info.id)
            if nft_wallet_info.did_id == new_did_id:
                self.log.info(
                    "Adding new NFT, NFT_ID:%s, DID_ID:%s",
                    uncurried_nft.singleton_launcher_id.hex(),
                    new_did_id,
                )
                wallet_id = wallet_info.id
                wallet_type = WalletType.NFT

        if wallet_id is None and new_derivation_record:
            # Cannot find an existed NFT wallet for the new NFT
            self.log.info(
                "Cannot find a NFT wallet for NFT_ID: %s DID_ID: %s, creating a new one.",
                uncurried_nft.singleton_launcher_id,
                new_did_id,
            )
            new_nft_wallet: NFTWallet = await NFTWallet.create_new_nft_wallet(
                self, self.main_wallet, did_id=new_did_id, name="NFT Wallet"
            )
            wallet_id = uint32(new_nft_wallet.wallet_id)
            wallet_type = WalletType.NFT
        return wallet_id, wallet_type

    async def new_coin_state(
        self,
        coin_states: List[CoinState],
        peer: WSChiaConnection,
        fork_height: Optional[uint32],
    ) -> None:
        # TODO: add comment about what this method does
        # Input states should already be sorted by cs_height, with reorgs at the beginning
        curr_h = -1
        for c_state in coin_states:
            last_change_height = last_change_height_cs(c_state)
            if last_change_height < curr_h:
                raise ValueError("Input coin_states is not sorted properly")
            curr_h = last_change_height

        trade_removals = await self.trade_manager.get_coins_of_interest()
        all_unconfirmed: List[TransactionRecord] = await self.tx_store.get_all_unconfirmed()
        trade_coin_removed: List[CoinState] = []
        used_up_to = -1
        ph_to_index_cache: LRUCache = LRUCache(100)

        local_records: List[Optional[WalletCoinRecord]] = await self.coin_store.get_coin_records(
            [st.coin.name() for st in coin_states]
        )

        assert len(local_records) == len(coin_states)
        for coin_state, local_record in zip(coin_states, local_records):
            try:
                async with self.db_wrapper.writer():
                    # This only succeeds if we don't raise out of the transaction
                    await self.retry_store.remove_state(coin_state)

                    existing: Optional[WalletCoinRecord]
                    coin_name: bytes32 = coin_state.coin.name()
                    wallet_info: Optional[Tuple[uint32, WalletType]] = await self.get_wallet_id_for_puzzle_hash(
                        coin_state.coin.puzzle_hash
                    )
                    self.log.debug("%s: %s", coin_name, coin_state)

                    # If we already have this coin, & it was spent & confirmed at the same heights, then return (done)
                    if local_record is not None:
                        local_spent = None
                        if local_record.spent_block_height != 0:
                            local_spent = local_record.spent_block_height
                        if (
                            local_spent == coin_state.spent_height
                            and local_record.confirmed_block_height == coin_state.created_height
                        ):
                            continue

                    wallet_id: Optional[uint32] = None
                    wallet_type: Optional[WalletType] = None
                    if wallet_info is not None:
                        wallet_id, wallet_type = wallet_info
                    elif local_record is not None:
                        wallet_id = uint32(local_record.wallet_id)
                        wallet_type = local_record.wallet_type
                    elif coin_state.created_height is not None:
                        wallet_id, wallet_type = await self.determine_coin_type(peer, coin_state, fork_height)
                        potential_dl = self.get_dl_wallet()
                        if potential_dl is not None:
                            if await potential_dl.get_singleton_record(coin_state.coin.name()) is not None:
                                wallet_id = potential_dl.id()
                                wallet_type = WalletType(potential_dl.type())

                    if wallet_id is None or wallet_type is None:
                        self.log.debug(f"No wallet for coin state: {coin_state}")
                        continue

                    # Update the DB to signal that we used puzzle hashes up to this one
                    derivation_index = ph_to_index_cache.get(coin_state.coin.puzzle_hash)
                    if derivation_index is None:
                        derivation_index = await self.puzzle_store.index_for_puzzle_hash(coin_state.coin.puzzle_hash)
                    if derivation_index is not None:
                        ph_to_index_cache.put(coin_state.coin.puzzle_hash, derivation_index)
                        if derivation_index > used_up_to:
                            await self.puzzle_store.set_used_up_to(derivation_index)
                            used_up_to = max(used_up_to, derivation_index)

                    if coin_state.created_height is None:
                        # TODO implements this coin got reorged
                        # TODO: we need to potentially roll back the pool wallet here
                        pass
                    # if the new coin has not been spent (i.e not ephemeral)
                    elif coin_state.created_height is not None and coin_state.spent_height is None:
                        if local_record is None:
                            await self.coin_added(
                                coin_state.coin,
                                uint32(coin_state.created_height),
                                all_unconfirmed,
                                wallet_id,
                                wallet_type,
                                peer,
                                coin_name,
                            )

                    # if the coin has been spent
                    elif coin_state.created_height is not None and coin_state.spent_height is not None:
                        self.log.debug("Coin Removed: %s", coin_state)
                        if coin_name in trade_removals:
                            trade_coin_removed.append(coin_state)
                        children: Optional[List[CoinState]] = None
                        record = local_record
                        if record is None:
                            farmer_reward = False
                            pool_reward = False
                            tx_type: int
                            if self.is_farmer_reward(uint32(coin_state.created_height), coin_state.coin):
                                farmer_reward = True
                                tx_type = TransactionType.FEE_REWARD.value
                            elif self.is_pool_reward(uint32(coin_state.created_height), coin_state.coin):
                                pool_reward = True
                                tx_type = TransactionType.COINBASE_REWARD.value
                            else:
                                tx_type = TransactionType.INCOMING_TX.value
                            record = WalletCoinRecord(
                                coin_state.coin,
                                uint32(coin_state.created_height),
                                uint32(coin_state.spent_height),
                                True,
                                farmer_reward or pool_reward,
                                wallet_type,
                                wallet_id,
                            )
                            await self.coin_store.add_coin_record(record)
                            # Coin first received
                            parent_coin_record: Optional[WalletCoinRecord] = await self.coin_store.get_coin_record(
                                coin_state.coin.parent_coin_info
                            )
                            if parent_coin_record is not None and wallet_type.value == parent_coin_record.wallet_type:
                                change = True
                            else:
                                change = False

                            if not change:
                                created_timestamp = await self.wallet_node.get_timestamp_for_height(
                                    coin_state.created_height
                                )
                                tx_record = TransactionRecord(
                                    confirmed_at_height=uint32(coin_state.created_height),
                                    created_at_time=uint64(created_timestamp),
                                    to_puzzle_hash=(
                                        await self.convert_puzzle_hash(wallet_id, coin_state.coin.puzzle_hash)
                                    ),
                                    amount=uint64(coin_state.coin.amount),
                                    fee_amount=uint64(0),
                                    confirmed=True,
                                    sent=uint32(0),
                                    spend_bundle=None,
                                    additions=[coin_state.coin],
                                    removals=[],
                                    wallet_id=wallet_id,
                                    sent_to=[],
                                    trade_id=None,
                                    type=uint32(tx_type),
                                    name=bytes32(token_bytes()),
                                    memos=[],
                                )
                                await self.tx_store.add_transaction_record(tx_record)

                            children = await self.wallet_node.fetch_children(
                                coin_name, peer=peer, fork_height=fork_height
                            )
                            assert children is not None
                            additions = [state.coin for state in children]
                            if len(children) > 0:
                                fee = 0

                                to_puzzle_hash = None
                                # Find coin that doesn't belong to us
                                amount = 0
                                for coin in additions:
                                    derivation_record = await self.puzzle_store.get_derivation_record_for_puzzle_hash(
                                        coin.puzzle_hash
                                    )
                                    if derivation_record is None:
                                        to_puzzle_hash = coin.puzzle_hash
                                        amount += coin.amount

                                if to_puzzle_hash is None:
                                    to_puzzle_hash = additions[0].puzzle_hash

                                spent_timestamp = await self.wallet_node.get_timestamp_for_height(
                                    coin_state.spent_height
                                )

                                # Reorg rollback adds reorged transactions so it's possible there is tx_record already
                                # Even though we are just adding coin record to the db (after reorg)
                                tx_records: List[TransactionRecord] = []
                                for out_tx_record in all_unconfirmed:
                                    for rem_coin in out_tx_record.removals:
                                        if rem_coin == coin_state.coin:
                                            tx_records.append(out_tx_record)

                                if len(tx_records) > 0:
                                    for tx_record in tx_records:
                                        await self.tx_store.set_confirmed(
                                            tx_record.name, uint32(coin_state.spent_height)
                                        )
                                else:
                                    tx_record = TransactionRecord(
                                        confirmed_at_height=uint32(coin_state.spent_height),
                                        created_at_time=uint64(spent_timestamp),
                                        to_puzzle_hash=(await self.convert_puzzle_hash(wallet_id, to_puzzle_hash)),
                                        amount=uint64(int(amount)),
                                        fee_amount=uint64(fee),
                                        confirmed=True,
                                        sent=uint32(0),
                                        spend_bundle=None,
                                        additions=additions,
                                        removals=[coin_state.coin],
                                        wallet_id=wallet_id,
                                        sent_to=[],
                                        trade_id=None,
                                        type=uint32(TransactionType.OUTGOING_TX.value),
                                        name=bytes32(token_bytes()),
                                        memos=[],
                                    )

                                    await self.tx_store.add_transaction_record(tx_record)
                        else:
                            await self.coin_store.set_spent(coin_name, uint32(coin_state.spent_height))
                            rem_tx_records: List[TransactionRecord] = []
                            for out_tx_record in all_unconfirmed:
                                for rem_coin in out_tx_record.removals:
                                    if rem_coin == coin_state.coin:
                                        rem_tx_records.append(out_tx_record)

                            for tx_record in rem_tx_records:
                                await self.tx_store.set_confirmed(tx_record.name, uint32(coin_state.spent_height))
                        for unconfirmed_record in all_unconfirmed:
                            for rem_coin in unconfirmed_record.removals:
                                if rem_coin == coin_state.coin:
                                    self.log.info(f"Setting tx_id: {unconfirmed_record.name} to confirmed")
                                    await self.tx_store.set_confirmed(
                                        unconfirmed_record.name, uint32(coin_state.spent_height)
                                    )

                        if record.wallet_type == WalletType.POOLING_WALLET:
                            if coin_state.spent_height is not None and coin_state.coin.amount == uint64(1):
                                wallet = self.wallets[uint32(record.wallet_id)]
                                assert isinstance(wallet, PoolWallet)
                                curr_coin_state: CoinState = coin_state

                                while curr_coin_state.spent_height is not None:
                                    cs: CoinSpend = await self.wallet_node.fetch_puzzle_solution(
                                        curr_coin_state.spent_height, curr_coin_state.coin, peer
                                    )
                                    success = await wallet.apply_state_transition(
                                        cs, uint32(curr_coin_state.spent_height)
                                    )
                                    if not success:
                                        break
                                    new_singleton_coin: Optional[Coin] = wallet.get_next_interesting_coin(cs)
                                    if new_singleton_coin is None:
                                        # No more singleton (maybe destroyed?)
                                        break

                                    coin_name = new_singleton_coin.name()
                                    existing = await self.coin_store.get_coin_record(coin_name)
                                    if existing is None:
                                        await self.coin_added(
                                            new_singleton_coin,
                                            uint32(coin_state.spent_height),
                                            [],
                                            uint32(record.wallet_id),
                                            record.wallet_type,
                                            peer,
                                            coin_name,
                                        )
                                    await self.coin_store.set_spent(
                                        curr_coin_state.coin.name(), uint32(curr_coin_state.spent_height)
                                    )
                                    await self.add_interested_coin_ids([new_singleton_coin.name()])
                                    new_coin_state: List[CoinState] = await self.wallet_node.get_coin_state(
                                        [coin_name], peer=peer, fork_height=fork_height
                                    )
                                    assert len(new_coin_state) == 1
                                    curr_coin_state = new_coin_state[0]
                        if record.wallet_type == WalletType.DATA_LAYER:
                            singleton_spend = await self.wallet_node.fetch_puzzle_solution(
                                coin_state.spent_height, coin_state.coin, peer
                            )
                            dl_wallet = self.wallets[uint32(record.wallet_id)]
                            assert isinstance(dl_wallet, DataLayerWallet)
                            await dl_wallet.singleton_removed(
                                singleton_spend,
                                uint32(coin_state.spent_height),
                            )

                        elif record.wallet_type == WalletType.NFT:
                            if coin_state.spent_height is not None:
                                nft_wallet = self.wallets[uint32(record.wallet_id)]
                                assert isinstance(nft_wallet, NFTWallet)
                                await nft_wallet.remove_coin(coin_state.coin, uint32(coin_state.spent_height))

                        # Check if a child is a singleton launcher
                        if children is None:
                            children = await self.wallet_node.fetch_children(
                                coin_name, peer=peer, fork_height=fork_height
                            )
                        assert children is not None
                        for child in children:
                            if child.coin.puzzle_hash != SINGLETON_LAUNCHER_HASH:
                                continue
                            if await self.have_a_pool_wallet_with_launched_id(child.coin.name()):
                                continue
                            if child.spent_height is None:
                                # TODO handle spending launcher later block
                                continue
                            launcher_spend: Optional[CoinSpend] = await self.wallet_node.fetch_puzzle_solution(
                                coin_state.spent_height, child.coin, peer
                            )
                            if launcher_spend is None:
                                continue
                            try:
                                pool_state = solution_to_pool_state(launcher_spend)
                                assert pool_state is not None
                            except (AssertionError, ValueError) as e:
                                self.log.debug(f"Not a pool wallet launcher {e}")
                                matched, inner_puzhash = await DataLayerWallet.match_dl_launcher(launcher_spend)
                                if (
                                    matched
                                    and inner_puzhash is not None
                                    and (await self.puzzle_store.puzzle_hash_exists(inner_puzhash))
                                ):
                                    for _, wallet in self.wallets.items():
                                        if wallet.type() == WalletType.DATA_LAYER.value:
                                            assert isinstance(wallet, DataLayerWallet)
                                            dl_wallet = wallet
                                            break
                                    else:  # No DL wallet exists yet
                                        dl_wallet = await DataLayerWallet.create_new_dl_wallet(
                                            self,
                                            self.main_wallet,
                                        )
                                    await dl_wallet.track_new_launcher_id(
                                        child.coin.name(),
                                        peer,
                                        spend=launcher_spend,
                                        height=uint32(child.spent_height),
                                    )
                                continue

                            # solution_to_pool_state may return None but this may not be an error
                            if pool_state is None:
                                self.log.debug("solution_to_pool_state returned None, ignore and continue")
                                continue

                            assert child.spent_height is not None
                            pool_wallet = await PoolWallet.create(
                                self,
                                self.main_wallet,
                                child.coin.name(),
                                [launcher_spend],
                                uint32(child.spent_height),
                                name="pool_wallet",
                            )
                            launcher_spend_additions = launcher_spend.additions()
                            assert len(launcher_spend_additions) == 1
                            coin_added = launcher_spend_additions[0]
                            coin_name = coin_added.name()
                            existing = await self.coin_store.get_coin_record(coin_name)
                            if existing is None:
                                await self.coin_added(
                                    coin_added,
                                    uint32(coin_state.spent_height),
                                    [],
                                    pool_wallet.id(),
                                    WalletType(pool_wallet.type()),
                                    peer,
                                    coin_name,
                                )
                            await self.add_interested_coin_ids([coin_name])

                    else:
                        raise RuntimeError("All cases already handled")  # Logic error, all cases handled
            except Exception as e:
                self.log.exception(f"Error adding state... {e}")
                if isinstance(e, PeerRequestException) or isinstance(e, aiosqlite.Error):
                    await self.retry_store.add_state(coin_state, peer.peer_node_id, fork_height)
                else:
                    await self.retry_store.remove_state(coin_state)
                continue
        for coin_state_removed in trade_coin_removed:
            await self.trade_manager.coins_of_interest_farmed(coin_state_removed, fork_height, peer)

    async def have_a_pool_wallet_with_launched_id(self, launcher_id: bytes32) -> bool:
        for wallet_id, wallet in self.wallets.items():
            if wallet.type() == WalletType.POOLING_WALLET:
                assert isinstance(wallet, PoolWallet)
                if (await wallet.get_current_state()).launcher_id == launcher_id:
                    self.log.warning("Already have, not recreating")
                    return True
        return False

    def is_pool_reward(self, created_height: uint32, coin: Coin) -> bool:
        if coin.amount != calculate_pool_reward(created_height) and coin.amount != calculate_pool_reward(
            uint32(max(0, created_height - 128))
        ):
            # Optimization to avoid the computation below. Any coin that has a different amount is not a pool reward
            return False
        for i in range(0, 30):
            try_height = created_height - i
            if try_height < 0:
                break
            calculated = pool_parent_id(uint32(try_height), self.constants.GENESIS_CHALLENGE)
            if calculated == coin.parent_coin_info:
                return True
        return False

    def is_farmer_reward(self, created_height: uint32, coin: Coin) -> bool:
        if coin.amount < calculate_base_farmer_reward(created_height):
            # Optimization to avoid the computation below. Any coin less than this base amount cannot be farmer reward
            return False
        for i in range(0, 30):
            try_height = created_height - i
            if try_height < 0:
                break
            calculated = farmer_parent_id(uint32(try_height), self.constants.GENESIS_CHALLENGE)
            if calculated == coin.parent_coin_info:
                return True
        return False

    async def get_wallet_id_for_puzzle_hash(self, puzzle_hash: bytes32) -> Optional[Tuple[uint32, WalletType]]:
        info = await self.puzzle_store.wallet_info_for_puzzle_hash(puzzle_hash)
        if info is not None:
            wallet_id, wallet_type = info
            return uint32(wallet_id), wallet_type

        interested_wallet_id = await self.interested_store.get_interested_puzzle_hash_wallet_id(puzzle_hash=puzzle_hash)
        if interested_wallet_id is not None:
            wallet_id = uint32(interested_wallet_id)
            if wallet_id not in self.wallets.keys():
                self.log.warning(f"Do not have wallet {wallet_id} for puzzle_hash {puzzle_hash}")
                return None
            wallet_type = WalletType(self.wallets[uint32(wallet_id)].type())
            return uint32(wallet_id), wallet_type
        return None

    async def coin_added(
        self,
        coin: Coin,
        height: uint32,
        all_unconfirmed_transaction_records: List[TransactionRecord],
        wallet_id: uint32,
        wallet_type: WalletType,
        peer: WSChiaConnection,
        coin_name: bytes32,
    ) -> None:
        """
        Adding coin to DB
        """

        self.log.debug(
            "Adding record to state manager coin: %s at %s wallet_id: %s and type: %s",
            coin,
            height,
            wallet_id,
            wallet_type,
        )
        farmer_reward = False
        pool_reward = False
        if self.is_farmer_reward(height, coin):
            farmer_reward = True
        elif self.is_pool_reward(height, coin):
            pool_reward = True

        farm_reward = False
        parent_coin_record: Optional[WalletCoinRecord] = await self.coin_store.get_coin_record(coin.parent_coin_info)
        if parent_coin_record is not None and wallet_type.value == parent_coin_record.wallet_type:
            change = True
        else:
            change = False

        if farmer_reward or pool_reward:
            farm_reward = True
            if pool_reward:
                tx_type: int = TransactionType.COINBASE_REWARD.value
            else:
                tx_type = TransactionType.FEE_REWARD.value
            timestamp = await self.wallet_node.get_timestamp_for_height(height)

            tx_record = TransactionRecord(
                confirmed_at_height=uint32(height),
                created_at_time=timestamp,
                to_puzzle_hash=(await self.convert_puzzle_hash(wallet_id, coin.puzzle_hash)),
                amount=uint64(coin.amount),
                fee_amount=uint64(0),
                confirmed=True,
                sent=uint32(0),
                spend_bundle=None,
                additions=[coin],
                removals=[],
                wallet_id=wallet_id,
                sent_to=[],
                trade_id=None,
                type=uint32(tx_type),
                name=coin_name,
                memos=[],
            )
            await self.tx_store.add_transaction_record(tx_record)
        else:
            records: List[TransactionRecord] = []
            for record in all_unconfirmed_transaction_records:
                for add_coin in record.additions:
                    if add_coin == coin:
                        records.append(record)

            if len(records) > 0:
                for record in records:
                    if record.confirmed is False:
                        await self.tx_store.set_confirmed(record.name, height)
            elif not change:
                timestamp = await self.wallet_node.get_timestamp_for_height(height)
                tx_record = TransactionRecord(
                    confirmed_at_height=uint32(height),
                    created_at_time=timestamp,
                    to_puzzle_hash=(await self.convert_puzzle_hash(wallet_id, coin.puzzle_hash)),
                    amount=uint64(coin.amount),
                    fee_amount=uint64(0),
                    confirmed=True,
                    sent=uint32(0),
                    spend_bundle=None,
                    additions=[coin],
                    removals=[],
                    wallet_id=wallet_id,
                    sent_to=[],
                    trade_id=None,
                    type=uint32(TransactionType.INCOMING_TX.value),
                    name=coin_name,
                    memos=[],
                )
                if coin.amount > 0:
                    await self.tx_store.add_transaction_record(tx_record)

        coin_record_1: WalletCoinRecord = WalletCoinRecord(
            coin, height, uint32(0), False, farm_reward, wallet_type, wallet_id
        )
        await self.coin_store.add_coin_record(coin_record_1, coin_name)

        await self.wallets[wallet_id].coin_added(coin, height, peer)

        await self.create_more_puzzle_hashes()

    async def add_pending_transaction(self, tx_record: TransactionRecord):
        """
        Called from wallet before new transaction is sent to the full_node
        """
        # Wallet node will use this queue to retry sending this transaction until full nodes receives it
        await self.tx_store.add_transaction_record(tx_record)
        all_coins_names = []
        all_coins_names.extend([coin.name() for coin in tx_record.additions])
        all_coins_names.extend([coin.name() for coin in tx_record.removals])

        await self.add_interested_coin_ids(all_coins_names)
        if tx_record.spend_bundle is not None:
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
        updated = await self.tx_store.increment_sent(spendbundle_id, name, send_status, error)
        if updated:
            tx: Optional[TransactionRecord] = await self.get_transaction(spendbundle_id)
            if tx is not None:
                self.state_changed("tx_update", tx.wallet_id, {"transaction": tx})

    async def get_all_transactions(self, wallet_id: int) -> List[TransactionRecord]:
        """
        Retrieves all confirmed and pending transactions
        """
        records = await self.tx_store.get_all_transactions_for_wallet(wallet_id)
        return records

    async def get_transaction(self, tx_id: bytes32) -> Optional[TransactionRecord]:
        return await self.tx_store.get_transaction_record(tx_id)

    async def get_transaction_by_wallet_record(self, wr: WalletCoinRecord) -> Optional[TransactionRecord]:
        records = await self.tx_store.get_transactions_by_height(wr.confirmed_block_height)
        for record in records:
            if wr.coin in record.additions or record.removals:
                return record
        return None

    async def get_coin_record_by_wallet_record(self, wr: WalletCoinRecord) -> CoinRecord:
        timestamp: uint64 = await self.wallet_node.get_timestamp_for_height(wr.confirmed_block_height)
        return wr.to_coin_record(timestamp)

    async def get_coin_records_by_coin_ids(self, **kwargs) -> List[CoinRecord]:
        records: List[Optional[WalletCoinRecord]] = await self.coin_store.get_coin_records(**kwargs)
        return [await self.get_coin_record_by_wallet_record(record) for record in records if record is not None]

    async def is_addition_relevant(self, addition: Coin):
        """
        Check whether we care about a new addition (puzzle_hash). Returns true if we
        control this puzzle hash.
        """
        result = await self.puzzle_store.puzzle_hash_exists(addition.puzzle_hash)
        return result

    async def get_wallet_for_coin(self, coin_id: bytes32) -> Optional[WalletProtocol]:
        coin_record = await self.coin_store.get_coin_record(coin_id)
        if coin_record is None:
            return None
        wallet_id = uint32(coin_record.wallet_id)
        wallet = self.wallets[wallet_id]
        return wallet

    async def reorg_rollback(self, height: int) -> List[uint32]:
        """
        Rolls back and updates the coin_store and transaction store. It's possible this height
        is the tip, or even beyond the tip.
        """
        await self.nft_store.rollback_to_block(height)
        await self.coin_store.rollback_to_block(height)
        reorged: List[TransactionRecord] = await self.tx_store.get_transaction_above(height)
        await self.tx_store.rollback_to_block(height)
        for record in reorged:
            if record.type in [
                TransactionType.OUTGOING_TX,
                TransactionType.OUTGOING_TRADE,
                TransactionType.INCOMING_TRADE,
            ]:
                await self.tx_store.tx_reorged(record)

        # Removes wallets that were created from a blockchain transaction which got reorged.
        remove_ids: List[uint32] = []
        for wallet_id, wallet in self.wallets.items():
            if wallet.type() == WalletType.POOLING_WALLET.value:
                assert isinstance(wallet, PoolWallet)
                remove: bool = await wallet.rewind(height)
                if remove:
                    remove_ids.append(wallet_id)
            if wallet.type() == WalletType.NFT.value:
                assert isinstance(wallet, NFTWallet)
                if await wallet.get_nft_count() == 0:
                    remove_ids.append(wallet_id)
        for wallet_id in remove_ids:
            await self.user_store.delete_wallet(wallet_id)

        return remove_ids

    async def _await_closed(self) -> None:
        await self.db_wrapper.close()

    def unlink_db(self) -> None:
        Path(self.db_path).unlink()

    async def get_all_wallet_info_entries(self, wallet_type: Optional[WalletType] = None) -> List[WalletInfo]:
        return await self.user_store.get_all_wallet_info_entries(wallet_type)

    async def get_wallet_for_asset_id(self, asset_id: str):
        for wallet_id in self.wallets:
            wallet = self.wallets[wallet_id]
            if wallet.type() == WalletType.CAT:
                assert isinstance(wallet, CATWallet)
                if bytes(wallet.cat_info.limitations_program_hash).hex() == asset_id:
                    return wallet
            elif wallet.type() == WalletType.DATA_LAYER:
                assert isinstance(wallet, DataLayerWallet)
                if await wallet.get_latest_singleton(bytes32.from_hexstr(asset_id)) is not None:
                    return wallet
            elif wallet.type() == WalletType.NFT:
                assert isinstance(wallet, NFTWallet)
                nft_coin = await self.nft_store.get_nft_by_id(bytes32.from_hexstr(asset_id), wallet_id)
                if nft_coin:
                    return wallet
        return None

    async def get_wallet_for_puzzle_info(self, puzzle_driver: PuzzleInfo):
        for wallet in self.wallets.values():
            match_function = getattr(wallet, "match_puzzle_info", None)
            if match_function is not None and callable(match_function):
                if match_function(puzzle_driver):
                    return wallet
        return None

    async def create_wallet_for_puzzle_info(self, puzzle_driver: PuzzleInfo, name=None):
        if AssetType(puzzle_driver.type()) in self.asset_to_wallet_map:
            await self.asset_to_wallet_map[AssetType(puzzle_driver.type())].create_from_puzzle_info(
                self,
                self.main_wallet,
                puzzle_driver,
                name,
            )

    async def add_new_wallet(self, wallet: Any, wallet_id: int, create_puzzle_hashes=True):
        self.wallets[uint32(wallet_id)] = wallet
        if create_puzzle_hashes:
            await self.create_more_puzzle_hashes()
        self.state_changed("wallet_created")

    async def get_spendable_coins_for_wallet(
        self, wallet_id: int, records: Optional[Set[WalletCoinRecord]] = None
    ) -> Set[WalletCoinRecord]:
        if records is None:
            records = await self.coin_store.get_unspent_coins_for_wallet(wallet_id)

        # Coins that are currently part of a transaction
        unconfirmed_tx: List[TransactionRecord] = await self.tx_store.get_unconfirmed_for_wallet(wallet_id)
        removal_dict: Dict[bytes32, Coin] = {}
        for tx in unconfirmed_tx:
            for coin in tx.removals:
                # TODO, "if" might not be necessary once unconfirmed tx doesn't contain coins for other wallets
                if await self.does_coin_belong_to_wallet(coin, wallet_id):
                    removal_dict[coin.name()] = coin

        # Coins that are part of the trade
        offer_locked_coins: Dict[bytes32, WalletCoinRecord] = await self.trade_manager.get_locked_coins()

        filtered = set()
        for record in records:
            if record.coin.name() in offer_locked_coins:
                continue
            if record.coin.name() in removal_dict:
                continue
            filtered.add(record)

        return filtered

    async def new_peak(self, peak: wallet_protocol.NewPeakWallet):
        for wallet_id, wallet in self.wallets.items():
            if wallet.type() == uint8(WalletType.POOLING_WALLET):
                assert isinstance(wallet, PoolWallet)
                await wallet.new_peak(uint64(peak.height))
        current_time = int(time.time())

        if self.wallet_node.last_wallet_tx_resend_time < current_time - self.wallet_node.wallet_tx_resend_timeout_secs:
            self.tx_pending_changed()

    async def add_interested_puzzle_hashes(self, puzzle_hashes: List[bytes32], wallet_ids: List[int]) -> None:
        for puzzle_hash, wallet_id in zip(puzzle_hashes, wallet_ids):
            await self.interested_store.add_interested_puzzle_hash(puzzle_hash, wallet_id)
        if len(puzzle_hashes) > 0:
            await self.wallet_node.new_peak_queue.subscribe_to_puzzle_hashes(puzzle_hashes)

    async def add_interested_coin_ids(self, coin_ids: List[bytes32]) -> None:
        for coin_id in coin_ids:
            await self.interested_store.add_interested_coin_id(coin_id)
        if len(coin_ids) > 0:
            await self.wallet_node.new_peak_queue.subscribe_to_coin_ids(coin_ids)

    async def delete_trade_transactions(self, trade_id: bytes32):
        txs: List[TransactionRecord] = await self.tx_store.get_transactions_by_trade_id(trade_id)
        for tx in txs:
            await self.tx_store.delete_transaction_record(tx.name)

    async def convert_puzzle_hash(self, wallet_id: uint32, puzzle_hash: bytes32) -> bytes32:
        wallet = self.wallets[wallet_id]
        # This should be general to wallets but for right now this is just for CATs so we'll add this if
        if wallet.type() == WalletType.CAT.value:
            assert isinstance(wallet, CATWallet)
            return await wallet.convert_puzzle_hash(puzzle_hash)

        return puzzle_hash

    def get_dl_wallet(self) -> Optional[DataLayerWallet]:
        for _, wallet in self.wallets.items():
            if wallet.type() == WalletType.DATA_LAYER.value:
                assert isinstance(wallet, DataLayerWallet)
                return wallet
        return None
