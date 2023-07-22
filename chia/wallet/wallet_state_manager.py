from __future__ import annotations

import asyncio
import logging
import multiprocessing.context
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_bytes
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Set, Type, TypeVar

import aiosqlite
from blspy import G1Element, G2Element, PrivateKey

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.consensus.coinbase import farmer_parent_id, pool_parent_id
from chia.consensus.constants import ConsensusConstants
from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.data_layer.dl_wallet_store import DataLayerStore
from chia.pools.pool_puzzles import (
    SINGLETON_LAUNCHER_HASH,
    get_most_recent_singleton_coin_from_coin_spend,
    solution_to_pool_state,
)
from chia.pools.pool_wallet import PoolWallet
from chia.protocols.wallet_protocol import CoinState, NewPeakWallet
from chia.rpc.rpc_server import StateChangedProtocol
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import encode_puzzle_hash
from chia.util.db_synchronous import db_synchronous_on
from chia.util.db_wrapper import DBWrapper2
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
from chia.util.lru_cache import LRUCache
from chia.util.misc import UInt32Range, UInt64Range, VersionedBlob
from chia.util.path import path_from_root
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, CAT_MOD_HASH, construct_cat_puzzle, match_cat_puzzle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.db_wallet.db_wallet_puzzles import MIRROR_PUZZLE_HASH
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import (
    _derive_path,
    _derive_path_unhardened,
    master_sk_to_wallet_sk,
    master_sk_to_wallet_sk_intermediate,
    master_sk_to_wallet_sk_unhardened,
    master_sk_to_wallet_sk_unhardened_intermediate,
)
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.did_wallet.did_wallet_puzzles import DID_INNERPUZ_MOD, match_did_puzzle
from chia.wallet.key_val_store import KeyValStore
from chia.wallet.nft_wallet.nft_puzzles import get_metadata_and_phs, get_new_owner_did
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.notification_manager import NotificationManager
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.puzzles.clawback.drivers import generate_clawback_spend_bundle, match_clawback_puzzle
from chia.wallet.puzzles.clawback.metadata import ClawbackMetadata, ClawbackVersion
from chia.wallet.singleton import create_singleton_puzzle
from chia.wallet.trade_manager import TradeManager
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.compute_hints import compute_spend_hints_and_additions
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.puzzle_decorator import PuzzleDecoratorManager
from chia.wallet.util.query_filter import HashFilter
from chia.wallet.util.transaction_type import CLAWBACK_INCOMING_TRANSACTION_TYPES, TransactionType
from chia.wallet.util.wallet_sync_utils import (
    PeerRequestException,
    fetch_coin_spend_for_coin_state,
    last_change_height_cs,
)
from chia.wallet.util.wallet_types import CoinType, WalletIdentifier, WalletType
from chia.wallet.vc_wallet.vc_drivers import VerifiedCredential
from chia.wallet.vc_wallet.vc_store import VCStore
from chia.wallet.vc_wallet.vc_wallet import VCWallet
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_blockchain import WalletBlockchain
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_coin_store import WalletCoinStore
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_interested_store import WalletInterestedStore
from chia.wallet.wallet_nft_store import WalletNftStore
from chia.wallet.wallet_pool_store import WalletPoolStore
from chia.wallet.wallet_protocol import WalletProtocol
from chia.wallet.wallet_puzzle_store import WalletPuzzleStore
from chia.wallet.wallet_retry_store import WalletRetryStore
from chia.wallet.wallet_transaction_store import WalletTransactionStore
from chia.wallet.wallet_user_store import WalletUserStore

TWalletType = TypeVar("TWalletType", bound=WalletProtocol)

if TYPE_CHECKING:
    from chia.wallet.wallet_node import WalletNode


PendingTxCallback = Callable[[], None]


class WalletStateManager:
    constants: ConsensusConstants
    config: Dict[str, Any]
    tx_store: WalletTransactionStore
    puzzle_store: WalletPuzzleStore
    user_store: WalletUserStore
    nft_store: WalletNftStore
    vc_store: VCStore
    basic_store: KeyValStore

    # Makes sure only one asyncio thread is changing the blockchain state at one time
    lock: asyncio.Lock

    log: logging.Logger

    # TODO Don't allow user to send tx until wallet is synced
    _sync_target: Optional[uint32]

    state_changed_callback: Optional[StateChangedProtocol] = None
    pending_tx_callback: Optional[PendingTxCallback]
    db_path: Path
    db_wrapper: DBWrapper2

    main_wallet: Wallet
    wallets: Dict[uint32, WalletProtocol]
    private_key: PrivateKey

    trade_manager: TradeManager
    notification_manager: NotificationManager
    blockchain: WalletBlockchain
    coin_store: WalletCoinStore
    interested_store: WalletInterestedStore
    retry_store: WalletRetryStore
    multiprocessing_context: multiprocessing.context.BaseContext
    server: ChiaServer
    root_path: Path
    wallet_node: WalletNode
    pool_store: WalletPoolStore
    dl_store: DataLayerStore
    default_cats: Dict[str, Any]
    asset_to_wallet_map: Dict[AssetType, Any]
    initial_num_public_keys: int
    decorator_manager: PuzzleDecoratorManager

    @staticmethod
    async def create(
        private_key: PrivateKey,
        config: Dict[str, Any],
        db_path: Path,
        constants: ConsensusConstants,
        server: ChiaServer,
        root_path: Path,
        wallet_node: WalletNode,
    ) -> WalletStateManager:
        self = WalletStateManager()
        self.config = config
        self.constants = constants
        self.server = server
        self.root_path = root_path
        self.log = logging.getLogger(__name__)
        self.lock = asyncio.Lock()
        self.log.debug(f"Starting in db path: {db_path}")
        fingerprint = private_key.get_g1().get_fingerprint()
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
        self.vc_store = await VCStore.create(self.db_wrapper)
        self.basic_store = await KeyValStore.create(self.db_wrapper)
        self.trade_manager = await TradeManager.create(self, self.db_wrapper)
        self.notification_manager = await NotificationManager.create(self, self.db_wrapper)
        self.pool_store = await WalletPoolStore.create(self.db_wrapper)
        self.dl_store = await DataLayerStore.create(self.db_wrapper)
        self.interested_store = await WalletInterestedStore.create(self.db_wrapper)
        self.retry_store = await WalletRetryStore.create(self.db_wrapper)
        self.default_cats = DEFAULT_CATS

        self.wallet_node = wallet_node
        self._sync_target = None
        self.blockchain = await WalletBlockchain.create(self.basic_store, self.constants)
        self.state_changed_callback = None
        self.pending_tx_callback = None
        self.db_path = db_path
        puzzle_decorators = self.config.get("puzzle_decorators", {}).get(fingerprint, [])
        self.decorator_manager = PuzzleDecoratorManager.create(puzzle_decorators)

        main_wallet_info = await self.user_store.get_wallet_by_id(1)
        assert main_wallet_info is not None

        self.private_key = private_key
        self.main_wallet = await Wallet.create(self, main_wallet_info)

        self.wallets = {main_wallet_info.id: self.main_wallet}

        self.asset_to_wallet_map = {
            AssetType.CAT: CATWallet,
        }

        wallet: Optional[WalletProtocol] = None
        for wallet_info in await self.get_all_wallet_info_entries():
            wallet_type = WalletType(wallet_info.type)
            if wallet_type == WalletType.STANDARD_WALLET:
                if wallet_info.id == 1:
                    continue
                wallet = await Wallet.create(self, wallet_info)
            elif wallet_type == WalletType.CAT:
                wallet = await CATWallet.create(
                    self,
                    self.main_wallet,
                    wallet_info,
                )
            elif wallet_type == WalletType.DECENTRALIZED_ID:
                wallet = await DIDWallet.create(
                    self,
                    self.main_wallet,
                    wallet_info,
                )
            elif wallet_type == WalletType.NFT:
                wallet = await NFTWallet.create(
                    self,
                    self.main_wallet,
                    wallet_info,
                )
            elif wallet_type == WalletType.POOLING_WALLET:
                wallet = await PoolWallet.create_from_db(
                    self,
                    self.main_wallet,
                    wallet_info,
                )
            elif wallet_type == WalletType.DATA_LAYER:
                wallet = await DataLayerWallet.create(self, wallet_info)
            elif wallet_type == WalletType.VC:  # pragma: no cover
                wallet = await VCWallet.create(
                    self,
                    self.main_wallet,
                    wallet_info,
                )
            if wallet is not None:
                self.wallets[wallet_info.id] = wallet

        return self

    def get_public_key_unhardened(self, index: uint32) -> G1Element:
        return master_sk_to_wallet_sk_unhardened(self.private_key, index).get_g1()

    async def get_private_key(self, puzzle_hash: bytes32) -> PrivateKey:
        record = await self.puzzle_store.record_for_puzzle_hash(puzzle_hash)
        if record is None:
            raise ValueError(f"No key for puzzle hash: {puzzle_hash.hex()}")
        if record.hardened:
            return master_sk_to_wallet_sk(self.private_key, record.index)
        return master_sk_to_wallet_sk_unhardened(self.private_key, record.index)

    def get_wallet(self, id: uint32, required_type: Type[TWalletType]) -> TWalletType:
        wallet = self.wallets[id]
        if not isinstance(wallet, required_type):
            raise Exception(
                f"wallet id {id} is of type {type(wallet).__name__} but type {required_type.__name__} is required",
            )

        return wallet

    async def create_more_puzzle_hashes(
        self,
        from_zero: bool = False,
        mark_existing_as_used: bool = True,
        up_to_index: Optional[uint32] = None,
        num_additional_phs: Optional[int] = None,
    ) -> None:
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
                    if target_wallet.type() == WalletType.POOLING_WALLET:
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
                            target_wallet.type(),
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
                            target_wallet.type(),
                            uint32(target_wallet.id()),
                            False,
                        )
                    )
                self.log.info(f"Done: {creating_msg} Time: {time.time() - start_t} seconds")
            await self.puzzle_store.add_derivation_paths(derivation_paths)
            if len(derivation_paths) > 0:
                if wallet_id == self.main_wallet.id():
                    await self.wallet_node.new_peak_queue.subscribe_to_puzzle_hashes(
                        [record.puzzle_hash for record in derivation_paths]
                    )
                self.state_changed("new_derivation_index", data_object={"index": derivation_paths[-1].index})
        # By default, we'll mark previously generated unused puzzle hashes as used if we have new paths
        if mark_existing_as_used and unused > 0 and new_paths:
            self.log.info(f"Updating last used derivation index: {unused - 1}")
            await self.puzzle_store.set_used_up_to(uint32(unused - 1))

    async def update_wallet_puzzle_hashes(self, wallet_id: uint32) -> None:
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
                puzzlehash = target_wallet.puzzle_hash_for_pk(pubkey)
                self.log.info(f"Generating public key at index {index} puzzle hash {puzzlehash.hex()}")
                derivation_paths.append(
                    DerivationRecord(
                        uint32(index),
                        puzzlehash,
                        pubkey,
                        WalletType(target_wallet.wallet_info.type),
                        uint32(target_wallet.wallet_info.id),
                        False,
                    )
                )
            await self.puzzle_store.add_derivation_paths(derivation_paths)

    async def get_unused_derivation_record(self, wallet_id: uint32, *, hardened: bool = False) -> DerivationRecord:
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
            if record is None:
                raise ValueError(f"Missing derivation '{unused}' for wallet id '{wallet_id}' (hardened={hardened})")

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

    def set_callback(self, callback: StateChangedProtocol) -> None:
        """
        Callback to be called when the state of the wallet changes.
        """
        self.state_changed_callback = callback

    def set_pending_callback(self, callback: PendingTxCallback) -> None:
        """
        Callback to be called when new pending transaction enters the store
        """
        self.pending_tx_callback = callback

    def state_changed(
        self, state: str, wallet_id: Optional[int] = None, data_object: Optional[Dict[str, Any]] = None
    ) -> None:
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

    async def synced(self) -> bool:
        if len(self.server.get_connections(NodeType.FULL_NODE)) == 0:
            return False

        latest = await self.blockchain.get_peak_block()
        if latest is None:
            return False

        if "simulator" in self.config.get("selected_network", ""):
            return True  # sim is always synced if we have a genesis block.

        if latest.height - await self.blockchain.get_finished_sync_up_to() > 1:
            return False

        latest_timestamp = self.blockchain.get_latest_timestamp()
        has_pending_queue_items = self.wallet_node.new_peak_queue.has_pending_data_process_items()

        if latest_timestamp > int(time.time()) - 5 * 60 and not has_pending_queue_items:
            return True
        return False

    @property
    def sync_mode(self) -> bool:
        return self._sync_target is not None

    @property
    def sync_target(self) -> Optional[uint32]:
        return self._sync_target

    @asynccontextmanager
    async def set_sync_mode(self, target_height: uint32) -> AsyncIterator[uint32]:
        if self.log.level == logging.DEBUG:
            self.log.debug(f"set_sync_mode enter {await self.blockchain.get_finished_sync_up_to()}-{target_height}")
        async with self.lock:
            self._sync_target = target_height
            start_time = time.time()
            start_height = await self.blockchain.get_finished_sync_up_to()
            self.log.info(f"set_sync_mode syncing - range: {start_height}-{target_height}")
            self.state_changed("sync_changed")
            try:
                yield start_height
            except Exception:
                self.log.exception(
                    f"set_sync_mode failed - range: {start_height}-{target_height}, seconds: {time.time() - start_time}"
                )
            finally:
                self.state_changed("sync_changed")
                if self.log.level == logging.DEBUG:
                    self.log.debug(
                        f"set_sync_mode exit - range: {start_height}-{target_height}, "
                        f"get_finished_sync_up_to: {await self.blockchain.get_finished_sync_up_to()}, "
                        f"seconds: {time.time() - start_time}"
                    )
                self._sync_target = None

    async def get_confirmed_spendable_balance_for_wallet(
        self, wallet_id: int, unspent_records: Optional[Set[WalletCoinRecord]] = None
    ) -> uint128:
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
        wallet_identifier = await self.puzzle_store.get_wallet_identifier_for_puzzle_hash(coin.puzzle_hash)
        return wallet_identifier is not None and wallet_identifier.id == wallet_id

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
    ) -> Optional[WalletIdentifier]:
        if coin_state.created_height is not None and (
            self.is_pool_reward(uint32(coin_state.created_height), coin_state.coin)
            or self.is_farmer_reward(uint32(coin_state.created_height), coin_state.coin)
        ):
            return None

        response: List[CoinState] = await self.wallet_node.get_coin_state(
            [coin_state.coin.parent_coin_info], peer=peer, fork_height=fork_height
        )
        if len(response) == 0:
            self.log.warning(f"Could not find a parent coin with ID: {coin_state.coin.parent_coin_info}")
            return None
        parent_coin_state = response[0]
        assert parent_coin_state.spent_height == coin_state.created_height

        coin_spend = await fetch_coin_spend_for_coin_state(parent_coin_state, peer)
        if coin_spend is None:
            return None

        puzzle = Program.from_bytes(bytes(coin_spend.puzzle_reveal))

        uncurried = uncurry_puzzle(puzzle)

        # Check if the coin is a CAT
        cat_curried_args = match_cat_puzzle(uncurried)
        if cat_curried_args is not None:
            return await self.handle_cat(
                cat_curried_args,
                parent_coin_state,
                coin_state,
                coin_spend,
                peer,
                fork_height,
            )

        # Check if the coin is a NFT
        #                                                        hint
        # First spend where 1 mojo coin -> Singleton launcher -> NFT -> NFT
        uncurried_nft = UncurriedNFT.uncurry(uncurried.mod, uncurried.args)
        if uncurried_nft is not None and coin_state.coin.amount % 2 == 1:
            return await self.handle_nft(coin_spend, uncurried_nft, parent_coin_state, coin_state)

        # Check if the coin is a DID
        did_curried_args = match_did_puzzle(uncurried.mod, uncurried.args)
        if did_curried_args is not None and coin_state.coin.amount % 2 == 1:
            return await self.handle_did(did_curried_args, parent_coin_state, coin_state, coin_spend, peer)

        # Check if the coin is clawback
        solution = coin_spend.solution.to_program()
        clawback_metadata = match_clawback_puzzle(uncurried, puzzle, solution)
        if clawback_metadata is not None:
            return await self.handle_clawback(clawback_metadata, coin_state, coin_spend, peer)

        # Check if the coin is a VC
        is_vc, err_msg = VerifiedCredential.is_vc(uncurried)
        if is_vc:
            return await self.handle_vc(coin_spend)

        await self.notification_manager.potentially_add_new_notification(coin_state, coin_spend)

        return None

    async def auto_claim_coins(self) -> None:
        # Get unspent clawback coin
        current_timestamp = self.blockchain.get_latest_timestamp()
        clawback_coins: Dict[Coin, ClawbackMetadata] = {}
        tx_fee = uint64(self.config.get("auto_claim", {}).get("tx_fee", 0))
        min_amount = uint64(self.config.get("auto_claim", {}).get("min_amount", 0))
        unspent_coins = await self.coin_store.get_coin_records(
            coin_type=CoinType.CLAWBACK,
            wallet_type=WalletType.STANDARD_WALLET,
            spent_range=UInt32Range(stop=uint32(0)),
            amount_range=UInt64Range(start=uint64(min_amount)),
        )
        for coin in unspent_coins.records:
            try:
                metadata: ClawbackMetadata = coin.parsed_metadata()
                if await metadata.is_recipient(self.puzzle_store):
                    coin_timestamp = await self.wallet_node.get_timestamp_for_height(coin.confirmed_block_height)
                    if current_timestamp - coin_timestamp >= metadata.time_lock:
                        clawback_coins[coin.coin] = metadata
                        if len(clawback_coins) >= self.config.get("auto_claim", {}).get("batch_size", 50):
                            await self.spend_clawback_coins(clawback_coins, tx_fee)
                            clawback_coins = {}
            except Exception as e:
                self.log.error(f"Failed to claim clawback coin {coin.coin.name().hex()}: %s", e)
        if len(clawback_coins) > 0:
            await self.spend_clawback_coins(clawback_coins, tx_fee)

    async def spend_clawback_coins(self, clawback_coins: Dict[Coin, ClawbackMetadata], fee: uint64) -> List[bytes32]:
        assert len(clawback_coins) > 0
        coin_spends: List[CoinSpend] = []
        message: bytes32 = std_hash(b"".join([c.name() for c in clawback_coins.keys()]))
        now: uint64 = uint64(int(time.time()))
        derivation_record: Optional[DerivationRecord] = None
        amount: uint64 = uint64(0)
        for coin, metadata in clawback_coins.items():
            try:
                self.log.info(f"Claiming clawback coin {coin.name().hex()}")
                # Get incoming tx
                incoming_tx = await self.tx_store.get_transaction_record(coin.name())
                assert incoming_tx is not None, f"Cannot find incoming tx for clawback coin {coin.name().hex()}"
                if incoming_tx.sent > 0:
                    self.log.error(
                        f"Clawback coin {coin.name().hex()} is already in a pending spend bundle. {incoming_tx}"
                    )
                    continue

                recipient_puzhash: bytes32 = metadata.recipient_puzzle_hash
                sender_puzhash: bytes32 = metadata.sender_puzzle_hash
                is_recipient: bool = await metadata.is_recipient(self.puzzle_store)
                if is_recipient:
                    derivation_record = await self.puzzle_store.get_derivation_record_for_puzzle_hash(recipient_puzhash)
                else:
                    derivation_record = await self.puzzle_store.get_derivation_record_for_puzzle_hash(sender_puzhash)
                assert derivation_record is not None
                if self.main_wallet.secret_key_store.secret_key_for_public_key(derivation_record.pubkey) is None:
                    await self.main_wallet.hack_populate_secret_key_for_puzzle_hash(derivation_record.puzzle_hash)
                amount = uint64(amount + coin.amount)
                # Remove the clawback hint since it is unnecessary for the XCH coin
                memos: List[bytes] = [] if len(incoming_tx.memos) == 0 else incoming_tx.memos[0][1][1:]
                inner_puzzle: Program = self.main_wallet.puzzle_for_pk(derivation_record.pubkey)
                inner_solution: Program = self.main_wallet.make_solution(
                    primaries=[
                        Payment(
                            derivation_record.puzzle_hash,
                            uint64(coin.amount),
                            memos,  # Forward memo of the first coin
                        )
                    ],
                    coin_announcements=None if len(coin_spends) > 0 or fee == 0 else {message},
                )
                coin_spend: CoinSpend = generate_clawback_spend_bundle(coin, metadata, inner_puzzle, inner_solution)
                coin_spends.append(coin_spend)
            except Exception as e:
                self.log.error(f"Failed to create clawback spend bundle for {coin.name().hex()}: {e}")
        if len(coin_spends) == 0:
            return []
        spend_bundle: SpendBundle = await self.main_wallet.sign_transaction(coin_spends)
        if fee > 0:
            chia_tx = await self.main_wallet.create_tandem_xch_tx(
                fee, Announcement(coin_spends[0].coin.name(), message)
            )
            assert chia_tx.spend_bundle is not None
            spend_bundle = SpendBundle.aggregate([spend_bundle, chia_tx.spend_bundle])
        assert derivation_record is not None
        tx_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=now,
            to_puzzle_hash=derivation_record.puzzle_hash,
            amount=amount,
            fee_amount=uint64(fee),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=uint32(1),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_CLAWBACK),
            name=spend_bundle.name(),
            memos=list(compute_memos(spend_bundle).items()),
        )
        await self.add_pending_transaction(tx_record)
        # Update incoming tx to prevent double spend and mark it is pending
        for coin_spend in coin_spends:
            await self.tx_store.increment_sent(coin_spend.coin.name(), "", MempoolInclusionStatus.PENDING, None)
        return [tx_record.name]

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
        wallet_identifier = await self.get_wallet_identifier_for_puzzle_hash(coin_state.coin.puzzle_hash)
        return wallet_identifier is not None and wallet_identifier.type == WalletType.STANDARD_WALLET

    async def handle_cat(
        self,
        curried_args: Iterator[Program],
        parent_coin_state: CoinState,
        coin_state: CoinState,
        coin_spend: CoinSpend,
        peer: WSChiaConnection,
        fork_height: Optional[uint32],
    ) -> Optional[WalletIdentifier]:
        """
        Handle the new coin when it is a CAT
        :param curried_args: Curried arg of the CAT mod
        :param parent_coin_state: Parent coin state
        :param coin_state: Current coin state
        :param coin_spend: New coin spend
        :return: Wallet ID & Wallet Type
        """
        mod_hash, tail_hash, inner_puzzle = curried_args

        hinted_coin = compute_spend_hints_and_additions(coin_spend)[coin_state.coin.name()]
        assert hinted_coin.hint is not None, f"hint missing for coin {hinted_coin.coin}"
        derivation_record = await self.puzzle_store.get_derivation_record_for_puzzle_hash(hinted_coin.hint)

        if derivation_record is None:
            self.log.info(f"Received state for the coin that doesn't belong to us {coin_state}")
            return None
        else:
            our_inner_puzzle: Program = self.main_wallet.puzzle_for_pk(derivation_record.pubkey)
            asset_id: bytes32 = bytes32(bytes(tail_hash)[1:])
            cat_puzzle = construct_cat_puzzle(CAT_MOD, asset_id, our_inner_puzzle, CAT_MOD_HASH)
            if cat_puzzle.get_tree_hash() != coin_state.coin.puzzle_hash:
                return None
            if bytes(tail_hash).hex()[2:] in self.default_cats or self.config.get(
                "automatically_add_unknown_cats", False
            ):
                cat_wallet = await CATWallet.get_or_create_wallet_for_cat(
                    self, self.main_wallet, bytes(tail_hash).hex()[2:]
                )
                return WalletIdentifier.create(cat_wallet)
            else:
                # Found unacknowledged CAT, save it in the database.
                await self.interested_store.add_unacknowledged_token(
                    asset_id,
                    CATWallet.default_wallet_name_for_unknown_cat(asset_id.hex()),
                    None if parent_coin_state.spent_height is None else uint32(parent_coin_state.spent_height),
                    parent_coin_state.coin.puzzle_hash,
                )
                await self.interested_store.add_unacknowledged_coin_state(
                    asset_id,
                    coin_state,
                    fork_height,
                )
                self.state_changed("added_stray_cat")
                return None

    async def handle_did(
        self,
        curried_args: Iterator[Program],
        parent_coin_state: CoinState,
        coin_state: CoinState,
        coin_spend: CoinSpend,
        peer: WSChiaConnection,
    ) -> Optional[WalletIdentifier]:
        """
        Handle the new coin when it is a DID
        :param curried_args: Curried arg of the DID mod
        :param parent_coin_state: Parent coin state
        :param coin_state: Current coin state
        :param coin_spend: New coin spend
        :return: Wallet ID & Wallet Type
        """
        p2_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata = curried_args
        inner_puzzle_hash = p2_puzzle.get_tree_hash()
        self.log.info(f"parent: {parent_coin_state.coin.name()} inner_puzzle_hash for parent is {inner_puzzle_hash}")

        hinted_coin = compute_spend_hints_and_additions(coin_spend)[coin_state.coin.name()]
        assert hinted_coin.hint is not None, f"hint missing for coin {hinted_coin.coin}"
        derivation_record = await self.puzzle_store.get_derivation_record_for_puzzle_hash(hinted_coin.hint)

        launch_id: bytes32 = bytes32(bytes(singleton_struct.rest().first())[1:])
        if derivation_record is None:
            self.log.info(f"Received state for the coin that doesn't belong to us {coin_state}")
            # Check if it was owned by us
            removed_wallet_ids = []
            for wallet in self.wallets.values():
                if not isinstance(wallet, DIDWallet):
                    continue
                if (
                    wallet.did_info.origin_coin is not None
                    and launch_id == wallet.did_info.origin_coin.name()
                    and not wallet.did_info.sent_recovery_transaction
                ):
                    await self.user_store.delete_wallet(wallet.id())
                    removed_wallet_ids.append(wallet.id())
            for remove_id in removed_wallet_ids:
                self.wallets.pop(remove_id)
                self.log.info(f"Removed DID wallet {remove_id}, Launch_ID: {launch_id.hex()}")
                self.state_changed("wallet_removed", remove_id)
            return None
        else:
            our_inner_puzzle: Program = self.main_wallet.puzzle_for_pk(derivation_record.pubkey)

            self.log.info(f"Found DID, launch_id {launch_id}.")
            did_puzzle = DID_INNERPUZ_MOD.curry(
                our_inner_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata
            )
            full_puzzle = create_singleton_puzzle(did_puzzle, launch_id)
            did_puzzle_empty_recovery = DID_INNERPUZ_MOD.curry(
                our_inner_puzzle, Program.to([]).get_tree_hash(), uint64(0), singleton_struct, metadata
            )
            full_puzzle_empty_recovery = create_singleton_puzzle(did_puzzle_empty_recovery, launch_id)
            if full_puzzle.get_tree_hash() != coin_state.coin.puzzle_hash:
                if full_puzzle_empty_recovery.get_tree_hash() == coin_state.coin.puzzle_hash:
                    did_puzzle = did_puzzle_empty_recovery
                    self.log.info("DID recovery list was reset by the previous owner.")
                else:
                    self.log.error("DID puzzle hash doesn't match, please check curried parameters.")
                    return None
            # Create DID wallet
            response: List[CoinState] = await self.wallet_node.get_coin_state([launch_id], peer=peer)
            if len(response) == 0:
                self.log.warning(f"Could not find the launch coin with ID: {launch_id}")
                return None
            launch_coin: CoinState = response[0]
            origin_coin = launch_coin.coin

            for wallet in self.wallets.values():
                if wallet.type() == WalletType.DECENTRALIZED_ID:
                    assert isinstance(wallet, DIDWallet)
                    assert wallet.did_info.origin_coin is not None
                    if origin_coin.name() == wallet.did_info.origin_coin.name():
                        return WalletIdentifier.create(wallet)
            did_wallet = await DIDWallet.create_new_did_wallet_from_coin_spend(
                self,
                self.main_wallet,
                launch_coin.coin,
                did_puzzle,
                coin_spend,
                f"DID {encode_puzzle_hash(launch_id, AddressType.DID.hrp(self.config))}",
            )
            wallet_identifier = WalletIdentifier.create(did_wallet)
            self.state_changed("wallet_created", wallet_identifier.id, {"did_id": did_wallet.get_my_DID()})
            return wallet_identifier

    async def get_minter_did(self, launcher_coin: Coin, peer: WSChiaConnection) -> Optional[bytes32]:
        # Get minter DID
        eve_coin = (await self.wallet_node.fetch_children(launcher_coin.name(), peer=peer))[0]
        eve_coin_spend = await fetch_coin_spend_for_coin_state(eve_coin, peer)
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
            did_spend = await fetch_coin_spend_for_coin_state(did_coin[0], peer)
            puzzle = Program.from_bytes(bytes(did_spend.puzzle_reveal))
            uncurried = uncurry_puzzle(puzzle)
            did_curried_args = match_did_puzzle(uncurried.mod, uncurried.args)
            if did_curried_args is not None:
                p2_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata = did_curried_args
                minter_did = bytes32(bytes(singleton_struct.rest().first())[1:])
        return minter_did

    async def handle_nft(
        self, coin_spend: CoinSpend, uncurried_nft: UncurriedNFT, parent_coin_state: CoinState, coin_state: CoinState
    ) -> Optional[WalletIdentifier]:
        """
        Handle the new coin when it is a NFT
        :param coin_spend: New coin spend
        :param uncurried_nft: Uncurried NFT
        :param parent_coin_state: Parent coin state
        :param coin_state: Current coin state
        :return: Wallet ID & Wallet Type
        """
        wallet_identifier = None
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
            return wallet_identifier
        for nft_wallet in self.wallets.copy().values():
            if not isinstance(nft_wallet, NFTWallet):
                continue
            if nft_wallet.nft_wallet_info.did_id == old_did_id and old_derivation_record is not None:
                self.log.info(
                    "Removing old NFT, NFT_ID:%s, DID_ID:%s",
                    uncurried_nft.singleton_launcher_id.hex(),
                    old_did_id,
                )
                if parent_coin_state.spent_height is not None:
                    await nft_wallet.remove_coin(coin_spend.coin, uint32(parent_coin_state.spent_height))
                    is_empty = await nft_wallet.is_empty()
                    has_did = False
                    for did_wallet in self.wallets.values():
                        if not isinstance(did_wallet, DIDWallet):
                            continue
                        assert did_wallet.did_info.origin_coin is not None
                        if did_wallet.did_info.origin_coin.name() == old_did_id:
                            has_did = True
                            break
                    if is_empty and nft_wallet.did_id is not None and not has_did:
                        self.log.info(f"No NFT, deleting wallet {nft_wallet.did_id.hex()} ...")
                        await self.user_store.delete_wallet(nft_wallet.wallet_info.id)
                        self.wallets.pop(nft_wallet.wallet_info.id)
            if nft_wallet.nft_wallet_info.did_id == new_did_id and new_derivation_record is not None:
                self.log.info(
                    "Adding new NFT, NFT_ID:%s, DID_ID:%s",
                    uncurried_nft.singleton_launcher_id.hex(),
                    new_did_id,
                )
                wallet_identifier = WalletIdentifier.create(nft_wallet)

        if wallet_identifier is None and new_derivation_record is not None:
            # Cannot find an existed NFT wallet for the new NFT
            self.log.info(
                "Cannot find a NFT wallet for NFT_ID: %s DID_ID: %s, creating a new one.",
                uncurried_nft.singleton_launcher_id,
                new_did_id,
            )
            new_nft_wallet: NFTWallet = await NFTWallet.create_new_nft_wallet(
                self, self.main_wallet, did_id=new_did_id, name="NFT Wallet"
            )
            wallet_identifier = WalletIdentifier.create(new_nft_wallet)
        return wallet_identifier

    async def handle_clawback(
        self,
        metadata: ClawbackMetadata,
        coin_state: CoinState,
        coin_spend: CoinSpend,
        peer: WSChiaConnection,
    ) -> Optional[WalletIdentifier]:
        """
        Handle Clawback coins
        :param metadata: Clawback metadata for spending the merkle coin
        :param coin_state: Clawback merkle coin
        :param coin_spend: Parent coin spend
        :param peer: Fullnode peer
        :return:
        """
        # Record metadata
        assert coin_state.created_height is not None
        is_recipient: Optional[bool] = None
        # Check if the wallet is the sender
        sender_derivation_record: Optional[
            DerivationRecord
        ] = await self.puzzle_store.get_derivation_record_for_puzzle_hash(metadata.sender_puzzle_hash)
        # Check if the wallet is the recipient
        recipient_derivation_record = await self.puzzle_store.get_derivation_record_for_puzzle_hash(
            metadata.recipient_puzzle_hash
        )
        if sender_derivation_record is not None:
            self.log.info("Found Clawback merkle coin %s as the sender.", coin_state.coin.name().hex())
            is_recipient = False
        elif recipient_derivation_record is not None:
            self.log.info("Found Clawback merkle coin %s as the recipient.", coin_state.coin.name().hex())
            is_recipient = True
            # For the recipient we need to manually subscribe the merkle coin
            await self.add_interested_coin_ids([coin_state.coin.name()])
        if is_recipient is not None:
            spend_bundle = SpendBundle([coin_spend], G2Element())
            memos = compute_memos(spend_bundle)
            spent_height: uint32 = uint32(0)
            if coin_state.spent_height is not None:
                self.log.debug("Resync clawback coin: %s", coin_state.coin.name().hex())
                # Resync case
                spent_height = uint32(coin_state.spent_height)
                # Create Clawback outgoing transaction
                created_timestamp = await self.wallet_node.get_timestamp_for_height(uint32(coin_state.spent_height))
                clawback_coin_spend: CoinSpend = await fetch_coin_spend_for_coin_state(coin_state, peer)
                clawback_spend_bundle: SpendBundle = SpendBundle([clawback_coin_spend], G2Element())
                if await self.puzzle_store.puzzle_hash_exists(clawback_spend_bundle.additions()[0].puzzle_hash):
                    tx_record = TransactionRecord(
                        confirmed_at_height=uint32(coin_state.spent_height),
                        created_at_time=created_timestamp,
                        to_puzzle_hash=metadata.sender_puzzle_hash
                        if clawback_spend_bundle.additions()[0].puzzle_hash == metadata.sender_puzzle_hash
                        else metadata.recipient_puzzle_hash,
                        amount=uint64(coin_state.coin.amount),
                        fee_amount=uint64(0),
                        confirmed=True,
                        sent=uint32(0),
                        spend_bundle=clawback_spend_bundle,
                        additions=clawback_spend_bundle.additions(),
                        removals=clawback_spend_bundle.removals(),
                        wallet_id=uint32(1),
                        sent_to=[],
                        trade_id=None,
                        type=uint32(TransactionType.OUTGOING_CLAWBACK),
                        name=clawback_spend_bundle.name(),
                        memos=list(compute_memos(clawback_spend_bundle).items()),
                    )
                    await self.tx_store.add_transaction_record(tx_record)
            coin_record = WalletCoinRecord(
                coin_state.coin,
                uint32(coin_state.created_height),
                spent_height,
                spent_height != 0,
                False,
                WalletType.STANDARD_WALLET,
                1,
                CoinType.CLAWBACK,
                VersionedBlob(ClawbackVersion.V1.value, bytes(metadata)),
            )
            # Add merkle coin
            await self.coin_store.add_coin_record(coin_record)
            # Add tx record
            # We use TransactionRecord.confirmed to indicate if a Clawback transaction is claimable
            # If the Clawback coin is unspent, confirmed should be false
            created_timestamp = await self.wallet_node.get_timestamp_for_height(uint32(coin_state.created_height))
            tx_record = TransactionRecord(
                confirmed_at_height=uint32(coin_state.created_height),
                created_at_time=uint64(created_timestamp),
                to_puzzle_hash=metadata.recipient_puzzle_hash,
                amount=uint64(coin_state.coin.amount),
                fee_amount=uint64(0),
                confirmed=spent_height != 0,
                sent=uint32(0),
                spend_bundle=None,
                additions=[coin_state.coin],
                removals=[coin_spend.coin],
                wallet_id=uint32(1),
                sent_to=[],
                trade_id=None,
                type=uint32(
                    TransactionType.INCOMING_CLAWBACK_RECEIVE
                    if is_recipient
                    else TransactionType.INCOMING_CLAWBACK_SEND
                ),
                # Use coin ID as the TX ID to mapping with the coin table
                name=coin_record.coin.name(),
                memos=list(memos.items()),
            )
            await self.tx_store.add_transaction_record(tx_record)
        return None

    async def handle_vc(self, parent_coin_spend: CoinSpend) -> Optional[WalletIdentifier]:
        # Check the ownership
        vc: VerifiedCredential = VerifiedCredential.get_next_from_coin_spend(parent_coin_spend)
        derivation_record: Optional[DerivationRecord] = await self.puzzle_store.get_derivation_record_for_puzzle_hash(
            vc.inner_puzzle_hash
        )
        if derivation_record is None:
            self.log.warning(
                f"Verified credential {vc.launcher_id.hex()} is not belong to the current wallet."
            )  # pragma: no cover
            return None  # pragma: no cover
        self.log.info(f"Found verified credential {vc.launcher_id.hex()}.")
        for wallet_info in await self.get_all_wallet_info_entries(wallet_type=WalletType.VC):
            return WalletIdentifier(wallet_info.id, WalletType.VC)
        else:
            # Create a new VC wallet
            vc_wallet = await VCWallet.create_new_vc_wallet(self, self.main_wallet)  # pragma: no cover
            return WalletIdentifier(vc_wallet.id(), WalletType.VC)  # pragma: no cover

    async def _add_coin_states(
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
        used_up_to = -1
        ph_to_index_cache: LRUCache[bytes32, uint32] = LRUCache(100)

        coin_names = [bytes32(coin_state.coin.name()) for coin_state in coin_states]
        local_records = await self.coin_store.get_coin_records(coin_id_filter=HashFilter.include(coin_names))

        for coin_name, coin_state in zip(coin_names, coin_states):
            if peer.closed:
                raise ConnectionError("Connection closed")
            self.log.debug("Add coin state: %s: %s", coin_name, coin_state)
            local_record = local_records.coin_id_to_record.get(coin_name)
            rollback_wallets = None
            try:
                async with self.db_wrapper.writer():
                    rollback_wallets = self.wallets.copy()  # Shallow copy of wallets if writer rolls back the db
                    # This only succeeds if we don't raise out of the transaction
                    await self.retry_store.remove_state(coin_state)

                    wallet_identifier = await self.get_wallet_identifier_for_puzzle_hash(coin_state.coin.puzzle_hash)

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

                    if coin_state.spent_height is not None and coin_name in trade_removals:
                        await self.trade_manager.coins_of_interest_farmed(coin_state, fork_height, peer)
                    if wallet_identifier is not None:
                        self.log.debug(f"Found existing wallet_identifier: {wallet_identifier}, coin: {coin_name}")
                    elif local_record is not None:
                        wallet_identifier = WalletIdentifier(uint32(local_record.wallet_id), local_record.wallet_type)
                    elif coin_state.created_height is not None:
                        wallet_identifier = await self.determine_coin_type(peer, coin_state, fork_height)
                        try:
                            dl_wallet = self.get_dl_wallet()
                        except ValueError:
                            pass
                        else:
                            if (
                                await dl_wallet.get_singleton_record(coin_name) is not None
                                or coin_state.coin.puzzle_hash == MIRROR_PUZZLE_HASH
                            ):
                                wallet_identifier = WalletIdentifier.create(dl_wallet)

                    if wallet_identifier is None:
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
                            used_up_to = derivation_index

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
                                wallet_identifier.id,
                                wallet_identifier.type,
                                peer,
                                coin_name,
                            )

                    # if the coin has been spent
                    elif coin_state.created_height is not None and coin_state.spent_height is not None:
                        self.log.debug("Coin spent: %s", coin_state)
                        children = await self.wallet_node.fetch_children(coin_name, peer=peer, fork_height=fork_height)
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
                                wallet_identifier.type,
                                wallet_identifier.id,
                            )
                            await self.coin_store.add_coin_record(record)
                            # Coin first received
                            parent_coin_record: Optional[WalletCoinRecord] = await self.coin_store.get_coin_record(
                                coin_state.coin.parent_coin_info
                            )
                            if (
                                parent_coin_record is not None
                                and wallet_identifier.type == parent_coin_record.wallet_type
                            ):
                                change = True
                            else:
                                change = False

                            if not change:
                                created_timestamp = await self.wallet_node.get_timestamp_for_height(
                                    uint32(coin_state.created_height)
                                )
                                tx_record = TransactionRecord(
                                    confirmed_at_height=uint32(coin_state.created_height),
                                    created_at_time=uint64(created_timestamp),
                                    to_puzzle_hash=(
                                        await self.convert_puzzle_hash(
                                            wallet_identifier.id, coin_state.coin.puzzle_hash
                                        )
                                    ),
                                    amount=uint64(coin_state.coin.amount),
                                    fee_amount=uint64(0),
                                    confirmed=True,
                                    sent=uint32(0),
                                    spend_bundle=None,
                                    additions=[coin_state.coin],
                                    removals=[],
                                    wallet_id=wallet_identifier.id,
                                    sent_to=[],
                                    trade_id=None,
                                    type=uint32(tx_type),
                                    name=bytes32(token_bytes()),
                                    memos=[],
                                )
                                await self.tx_store.add_transaction_record(tx_record)

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
                                    if derivation_record is None:  # not change
                                        to_puzzle_hash = coin.puzzle_hash
                                        amount += coin.amount
                                    elif wallet_identifier.type == WalletType.CAT:
                                        # We subscribe to change for CATs since they didn't hint previously
                                        await self.add_interested_coin_ids([coin.name()])

                                if to_puzzle_hash is None:
                                    to_puzzle_hash = additions[0].puzzle_hash

                                spent_timestamp = await self.wallet_node.get_timestamp_for_height(
                                    uint32(coin_state.spent_height)
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
                                    tx_name = bytes(coin_state.coin.name())
                                    for added_coin in additions:
                                        tx_name += bytes(added_coin.name())
                                    tx_name = std_hash(tx_name)
                                    tx_record = TransactionRecord(
                                        confirmed_at_height=uint32(coin_state.spent_height),
                                        created_at_time=uint64(spent_timestamp),
                                        to_puzzle_hash=(
                                            await self.convert_puzzle_hash(wallet_identifier.id, to_puzzle_hash)
                                        ),
                                        amount=uint64(int(amount)),
                                        fee_amount=uint64(fee),
                                        confirmed=True,
                                        sent=uint32(0),
                                        spend_bundle=None,
                                        additions=additions,
                                        removals=[coin_state.coin],
                                        wallet_id=wallet_identifier.id,
                                        sent_to=[],
                                        trade_id=None,
                                        type=uint32(TransactionType.OUTGOING_TX.value),
                                        name=tx_name,
                                        memos=[],
                                    )

                                    await self.tx_store.add_transaction_record(tx_record)
                        else:
                            await self.coin_store.set_spent(coin_name, uint32(coin_state.spent_height))
                            if record.coin_type == CoinType.CLAWBACK:
                                await self.interested_store.remove_interested_coin_id(coin_state.coin.name())
                            confirmed_tx_records: List[TransactionRecord] = []
                            for tx_record in all_unconfirmed:
                                if tx_record.type in CLAWBACK_INCOMING_TRANSACTION_TYPES:
                                    for add_coin in tx_record.additions:
                                        if add_coin == coin_state.coin:
                                            confirmed_tx_records.append(tx_record)
                                else:
                                    for rem_coin in tx_record.removals:
                                        if rem_coin == coin_state.coin:
                                            confirmed_tx_records.append(tx_record)

                            for tx_record in confirmed_tx_records:
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
                                pool_wallet = self.get_wallet(id=uint32(record.wallet_id), required_type=PoolWallet)
                                curr_coin_state: CoinState = coin_state

                                while curr_coin_state.spent_height is not None:
                                    cs = await fetch_coin_spend_for_coin_state(curr_coin_state, peer)
                                    success = await pool_wallet.apply_state_transition(
                                        cs, uint32(curr_coin_state.spent_height)
                                    )
                                    if not success:
                                        break
                                    new_singleton_coin = get_most_recent_singleton_coin_from_coin_spend(cs)
                                    if new_singleton_coin is None:
                                        # No more singleton (maybe destroyed?)
                                        break

                                    coin_name = new_singleton_coin.name()
                                    existing = await self.coin_store.get_coin_record(coin_name)
                                    if existing is None:
                                        await self.coin_added(
                                            new_singleton_coin,
                                            uint32(curr_coin_state.spent_height),
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
                            singleton_spend = await fetch_coin_spend_for_coin_state(coin_state, peer)
                            dl_wallet = self.get_wallet(id=uint32(record.wallet_id), required_type=DataLayerWallet)
                            await dl_wallet.singleton_removed(
                                singleton_spend,
                                uint32(coin_state.spent_height),
                            )

                        elif record.wallet_type == WalletType.NFT:
                            if coin_state.spent_height is not None:
                                nft_wallet = self.get_wallet(id=uint32(record.wallet_id), required_type=NFTWallet)
                                await nft_wallet.remove_coin(coin_state.coin, uint32(coin_state.spent_height))
                        elif record.wallet_type == WalletType.VC:
                            if coin_state.spent_height is not None:
                                vc_wallet = self.get_wallet(id=uint32(record.wallet_id), required_type=VCWallet)
                                await vc_wallet.remove_coin(coin_state.coin, uint32(coin_state.spent_height))

                        # Check if a child is a singleton launcher
                        for child in children:
                            if child.coin.puzzle_hash != SINGLETON_LAUNCHER_HASH:
                                continue
                            if await self.have_a_pool_wallet_with_launched_id(child.coin.name()):
                                continue
                            if child.spent_height is None:
                                # TODO handle spending launcher later block
                                continue
                            launcher_spend = await fetch_coin_spend_for_coin_state(child, peer)
                            if launcher_spend is None:
                                continue
                            try:
                                pool_state = solution_to_pool_state(launcher_spend)
                                assert pool_state is not None
                            except (AssertionError, ValueError) as e:
                                self.log.debug(f"Not a pool wallet launcher {e}, child: {child}")
                                matched, inner_puzhash = await DataLayerWallet.match_dl_launcher(launcher_spend)
                                if (
                                    matched
                                    and inner_puzhash is not None
                                    and (await self.puzzle_store.puzzle_hash_exists(inner_puzhash))
                                ):
                                    try:
                                        dl_wallet = self.get_dl_wallet()
                                    except ValueError:
                                        dl_wallet = await DataLayerWallet.create_new_dl_wallet(
                                            self,
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

                            pool_wallet = await PoolWallet.create(
                                self,
                                self.main_wallet,
                                child.coin.name(),
                                [launcher_spend],
                                uint32(child.spent_height),
                                name="pool_wallet",
                            )
                            launcher_spend_additions = compute_additions(launcher_spend)
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
                                    pool_wallet.type(),
                                    peer,
                                    coin_name,
                                )
                            await self.add_interested_coin_ids([coin_name])

                    else:
                        raise RuntimeError("All cases already handled")  # Logic error, all cases handled
            except Exception as e:
                self.log.exception(f"Failed to add coin_state: {coin_state}, error: {e}")
                if rollback_wallets is not None:
                    self.wallets = rollback_wallets  # Restore since DB will be rolled back by writer
                if isinstance(e, PeerRequestException) or isinstance(e, aiosqlite.Error):
                    await self.retry_store.add_state(coin_state, peer.peer_node_id, fork_height)
                else:
                    await self.retry_store.remove_state(coin_state)
                continue

    async def add_coin_states(
        self,
        coin_states: List[CoinState],
        peer: WSChiaConnection,
        fork_height: Optional[uint32],
    ) -> bool:
        try:
            await self._add_coin_states(coin_states, peer, fork_height)
        except Exception as e:
            log_level = logging.DEBUG if peer.closed else logging.ERROR
            self.log.log(log_level, f"add_coin_states failed - exception {e}, traceback: {traceback.format_exc()}")
            return False

        await self.blockchain.clean_block_records()

        return True

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

    async def get_wallet_identifier_for_puzzle_hash(self, puzzle_hash: bytes32) -> Optional[WalletIdentifier]:
        wallet_identifier = await self.puzzle_store.get_wallet_identifier_for_puzzle_hash(puzzle_hash)
        if wallet_identifier is not None:
            return wallet_identifier

        interested_wallet_id = await self.interested_store.get_interested_puzzle_hash_wallet_id(puzzle_hash=puzzle_hash)
        if interested_wallet_id is not None:
            wallet_id = uint32(interested_wallet_id)
            if wallet_id not in self.wallets.keys():
                self.log.warning(f"Do not have wallet {wallet_id} for puzzle_hash {puzzle_hash}")
                return None
            return WalletIdentifier(uint32(wallet_id), self.wallets[uint32(wallet_id)].type())
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

        if self.is_pool_reward(height, coin):
            tx_type = TransactionType.COINBASE_REWARD
        elif self.is_farmer_reward(height, coin):
            tx_type = TransactionType.FEE_REWARD
        else:
            tx_type = TransactionType.INCOMING_TX

        coinbase = tx_type in {TransactionType.FEE_REWARD, TransactionType.COINBASE_REWARD}
        coin_confirmed_transaction = False
        if not coinbase:
            for record in all_unconfirmed_transaction_records:
                if coin in record.additions and not record.confirmed:
                    await self.tx_store.set_confirmed(record.name, height)
                    coin_confirmed_transaction = True
                    break

        parent_coin_record: Optional[WalletCoinRecord] = await self.coin_store.get_coin_record(coin.parent_coin_info)
        change = parent_coin_record is not None and wallet_type.value == parent_coin_record.wallet_type

        if coinbase or not coin_confirmed_transaction and not change:
            tx_record = TransactionRecord(
                confirmed_at_height=uint32(height),
                created_at_time=await self.wallet_node.get_timestamp_for_height(height),
                to_puzzle_hash=await self.convert_puzzle_hash(wallet_id, coin.puzzle_hash),
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
            if tx_record.amount > 0:
                await self.tx_store.add_transaction_record(tx_record)

        # We only add normal coins here
        coin_record: WalletCoinRecord = WalletCoinRecord(
            coin, height, uint32(0), False, coinbase, wallet_type, wallet_id
        )
        await self.coin_store.add_coin_record(coin_record, coin_name)

        await self.wallets[wallet_id].coin_added(coin, height, peer)

        await self.create_more_puzzle_hashes()

    async def add_pending_transaction(self, tx_record: TransactionRecord) -> None:
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

    async def add_transaction(self, tx_record: TransactionRecord) -> None:
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
    ) -> None:
        """
        Full node received our transaction, no need to keep it in queue anymore, unless there was an error
        """

        updated = await self.tx_store.increment_sent(spendbundle_id, name, send_status, error)
        if updated:
            tx: Optional[TransactionRecord] = await self.get_transaction(spendbundle_id)
            if tx is not None and tx.spend_bundle is not None:
                self.log.info("Checking if we need to cancel trade for tx: %s", tx.name)
                # we're only interested in errors that are not temporary
                if (
                    send_status != MempoolInclusionStatus.SUCCESS
                    and error
                    and error not in (Err.INVALID_FEE_LOW_FEE, Err.INVALID_FEE_TOO_CLOSE_TO_ZERO)
                ):
                    coins_removed = tx.spend_bundle.removals()
                    trade_coins_removed = set([])
                    trade = None
                    for removed_coin in coins_removed:
                        trade = await self.trade_manager.get_trade_by_coin(removed_coin)
                        if trade is not None and trade.status in (
                            TradeStatus.PENDING_CONFIRM.value,
                            TradeStatus.PENDING_ACCEPT.value,
                            TradeStatus.PENDING_CANCEL.value,
                        ):
                            # offer was tied to these coins, lets subscribe to them to get a confirmation to
                            # cancel it if it's confirmed
                            # we send transactions to multiple peers, and in cases when mempool gets
                            # fragmented, it's safest to wait for confirmation from blockchain before setting
                            # offer to failed
                            trade_coins_removed.add(removed_coin.name())
                    if trade and trade_coins_removed:
                        if not tx.is_valid():
                            # we've tried to send this transaction to a full node multiple times
                            # but failed, it's safe to assume that it's not going to be accepted
                            # we can mark this offer as failed
                            self.log.info("This offer can't be posted, removing it from pending offers")
                            assert trade is not None
                            await self.trade_manager.fail_pending_offer(trade.trade_id)

                        else:
                            self.log.info(
                                "Subscribing to unspendable offer coins: %s",
                                [x.hex() for x in trade_coins_removed],
                            )
                            await self.add_interested_coin_ids(list(trade_coins_removed))

                    self.state_changed(
                        "tx_update", tx.wallet_id, {"transaction": tx, "error": error.name, "status": send_status.value}
                    )
                else:
                    self.state_changed("tx_update", tx.wallet_id, {"transaction": tx})

    async def get_all_transactions(self, wallet_id: int) -> List[TransactionRecord]:
        """
        Retrieves all confirmed and pending transactions
        """
        records = await self.tx_store.get_all_transactions_for_wallet(wallet_id)
        return records

    async def get_transaction(self, tx_id: bytes32) -> Optional[TransactionRecord]:
        return await self.tx_store.get_transaction_record(tx_id)

    async def get_coin_record_by_wallet_record(self, wr: WalletCoinRecord) -> CoinRecord:
        timestamp: uint64 = await self.wallet_node.get_timestamp_for_height(wr.confirmed_block_height)
        return wr.to_coin_record(timestamp)

    async def get_coin_records_by_coin_ids(self, **kwargs: Any) -> List[CoinRecord]:
        result = await self.coin_store.get_coin_records(**kwargs)
        return [await self.get_coin_record_by_wallet_record(record) for record in result.records]

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
        await self.retry_store.rollback_to_block(height)
        await self.nft_store.rollback_to_block(height)
        await self.coin_store.rollback_to_block(height)
        await self.interested_store.rollback_to_block(height)
        reorged: List[TransactionRecord] = await self.tx_store.get_transaction_above(height)
        await self.tx_store.rollback_to_block(height)
        for record in reorged:
            if TransactionType(record.type) in [
                TransactionType.OUTGOING_TX,
                TransactionType.OUTGOING_TRADE,
                TransactionType.INCOMING_TRADE,
                TransactionType.OUTGOING_CLAWBACK,
                TransactionType.INCOMING_CLAWBACK_SEND,
                TransactionType.INCOMING_CLAWBACK_RECEIVE,
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
        for wallet_id in remove_ids:
            await self.user_store.delete_wallet(wallet_id)
            self.state_changed("wallet_removed", wallet_id)

        return remove_ids

    async def _await_closed(self) -> None:
        await self.db_wrapper.close()

    def unlink_db(self) -> None:
        Path(self.db_path).unlink()

    async def get_all_wallet_info_entries(self, wallet_type: Optional[WalletType] = None) -> List[WalletInfo]:
        return await self.user_store.get_all_wallet_info_entries(wallet_type)

    async def get_wallet_for_asset_id(self, asset_id: str) -> Optional[WalletProtocol]:
        for wallet_id, wallet in self.wallets.items():
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

    async def get_wallet_for_puzzle_info(self, puzzle_driver: PuzzleInfo) -> Optional[WalletProtocol]:
        for wallet in self.wallets.values():
            match_function = getattr(wallet, "match_puzzle_info", None)
            if match_function is not None and callable(match_function):
                if await match_function(puzzle_driver):
                    return wallet
        return None

    async def create_wallet_for_puzzle_info(self, puzzle_driver: PuzzleInfo, name: Optional[str] = None) -> None:
        if AssetType(puzzle_driver.type()) in self.asset_to_wallet_map:
            await self.asset_to_wallet_map[AssetType(puzzle_driver.type())].create_from_puzzle_info(
                self,
                self.main_wallet,
                puzzle_driver,
                name,
            )

    async def add_new_wallet(self, wallet: WalletProtocol) -> None:
        self.wallets[wallet.id()] = wallet
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

    async def new_peak(self, peak: NewPeakWallet) -> None:
        for wallet_id, wallet in self.wallets.items():
            if wallet.type() == WalletType.POOLING_WALLET:
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

    async def delete_trade_transactions(self, trade_id: bytes32) -> None:
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

    def get_dl_wallet(self) -> DataLayerWallet:
        for wallet in self.wallets.values():
            if wallet.type() == WalletType.DATA_LAYER.value:
                assert isinstance(
                    wallet, DataLayerWallet
                ), f"WalletType.DATA_LAYER should be a DataLayerWallet instance got: {type(wallet).__name__}"
                return wallet
        raise ValueError("DataLayerWallet not available")

    async def get_or_create_vc_wallet(self) -> VCWallet:
        for _, wallet in self.wallets.items():
            if WalletType(wallet.type()) == WalletType.VC:
                assert isinstance(wallet, VCWallet)
                vc_wallet: VCWallet = wallet
                break
        else:
            # Create a new VC wallet
            vc_wallet = await VCWallet.create_new_vc_wallet(self, self.main_wallet)

        return vc_wallet
