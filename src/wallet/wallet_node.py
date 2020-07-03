import asyncio
import json
import time
from typing import Dict, Optional, Tuple, List, AsyncGenerator, Callable
import concurrent
from pathlib import Path
import random
import socket
import logging
import traceback
from blspy import PrivateKey

from src.full_node.full_node import OutboundMessageGenerator
from src.types.peer_info import PeerInfo
from src.util.byte_types import hexstr_to_bytes
from src.util.merkle_set import (
    confirm_included_already_hashed,
    confirm_not_included_already_hashed,
    MerkleSet,
)
from src.protocols import introducer_protocol, wallet_protocol
from src.consensus.constants import ConsensusConstants
from src.server.connection import PeerConnections
from src.server.server import ChiaServer
from src.server.outbound_message import OutboundMessage, NodeType, Message, Delivery
from src.util.ints import uint32, uint64
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request
from src.wallet.derivation_record import DerivationRecord
from src.wallet.settings.settings_objects import BackupInitialized
from src.wallet.transaction_record import TransactionRecord
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet_action import WalletAction
from src.wallet.wallet_state_manager import WalletStateManager
from src.wallet.block_record import BlockRecord
from src.types.header_block import HeaderBlock
from src.types.full_block import FullBlock
from src.types.coin import Coin, hash_coin_list
from src.full_node.blockchain import ReceiveBlockResult
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.util.errors import Err
from src.util.path import path_from_root, mkdir
from src.util.keychain import Keychain


class WalletNode:
    key_config: Dict
    config: Dict
    constants: ConsensusConstants
    server: Optional[ChiaServer]
    log: logging.Logger

    # Maintains the state of the wallet (blockchain and transactions), handles DB connections
    wallet_state_manager: Optional[WalletStateManager]

    # Maintains headers recently received. Once the desired removals and additions are downloaded,
    # the data is persisted in the WalletStateManager. These variables are also used to store
    # temporary sync data. The bytes is the transaction filter.
    cached_blocks: Dict[bytes32, Tuple[BlockRecord, HeaderBlock, bytes]]

    # Prev hash to curr hash
    future_block_hashes: Dict[bytes32, bytes32]

    # Hashes of the PoT and PoSpace for all blocks (including occasional difficulty adjustments)
    proof_hashes: List[Tuple[bytes32, Optional[uint64], Optional[uint64]]]

    # List of header hashes downloaded during sync
    header_hashes: List[bytes32]
    header_hashes_error: bool

    # Event to signal when a block is received (during sync)
    potential_blocks_received: Dict[uint32, asyncio.Event]
    potential_header_hashes: Dict[uint32, bytes32]

    # How far away from LCA we must be to perform a full sync. Before then, do a short sync,
    # which is consecutive requests for the previous block
    short_sync_threshold: int
    sync_generator_task: Optional[AsyncGenerator]
    _shut_down: bool
    root_path: Path
    state_changed_callback: Optional[Callable]

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
        self.cached_blocks = {}
        self.future_block_hashes = {}
        self.keychain = keychain

        # Sync data
        self._shut_down = False
        self.proof_hashes = []
        self.header_hashes = []
        self.header_hashes_error = False
        self.short_sync_threshold = 15  # Change the test when changing this
        self.potential_blocks_received = {}
        self.potential_header_hashes = {}
        self.state_changed_callback = None
        self.wallet_state_manager = None
        self.backup_initialized = False  # Delay first launch sync after user imports backup info or decides to skip
        self.sync_generator_task = None
        self.server = None

    async def _start(
        self,
        public_key_fingerprint: Optional[int] = None,
        new_wallet: bool = False,
        backup_file: Optional[Path] = None,
    ) -> bool:
        self._shut_down = False
        private_keys = self.keychain.get_all_private_keys()
        if len(private_keys) == 0:
            self.log.warning(
                "No keys present. Create keys with the UI, or with the 'chia keys' program."
            )
            return False

        private_key: Optional[PrivateKey] = None
        if public_key_fingerprint is not None:
            for sk, _ in private_keys:
                if sk.get_g1().get_fingerprint() == public_key_fingerprint:
                    private_key = sk
                    break
        else:
            private_key = private_keys[0][0]

        if private_key is None:
            raise RuntimeError("Invalid fingerprint {public_key_fingerprint}")

        db_path_key_suffix = str(private_key.get_g1().get_fingerprint())
        path = path_from_root(
            self.root_path, f"{self.config['database_path']}-{db_path_key_suffix}"
        )
        mkdir(path.parent)
        self.wallet_state_manager = await WalletStateManager.create(
            private_key, self.config, path, self.constants
        )

        assert self.wallet_state_manager is not None

        if new_wallet is True:
            await self.wallet_state_manager.user_settings.user_created_new_wallet()

        backup_settings: BackupInitialized = self.wallet_state_manager.user_settings.get_backup_settings()
        if backup_settings.user_initialized is False:
            if backup_file is None:
                self.backup_initialized = False
                return False
            else:
                await self.wallet_state_manager.import_backup_info(backup_file)

        self.backup_initialized = True

        if self.state_changed_callback is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)

        self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)
        return True

    def _close(self):
        self._shut_down = True
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        self.wsm_close_task = asyncio.create_task(
            self.wallet_state_manager.close_all_stores()
        )
        self.global_connections.close_all_connections()

    async def _await_closed(self):
        if self.sync_generator_task is not None:
            await self.sync_generator_task.aclose()
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        await self.wsm_close_task

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback
        if self.global_connections is not None:
            self.global_connections.set_state_changed_callback(callback)

        if self.wallet_state_manager is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)
            self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)

    def _pending_tx_handler(self):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        asyncio.ensure_future(self._resend_queue())

    async def _action_messages(self) -> List[OutboundMessage]:
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return []
        actions: List[
            WalletAction
        ] = await self.wallet_state_manager.action_store.get_all_pending_actions()
        result: List[OutboundMessage] = []
        for action in actions:
            data = json.loads(action.data)
            action_data = data["data"]["action_data"]
            if action.name == "request_generator":
                header_hash = bytes32(hexstr_to_bytes(action_data["header_hash"]))
                height = uint32(action_data["height"])
                msg = Message(
                    "request_generator",
                    wallet_protocol.RequestGenerator(height, header_hash),
                )
                out_msg = OutboundMessage(NodeType.FULL_NODE, msg, Delivery.BROADCAST)
                result.append(out_msg)

        return result

    async def _resend_queue(self):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        if self._shut_down:
            return
        if self.server is None:
            return

        for msg in await self._messages_to_resend():
            self.server.push_message(msg)

        for msg in await self._action_messages():
            self.server.push_message(msg)

    async def _messages_to_resend(self) -> List[OutboundMessage]:
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return []
        messages: List[OutboundMessage] = []

        records: List[
            TransactionRecord
        ] = await self.wallet_state_manager.tx_store.get_not_sent()

        for record in records:
            if record.spend_bundle is None:
                continue
            msg = OutboundMessage(
                NodeType.FULL_NODE,
                Message(
                    "send_transaction",
                    wallet_protocol.SendTransaction(record.spend_bundle),
                ),
                Delivery.BROADCAST,
            )
            messages.append(msg)

        return messages

    def _set_global_connections(self, global_connections: PeerConnections):
        self.global_connections = global_connections

    def _set_server(self, server: ChiaServer):
        self.server = server

    async def _on_connect(self) -> AsyncGenerator[OutboundMessage, None]:
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        messages = await self._messages_to_resend()

        for msg in messages:
            yield msg

    def _num_needed_peers(self) -> int:
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return 0
        assert self.server is not None
        diff = self.config["target_peer_count"] - len(
            self.global_connections.get_full_node_connections()
        )
        if diff < 0:
            return 0

        if "full_node_peer" in self.config:
            full_node_peer = PeerInfo(
                self.config["full_node_peer"]["host"],
                self.config["full_node_peer"]["port"],
            )
            peers = [
                c.get_peer_info()
                for c in self.global_connections.get_full_node_connections()
            ]
            full_node_resolved = PeerInfo(
                socket.gethostbyname(full_node_peer.host), full_node_peer.port
            )
            if full_node_peer in peers or full_node_resolved in peers:
                self.log.info(
                    f"Will not attempt to connect to other nodes, already connected to {full_node_peer}"
                )
                for connection in self.global_connections.get_full_node_connections():
                    if (
                        connection.get_peer_info() != full_node_peer
                        and connection.get_peer_info() != full_node_resolved
                    ):
                        self.log.info(
                            f"Closing unnecessary connection to {connection.get_peer_info()}."
                        )
                        self.global_connections.close(connection)
                return 0
        return diff

    @api_request
    async def respond_peers(
        self, request: introducer_protocol.RespondPeers
    ) -> OutboundMessageGenerator:
        """
        We have received a list of full node peers that we can connect to.
        """
        if self.server is None or self.wallet_state_manager is None:
            return
        conns = self.global_connections
        for peer in request.peer_list:
            conns.peers.add(peer)

        # Pseudo-message to close the connection
        yield OutboundMessage(NodeType.INTRODUCER, Message("", None), Delivery.CLOSE)

        unconnected = conns.get_unconnected_peers(
            recent_threshold=self.config["recent_peer_threshold"]
        )
        to_connect = unconnected[: self._num_needed_peers()]
        if not len(to_connect):
            return

        self.log.info(f"Trying to connect to peers: {to_connect}")
        tasks = []
        for peer in to_connect:
            tasks.append(
                asyncio.create_task(self.server.start_client(peer, self._on_connect))
            )
        await asyncio.gather(*tasks)

    async def _sync(self):
        """
        Wallet has fallen far behind (or is starting up for the first time), and must be synced
        up to the LCA of the blockchain.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return

        # 1. Get all header hashes
        self.header_hashes = []
        self.header_hashes_error = False
        self.proof_hashes = []
        self.potential_header_hashes = {}
        genesis = FullBlock.from_bytes(self.constants["GENESIS_BLOCK"])
        genesis_challenge = genesis.proof_of_space.challenge_hash
        request_header_hashes = wallet_protocol.RequestAllHeaderHashesAfter(
            uint32(0), genesis_challenge
        )
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("request_all_header_hashes_after", request_header_hashes),
            Delivery.RESPOND,
        )
        timeout = 50
        sleep_interval = 3
        sleep_interval_short = 1
        start_wait = time.time()
        while time.time() - start_wait < timeout:
            if self._shut_down:
                return
            if self.header_hashes_error:
                raise ValueError(
                    f"Received error from full node while fetching hashes from {request_header_hashes}."
                )
            if len(self.header_hashes) > 0:
                break
            await asyncio.sleep(0.5)
        if len(self.header_hashes) == 0:
            raise TimeoutError("Took too long to fetch header hashes.")

        # 2. Find fork point
        fork_point_height: uint32 = self.wallet_state_manager.find_fork_point_alternate_chain(
            self.header_hashes
        )
        fork_point_hash: bytes32 = self.header_hashes[fork_point_height]

        # Sync a little behind, in case there is a short reorg
        tip_height = (
            len(self.header_hashes) - 5
            if len(self.header_hashes) > 5
            else len(self.header_hashes)
        )
        self.log.info(
            f"Fork point: {fork_point_hash} at height {fork_point_height}. Will sync up to {tip_height}"
        )
        for height in range(0, tip_height + 1):
            self.potential_blocks_received[uint32(height)] = asyncio.Event()

        header_validate_start_height: uint32
        if self.config["starting_height"] == 0:
            header_validate_start_height = fork_point_height
        else:
            # Request all proof hashes
            request_proof_hashes = wallet_protocol.RequestAllProofHashes()
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("request_all_proof_hashes", request_proof_hashes),
                Delivery.RESPOND,
            )
            start_wait = time.time()
            while time.time() - start_wait < timeout:
                if self._shut_down:
                    return
                if len(self.proof_hashes) > 0:
                    break
                await asyncio.sleep(0.5)
            if len(self.proof_hashes) == 0:
                raise TimeoutError("Took too long to fetch proof hashes.")
            if len(self.proof_hashes) < tip_height:
                raise ValueError("Not enough proof hashes fetched.")

            # Creates map from height to difficulty
            heights: List[uint32] = []
            difficulty_weights: List[uint64] = []
            difficulty: uint64
            for i in range(tip_height):
                if self.proof_hashes[i][1] is not None:
                    difficulty = self.proof_hashes[i][1]
                if i > (fork_point_height + 1) and i % 2 == 1:  # Only add odd heights
                    heights.append(uint32(i))
                    difficulty_weights.append(difficulty)

            # Randomly sample based on difficulty
            query_heights_odd = sorted(
                list(
                    set(
                        random.choices(
                            heights, difficulty_weights, k=min(100, len(heights))
                        )
                    )
                )
            )
            query_heights: List[uint32] = []

            for odd_height in query_heights_odd:
                query_heights += [uint32(odd_height - 1), odd_height]

            # Send requests for these heights
            # Verify these proofs
            last_request_time = float(0)
            highest_height_requested = uint32(0)
            request_made = False

            for height_index in range(len(query_heights)):
                total_time_slept = 0
                while True:
                    if self._shut_down:
                        return
                    if total_time_slept > timeout:
                        raise TimeoutError("Took too long to fetch blocks")

                    # Request batches that we don't have yet
                    for batch_start_index in range(
                        height_index,
                        min(
                            height_index + self.config["num_sync_batches"],
                            len(query_heights),
                        ),
                    ):
                        if self._shut_down:
                            return
                        blocks_missing = not self.potential_blocks_received[
                            uint32(query_heights[batch_start_index])
                        ].is_set()
                        if (
                            (
                                time.time() - last_request_time > sleep_interval
                                and blocks_missing
                            )
                            or (query_heights[batch_start_index])
                            > highest_height_requested
                        ):
                            self.log.info(
                                f"Requesting sync header {query_heights[batch_start_index]}"
                            )
                            if (
                                query_heights[batch_start_index]
                                > highest_height_requested
                            ):
                                highest_height_requested = uint32(
                                    query_heights[batch_start_index]
                                )
                            request_made = True
                            request_header = wallet_protocol.RequestHeader(
                                uint32(query_heights[batch_start_index]),
                                self.header_hashes[query_heights[batch_start_index]],
                            )
                            yield OutboundMessage(
                                NodeType.FULL_NODE,
                                Message("request_header", request_header),
                                Delivery.RANDOM,
                            )
                    if request_made:
                        last_request_time = time.time()
                        request_made = False
                    try:
                        aw = self.potential_blocks_received[
                            uint32(query_heights[height_index])
                        ].wait()
                        await asyncio.wait_for(aw, timeout=sleep_interval)
                        break
                    except concurrent.futures.TimeoutError:
                        total_time_slept += sleep_interval
                        self.log.info("Did not receive desired headers")

            self.log.info(
                f"Finished downloading sample of headers at heights: {query_heights}, validating."
            )
            # Validates the downloaded proofs
            assert self.wallet_state_manager.validate_select_proofs(
                self.proof_hashes,
                query_heights_odd,
                self.cached_blocks,
                self.potential_header_hashes,
            )
            self.log.info("All proofs validated successfuly.")

            # Add blockrecords one at a time, to catch up to starting height
            weight = self.wallet_state_manager.block_records[fork_point_hash].weight
            header_validate_start_height = min(
                max(fork_point_height, self.config["starting_height"] - 1),
                tip_height + 1,
            )
            if fork_point_height == 0:
                difficulty = self.constants["DIFFICULTY_STARTING"]
            else:
                fork_point_parent_hash = self.wallet_state_manager.block_records[
                    fork_point_hash
                ].prev_header_hash
                fork_point_parent_weight = self.wallet_state_manager.block_records[
                    fork_point_parent_hash
                ]
                difficulty = uint64(weight - fork_point_parent_weight)
            for height in range(fork_point_height + 1, header_validate_start_height):
                _, difficulty_change, total_iters = self.proof_hashes[height]
                weight += difficulty
                block_record = BlockRecord(
                    self.header_hashes[height],
                    self.header_hashes[height - 1],
                    uint32(height),
                    weight,
                    [],
                    [],
                    total_iters,
                    None,
                )
                res = await self.wallet_state_manager.receive_block(block_record, None)
                assert (
                    res == ReceiveBlockResult.ADDED_TO_HEAD
                    or res == ReceiveBlockResult.ADDED_AS_ORPHAN
                )
            self.log.info(
                f"Fast sync successful up to height {header_validate_start_height - 1}"
            )

        # Download headers in batches, and verify them as they come in. We download a few batches ahead,
        # in case there are delays. TODO(mariano): optimize sync by pipelining
        last_request_time = float(0)
        highest_height_requested = uint32(0)
        request_made = False

        for height_checkpoint in range(
            header_validate_start_height + 1, tip_height + 1
        ):
            total_time_slept = 0
            while True:
                # Request batches that we don't have yet
                for batch_start in range(
                    height_checkpoint,
                    min(
                        height_checkpoint + self.config["num_sync_batches"],
                        tip_height + 1,
                    ),
                ):
                    if self._shut_down:
                        return
                    if total_time_slept > timeout:
                        raise TimeoutError("Took too long to fetch blocks")
                    batch_end = min(batch_start + 1, tip_height + 1)
                    blocks_missing = any(
                        [
                            not (self.potential_blocks_received[uint32(h)]).is_set()
                            for h in range(batch_start, batch_end)
                        ]
                    )
                    if (
                        time.time() - last_request_time > sleep_interval
                        and blocks_missing
                    ) or (batch_end - 1) > highest_height_requested:
                        self.log.info(f"Requesting sync header {batch_start}")
                        if batch_end - 1 > highest_height_requested:
                            highest_height_requested = uint32(batch_end - 1)
                        request_made = True
                        request_header = wallet_protocol.RequestHeader(
                            uint32(batch_start), self.header_hashes[batch_start],
                        )
                        yield OutboundMessage(
                            NodeType.FULL_NODE,
                            Message("request_header", request_header),
                            Delivery.RANDOM,
                        )
                if request_made:
                    last_request_time = time.time()
                    request_made = False

                awaitables = [
                    self.potential_blocks_received[uint32(height_checkpoint)].wait()
                ]
                future = asyncio.gather(*awaitables, return_exceptions=True)
                try:
                    await asyncio.wait_for(future, timeout=sleep_interval)
                except concurrent.futures.TimeoutError:
                    try:
                        await future
                    except asyncio.CancelledError:
                        pass
                    total_time_slept += sleep_interval
                    self.log.info("Did not receive desired headers")
                    continue

                # Succesfully downloaded header. Now confirm it's added to chain.
                hh = self.potential_header_hashes[height_checkpoint]
                if hh in self.wallet_state_manager.block_records:
                    # Successfully added the block to chain
                    break
                else:
                    # Not added to chain yet. Try again soon.
                    await asyncio.sleep(sleep_interval_short)
                    if self._shut_down:
                        return
                    total_time_slept += sleep_interval_short
                    if hh in self.wallet_state_manager.block_records:
                        break
                    else:
                        self.log.warning(
                            "Received header, but it has not been added to chain. Retrying."
                        )
                        _, hb, tfilter = self.cached_blocks[hh]
                        respond_header_msg = wallet_protocol.RespondHeader(hb, tfilter)
                        async for msg in self.respond_header(respond_header_msg):
                            yield msg

        self.log.info(
            f"Finished sync process up to height {max(self.wallet_state_manager.height_to_hash.keys())}"
        )

    async def _block_finished(
        self,
        block_record: BlockRecord,
        header_block: HeaderBlock,
        transaction_filter: Optional[bytes],
    ) -> Optional[wallet_protocol.RespondHeader]:
        """
        This is called when we have finished a block (which means we have downloaded the header,
        as well as the relevant additions and removals for the wallets).
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return None
        self.log.info(
            f"Finishing block {block_record.header_hash} at height {block_record.height}"
        )
        assert block_record.prev_header_hash in self.wallet_state_manager.block_records
        assert block_record.additions is not None and block_record.removals is not None

        # We have completed a block that we can add to chain, so add it.
        res = await self.wallet_state_manager.receive_block(block_record, header_block)
        if res == ReceiveBlockResult.DISCONNECTED_BLOCK:
            self.log.error("Attempted to add disconnected block")
            return None
        elif res == ReceiveBlockResult.INVALID_BLOCK:
            self.log.error("Attempted to add invalid block")
            return None
        elif res == ReceiveBlockResult.ALREADY_HAVE_BLOCK:
            return None
        elif res == ReceiveBlockResult.ADDED_AS_ORPHAN:
            self.log.info(
                f"Added orphan {block_record.header_hash} at height {block_record.height}"
            )
        elif res == ReceiveBlockResult.ADDED_TO_HEAD:
            self.log.info(
                f"Updated LCA to {block_record.header_hash} at height {block_record.height}"
            )
            # Removes outdated cached blocks if we're not syncing
            if not self.wallet_state_manager.sync_mode:
                remove_header_hashes = []
                for header_hash in self.cached_blocks:
                    if (
                        block_record.height - self.cached_blocks[header_hash][0].height
                        > 100
                    ):
                        remove_header_hashes.append(header_hash)
                for header_hash in remove_header_hashes:
                    del self.cached_blocks[header_hash]
        else:
            raise RuntimeError("Invalid state")

        # Now for the cases of already have, orphan, and added to head, move on to the next block
        if block_record.header_hash in self.future_block_hashes:
            new_hh = self.future_block_hashes[block_record.header_hash]
            _, new_hb, new_tfilter = self.cached_blocks[new_hh]
            return wallet_protocol.RespondHeader(new_hb, new_tfilter)
        return None

    @api_request
    async def transaction_ack_with_peer_name(
        self, ack: wallet_protocol.TransactionAck, name: str
    ):
        """
        This is an ack for our previous SendTransaction call. This removes the transaction from
        the send queue if we have sent it to enough nodes.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        if ack.status == MempoolInclusionStatus.SUCCESS:
            self.log.info(
                f"SpendBundle has been received and accepted to mempool by the FullNode. {ack}"
            )
        elif ack.status == MempoolInclusionStatus.PENDING:
            self.log.info(
                f"SpendBundle has been received (and is pending) by the FullNode. {ack}"
            )
        else:
            self.log.warning(f"SpendBundle has been rejected by the FullNode. {ack}")
        if ack.error is not None:
            await self.wallet_state_manager.remove_from_queue(
                ack.txid, name, ack.status, Err[ack.error]
            )
        else:
            await self.wallet_state_manager.remove_from_queue(
                ack.txid, name, ack.status, None
            )

    @api_request
    async def respond_all_proof_hashes(
        self, response: wallet_protocol.RespondAllProofHashes
    ):
        """
        Receipt of proof hashes, used during sync for interactive weight verification protocol.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        if not self.wallet_state_manager.sync_mode:
            self.log.warning("Receiving proof hashes while not syncing.")
            return
        self.proof_hashes = response.hashes

    @api_request
    async def respond_all_header_hashes_after(
        self, response: wallet_protocol.RespondAllHeaderHashesAfter
    ):
        """
        Response containing all header hashes after a point. This is used to find the fork
        point between our current blockchain, and the current heaviest tip.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        if not self.wallet_state_manager.sync_mode:
            self.log.warning("Receiving header hashes while not syncing.")
            return
        self.header_hashes = response.hashes

    @api_request
    async def reject_all_header_hashes_after_request(
        self, response: wallet_protocol.RejectAllHeaderHashesAfterRequest
    ):
        """
        Error in requesting all header hashes.
        """
        self.log.error("All header hashes after request rejected")
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        self.header_hashes_error = True

    @api_request
    async def new_lca(self, request: wallet_protocol.NewLCA):
        """
        Notification from full node that a new LCA (Least common ancestor of the three blockchain
        tips) has been added to the full node.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        if self._shut_down:
            return
        if self.wallet_state_manager.sync_mode:
            return
        # If already seen LCA, ignore.
        if request.lca_hash in self.wallet_state_manager.block_records:
            return

        lca = self.wallet_state_manager.block_records[self.wallet_state_manager.lca]
        # If it's not the heaviest chain, ignore.
        if request.weight < lca.weight:
            return

        if int(request.height) - int(lca.height) > self.short_sync_threshold:
            try:
                # Performs sync, and catch exceptions so we don't close the connection
                self.wallet_state_manager.set_sync_mode(True)
                self.sync_generator_task = self._sync()
                assert self.sync_generator_task is not None
                async for ret_msg in self.sync_generator_task:
                    yield ret_msg
            except Exception as e:
                tb = traceback.format_exc()
                self.log.error(f"Error with syncing. {type(e)} {tb}")
            self.wallet_state_manager.set_sync_mode(False)
        else:
            header_request = wallet_protocol.RequestHeader(
                uint32(request.height), request.lca_hash
            )
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("request_header", header_request),
                Delivery.RESPOND,
            )

        # Try sending queued up transaction when new LCA arrives
        await self._resend_queue()

    @api_request
    async def respond_header(self, response: wallet_protocol.RespondHeader):
        """
        The full node responds to our RequestHeader call. We cannot finish this block
        until we have the required additions / removals for our wallets.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        while True:
            if self._shut_down:
                return
            # We loop, to avoid infinite recursion. At the end of each iteration, we might want to
            # process the next block, if it exists.

            block = response.header_block

            # If we already have, return
            if block.header_hash in self.wallet_state_manager.block_records:
                return
            if block.height < 1:
                return

            block_record = BlockRecord(
                block.header_hash,
                block.prev_header_hash,
                block.height,
                block.weight,
                None,
                None,
                response.header_block.header.data.total_iters,
                response.header_block.challenge.get_hash(),
            )

            if self.wallet_state_manager.sync_mode:
                self.potential_blocks_received[uint32(block.height)].set()
                self.potential_header_hashes[block.height] = block.header_hash

            # Caches the block so we can finalize it when additions and removals arrive
            self.cached_blocks[block_record.header_hash] = (
                block_record,
                block,
                response.transactions_filter,
            )

            if block.prev_header_hash not in self.wallet_state_manager.block_records:
                # We do not have the previous block record, so wait for that. When the previous gets added to chain,
                # this method will get called again and we can continue. During sync, the previous blocks are already
                # requested. During normal operation, this might not be the case.
                self.future_block_hashes[block.prev_header_hash] = block.header_hash

                lca = self.wallet_state_manager.block_records[
                    self.wallet_state_manager.lca
                ]
                if (
                    block_record.height - lca.height < self.short_sync_threshold
                    and not self.wallet_state_manager.sync_mode
                ):
                    # Only requests the previous block if we are not in sync mode, close to the new block,
                    # and don't have prev
                    header_request = wallet_protocol.RequestHeader(
                        uint32(block_record.height - 1), block_record.prev_header_hash,
                    )
                    yield OutboundMessage(
                        NodeType.FULL_NODE,
                        Message("request_header", header_request),
                        Delivery.RESPOND,
                    )
                return

            # If the block has transactions that we are interested in, fetch adds/deletes
            (
                additions,
                removals,
            ) = await self.wallet_state_manager.get_filter_additions_removals(
                block_record, response.transactions_filter
            )
            if len(additions) > 0 or len(removals) > 0:
                request_a = wallet_protocol.RequestAdditions(
                    block.height, block.header_hash, additions
                )
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message("request_additions", request_a),
                    Delivery.RESPOND,
                )
                return

            # If we don't have any transactions in filter, don't fetch, and finish the block
            block_record = BlockRecord(
                block_record.header_hash,
                block_record.prev_header_hash,
                block_record.height,
                block_record.weight,
                [],
                [],
                block_record.total_iters,
                block_record.new_challenge_hash,
            )
            respond_header_msg: Optional[
                wallet_protocol.RespondHeader
            ] = await self._block_finished(
                block_record, block, response.transactions_filter
            )
            if respond_header_msg is None:
                return
            else:
                response = respond_header_msg

    @api_request
    async def reject_header_request(
        self, response: wallet_protocol.RejectHeaderRequest
    ):
        """
        The full node has rejected our request for a header.
        """
        # TODO(mariano): implement
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        self.log.error("Header request rejected")

    @api_request
    async def respond_additions(self, response: wallet_protocol.RespondAdditions):
        """
        The full node has responded with the additions for a block. We will use this
        to try to finish the block, and add it to the state.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        if self._shut_down:
            return
        if response.header_hash not in self.cached_blocks:
            self.log.warning("Do not have header for additions")
            return
        block_record, header_block, transaction_filter = self.cached_blocks[
            response.header_hash
        ]
        assert response.height == block_record.height

        additions: List[Coin]
        if response.proofs is None:
            # If there are no proofs, it means all additions were returned in the response.
            # we must find the ones relevant to our wallets.
            all_coins: List[Coin] = []
            for puzzle_hash, coin_list_0 in response.coins:
                all_coins += coin_list_0
            additions = await self.wallet_state_manager.get_relevant_additions(
                all_coins
            )
            # Verify root
            additions_merkle_set = MerkleSet()

            # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
            for puzzle_hash, coins in response.coins:
                additions_merkle_set.add_already_hashed(puzzle_hash)
                additions_merkle_set.add_already_hashed(hash_coin_list(coins))

            additions_root = additions_merkle_set.get_root()
            if header_block.header.data.additions_root != additions_root:
                return
        else:
            # This means the full node has responded only with the relevant additions
            # for our wallet. Each merkle proof must be verified.
            additions = []
            assert len(response.coins) == len(response.proofs)
            for i in range(len(response.coins)):
                assert response.coins[i][0] == response.proofs[i][0]
                coin_list_1: List[Coin] = response.coins[i][1]
                puzzle_hash_proof: bytes32 = response.proofs[i][1]
                coin_list_proof: Optional[bytes32] = response.proofs[i][2]
                if len(coin_list_1) == 0:
                    # Verify exclusion proof for puzzle hash
                    assert confirm_not_included_already_hashed(
                        header_block.header.data.additions_root,
                        response.coins[i][0],
                        puzzle_hash_proof,
                    )
                else:
                    # Verify inclusion proof for puzzle hash
                    assert confirm_included_already_hashed(
                        header_block.header.data.additions_root,
                        response.coins[i][0],
                        puzzle_hash_proof,
                    )
                    # Verify inclusion proof for coin list
                    assert confirm_included_already_hashed(
                        header_block.header.data.additions_root,
                        hash_coin_list(coin_list_1),
                        coin_list_proof,
                    )
                    for coin in coin_list_1:
                        assert coin.puzzle_hash == response.coins[i][0]
                    additions += coin_list_1
        new_br = BlockRecord(
            block_record.header_hash,
            block_record.prev_header_hash,
            block_record.height,
            block_record.weight,
            additions,
            None,
            block_record.total_iters,
            header_block.challenge.get_hash(),
        )
        self.cached_blocks[response.header_hash] = (
            new_br,
            header_block,
            transaction_filter,
        )

        if transaction_filter is None:
            raise RuntimeError("Got additions for block with no transactions.")

        (_, removals,) = await self.wallet_state_manager.get_filter_additions_removals(
            new_br, transaction_filter
        )
        request_all_removals = False
        for coin in additions:
            puzzle_store = self.wallet_state_manager.puzzle_store
            record_info: Optional[
                DerivationRecord
            ] = await puzzle_store.get_derivation_record_for_puzzle_hash(
                coin.puzzle_hash.hex()
            )
            if (
                record_info is not None
                and record_info.wallet_type == WalletType.COLOURED_COIN
            ):
                request_all_removals = True
                break

        if len(removals) > 0 or request_all_removals:
            if request_all_removals:
                request_r = wallet_protocol.RequestRemovals(
                    header_block.height, header_block.header_hash, None
                )
            else:
                request_r = wallet_protocol.RequestRemovals(
                    header_block.height, header_block.header_hash, removals
                )
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("request_removals", request_r),
                Delivery.RESPOND,
            )
        else:
            # We have collected all three things: header, additions, and removals (since there are no
            # relevant removals for us). Can proceed. Otherwise, we wait for the removals to arrive.
            new_br = BlockRecord(
                new_br.header_hash,
                new_br.prev_header_hash,
                new_br.height,
                new_br.weight,
                new_br.additions,
                [],
                new_br.total_iters,
                new_br.new_challenge_hash,
            )
            respond_header_msg: Optional[
                wallet_protocol.RespondHeader
            ] = await self._block_finished(new_br, header_block, transaction_filter)
            if respond_header_msg is not None:
                async for msg in self.respond_header(respond_header_msg):
                    yield msg

    @api_request
    async def respond_removals(self, response: wallet_protocol.RespondRemovals):
        """
        The full node has responded with the removals for a block. We will use this
        to try to finish the block, and add it to the state.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        if self._shut_down:
            return
        if (
            response.header_hash not in self.cached_blocks
            or self.cached_blocks[response.header_hash][0].additions is None
        ):
            self.log.warning(
                "Do not have header for removals, or do not have additions"
            )
            return

        block_record, header_block, transaction_filter = self.cached_blocks[
            response.header_hash
        ]
        assert response.height == block_record.height

        all_coins: List[Coin] = []
        for coin_name, coin in response.coins:
            if coin is not None:
                all_coins.append(coin)

        if response.proofs is None:
            # If there are no proofs, it means all removals were returned in the response.
            # we must find the ones relevant to our wallets.

            # Verify removals root
            removals_merkle_set = MerkleSet()
            for coin in all_coins:
                if coin is not None:
                    removals_merkle_set.add_already_hashed(coin.name())
            removals_root = removals_merkle_set.get_root()
            assert header_block.header.data.removals_root == removals_root

        else:
            # This means the full node has responded only with the relevant removals
            # for our wallet. Each merkle proof must be verified.
            assert len(response.coins) == len(response.proofs)
            for i in range(len(response.coins)):
                # Coins are in the same order as proofs
                assert response.coins[i][0] == response.proofs[i][0]
                coin = response.coins[i][1]
                if coin is None:
                    # Verifies merkle proof of exclusion
                    assert confirm_not_included_already_hashed(
                        header_block.header.data.removals_root,
                        response.coins[i][0],
                        response.proofs[i][1],
                    )
                else:
                    # Verifies merkle proof of inclusion of coin name
                    assert response.coins[i][0] == coin.name()
                    assert confirm_included_already_hashed(
                        header_block.header.data.removals_root,
                        coin.name(),
                        response.proofs[i][1],
                    )

        new_br = BlockRecord(
            block_record.header_hash,
            block_record.prev_header_hash,
            block_record.height,
            block_record.weight,
            block_record.additions,
            all_coins,
            block_record.total_iters,
            header_block.challenge.get_hash(),
        )

        self.cached_blocks[response.header_hash] = (
            new_br,
            header_block,
            transaction_filter,
        )

        # We have collected all three things: header, additions, and removals. Can proceed.
        respond_header_msg: Optional[
            wallet_protocol.RespondHeader
        ] = await self._block_finished(new_br, header_block, transaction_filter)
        if respond_header_msg is not None:
            async for msg in self.respond_header(respond_header_msg):
                yield msg

    @api_request
    async def reject_removals_request(
        self, response: wallet_protocol.RejectRemovalsRequest
    ):
        """
        The full node has rejected our request for removals.
        """
        # TODO(mariano): implement
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        self.log.error("Removals request rejected")

    @api_request
    async def reject_additions_request(
        self, response: wallet_protocol.RejectAdditionsRequest
    ):
        """
        The full node has rejected our request for additions.
        """
        # TODO(mariano): implement
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        self.log.error("Additions request rejected")

    @api_request
    async def respond_generator(self, response: wallet_protocol.RespondGenerator):
        """
        The full node respond with transaction generator
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        wrapper = response.generatorResponse
        if wrapper.generator is not None:
            self.log.info(
                f"generator received {wrapper.header_hash} {wrapper.generator.get_tree_hash()} {wrapper.height}"
            )
            await self.wallet_state_manager.generator_received(
                wrapper.height, wrapper.header_hash, wrapper.generator
            )

    @api_request
    async def reject_generator(self, response: wallet_protocol.RejectGeneratorRequest):
        """
        The full node rejected our request for generator
        """
        # TODO (Straya): implement
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        self.log.info("generator rejected")
