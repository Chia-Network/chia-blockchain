import asyncio
import json
import logging
import socket
import time
import traceback
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Union

from blspy import G1Element, PrivateKey

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.daemon.keychain_proxy import (
    KeychainProxy,
    KeychainProxyConnectionFailure,
    KeyringIsEmpty,
    KeyringIsLocked,
    connect_to_keychain_and_validate,
    wrap_local_keychain,
)
from chia.pools.pool_puzzles import SINGLETON_LAUNCHER_HASH
from chia.protocols import farmer_protocol, wallet_protocol
from chia.protocols.full_node_protocol import RequestProofOfWeight, RespondProofOfWeight
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import (
    RejectAdditionsRequest,
    RejectRemovalsRequest,
    RequestAdditions,
    RequestHeaderBlocks,
    RespondAdditions,
    RespondBlockHeader,
    RespondHeaderBlocks,
    RespondRemovals,
)
from chia.server.node_discovery import WalletPeers
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin, hash_coin_list
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.header_block import HeaderBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.check_fork_next_block import check_fork_next_block
from chia.util.errors import Err, ValidationError
from chia.util.ints import uint32, uint64, uint128
from chia.util.keychain import Keychain
from chia.util.lru_cache import LRUCache
from chia.util.merkle_set import MerkleSet, confirm_included_already_hashed, confirm_not_included_already_hashed
from chia.util.path import mkdir, path_from_root
from chia.util.profiler import profile_task
from chia.wallet.block_record import HeaderBlockRecord
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.settings.settings_objects import BackupInitialized
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.backup_utils import open_backup_file
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_action import WalletAction
from chia.wallet.wallet_blockchain import ReceiveBlockResult
from chia.wallet.wallet_state_manager import WalletStateManager


class WalletNode:
    key_config: Dict
    config: Dict
    constants: ConsensusConstants
    keychain_proxy: Optional[KeychainProxy]
    local_keychain: Optional[Keychain]  # For testing only. KeychainProxy is used in normal cases
    server: Optional[ChiaServer]
    log: logging.Logger
    wallet_peers: WalletPeers
    # Maintains the state of the wallet (blockchain and transactions), handles DB connections
    wallet_state_manager: Optional[WalletStateManager]

    # How far away from LCA we must be to perform a full sync. Before then, do a short sync,
    # which is consecutive requests for the previous block
    short_sync_threshold: int
    _shut_down: bool
    root_path: Path
    state_changed_callback: Optional[Callable]
    syncing: bool
    full_node_peer: Optional[PeerInfo]
    peer_task: Optional[asyncio.Task]
    logged_in: bool
    wallet_peers_initialized: bool

    def __init__(
        self,
        config: Dict,
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = None,
        local_keychain: Optional[Keychain] = None,
    ):
        self.config = config
        self.constants = consensus_constants
        self.keychain_proxy = None
        self.local_keychain = local_keychain
        self.root_path = root_path
        self.log = logging.getLogger(name if name else __name__)
        # Normal operation data
        self.cached_blocks: Dict = {}
        self.future_block_hashes: Dict = {}

        # Sync data
        self._shut_down = False
        self.proof_hashes: List = []
        self.header_hashes: List = []
        self.header_hashes_error = False
        self.short_sync_threshold = 15  # Change the test when changing this
        self.potential_blocks_received: Dict = {}
        self.potential_header_hashes: Dict = {}
        self.state_changed_callback = None
        self.wallet_state_manager = None
        self.backup_initialized = False  # Delay first launch sync after user imports backup info or decides to skip
        self.server = None
        self.wsm_close_task = None
        self.sync_task: Optional[asyncio.Task] = None
        self.logged_in_fingerprint: Optional[int] = None
        self.peer_task = None
        self.logged_in = False
        self.wallet_peers_initialized = False
        self.last_new_peak_messages = LRUCache(5)

    async def ensure_keychain_proxy(self) -> KeychainProxy:
        if not self.keychain_proxy:
            if self.local_keychain:
                self.keychain_proxy = wrap_local_keychain(self.local_keychain, log=self.log)
            else:
                self.keychain_proxy = await connect_to_keychain_and_validate(self.root_path, self.log)
                if not self.keychain_proxy:
                    raise KeychainProxyConnectionFailure("Failed to connect to keychain service")
        return self.keychain_proxy

    async def get_key_for_fingerprint(self, fingerprint: Optional[int]) -> Optional[PrivateKey]:
        key: PrivateKey = None
        try:
            keychain_proxy = await self.ensure_keychain_proxy()
            key = await keychain_proxy.get_key_for_fingerprint(fingerprint)
        except KeyringIsEmpty:
            self.log.warning("No keys present. Create keys with the UI, or with the 'sit keys' program.")
            return None
        except KeyringIsLocked:
            self.log.warning("Keyring is locked")
            return None
        except KeychainProxyConnectionFailure as e:
            tb = traceback.format_exc()
            self.log.error(f"Missing keychain_proxy: {e} {tb}")
            raise e  # Re-raise so that the caller can decide whether to continue or abort
        return key

    async def _start(
        self,
        fingerprint: Optional[int] = None,
        new_wallet: bool = False,
        backup_file: Optional[Path] = None,
        skip_backup_import: bool = False,
    ) -> bool:
        try:
            private_key = await self.get_key_for_fingerprint(fingerprint)
        except KeychainProxyConnectionFailure:
            self.log.error("Failed to connect to keychain service")
            return False

        if private_key is None:
            self.logged_in = False
            return False

        if self.config.get("enable_profiler", False):
            asyncio.create_task(profile_task(self.root_path, "wallet", self.log))

        db_path_key_suffix = str(private_key.get_g1().get_fingerprint())
        db_path_replaced: str = (
            self.config["database_path"]
            .replace("CHALLENGE", self.config["selected_network"])
            .replace("KEY", db_path_key_suffix)
        )
        path = path_from_root(self.root_path, db_path_replaced)
        mkdir(path.parent)
        self.new_peak_lock = asyncio.Lock()
        assert self.server is not None
        self.wallet_state_manager = await WalletStateManager.create(
            private_key, self.config, path, self.constants, self.server, self.root_path
        )

        self.wsm_close_task = None

        assert self.wallet_state_manager is not None

        backup_settings: BackupInitialized = self.wallet_state_manager.user_settings.get_backup_settings()
        if backup_settings.user_initialized is False:
            if new_wallet is True:
                await self.wallet_state_manager.user_settings.user_created_new_wallet()
                self.wallet_state_manager.new_wallet = True
            elif skip_backup_import is True:
                await self.wallet_state_manager.user_settings.user_skipped_backup_import()
            elif backup_file is not None:
                await self.wallet_state_manager.import_backup_info(backup_file)
            else:
                self.backup_initialized = False
                await self.wallet_state_manager.close_all_stores()
                self.wallet_state_manager = None
                self.logged_in = False
                return False

        self.backup_initialized = True

        # Start peers here after the backup initialization has finished
        # We only want to do this once per instantiation
        # However, doing it earlier before backup initialization causes
        # the wallet to spam the introducer
        if self.wallet_peers_initialized is False:
            asyncio.create_task(self.wallet_peers.start())
            self.wallet_peers_initialized = True

        if backup_file is not None:
            json_dict = open_backup_file(backup_file, self.wallet_state_manager.private_key)
            if "start_height" in json_dict["data"]:
                start_height = json_dict["data"]["start_height"]
                self.config["starting_height"] = max(0, start_height - self.config["start_height_buffer"])
            else:
                self.config["starting_height"] = 0
        else:
            self.config["starting_height"] = 0

        if self.state_changed_callback is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)

        self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)
        self._shut_down = False

        self.peer_task = asyncio.create_task(self._periodically_check_full_node())
        self.sync_event = asyncio.Event()
        self.sync_task = asyncio.create_task(self.sync_job())
        if fingerprint is None:
            self.logged_in_fingerprint = private_key.get_g1().get_fingerprint()
        else:
            self.logged_in_fingerprint = fingerprint
        self.logged_in = True
        return True

    def _close(self):
        self.log.info("self._close")
        self.logged_in_fingerprint = None
        self._shut_down = True

    async def _await_closed(self):
        self.log.info("self._await_closed")
        await self.server.close_all_connections()
        asyncio.create_task(self.wallet_peers.ensure_is_closed())
        if self.wallet_state_manager is not None:
            await self.wallet_state_manager.close_all_stores()
            self.wallet_state_manager = None
        if self.sync_task is not None:
            self.sync_task.cancel()
            self.sync_task = None
        if self.peer_task is not None:
            self.peer_task.cancel()
            self.peer_task = None
        self.logged_in = False

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

        if self.wallet_state_manager is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)
            self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)

    def _pending_tx_handler(self):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return None
        asyncio.create_task(self._resend_queue())

    async def _action_messages(self) -> List[Message]:
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return []
        actions: List[WalletAction] = await self.wallet_state_manager.action_store.get_all_pending_actions()
        result: List[Message] = []
        for action in actions:
            data = json.loads(action.data)
            action_data = data["data"]["action_data"]
            if action.name == "request_puzzle_solution":
                coin_name = bytes32(hexstr_to_bytes(action_data["coin_name"]))
                height = uint32(action_data["height"])
                msg = make_msg(
                    ProtocolMessageTypes.request_puzzle_solution,
                    wallet_protocol.RequestPuzzleSolution(coin_name, height),
                )
                result.append(msg)

        return result

    async def _resend_queue(self):
        if (
            self._shut_down
            or self.server is None
            or self.wallet_state_manager is None
            or self.backup_initialized is None
        ):
            return None

        for msg, sent_peers in await self._messages_to_resend():
            if (
                self._shut_down
                or self.server is None
                or self.wallet_state_manager is None
                or self.backup_initialized is None
            ):
                return None
            full_nodes = self.server.get_full_node_connections()
            for peer in full_nodes:
                if peer.peer_node_id in sent_peers:
                    continue
                await peer.send_message(msg)

        for msg in await self._action_messages():
            if (
                self._shut_down
                or self.server is None
                or self.wallet_state_manager is None
                or self.backup_initialized is None
            ):
                return None
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

    async def _messages_to_resend(self) -> List[Tuple[Message, Set[bytes32]]]:
        if self.wallet_state_manager is None or self.backup_initialized is False or self._shut_down:
            return []
        messages: List[Tuple[Message, Set[bytes32]]] = []

        records: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_not_sent()

        for record in records:
            if record.spend_bundle is None:
                continue
            msg = make_msg(
                ProtocolMessageTypes.send_transaction,
                wallet_protocol.SendTransaction(record.spend_bundle),
            )
            already_sent = set()
            for peer, status, _ in record.sent_to:
                if status == MempoolInclusionStatus.SUCCESS.value:
                    already_sent.add(hexstr_to_bytes(peer))
            messages.append((msg, already_sent))

        return messages

    def set_server(self, server: ChiaServer):
        self.server = server
        DNS_SERVERS_EMPTY: list = []
        # TODO: Perhaps use a different set of DNS seeders for wallets, to split the traffic.
        self.wallet_peers = WalletPeers(
            self.server,
            self.root_path,
            self.config["target_peer_count"],
            self.config["wallet_peers_path"],
            self.config["introducer_peer"],
            DNS_SERVERS_EMPTY,
            self.config["peer_connect_interval"],
            self.config["selected_network"],
            None,
            self.log,
        )

    async def on_connect(self, peer: WSChiaConnection):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return None
        messages_peer_ids = await self._messages_to_resend()
        self.wallet_state_manager.state_changed("add_connection")
        for msg, peer_ids in messages_peer_ids:
            if peer.peer_node_id in peer_ids:
                continue
            await peer.send_message(msg)
        if not self.has_full_node() and self.wallet_peers is not None:
            asyncio.create_task(self.wallet_peers.on_connect(peer))

    async def _periodically_check_full_node(self) -> None:
        tries = 0
        while not self._shut_down and tries < 5:
            if self.has_full_node():
                await self.wallet_peers.ensure_is_closed()
                if self.wallet_state_manager is not None:
                    self.wallet_state_manager.state_changed("add_connection")
                break
            tries += 1
            await asyncio.sleep(self.config["peer_connect_interval"])

    def has_full_node(self) -> bool:
        if self.server is None:
            return False
        if "full_node_peer" in self.config:
            full_node_peer = PeerInfo(
                self.config["full_node_peer"]["host"],
                self.config["full_node_peer"]["port"],
            )
            peers = [c.get_peer_info() for c in self.server.get_full_node_connections()]
            # If full_node_peer is already an address, use it, otherwise
            # resolve it here.
            if full_node_peer.is_valid():
                full_node_resolved = full_node_peer
            else:
                full_node_resolved = PeerInfo(socket.gethostbyname(full_node_peer.host), full_node_peer.port)
            if full_node_peer in peers or full_node_resolved in peers:
                self.log.info(f"Will not attempt to connect to other nodes, already connected to {full_node_peer}")
                for connection in self.server.get_full_node_connections():
                    if (
                        connection.get_peer_info() != full_node_peer
                        and connection.get_peer_info() != full_node_resolved
                    ):
                        self.log.info(f"Closing unnecessary connection to {connection.get_peer_logging()}.")
                        asyncio.create_task(connection.close())
                return True
        return False

    async def update_stakings(self, peer: WSChiaConnection, height: uint64, farmer_public_key: G1Element) -> None:
        "fetch staking"
        height = height - 1 if height > 0 else 0
        blockchain = self.wallet_state_manager.blockchain

        # calculate blocks from cache
        blocks = 0
        if blockchain.get_peak_height() is not None:
            block_range = self.constants.STAKING_ESTIMATE_BLOCK_RANGE
            curr: Optional[BlockRecord] = blockchain.try_block_record(blockchain.height_to_hash(height))
            begin_height = max((curr.height if curr is not None else 0) - block_range, 1)
            while curr is not None and curr.height > begin_height:
                if curr.farmer_public_key == farmer_public_key:
                    blocks += 1
                curr = blockchain.try_block_record(curr.prev_hash)

        res: Optional[farmer_protocol.FarmerStakings] = await peer.request_stakings(
            farmer_protocol.RequestStakings(
                public_keys=[farmer_public_key],
                height=height,
                blocks=blocks,
            )
        )
        if res is None or not isinstance(res, farmer_protocol.FarmerStakings):
            raise ValueError("Peer returned no response")
        self.wallet_state_manager.blockchain.stakings.update({bytes(k): Decimal(v) for k, v in res.stakings})

    async def complete_blocks(self, header_blocks: List[HeaderBlock], peer: WSChiaConnection):
        if self.wallet_state_manager is None:
            return None
        header_block_records: List[HeaderBlockRecord] = []
        assert self.server
        trusted = self.server.is_trusted_peer(peer, self.config["trusted_peers"])
        async with self.wallet_state_manager.blockchain.lock:
            for block in header_blocks:
                await self.update_stakings(
                    peer, block.height, block.reward_chain_block.proof_of_space.farmer_public_key
                )

                if block.is_transaction_block:
                    # Find additions and removals
                    (additions, removals,) = await self.wallet_state_manager.get_filter_additions_removals(
                        block, block.transactions_filter, None
                    )

                    # Get Additions
                    added_coins = await self.get_additions(peer, block, additions)
                    if added_coins is None:
                        raise ValueError("Failed to fetch additions")

                    # Get removals
                    removed_coins = await self.get_removals(peer, block, added_coins, removals)
                    if removed_coins is None:
                        raise ValueError("Failed to fetch removals")

                    # If there is a launcher created, or we have a singleton spent, fetches the required solutions
                    additional_coin_spends: List[CoinSpend] = await self.get_additional_coin_spends(
                        peer, block, added_coins, removed_coins
                    )

                    hbr = HeaderBlockRecord(block, added_coins, removed_coins)
                else:
                    hbr = HeaderBlockRecord(block, [], [])
                    header_block_records.append(hbr)
                    additional_coin_spends = []
                (result, error, fork_h,) = await self.wallet_state_manager.blockchain.receive_block(
                    hbr, trusted=trusted, additional_coin_spends=additional_coin_spends
                )
                if result == ReceiveBlockResult.NEW_PEAK:
                    if not self.wallet_state_manager.sync_mode:
                        self.wallet_state_manager.blockchain.clean_block_records()
                    self.wallet_state_manager.state_changed("new_block")
                    self.wallet_state_manager.state_changed("sync_changed")
                    await self.wallet_state_manager.new_peak()
                elif result == ReceiveBlockResult.INVALID_BLOCK:
                    self.log.info(f"Invalid block from peer: {peer.get_peer_logging()} {error}")
                    await peer.close()
                    return
                else:
                    self.log.debug(f"Result: {result}")

    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection):
        if self.wallet_state_manager is None:
            return

        if self.wallet_state_manager.blockchain.contains_block(peak.header_hash):
            self.log.debug(f"known peak {peak.header_hash}")
            return

        if self.wallet_state_manager.sync_mode:
            self.last_new_peak_messages.put(peer, peak)
            return

        async with self.new_peak_lock:
            curr_peak = self.wallet_state_manager.blockchain.get_peak()
            if curr_peak is not None and curr_peak.weight >= peak.weight:
                return

            request = wallet_protocol.RequestBlockHeader(peak.height)
            response: Optional[RespondBlockHeader] = await peer.request_block_header(request)
            if response is None or not isinstance(response, RespondBlockHeader) or response.header_block is None:
                self.log.warning(f"bad peak response from peer {response}")
                return
            header_block = response.header_block
            curr_peak_height = 0 if curr_peak is None else curr_peak.height
            if (curr_peak_height == 0 and peak.height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS) or (
                curr_peak_height > peak.height - 200
            ):

                if peak.height <= curr_peak_height + self.config["short_sync_blocks_behind_threshold"]:
                    await self.wallet_short_sync_backtrack(header_block, peer)
                else:
                    await self.batch_sync_to_peak(curr_peak_height, peak)
            elif peak.height >= self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
                # Request weight proof
                # Sync if PoW validates
                weight_request = RequestProofOfWeight(peak.height, peak.header_hash)
                weight_proof_response: RespondProofOfWeight = await peer.request_proof_of_weight(
                    weight_request, timeout=360
                )
                if weight_proof_response is None:
                    return

                weight_proof = weight_proof_response.wp
                if self.wallet_state_manager is None:
                    return
                if self.server is not None and self.server.is_trusted_peer(peer, self.config["trusted_peers"]):
                    valid, fork_point = self.wallet_state_manager.weight_proof_handler.get_fork_point_no_validations(
                        weight_proof
                    )
                else:
                    valid, fork_point, _ = await self.wallet_state_manager.weight_proof_handler.validate_weight_proof(
                        weight_proof
                    )
                if not valid:
                    self.log.error(
                        f"invalid weight proof, num of epochs {len(weight_proof.sub_epochs)}"
                        f" recent blocks num ,{len(weight_proof.recent_chain_data)}"
                    )
                    self.log.debug(f"{weight_proof}")
                    return
                self.log.info(f"Validated, fork point is {fork_point}")
                self.wallet_state_manager.sync_store.add_potential_fork_point(
                    header_block.header_hash, uint32(fork_point)
                )
                self.wallet_state_manager.sync_store.add_potential_peak(header_block)
                self.start_sync()

    async def wallet_short_sync_backtrack(self, header_block, peer):
        top = header_block
        blocks = [top]
        # Fetch blocks backwards until we hit the one that we have,
        # then complete them with additions / removals going forward
        while not self.wallet_state_manager.blockchain.contains_block(top.prev_header_hash) and top.height > 0:
            request_prev = wallet_protocol.RequestBlockHeader(top.height - 1)
            response_prev: Optional[RespondBlockHeader] = await peer.request_block_header(request_prev)
            if response_prev is None or not isinstance(response_prev, RespondBlockHeader):
                raise RuntimeError("bad block header response from peer while syncing")
            prev_head = response_prev.header_block
            blocks.append(prev_head)
            top = prev_head
        blocks.reverse()
        await self.complete_blocks(blocks, peer)
        await self.wallet_state_manager.create_more_puzzle_hashes()

    async def batch_sync_to_peak(self, fork_height, peak):
        advanced_peak = False
        batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS
        for i in range(max(0, fork_height - 1), peak.height, batch_size):
            start_height = i
            end_height = min(peak.height, start_height + batch_size)
            peers = self.server.get_full_node_connections()
            added = False
            for peer in peers:
                try:
                    added, advanced_peak = await self.fetch_blocks_and_validate(
                        peer, uint32(start_height), uint32(end_height), None if advanced_peak else fork_height
                    )
                    if added:
                        break
                except Exception as e:
                    await peer.close()
                    exc = traceback.format_exc()
                    self.log.error(f"Error while trying to fetch from peer:{e} {exc}")
            if not added:
                raise RuntimeError(f"Was not able to add blocks {start_height}-{end_height}")

            curr_peak = self.wallet_state_manager.blockchain.get_peak()
            assert peak is not None
            self.wallet_state_manager.blockchain.clean_block_record(
                min(end_height, curr_peak.height) - self.constants.BLOCKS_CACHE_SIZE
            )

    def start_sync(self) -> None:
        self.log.info("self.sync_event.set()")
        self.sync_event.set()

    async def check_new_peak(self) -> None:
        if self.wallet_state_manager is None:
            return None

        current_peak: Optional[BlockRecord] = self.wallet_state_manager.blockchain.get_peak()
        if current_peak is None:
            return None
        potential_peaks: List[
            Tuple[bytes32, HeaderBlock]
        ] = self.wallet_state_manager.sync_store.get_potential_peaks_tuples()
        for _, block in potential_peaks:
            if current_peak.weight < block.weight:
                await asyncio.sleep(5)
                self.start_sync()
                return None

    async def sync_job(self) -> None:
        while True:
            self.log.info("Loop start in sync job")
            if self._shut_down is True:
                break
            asyncio.create_task(self.check_new_peak())
            await self.sync_event.wait()
            self.last_new_peak_messages = LRUCache(5)
            self.sync_event.clear()

            if self._shut_down is True:
                break
            try:
                assert self.wallet_state_manager is not None
                self.wallet_state_manager.set_sync_mode(True)
                await self._sync()
            except Exception as e:
                tb = traceback.format_exc()
                self.log.error(f"Loop exception in sync {e}. {tb}")
            finally:
                if self.wallet_state_manager is not None:
                    self.wallet_state_manager.set_sync_mode(False)
                for peer, peak in self.last_new_peak_messages.cache.items():
                    asyncio.create_task(self.new_peak_wallet(peak, peer))
            self.log.info("Loop end in sync job")

    async def _sync(self) -> None:
        """
        Wallet has fallen far behind (or is starting up for the first time), and must be synced
        up to the LCA of the blockchain.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False or self.server is None:
            return None

        highest_weight: uint128 = uint128(0)
        peak_height: uint32 = uint32(0)
        peak: Optional[HeaderBlock] = None
        potential_peaks: List[
            Tuple[bytes32, HeaderBlock]
        ] = self.wallet_state_manager.sync_store.get_potential_peaks_tuples()

        self.log.info(f"Have collected {len(potential_peaks)} potential peaks")

        for header_hash, potential_peak_block in potential_peaks:
            if potential_peak_block.weight > highest_weight:
                highest_weight = potential_peak_block.weight
                peak_height = potential_peak_block.height
                peak = potential_peak_block

        if peak_height is None or peak_height == 0:
            return None

        if self.wallet_state_manager.peak is not None and highest_weight <= self.wallet_state_manager.peak.weight:
            self.log.info("Not performing sync, already caught up.")
            return None

        peers: List[WSChiaConnection] = self.server.get_full_node_connections()
        if len(peers) == 0:
            self.log.info("No peers to sync to")
            return None

        async with self.wallet_state_manager.blockchain.lock:
            fork_height = None
            if peak is not None:
                fork_height = self.wallet_state_manager.sync_store.get_potential_fork_point(peak.header_hash)
                assert fork_height is not None
                # This is the fork point in SES in the case where no fork was detected
                peers = self.server.get_full_node_connections()
                fork_height = await check_fork_next_block(
                    self.wallet_state_manager.blockchain, fork_height, peers, wallet_next_block_check
                )

            if fork_height is None:
                fork_height = uint32(0)
            await self.wallet_state_manager.blockchain.warmup(fork_height)
            await self.batch_sync_to_peak(fork_height, peak)

    async def fetch_blocks_and_validate(
        self,
        peer: WSChiaConnection,
        height_start: uint32,
        height_end: uint32,
        fork_point_with_peak: Optional[uint32],
    ) -> Tuple[bool, bool]:
        """
        Returns whether the blocks validated, and whether the peak was advanced
        """
        if self.wallet_state_manager is None:
            return False, False

        self.log.info(f"Requesting blocks {height_start}-{height_end}")
        request = RequestHeaderBlocks(uint32(height_start), uint32(height_end))
        res: Optional[RespondHeaderBlocks] = await peer.request_header_blocks(request)
        if res is None or not isinstance(res, RespondHeaderBlocks):
            raise ValueError("Peer returned no response")
        header_blocks: List[HeaderBlock] = res.header_blocks
        advanced_peak = False
        if header_blocks is None:
            raise ValueError(f"No response from peer {peer}")
        assert self.server
        trusted = self.server.is_trusted_peer(peer, self.config["trusted_peers"])
        pre_validation_results: Optional[List[PreValidationResult]] = None
        if not trusted:
            pre_validation_results = await self.wallet_state_manager.blockchain.pre_validate_blocks_multiprocessing(
                header_blocks
            )
            if pre_validation_results is None:
                return False, advanced_peak
            assert len(header_blocks) == len(pre_validation_results)

        for i in range(len(header_blocks)):
            header_block = header_blocks[i]

            await self.update_stakings(
                peer, header_block.height, header_block.reward_chain_block.proof_of_space.farmer_public_key
            )

            if not trusted and pre_validation_results is not None and pre_validation_results[i].error is not None:
                raise ValidationError(Err(pre_validation_results[i].error))

            fork_point_with_old_peak = None if advanced_peak else fork_point_with_peak
            if header_block.is_transaction_block:
                # Find additions and removals
                (additions, removals,) = await self.wallet_state_manager.get_filter_additions_removals(
                    header_block, header_block.transactions_filter, fork_point_with_old_peak
                )

                # Get Additions
                added_coins = await self.get_additions(peer, header_block, additions)
                if added_coins is None:
                    raise ValueError("Failed to fetch additions")

                # Get removals
                removed_coins = await self.get_removals(peer, header_block, added_coins, removals)
                if removed_coins is None:
                    raise ValueError("Failed to fetch removals")

                # If there is a launcher created, or we have a singleton spent, fetches the required solutions
                additional_coin_spends: List[CoinSpend] = await self.get_additional_coin_spends(
                    peer, header_block, added_coins, removed_coins
                )

                header_block_record = HeaderBlockRecord(header_block, added_coins, removed_coins)
            else:
                header_block_record = HeaderBlockRecord(header_block, [], [])
                additional_coin_spends = []
            start_t = time.time()
            if trusted:
                (result, error, fork_h,) = await self.wallet_state_manager.blockchain.receive_block(
                    header_block_record,
                    None,
                    trusted,
                    fork_point_with_old_peak,
                    additional_coin_spends=additional_coin_spends,
                )
            else:
                assert pre_validation_results is not None
                (result, error, fork_h,) = await self.wallet_state_manager.blockchain.receive_block(
                    header_block_record,
                    pre_validation_results[i],
                    trusted,
                    fork_point_with_old_peak,
                    additional_coin_spends=additional_coin_spends,
                )
            self.log.debug(
                f"Time taken to validate {header_block.height} with fork "
                f"{fork_point_with_old_peak}: {time.time() - start_t}"
            )
            if result == ReceiveBlockResult.NEW_PEAK:
                advanced_peak = True
                self.wallet_state_manager.state_changed("new_block")
            elif result == ReceiveBlockResult.INVALID_BLOCK:
                raise ValueError(f"Value error peer sent us invalid block {error} {fork_h}")
        if advanced_peak:
            await self.wallet_state_manager.create_more_puzzle_hashes()
        return True, advanced_peak

    def validate_additions(
        self,
        coins: List[Tuple[bytes32, List[Coin]]],
        proofs: Optional[List[Tuple[bytes32, bytes, Optional[bytes]]]],
        root,
    ):
        if proofs is None:
            # Verify root
            additions_merkle_set = MerkleSet()

            # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
            for puzzle_hash, coins_l in coins:
                additions_merkle_set.add_already_hashed(puzzle_hash)
                additions_merkle_set.add_already_hashed(hash_coin_list(coins_l))

            additions_root = additions_merkle_set.get_root()
            if root != additions_root:
                return False
        else:
            for i in range(len(coins)):
                assert coins[i][0] == proofs[i][0]
                coin_list_1: List[Coin] = coins[i][1]
                puzzle_hash_proof: bytes32 = proofs[i][1]
                coin_list_proof: Optional[bytes32] = proofs[i][2]
                if len(coin_list_1) == 0:
                    # Verify exclusion proof for puzzle hash
                    not_included = confirm_not_included_already_hashed(
                        root,
                        coins[i][0],
                        puzzle_hash_proof,
                    )
                    if not_included is False:
                        return False
                else:
                    try:
                        # Verify inclusion proof for coin list
                        included = confirm_included_already_hashed(
                            root,
                            hash_coin_list(coin_list_1),
                            coin_list_proof,
                        )
                        if included is False:
                            return False
                    except AssertionError:
                        return False
                    try:
                        # Verify inclusion proof for puzzle hash
                        included = confirm_included_already_hashed(
                            root,
                            coins[i][0],
                            puzzle_hash_proof,
                        )
                        if included is False:
                            return False
                    except AssertionError:
                        return False

        return True

    def validate_removals(self, coins, proofs, root):
        if proofs is None:
            # If there are no proofs, it means all removals were returned in the response.
            # we must find the ones relevant to our wallets.

            # Verify removals root
            removals_merkle_set = MerkleSet()
            for name_coin in coins:
                # TODO review all verification
                name, coin = name_coin
                if coin is not None:
                    removals_merkle_set.add_already_hashed(coin.name())
            removals_root = removals_merkle_set.get_root()
            if root != removals_root:
                return False
        else:
            # This means the full node has responded only with the relevant removals
            # for our wallet. Each merkle proof must be verified.
            if len(coins) != len(proofs):
                return False
            for i in range(len(coins)):
                # Coins are in the same order as proofs
                if coins[i][0] != proofs[i][0]:
                    return False
                coin = coins[i][1]
                if coin is None:
                    # Verifies merkle proof of exclusion
                    not_included = confirm_not_included_already_hashed(
                        root,
                        coins[i][0],
                        proofs[i][1],
                    )
                    if not_included is False:
                        return False
                else:
                    # Verifies merkle proof of inclusion of coin name
                    if coins[i][0] != coin.name():
                        return False
                    included = confirm_included_already_hashed(
                        root,
                        coin.name(),
                        proofs[i][1],
                    )
                    if included is False:
                        return False
        return True

    async def fetch_puzzle_solution(self, peer, height: uint32, coin: Coin) -> CoinSpend:
        solution_response = await peer.request_puzzle_solution(
            wallet_protocol.RequestPuzzleSolution(coin.name(), height)
        )
        if solution_response is None or not isinstance(solution_response, wallet_protocol.RespondPuzzleSolution):
            raise ValueError(f"Was not able to obtain solution {solution_response}")
        return CoinSpend(coin, solution_response.response.puzzle, solution_response.response.solution)

    async def get_additional_coin_spends(
        self, peer, block, added_coins: List[Coin], removed_coins: List[Coin]
    ) -> List[CoinSpend]:
        assert self.wallet_state_manager is not None
        additional_coin_spends: List[CoinSpend] = []
        if len(removed_coins) > 0:
            removed_coin_ids = set([coin.name() for coin in removed_coins])
            all_added_coins = await self.get_additions(peer, block, [], get_all_additions=True)
            assert all_added_coins is not None
            if all_added_coins is not None:
                all_added_coin_parents = [c.parent_coin_info for c in all_added_coins]
                for coin in all_added_coins:
                    # This searches specifically for a launcher being created, and adds the solution of the launcher
                    if (
                        coin.puzzle_hash == SINGLETON_LAUNCHER_HASH  # Check that it's a launcher
                        and coin.name() in all_added_coin_parents  # Check that it's ephemermal
                        and coin.parent_coin_info in removed_coin_ids  # Check that an interesting coin created it
                    ):
                        cs: CoinSpend = await self.fetch_puzzle_solution(peer, block.height, coin)
                        additional_coin_spends.append(cs)
                        # Apply this coin solution, which might add things to interested list
                        await self.wallet_state_manager.get_next_interesting_coin_ids(cs, False)

                all_removed_coins: Optional[List[Coin]] = await self.get_removals(
                    peer, block, added_coins, removed_coins, request_all_removals=True
                )
                assert all_removed_coins is not None
                all_removed_coins_dict: Dict[bytes32, Coin] = {coin.name(): coin for coin in all_removed_coins}
                keep_searching = True
                while keep_searching:
                    # This keeps fetching solutions for coins we are interested list, in this block, until
                    # there are no more interested things to fetch
                    keep_searching = False
                    interested_ids: List[
                        bytes32
                    ] = await self.wallet_state_manager.interested_store.get_interested_coin_ids()
                    for coin_id in interested_ids:
                        if coin_id in all_removed_coins_dict:
                            coin = all_removed_coins_dict[coin_id]
                            cs = await self.fetch_puzzle_solution(peer, block.height, coin)

                            # Apply this coin solution, which might add things to interested list
                            await self.wallet_state_manager.get_next_interesting_coin_ids(cs, False)
                            additional_coin_spends.append(cs)
                            keep_searching = True
                            all_removed_coins_dict.pop(coin_id)
                            break
        return additional_coin_spends

    async def get_additions(
        self, peer: WSChiaConnection, block_i, additions: Optional[List[bytes32]], get_all_additions: bool = False
    ) -> Optional[List[Coin]]:
        if (additions is not None and len(additions) > 0) or get_all_additions:
            if get_all_additions:
                additions = None
            additions_request = RequestAdditions(block_i.height, block_i.header_hash, additions)
            additions_res: Optional[Union[RespondAdditions, RejectAdditionsRequest]] = await peer.request_additions(
                additions_request
            )
            if additions_res is None:
                await peer.close()
                return None
            elif isinstance(additions_res, RespondAdditions):
                validated = self.validate_additions(
                    additions_res.coins,
                    additions_res.proofs,
                    block_i.foliage_transaction_block.additions_root,
                )
                if not validated:
                    await peer.close()
                    return None
                added_coins = []
                for ph_coins in additions_res.coins:
                    ph, coins = ph_coins
                    added_coins.extend(coins)
                return added_coins
            elif isinstance(additions_res, RejectRemovalsRequest):
                await peer.close()
                return None
            return None
        else:
            return []  # No added coins

    async def get_removals(
        self, peer: WSChiaConnection, block_i, additions, removals, request_all_removals=False
    ) -> Optional[List[Coin]]:
        assert self.wallet_state_manager is not None
        # Check if we need all removals
        for coin in additions:
            puzzle_store = self.wallet_state_manager.puzzle_store
            record_info: Optional[DerivationRecord] = await puzzle_store.get_derivation_record_for_puzzle_hash(
                coin.puzzle_hash
            )
            if record_info is not None and record_info.wallet_type == WalletType.COLOURED_COIN:
                # TODO why ?
                request_all_removals = True
                break
            if record_info is not None and record_info.wallet_type == WalletType.DISTRIBUTED_ID:
                request_all_removals = True
                break
        if len(removals) > 0 or request_all_removals:
            if request_all_removals:
                removals_request = wallet_protocol.RequestRemovals(block_i.height, block_i.header_hash, None)
            else:
                removals_request = wallet_protocol.RequestRemovals(block_i.height, block_i.header_hash, removals)
            removals_res: Optional[Union[RespondRemovals, RejectRemovalsRequest]] = await peer.request_removals(
                removals_request
            )
            if removals_res is None:
                return None
            elif isinstance(removals_res, RespondRemovals):
                validated = self.validate_removals(
                    removals_res.coins,
                    removals_res.proofs,
                    block_i.foliage_transaction_block.removals_root,
                )
                if validated is False:
                    await peer.close()
                    return None
                removed_coins = []
                for _, coins_l in removals_res.coins:
                    if coins_l is not None:
                        removed_coins.append(coins_l)

                return removed_coins
            elif isinstance(removals_res, RejectRemovalsRequest):
                return None
            else:
                return None

        else:
            return []


async def wallet_next_block_check(
    peer: WSChiaConnection, potential_peek: uint32, blockchain: BlockchainInterface
) -> bool:
    block_response = await peer.request_header_blocks(
        wallet_protocol.RequestHeaderBlocks(potential_peek, potential_peek)
    )
    if block_response is not None and isinstance(block_response, wallet_protocol.RespondHeaderBlocks):
        our_peak = blockchain.get_peak()
        if our_peak is not None and block_response.header_blocks[0].prev_header_hash == our_peak.header_hash:
            return True
    return False
