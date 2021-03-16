import asyncio
import json
import logging
import socket
import time
import traceback
from asyncio import Task
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Union

from blspy import PrivateKey

from src.consensus.block_record import BlockRecord
from src.consensus.constants import ConsensusConstants
from src.consensus.multiprocess_validation import PreValidationResult
from src.protocols import wallet_protocol
from src.protocols.full_node_protocol import RequestProofOfWeight, RespondProofOfWeight
from src.protocols.protocol_message_types import ProtocolMessageTypes
from src.protocols.wallet_protocol import (
    RejectAdditionsRequest,
    RejectRemovalsRequest,
    RequestAdditions,
    RequestHeaderBlocks,
    RespondAdditions,
    RespondBlockHeader,
    RespondHeaderBlocks,
    RespondRemovals,
)
from src.server.node_discovery import WalletPeers
from src.server.outbound_message import Message, NodeType, make_msg
from src.server.server import ChiaServer
from src.server.ws_connection import WSChiaConnection
from src.types.blockchain_format.coin import Coin, hash_coin_list
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.header_block import HeaderBlock
from src.types.peer_info import PeerInfo
from src.util.byte_types import hexstr_to_bytes
from src.util.errors import Err, ValidationError
from src.util.genesis_wait import wait_for_genesis_challenge
from src.util.ints import uint32, uint128
from src.util.keychain import Keychain
from src.util.merkle_set import MerkleSet, confirm_included_already_hashed, confirm_not_included_already_hashed
from src.util.path import mkdir, path_from_root
from src.wallet.block_record import HeaderBlockRecord
from src.wallet.derivation_record import DerivationRecord
from src.wallet.settings.settings_objects import BackupInitialized
from src.wallet.transaction_record import TransactionRecord
from src.wallet.util.backup_utils import open_backup_file
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet_action import WalletAction
from src.wallet.wallet_blockchain import ReceiveBlockResult
from src.wallet.wallet_state_manager import WalletStateManager


class WalletNode:
    key_config: Dict
    config: Dict
    constants: ConsensusConstants
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
    genesis_initialized: bool

    def __init__(
        self,
        config: Dict,
        keychain: Keychain,
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = None,
    ):
        self.config = config
        self.constants = consensus_constants
        self.root_path = root_path
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)
        # Normal operation data
        self.cached_blocks: Dict = {}
        self.future_block_hashes: Dict = {}
        self.keychain = keychain

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
        self.sync_task: Optional[Task] = None
        self.new_peak_lock: Optional[asyncio.Lock] = None
        self.logged_in_fingerprint: Optional[int] = None
        self.peer_task = None
        if self.constants.GENESIS_CHALLENGE is None:
            self.genesis_initialized = False
        else:
            self.genesis_initialized = True

    def get_key_for_fingerprint(self, fingerprint: Optional[int]):
        private_keys = self.keychain.get_all_private_keys()
        if len(private_keys) == 0:
            self.log.warning("No keys present. Create keys with the UI, or with the 'chia keys' program.")
            return None

        private_key: Optional[PrivateKey] = None
        if fingerprint is not None:
            for sk, _ in private_keys:
                if sk.get_g1().get_fingerprint() == fingerprint:
                    private_key = sk
                    break
        else:
            private_key = private_keys[0][0]
        return private_key

    async def regular_start(
        self,
        fingerprint: Optional[int] = None,
        new_wallet: bool = False,
        backup_file: Optional[Path] = None,
        skip_backup_import: bool = False,
    ):
        private_key = self.get_key_for_fingerprint(fingerprint)
        if private_key is None:
            return False

        db_path_key_suffix = str(private_key.get_g1().get_fingerprint())
        db_path_replaced: str = (
            self.config["database_path"]
            .replace("CHALLENGE", self.config["selected_network"])
            .replace("KEY", db_path_key_suffix)
        )
        path = path_from_root(self.root_path, db_path_replaced)
        mkdir(path.parent)

        self.wallet_state_manager = await WalletStateManager.create(private_key, self.config, path, self.constants)

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
                return False

        self.backup_initialized = True
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
        self.log.info("self.sync_job")
        self.logged_in_fingerprint = fingerprint
        return True

    async def delayed_start(self):
        self.log.info("delayed_start")
        config, constants = await wait_for_genesis_challenge(self.root_path, self.constants, "wallet")
        self.config = config
        self.constants = constants
        self.genesis_initialized = True
        await self.wallet_state_manager.initialize_constants(self.config, self.constants)
        self.wallet_state_manager.state_changed("sync_changed")

    async def _start(
        self,
        fingerprint: Optional[int] = None,
        new_wallet: bool = False,
        backup_file: Optional[Path] = None,
        skip_backup_import: bool = False,
    ) -> bool:
        if self.constants.GENESIS_CHALLENGE is None:
            await self.regular_start(fingerprint, new_wallet, backup_file, True)
            asyncio.create_task(self.delayed_start())
            if self.wallet_state_manager is not None:
                self.wallet_state_manager.state_changed("sync_changed")
            return True
        else:
            return await self.regular_start(fingerprint, new_wallet, backup_file, skip_backup_import)

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

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

        if self.wallet_state_manager is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)
            self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)

    def _pending_tx_handler(self):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
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
            return

        for msg, sent_peers in await self._messages_to_resend():
            if (
                self._shut_down
                or self.server is None
                or self.wallet_state_manager is None
                or self.backup_initialized is None
            ):
                return
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
                return
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
                already_sent.add(hexstr_to_bytes(peer))
            messages.append((msg, already_sent))

        return messages

    def set_server(self, server: ChiaServer):
        self.server = server
        self.wallet_peers = WalletPeers(
            self.server,
            self.root_path,
            self.config["target_peer_count"],
            self.config["wallet_peers_path"],
            self.config["introducer_peer"],
            self.config["peer_connect_interval"],
            self.log,
        )
        asyncio.create_task(self.wallet_peers.start())

    async def on_connect(self, peer: WSChiaConnection):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        messages_peer_ids = await self._messages_to_resend()
        for msg, peer_ids in messages_peer_ids:
            if peer.peer_node_id in peer_ids:
                continue
            await peer.send_message(msg)
        if not self.has_full_node() and self.wallet_peers is not None:
            asyncio.create_task(self.wallet_peers.on_connect(peer))

    async def _periodically_check_full_node(self):
        tries = 0
        while not self._shut_down and tries < 5:
            if self.has_full_node():
                await self.wallet_peers.ensure_is_closed()
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
            full_node_resolved = PeerInfo(socket.gethostbyname(full_node_peer.host), full_node_peer.port)
            if full_node_peer in peers or full_node_resolved in peers:
                self.log.info(f"Will not attempt to connect to other nodes, already connected to {full_node_peer}")
                for connection in self.server.get_full_node_connections():
                    if (
                        connection.get_peer_info() != full_node_peer
                        and connection.get_peer_info() != full_node_resolved
                    ):
                        self.log.info(f"Closing unnecessary connection to {connection.get_peer_info()}.")
                        asyncio.create_task(connection.close())
                return True
        return False

    async def complete_blocks(self, header_blocks: List[HeaderBlock], peer: WSChiaConnection):
        if self.wallet_state_manager is None:
            return
        header_block_records: List[HeaderBlockRecord] = []
        async with self.wallet_state_manager.blockchain.lock:
            for block in header_blocks:
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
                    hbr = HeaderBlockRecord(block, added_coins, removed_coins)
                else:
                    hbr = HeaderBlockRecord(block, [], [])
                    header_block_records.append(hbr)
                (
                    result,
                    error,
                    fork_h,
                ) = await self.wallet_state_manager.blockchain.receive_block(hbr)
                if result == ReceiveBlockResult.NEW_PEAK:
                    if not self.wallet_state_manager.sync_mode:
                        self.wallet_state_manager.blockchain.clean_block_records()
                    self.wallet_state_manager.state_changed("new_block")
                    self.wallet_state_manager.state_changed("sync_changed")
                elif result == ReceiveBlockResult.INVALID_BLOCK:
                    self.log.info(f"Invalid block from peer: {peer.get_peer_info()} {error}")
                    await peer.close()
                    return
                else:
                    self.log.debug(f"Result: {result}")

    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection):
        if self.wallet_state_manager is None:
            return

        curr_peak = self.wallet_state_manager.blockchain.get_peak()
        if curr_peak is not None and curr_peak.weight >= peak.weight:
            return
        if self.new_peak_lock is None:
            self.new_peak_lock = asyncio.Lock()
        async with self.new_peak_lock:
            request = wallet_protocol.RequestBlockHeader(peak.height)
            response: Optional[RespondBlockHeader] = await peer.request_block_header(request)

            if response is None or not isinstance(response, RespondBlockHeader) or response.header_block is None:
                return

            header_block = response.header_block

            if (curr_peak is None and header_block.height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS) or (
                curr_peak is not None and curr_peak.height > header_block.height - 200
            ):
                top = header_block
                blocks = [top]
                # Fetch blocks backwards until we hit the one that we have,
                # then complete them with additions / removals going forward
                while not self.wallet_state_manager.blockchain.contains_block(top.prev_header_hash) and top.height > 0:
                    request_prev = wallet_protocol.RequestBlockHeader(top.height - 1)
                    response_prev: Optional[RespondBlockHeader] = await peer.request_block_header(request_prev)
                    if response_prev is None:
                        return
                    if not isinstance(response_prev, RespondBlockHeader):
                        return
                    prev_head = response_prev.header_block
                    blocks.append(prev_head)
                    top = prev_head
                blocks.reverse()
                await self.complete_blocks(blocks, peer)
            elif header_block.height >= self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
                # Request weight proof
                # Sync if PoW validates
                if self.wallet_state_manager.sync_mode:
                    return
                weight_request = RequestProofOfWeight(header_block.height, header_block.header_hash)
                weight_proof_response: RespondProofOfWeight = await peer.request_proof_of_weight(
                    weight_request, timeout=180
                )
                if weight_proof_response is None:
                    return
                weight_proof = weight_proof_response.wp
                if self.wallet_state_manager is None:
                    return
                valid, fork_point = await self.wallet_state_manager.weight_proof_handler.validate_weight_proof(
                    weight_proof
                )
                if not valid:
                    self.log.error(
                        f"invalid weight proof, num of epochs {len(weight_proof.sub_epochs)}"
                        f" recent blocks num ,{len(weight_proof.recent_chain_data)}"
                    )
                    self.log.debug(f"{weight_proof}")
                    return None
                self.log.info(f"Validated, fork point is {fork_point}")
                self.wallet_state_manager.sync_store.add_potential_fork_point(
                    header_block.header_hash, uint32(fork_point)
                )
                self.wallet_state_manager.sync_store.add_potential_peak(header_block)
                self.start_sync()

    def start_sync(self):
        self.log.info("self.sync_event.set()")
        self.sync_event.set()

    async def check_new_peak(self):
        if self.genesis_initialized is False:
            return
        current_peak: Optional[BlockRecord] = self.wallet_state_manager.blockchain.get_peak()
        if current_peak is None:
            return
        potential_peaks: List[
            Tuple[bytes32, HeaderBlock]
        ] = self.wallet_state_manager.sync_store.get_potential_peaks_tuples()
        for _, block in potential_peaks:
            if current_peak.weight < block.weight:
                await asyncio.sleep(5)
                self.start_sync()
                return

    async def sync_job(self):
        while True:
            self.log.info("Loop start in sync job")
            if self._shut_down is True:
                break
            asyncio.create_task(self.check_new_peak())
            await self.sync_event.wait()
            self.sync_event.clear()

            if self._shut_down is True:
                break
            try:
                self.wallet_state_manager.set_sync_mode(True)
                await self._sync()
            except Exception as e:
                tb = traceback.format_exc()
                self.log.error(f"Loop exception in sync {e}. {tb}")
            finally:
                if self.wallet_state_manager is not None:
                    self.wallet_state_manager.set_sync_mode(False)
            self.log.info("Loop end in sync job")

    async def _sync(self):
        """
        Wallet has fallen far behind (or is starting up for the first time), and must be synced
        up to the LCA of the blockchain.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return

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
            return

        if self.wallet_state_manager.peak is not None and highest_weight <= self.wallet_state_manager.peak.weight:
            self.log.info("Not performing sync, already caught up.")
            return

        peers: List[WSChiaConnection] = self.server.get_full_node_connections()
        if len(peers) == 0:
            self.log.info("No peers to sync to")
            return

        async with self.wallet_state_manager.blockchain.lock:
            fork_height = self.wallet_state_manager.sync_store.get_potential_fork_point(peak.header_hash)
            if fork_height is None:
                fork_height = 0
            await self.wallet_state_manager.blockchain.warmup(fork_height)
            batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS
            advanced_peak = False
            for i in range(max(0, fork_height - 1), peak_height, batch_size):
                start_height = i
                end_height = min(peak_height, start_height + batch_size)
                peers: List[WSChiaConnection] = self.server.get_full_node_connections()
                added = False
                for peer in peers:
                    try:
                        added, advanced_peak = await self.fetch_blocks_and_validate(
                            peer, uint32(start_height), end_height, None if advanced_peak else fork_height
                        )
                        if added:
                            break
                    except Exception as e:
                        await peer.close()
                        exc = traceback.format_exc()
                        self.log.error(f"Error while trying to fetch from peer:{e} {exc}")
                if not added:
                    raise RuntimeError(f"Was not able to add blocks {start_height}-{end_height}")

                peak = self.wallet_state_manager.blockchain.get_peak()
                assert peak is not None
                self.wallet_state_manager.blockchain.clean_block_record(
                    min(
                        end_height - self.constants.BLOCKS_CACHE_SIZE,
                        peak.height - self.constants.BLOCKS_CACHE_SIZE,
                    )
                )

    async def fetch_blocks_and_validate(
        self,
        peer: WSChiaConnection,
        height_start: uint32,
        height_end: uint32,
        fork_point_with_peak: uint32,
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
        if (
            self.full_node_peer is not None
            and peer.peer_host == self.full_node_peer.host
            or peer.peer_host == "127.0.0.1"
        ):
            trusted = True
            pre_validation_results: Optional[List[PreValidationResult]] = None
        else:
            trusted = False
            pre_validation_results = await self.wallet_state_manager.blockchain.pre_validate_blocks_multiprocessing(
                header_blocks
            )
            if pre_validation_results is None:
                return False, advanced_peak
            assert len(header_blocks) == len(pre_validation_results)

        for i in range(len(header_blocks)):
            header_block = header_blocks[i]
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

                header_block_record = HeaderBlockRecord(header_block, added_coins, removed_coins)
            else:
                header_block_record = HeaderBlockRecord(header_block, [], [])
            start_t = time.time()
            if trusted:
                (result, error, fork_h,) = await self.wallet_state_manager.blockchain.receive_block(
                    header_block_record, None, trusted, fork_point_with_old_peak
                )
            else:
                assert pre_validation_results is not None
                (result, error, fork_h,) = await self.wallet_state_manager.blockchain.receive_block(
                    header_block_record, pre_validation_results[i], trusted, fork_point_with_old_peak
                )
            self.log.debug(
                f"Time taken to validate {header_block.height} with fork "
                f"{fork_point_with_old_peak}: {time.time() - start_t}"
            )
            if result == ReceiveBlockResult.NEW_PEAK:
                advanced_peak = True
                self.wallet_state_manager.state_changed("new_block")
            elif result == ReceiveBlockResult.INVALID_BLOCK:
                raise ValueError("Value error peer sent us invalid block")
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

    async def get_additions(self, peer: WSChiaConnection, block_i, additions) -> Optional[List[Coin]]:
        if len(additions) > 0:
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
            added_coins = []
            return added_coins

    async def get_removals(self, peer: WSChiaConnection, block_i, additions, removals) -> Optional[List[Coin]]:
        assert self.wallet_state_manager is not None
        request_all_removals = False
        # Check if we need all removals
        for coin in additions:
            puzzle_store = self.wallet_state_manager.puzzle_store
            record_info: Optional[DerivationRecord] = await puzzle_store.get_derivation_record_for_puzzle_hash(
                coin.puzzle_hash.hex()
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
