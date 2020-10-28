import asyncio
import concurrent
import logging
import traceback
import time
import random
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional, Tuple, Callable
import aiosqlite
from chiabip158 import PyBIP158
from chiapos import Verifier
import dataclasses
from blspy import G2Element, AugSchemeMPL

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import calculate_iterations
from src.full_node.block_store import BlockStore
from src.full_node.blockchain import Blockchain, ReceiveBlockResult
from src.full_node.coin_store import CoinStore
from src.full_node.full_node_store import FullNodeStore
from src.full_node.mempool_manager import MempoolManager
from src.full_node.sub_block_record import SubBlockRecord
from src.full_node.sync_blocks_processor import SyncBlocksProcessor
from src.full_node.sync_peers_handler import SyncPeersHandler
from src.full_node.sync_store import SyncStore
from src.protocols import (
    introducer_protocol,
    farmer_protocol,
    full_node_protocol,
    timelord_protocol,
    wallet_protocol,
)
from src.protocols.wallet_protocol import GeneratorResponse
from src.server.connection import PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.server.server import ChiaServer
from src.types.coin import Coin, hash_coin_list
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.types.mempool_item import MempoolItem
from src.types.program import Program
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.types.unfinished_block import UnfinishedBlock
from src.util.api_decorators import api_request
from src.full_node.bundle_tools import best_solution_program
from src.full_node.cost_calculator import calculate_cost_of_program
from src.util.errors import ConsensusError, Err
from src.util.hash import std_hash
from src.util.ints import uint32, uint64, uint128
from src.util.merkle_set import MerkleSet
from src.util.path import mkdir, path_from_root
from src.server.node_discovery import FullNodePeers
from src.types.peer_info import PeerInfo

OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]


class FullNode:
    block_store: BlockStore
    full_node_store: FullNodeStore
    full_node_peers: FullNodePeers
    sync_store: SyncStore
    coin_store: CoinStore
    mempool_manager: MempoolManager
    connection: aiosqlite.Connection
    sync_peers_handler: Optional[SyncPeersHandler]
    blockchain: Blockchain
    config: Dict
    global_connections: Optional[PeerConnections]
    server: Optional[ChiaServer]
    log: logging.Logger
    constants: ConsensusConstants
    _shut_down: bool
    root_path: Path
    state_changed_callback: Optional[Callable]

    def __init__(
        self,
        config: Dict,
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = None,
    ):
        self.root_path = root_path
        self.config = config
        self.server = None
        self._shut_down = False  # Set to true to close all infinite loops
        self.constants = consensus_constants
        self.sync_peers_handler = None
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.global_connections = None

        self.db_path = path_from_root(root_path, config["database_path"])
        mkdir(self.db_path.parent)

    async def _start(self):
        # create the store (db) and full node instance
        self.connection = await aiosqlite.connect(self.db_path)
        self.block_store = await BlockStore.create(self.connection)
        self.full_node_store = await FullNodeStore.create(self.connection)
        self.sync_store = await SyncStore.create()
        self.coin_store = await CoinStore.create(self.connection)
        self.log.info("Initializing blockchain from disk")
        self.blockchain = await Blockchain.create(self.coin_store, self.block_store, self.constants)
        self.mempool_manager = MempoolManager(self.coin_store, self.constants)
        if self.blockchain.get_peak() is None:
            self.log.info("Initialized with empty blockchain")
        else:
            self.log.info(
                f"Blockchain initialized to peak {self.blockchain.get_peak().header_hash} height {self.blockchain.get_peak().height}"
            )
            await self.mempool_manager.new_peak(self.blockchain.get_peak())

        self.state_changed_callback = None
        try:
            self.full_node_peers = FullNodePeers(
                self.server,
                self.root_path,
                self.global_connections,
                self.config["target_peer_count"] - self.config["target_outbound_peer_count"],
                self.config["target_outbound_peer_count"],
                self.config["peer_db_path"],
                self.config["introducer_peer"],
                self.config["peer_connect_interval"],
                self.log,
            )
            await self.full_node_peers.start()
        except Exception as e:
            self.log.error(f"Exception in peer discovery: {e}")

        # TODO(mariano)
        # uncompact_interval = self.config["send_uncompact_interval"]
        # if uncompact_interval > 0:
        #     self.broadcast_uncompact_task = asyncio.create_task(self.broadcast_uncompact_blocks(uncompact_interval))
        #
        # for ((_, _), block) in (await self.full_node_store.get_unfinished_blocks()).items():
        #     if block.height > self.full_node_store.get_unfinished_block_leader()[0]:
        #         self.full_node_store.set_unfinished_block_leader((block.height, 999999999999))

    def _set_global_connections(self, global_connections: PeerConnections):
        self.global_connections = global_connections

    def _set_server(self, server: ChiaServer):
        self.server = server

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback
        if self.global_connections is not None:
            self.global_connections.set_state_changed_callback(callback)

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    async def _send_challenges_to_timelords(self, delivery: Delivery = Delivery.BROADCAST) -> OutboundMessageGenerator:
        """
        Sends all of the current heads (as well as Pos infos) to all timelord peers.
        """
        challenge_requests: List[timelord_protocol.ChallengeStart] = []
        pos_info_requests: List[timelord_protocol.ProofOfSpaceInfo] = []
        tips: List[Header] = self.blockchain.get_current_tips()
        tips_blocks: List[Optional[FullBlock]] = [await self.block_store.get_block(tip.header_hash) for tip in tips]
        for tip in tips_blocks:
            assert tip is not None
            challenge = self.blockchain.get_challenge(tip)
            assert challenge is not None
            challenge_requests.append(timelord_protocol.ChallengeStart(challenge.get_hash(), tip.weight))

        tip_hashes = [tip.header_hash for tip in tips]
        tip_infos = [
            (tup[0], tup[1])
            for tup in list((await self.full_node_store.get_unfinished_blocks()).items())
            if tup[1].prev_header_hash in tip_hashes
        ]
        for ((chall, iters), _) in tip_infos:
            pos_info_requests.append(timelord_protocol.ProofOfSpaceInfo(chall, iters))

        # Sends our best unfinished block (proof of space) to peer
        for ((_, iters), block) in sorted(tip_infos, key=lambda t: t[0][1]):
            if block.height < self.full_node_store.get_unfinished_block_leader()[0]:
                continue
            unfinished_block_msg = full_node_protocol.NewUnfinishedBlock(
                block.prev_header_hash, iters, block.header_hash
            )
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("new_unfinished_block", unfinished_block_msg),
                delivery,
            )
            break
        for challenge_msg in challenge_requests:
            yield OutboundMessage(NodeType.TIMELORD, Message("challenge_start", challenge_msg), delivery)
        for pos_info_msg in pos_info_requests:
            yield OutboundMessage(
                NodeType.TIMELORD,
                Message("proof_of_space_info", pos_info_msg),
                delivery,
            )

    async def _on_connect(self) -> OutboundMessageGenerator:
        """
        Whenever we connect to another node / wallet, send them our current heads. Also send heads to farmers
        and challenges to timelords.
        """
        tips: List[Header] = self.blockchain.get_current_tips()
        for t in tips:
            request = full_node_protocol.NewTip(t.height, t.weight, t.header_hash)
            yield OutboundMessage(NodeType.FULL_NODE, Message("new_tip", request), Delivery.RESPOND)
        # If connected to a wallet, send the LCA
        lca = self.blockchain.lca_block
        new_lca = wallet_protocol.NewLCA(lca.header_hash, lca.height, lca.weight)
        yield OutboundMessage(NodeType.WALLET, Message("new_lca", new_lca), Delivery.RESPOND)

        # Send filter to node and request mempool items that are not in it
        my_filter = self.mempool_manager.get_filter()
        mempool_request = full_node_protocol.RequestMempoolTransactions(my_filter)

        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("request_mempool_transactions", mempool_request),
            Delivery.RESPOND,
        )

        # Update timelord with most recent information
        async for msg in self._send_challenges_to_timelords(Delivery.RESPOND):
            yield msg

    @api_request
    async def request_peers_with_peer_info(
        self,
        request: full_node_protocol.RequestPeers,
        peer_info: PeerInfo,
    ):
        async for msg in self.full_node_peers.request_peers(peer_info):
            yield msg

    @api_request
    async def respond_peers_with_peer_info(
        self,
        request: introducer_protocol.RespondPeers,
        peer_info: PeerInfo,
    ) -> OutboundMessageGenerator:
        await self.full_node_peers.respond_peers(request, peer_info, False)
        # Pseudo-message to close the connection
        yield OutboundMessage(NodeType.INTRODUCER, Message("", None), Delivery.CLOSE)

    @api_request
    async def respond_peers_full_node_with_peer_info(
        self,
        request: full_node_protocol.RespondPeers,
        peer_info: PeerInfo,
    ):
        await self.full_node_peers.respond_peers(request, peer_info, True)

    def _num_needed_peers(self) -> int:
        assert self.global_connections is not None
        diff = self.config["target_peer_count"] - len(self.global_connections.get_full_node_connections())
        return diff if diff >= 0 else 0

    def _close(self):
        self._shut_down = True
        self.blockchain.shut_down()
        self._stop_task = asyncio.create_task(self.full_node_peers.close())

    async def _await_closed(self):
        await self.connection.close()

    async def _sync(self) -> OutboundMessageGenerator:
        """
        Performs a full sync of the blockchain.
            - Check which are the heaviest tips
            - Request headers for the heaviest
            - Find the fork point to see where to start downloading headers
            - Verify the weight of the tip, using the headers
            - Download all blocks
            - Disconnect peers that provide invalid blocks or don't have the blocks
        """
        self.log.info("Starting to perform sync with peers.")
        self.log.info("Waiting to receive tips from peers.")
        self.sync_peers_handler = None
        self.sync_store.set_waiting_for_tips(True)
        # TODO: better way to tell that we have finished receiving tips
        # TODO: fix DOS issue. Attacker can request syncing to an invalid blockchain
        await asyncio.sleep(2)
        highest_weight: uint128 = uint128(0)
        tip_block: FullBlock
        tip_height = 0
        sync_start_time = time.time()

        # Based on responses from peers about the current heads, see which head is the heaviest
        # (similar to longest chain rule).
        self.sync_store.set_waiting_for_tips(False)

        potential_tips: List[Tuple[bytes32, FullBlock]] = self.sync_store.get_potential_tips_tuples()
        self.log.info(f"Have collected {len(potential_tips)} potential tips")
        if self._shut_down:
            return

        for header_hash, potential_tip_block in potential_tips:
            if potential_tip_block.proof_of_time is None:
                raise ValueError(f"Invalid tip block {potential_tip_block.header_hash} received")
            if potential_tip_block.weight > highest_weight:
                highest_weight = potential_tip_block.weight
                tip_block = potential_tip_block
                tip_height = potential_tip_block.height
        if highest_weight <= max([t.weight for t in self.blockchain.get_current_tips()]):
            self.log.info("Not performing sync, already caught up.")
            return

        assert tip_block
        self.log.info(f"Tip block {tip_block.header_hash} tip height {tip_block.height}")

        self.sync_store.set_potential_hashes_received(asyncio.Event())

        sleep_interval = 10
        total_time_slept = 0

        # TODO: verify weight here once we have the correct protocol messages (interative flyclient)
        while True:
            if total_time_slept > 30:
                raise TimeoutError("Took too long to fetch header hashes.")
            if self._shut_down:
                return
            # Download all the header hashes and find the fork point
            request = full_node_protocol.RequestAllHeaderHashes(tip_block.header_hash)
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("request_all_header_hashes", request),
                Delivery.RANDOM,
            )
            try:
                phr = self.sync_store.get_potential_hashes_received()
                assert phr is not None
                await asyncio.wait_for(
                    phr.wait(),
                    timeout=sleep_interval,
                )
                break
            # https://github.com/python/cpython/pull/13528
            except (concurrent.futures.TimeoutError, asyncio.TimeoutError):
                total_time_slept += sleep_interval
                self.log.warning("Did not receive desired header hashes")

        # Finding the fork point allows us to only download headers and blocks from the fork point
        header_hashes = self.sync_store.get_potential_hashes()

        async with self.blockchain.lock:
            # Lock blockchain so we can copy over the headers without any reorgs
            fork_point_height: uint32 = self.blockchain.find_fork_point_alternate_chain(header_hashes)

        fork_point_hash: bytes32 = header_hashes[fork_point_height]
        self.log.info(f"Fork point: {fork_point_hash} at height {fork_point_height}")

        assert self.global_connections is not None
        peers = [
            con.node_id
            for con in self.global_connections.get_connections()
            if (con.node_id is not None and con.connection_type == NodeType.FULL_NODE)
        ]

        self.sync_peers_handler = SyncPeersHandler(self.sync_store, peers, fork_point_height, self.blockchain)

        # Start processing blocks that we have received (no block yet)
        block_processor = SyncBlocksProcessor(
            self.sync_store,
            fork_point_height,
            uint32(tip_height),
            self.blockchain,
        )
        block_processor_task = asyncio.create_task(block_processor.process())
        lca = self.blockchain.lca_block
        while not self.sync_peers_handler.done():
            # Periodically checks for done, timeouts, shutdowns, new peers or disconnected peers.
            if self._shut_down:
                block_processor.shut_down()
                break
            if block_processor_task.done():
                break
            async for msg in self.sync_peers_handler.monitor_timeouts():
                yield msg  # Disconnects from peers that are not responding

            cur_peers = [
                con.node_id
                for con in self.global_connections.get_connections()
                if (con.node_id is not None and con.connection_type == NodeType.FULL_NODE)
            ]
            for node_id in cur_peers:
                if node_id not in peers:
                    self.sync_peers_handler.new_node_connected(node_id)
            for node_id in peers:
                if node_id not in cur_peers:
                    # Disconnected peer, removes requests that are being sent to it
                    self.sync_peers_handler.node_disconnected(node_id)
            peers = cur_peers

            async for msg in self.sync_peers_handler._add_to_request_sets():
                yield msg  # Send more requests if we can

            new_lca = self.blockchain.lca_block
            if new_lca != lca:
                new_lca_req = wallet_protocol.NewLCA(
                    new_lca.header_hash,
                    new_lca.height,
                    new_lca.weight,
                )
                yield OutboundMessage(NodeType.WALLET, Message("new_lca", new_lca_req), Delivery.BROADCAST)

            self._state_changed("block")
            await asyncio.sleep(5)

        # Awaits for all blocks to be processed, a timeout to happen, or the node to shutdown
        await block_processor_task
        block_processor_task.result()  # If there was a timeout, this will raise TimeoutError
        if self._shut_down:
            return

        current_tips = self.blockchain.get_current_tips()
        assert max([h.height for h in current_tips]) == tip_height

        self.full_node_store.set_proof_of_time_estimate_ips(
            (
                self.blockchain.get_next_min_iters(tip_block)
                * self.constants.MIN_ITERS_PROPORTION
                // self.constants.BLOCK_TIME_TARGET
            )
        )

        self.log.info(
            f"Finished sync up to height {tip_height}. Total time: "
            f"{round((time.time() - sync_start_time)/60, 2)} minutes."
        )

    async def _finish_sync(self) -> OutboundMessageGenerator:
        """
        Finalize sync by setting sync mode to False, clearing all sync information, and adding any final
        blocks that we have finalized recently.
        """
        potential_fut_blocks = (self.sync_store.get_potential_future_blocks()).copy()
        self.sync_store.set_sync_mode(False)

        async with self.blockchain.lock:
            await self.sync_store.clear_sync_info()

        for block in potential_fut_blocks:
            if self._shut_down:
                return
            async for msg in self.respond_block(full_node_protocol.RespondBlock(block)):
                yield msg

        # Update timelords with most recent information
        async for msg in self._send_challenges_to_timelords():
            yield msg

        lca = self.blockchain.lca_block
        new_lca = wallet_protocol.NewLCA(lca.header_hash, lca.height, lca.weight)
        yield OutboundMessage(NodeType.WALLET, Message("new_lca", new_lca), Delivery.BROADCAST)
        self._state_changed("block")

    @api_request
    async def new_tip(self, request: full_node_protocol.NewTip) -> OutboundMessageGenerator:
        """
        A peer notifies us that they have added a new tip to their blockchain. If we don't have it,
        we can ask for it.
        """
        # Check if we have this block in the blockchain
        if self.blockchain.contains_block(request.header_hash):
            return

        # TODO: potential optimization, don't request blocks that we have already sent out
        # a "request_block" message for.
        message = Message(
            "request_block",
            full_node_protocol.RequestBlock(request.height, request.header_hash),
        )
        yield OutboundMessage(NodeType.FULL_NODE, message, Delivery.RESPOND)

    @api_request
    async def removing_tip(self, request: full_node_protocol.RemovingTip) -> OutboundMessageGenerator:
        """
        A peer notifies us that they have removed a tip from their blockchain.
        """
        for _ in []:
            yield _

    @api_request
    async def new_transaction(self, transaction: full_node_protocol.NewTransaction) -> OutboundMessageGenerator:
        """
        A peer notifies us of a new transaction.
        Requests a full transaction if we haven't seen it previously, and if the fees are enough.
        """
        # Ignore if syncing
        if self.sync_store.get_sync_mode():
            return
        # Ignore if already seen
        if self.mempool_manager.seen(transaction.transaction_id):
            return

        if self.mempool_manager.is_fee_enough(transaction.fees, transaction.cost):
            requestTX = full_node_protocol.RequestTransaction(transaction.transaction_id)
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("request_transaction", requestTX),
                Delivery.RESPOND,
            )

    @api_request
    async def request_transaction(self, request: full_node_protocol.RequestTransaction) -> OutboundMessageGenerator:
        """ Peer has requested a full transaction from us. """
        # Ignore if syncing
        if self.sync_store.get_sync_mode():
            return
        spend_bundle = self.mempool_manager.get_spendbundle(request.transaction_id)
        if spend_bundle is None:
            reject = full_node_protocol.RejectTransactionRequest(request.transaction_id)
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("reject_transaction_request", reject),
                Delivery.RESPOND,
            )
            return

        transaction = full_node_protocol.RespondTransaction(spend_bundle)
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("respond_transaction", transaction),
            Delivery.RESPOND,
        )

        self.log.info(f"sending transaction (tx_id: {spend_bundle.name()}) to peer")

    @api_request
    async def respond_transaction(self, tx: full_node_protocol.RespondTransaction) -> OutboundMessageGenerator:
        """
        Receives a full transaction from peer.
        If tx is added to mempool, send tx_id to others. (new_transaction)
        """
        # Ignore if syncing
        if self.sync_store.get_sync_mode():
            return

        async with self.blockchain.lock:
            # Ignore if we have already added this transaction
            if self.mempool_manager.get_spendbundle(tx.transaction.name()) is not None:
                return
            cost, status, error = await self.mempool_manager.add_spendbundle(tx.transaction)
            if status == MempoolInclusionStatus.SUCCESS:
                self.log.info(f"Added transaction to mempool: {tx.transaction.name()}")
                fees = tx.transaction.fees()
                assert fees >= 0
                assert cost is not None
                new_tx = full_node_protocol.NewTransaction(
                    tx.transaction.name(),
                    cost,
                    uint64(tx.transaction.fees()),
                )
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message("new_transaction", new_tx),
                    Delivery.BROADCAST_TO_OTHERS,
                )
            else:
                self.log.warning(
                    f"Wasn't able to add transaction with id {tx.transaction.name()}, {status} error: {error}"
                )
                return

    @api_request
    async def reject_transaction_request(
        self, reject: full_node_protocol.RejectTransactionRequest
    ) -> OutboundMessageGenerator:
        """
        The peer rejects the request for a transaction.
        """
        self.log.warning(f"Rejected request for transaction {reject}")
        for _ in []:
            yield _

    @api_request
    async def new_proof_of_time(self, new_proof_of_time: full_node_protocol.NewProofOfTime) -> OutboundMessageGenerator:
        if new_proof_of_time.witness_type == 0:
            # A honest sanitizer will always sanitize until the LCA block.
            if new_proof_of_time.height >= self.blockchain.lca_block.height:
                return
            # If we already have the compact PoT in a connected to header block, return
            blocks: List[FullBlock] = await self.block_store.get_blocks_at([new_proof_of_time.height])
            if new_proof_of_time.height not in self.blockchain.height_to_hash:
                self.log.error(f"Height {new_proof_of_time.height} not found in height_to_hash.")
                return
            header_hash = self.blockchain.height_to_hash[new_proof_of_time.height]
            for block in blocks:
                assert block.proof_of_time is not None
                if block.proof_of_time.witness_type == 0 and block.header_hash == header_hash:
                    return
        else:
            # If we don't have an unfinished block for this PoT, we don't care about it
            if (
                await self.full_node_store.get_unfinished_block(
                    (
                        new_proof_of_time.challenge_hash,
                        new_proof_of_time.number_of_iterations,
                    )
                )
            ) is None:
                return

            # If we already have the PoT in a finished block, return
            blocks = await self.block_store.get_blocks_at([new_proof_of_time.height])
            for block in blocks:
                if (
                    block.proof_of_time is not None
                    and block.proof_of_time.challenge_hash == new_proof_of_time.challenge_hash
                    and block.proof_of_time.number_of_iterations == new_proof_of_time.number_of_iterations
                ):
                    return

            self.full_node_store.add_proof_of_time_heights(
                (
                    new_proof_of_time.challenge_hash,
                    new_proof_of_time.number_of_iterations,
                ),
                new_proof_of_time.height,
            )

        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message(
                "request_proof_of_time",
                full_node_protocol.RequestProofOfTime(
                    new_proof_of_time.height,
                    new_proof_of_time.challenge_hash,
                    new_proof_of_time.number_of_iterations,
                    new_proof_of_time.witness_type,
                ),
            ),
            Delivery.RESPOND,
        )

    @api_request
    async def request_proof_of_time(
        self, request_proof_of_time: full_node_protocol.RequestProofOfTime
    ) -> OutboundMessageGenerator:
        blocks: List[FullBlock] = await self.block_store.get_blocks_at([request_proof_of_time.height])
        for block in blocks:
            if (
                block.proof_of_time is not None
                and block.proof_of_time.challenge_hash == request_proof_of_time.challenge_hash
                and block.proof_of_time.number_of_iterations == request_proof_of_time.number_of_iterations
                and block.proof_of_time.witness_type == request_proof_of_time.witness_type
            ):
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message(
                        "respond_proof_of_time",
                        full_node_protocol.RespondProofOfTime(block.proof_of_time),
                    ),
                    Delivery.RESPOND,
                )
                return
        reject = Message(
            "reject_proof_of_time_request",
            full_node_protocol.RejectProofOfTimeRequest(
                request_proof_of_time.challenge_hash,
                request_proof_of_time.number_of_iterations,
            ),
        )
        yield OutboundMessage(NodeType.FULL_NODE, reject, Delivery.RESPOND)

    @api_request
    async def respond_proof_of_time(
        self, respond_proof_of_time: full_node_protocol.RespondProofOfTime
    ) -> OutboundMessageGenerator:
        """
        A proof of time, received by a peer full node. If we have the rest of the block,
        we can complete it. Otherwise, we just verify and propagate the proof.
        """
        processed = False
        if respond_proof_of_time.proof.witness_type == 0:
            request = timelord_protocol.ProofOfTimeFinished(respond_proof_of_time.proof)

            async for msg in self.proof_of_time_finished(request):
                yield msg
            processed = True

        if (
            await self.full_node_store.get_unfinished_block(
                (
                    respond_proof_of_time.proof.challenge_hash,
                    respond_proof_of_time.proof.number_of_iterations,
                )
            )
        ) is not None:
            height: Optional[uint32] = self.full_node_store.get_proof_of_time_heights(
                (
                    respond_proof_of_time.proof.challenge_hash,
                    respond_proof_of_time.proof.number_of_iterations,
                )
            )
            if height is not None:
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message(
                        "new_proof_of_time",
                        full_node_protocol.NewProofOfTime(
                            height,
                            respond_proof_of_time.proof.challenge_hash,
                            respond_proof_of_time.proof.number_of_iterations,
                            respond_proof_of_time.proof.witness_type,
                        ),
                    ),
                    Delivery.BROADCAST_TO_OTHERS,
                )
            if not processed:
                request = timelord_protocol.ProofOfTimeFinished(respond_proof_of_time.proof)
                async for msg in self.proof_of_time_finished(request):
                    yield msg

    @api_request
    async def reject_proof_of_time_request(
        self, reject: full_node_protocol.RejectProofOfTimeRequest
    ) -> OutboundMessageGenerator:
        self.log.warning(f"Rejected PoT Request {reject}")
        for _ in []:
            yield _

    async def _respond_compact_proof_of_time(
        self,
        proof: ProofOfTime,
    ) -> OutboundMessageGenerator:
        """
        A proof of time, received by a peer full node. If we have the rest of the block,
        we can complete it. Otherwise, we just verify and propagate the proof.
        """
        height: Optional[uint32] = self.block_store.get_height_proof_of_time(
            proof.challenge_hash,
            proof.number_of_iterations,
        )
        if height is None:
            self.log.info("No block for compact proof of time.")
            return
        if not proof.is_valid(self.constants.DISCRIMINANT_SIZE_BITS):
            self.log.error("Invalid compact proof of time.")
            return

        blocks: List[FullBlock] = await self.block_store.get_blocks_at([height])
        for block in blocks:
            assert block.proof_of_time is not None
            if (
                block.proof_of_time.witness_type != 0
                and block.proof_of_time.challenge_hash == proof.challenge_hash
                and block.proof_of_time.number_of_iterations == proof.number_of_iterations
            ):
                block_new = FullBlock(
                    block.proof_of_space,
                    proof,
                    block.header,
                    block.transactions_generator,
                    block.transactions_filter,
                )
                if self.block_store.seen_compact_proof(
                    proof.challenge_hash,
                    proof.number_of_iterations,
                ):
                    return
                await self.block_store.add_block(block_new)
                self.log.info(f"Stored compact block at height {block.height}.")
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message(
                        "new_proof_of_time",
                        full_node_protocol.NewProofOfTime(
                            height,
                            proof.challenge_hash,
                            proof.number_of_iterations,
                            proof.witness_type,
                        ),
                    ),
                    Delivery.BROADCAST_TO_OTHERS,
                )

    # Periodically scans for blocks with non compact proof of time
    # (witness_type != 0) and sends them to the connected timelords.
    async def broadcast_uncompact_blocks(self, uncompact_interval, delivery: Delivery = Delivery.BROADCAST):
        min_height = 1
        while not self._shut_down:
            while self.sync_store.get_sync_mode():
                if self._shut_down:
                    return
                await asyncio.sleep(30)

            broadcast_list: List = []
            new_min_height = None
            max_height = self.blockchain.lca_block.height
            uncompact_blocks = 0
            self.log.info("Scanning the blockchain for uncompact blocks.")

            for h in range(min_height, max_height):
                if self._shut_down:
                    return
                blocks: List[FullBlock] = await self.block_store.get_blocks_at([uint32(h)])
                header_hash = self.blockchain.height_to_hash[uint32(h)]
                for block in blocks:
                    assert block.proof_of_time is not None
                    if block.header_hash != header_hash:
                        continue

                    if block.proof_of_time.witness_type != 0:
                        challenge_msg = timelord_protocol.ChallengeStart(
                            block.proof_of_time.challenge_hash,
                            block.weight,
                        )
                        pos_info_msg = timelord_protocol.ProofOfSpaceInfo(
                            block.proof_of_time.challenge_hash,
                            block.proof_of_time.number_of_iterations,
                        )
                        broadcast_list.append(
                            (
                                challenge_msg,
                                pos_info_msg,
                            )
                        )
                        # Scan only since the first uncompact block we know about.
                        # No block earlier than this will be uncompact in the future,
                        # unless a reorg happens. The range to scan next time
                        # is always at least 200 blocks, to protect against reorgs.
                        if uncompact_blocks == 0 and h <= max(1, max_height - 200):
                            new_min_height = h
                        uncompact_blocks += 1

            if new_min_height is None:
                # Every block is compact, but we still keep at least 200 blocks to iterate.
                new_min_height = max(1, max_height - 200)
            min_height = new_min_height

            self.log.info(f"Collected {uncompact_blocks} uncompact blocks.")
            if len(broadcast_list) > 50:
                random.shuffle(broadcast_list)
                broadcast_list = broadcast_list[:50]
            if self.sync_store.get_sync_mode():
                continue
            if self.server is not None:
                for challenge_msg, pos_info_msg in broadcast_list:
                    self.server.push_message(
                        OutboundMessage(
                            NodeType.TIMELORD,
                            Message("challenge_start", challenge_msg),
                            delivery,
                        )
                    )
                    self.server.push_message(
                        OutboundMessage(
                            NodeType.TIMELORD,
                            Message("proof_of_space_info", pos_info_msg),
                            delivery,
                        )
                    )
            self.log.info(f"Broadcasted {len(broadcast_list)} uncompact blocks to timelords.")
            await asyncio.sleep(uncompact_interval)

    @api_request
    async def new_unfinished_block(
        self, new_unfinished_block: full_node_protocol.NewUnfinishedBlock
    ) -> OutboundMessageGenerator:
        if self.blockchain.contains_block(new_unfinished_block.new_header_hash):
            return
        if not self.blockchain.contains_block(new_unfinished_block.previous_header_hash):
            return
        prev_block: Optional[FullBlock] = await self.block_store.get_block(new_unfinished_block.previous_header_hash)
        if prev_block is not None:
            challenge = self.blockchain.get_challenge(prev_block)
            if challenge is not None:
                if (
                    await (
                        self.full_node_store.get_unfinished_block(
                            (
                                challenge.get_hash(),
                                new_unfinished_block.number_of_iterations,
                            )
                        )
                    )
                    is not None
                ):
                    return
            assert challenge is not None
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message(
                    "request_unfinished_block",
                    full_node_protocol.RequestUnfinishedBlock(new_unfinished_block.new_header_hash),
                ),
                Delivery.RESPOND,
            )

    @api_request
    async def request_unfinished_block(
        self, request_unfinished_block: full_node_protocol.RequestUnfinishedBlock
    ) -> OutboundMessageGenerator:
        for _, block in (await self.full_node_store.get_unfinished_blocks()).items():
            if block.header_hash == request_unfinished_block.header_hash:
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message(
                        "respond_unfinished_block",
                        full_node_protocol.RespondUnfinishedBlock(block),
                    ),
                    Delivery.RESPOND,
                )
                return
        fetched: Optional[FullBlock] = await self.block_store.get_block(request_unfinished_block.header_hash)
        if fetched is not None:
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message(
                    "respond_unfinished_block",
                    full_node_protocol.RespondUnfinishedBlock(fetched),
                ),
                Delivery.RESPOND,
            )
            return

        reject = Message(
            "reject_unfinished_block_request",
            full_node_protocol.RejectUnfinishedBlockRequest(request_unfinished_block.header_hash),
        )
        yield OutboundMessage(NodeType.FULL_NODE, reject, Delivery.RESPOND)

    @api_request
    async def respond_unfinished_block(
        self, respond_unfinished_block: full_node_protocol.RespondUnfinishedBlock
    ) -> OutboundMessageGenerator:
        """
        We have received an unfinished block, either created by us, or from another peer.
        We can validate it and if it's a good block, propagate it to other peers and
        timelords.
        """
        block = respond_unfinished_block.block
        # Adds the unfinished block to seen, and check if it's seen before, to prevent
        # processing it twice
        if self.full_node_store.seen_unfinished_block(block.header_hash):
            return

        if not self.blockchain.is_child_of_head(block):
            return

        prev_full_block: Optional[FullBlock] = await self.block_store.get_block(block.prev_header_hash)

        assert prev_full_block is not None
        async with self.blockchain.lock:
            (
                error_code,
                iterations_needed,
            ) = await self.blockchain.validate_unfinished_block(block, prev_full_block)

        if error_code is not None:
            raise ConsensusError(error_code)
        assert iterations_needed is not None

        challenge = self.blockchain.get_challenge(prev_full_block)
        assert challenge is not None
        challenge_hash = challenge.get_hash()

        if await (self.full_node_store.get_unfinished_block((challenge_hash, iterations_needed))) is not None:
            return

        expected_time: uint64 = uint64(int(iterations_needed / (self.full_node_store.get_proof_of_time_estimate_ips())))

        if expected_time > self.constants.PROPAGATION_DELAY_THRESHOLD:
            self.log.info(f"Block is slow, expected {expected_time} seconds, waiting")
            # If this block is slow, sleep to allow faster blocks to come out first
            await asyncio.sleep(5)

        leader: Tuple[uint32, uint64] = self.full_node_store.get_unfinished_block_leader()
        if leader is None or block.height > leader[0]:
            self.log.info(f"This is the first unfinished block at height {block.height}, so propagate.")
            # If this is the first block we see at this height, propagate
            self.full_node_store.set_unfinished_block_leader((block.height, expected_time))
        elif block.height == leader[0]:
            if expected_time > leader[1] + self.constants.PROPAGATION_THRESHOLD:
                # If VDF is expected to finish X seconds later than the best, don't propagate
                self.log.info(f"VDF will finish too late {expected_time} seconds, so don't propagate")
                return
            elif expected_time < leader[1]:
                self.log.info(f"New best unfinished block at height {block.height}")
                # If this will be the first block to finalize, update our leader
                self.full_node_store.set_unfinished_block_leader((leader[0], expected_time))
        else:
            # If we have seen an unfinished block at a greater or equal height, don't propagate
            self.log.info("Unfinished block at old height, so don't propagate")
            return

        await self.full_node_store.add_unfinished_block((challenge_hash, iterations_needed), block)

        timelord_request = timelord_protocol.ProofOfSpaceInfo(challenge_hash, iterations_needed)

        yield OutboundMessage(
            NodeType.TIMELORD,
            Message("proof_of_space_info", timelord_request),
            Delivery.BROADCAST,
        )
        new_unfinished_block = full_node_protocol.NewUnfinishedBlock(
            block.prev_header_hash, iterations_needed, block.header_hash
        )
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("new_unfinished_block", new_unfinished_block),
            Delivery.BROADCAST_TO_OTHERS,
        )
        self._state_changed("block")

    @api_request
    async def reject_unfinished_block_request(
        self, reject: full_node_protocol.RejectUnfinishedBlockRequest
    ) -> OutboundMessageGenerator:
        self.log.warning(f"Rejected unfinished block request {reject}")
        for _ in []:
            yield _

    @api_request
    async def request_all_header_hashes(
        self, request: full_node_protocol.RequestAllHeaderHashes
    ) -> OutboundMessageGenerator:
        try:
            header_hashes = self.blockchain.get_header_hashes(request.tip_header_hash)
            message = Message("all_header_hashes", full_node_protocol.AllHeaderHashes(header_hashes))
            yield OutboundMessage(NodeType.FULL_NODE, message, Delivery.RESPOND)
        except ValueError:
            self.log.info("Do not have requested header hashes.")

    @api_request
    async def all_header_hashes(
        self, all_header_hashes: full_node_protocol.AllHeaderHashes
    ) -> OutboundMessageGenerator:
        assert len(all_header_hashes.header_hashes) > 0
        self.sync_store.set_potential_hashes(all_header_hashes.header_hashes)
        phr = self.sync_store.get_potential_hashes_received()
        assert phr is not None
        phr.set()
        for _ in []:  # Yields nothing
            yield _

    @api_request
    async def request_header_block(self, request: full_node_protocol.RequestHeaderBlock) -> OutboundMessageGenerator:
        """
        A peer requests a list of header blocks, by height. Used for syncing or light clients.
        """
        full_block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
        if full_block is not None:
            header_block: Optional[HeaderBlock] = full_block.get_header_block()
            if header_block is not None and header_block.height == request.height:
                response = full_node_protocol.RespondHeaderBlock(header_block)
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message("respond_header_block", response),
                    Delivery.RESPOND,
                )
                return
        reject = full_node_protocol.RejectHeaderBlockRequest(request.height, request.header_hash)
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("reject_header_block_request", reject),
            Delivery.RESPOND,
        )

    @api_request
    async def respond_header_block(self, request: full_node_protocol.RespondHeaderBlock) -> OutboundMessageGenerator:
        """
        Receive header blocks from a peer.
        """
        self.log.info(f"Received header block {request.header_block.height}.")
        if self.sync_peers_handler is not None:
            async for req in self.sync_peers_handler.new_block(request.header_block):
                yield req

    @api_request
    async def reject_header_block_request(
        self, request: full_node_protocol.RejectHeaderBlockRequest
    ) -> OutboundMessageGenerator:
        self.log.warning(f"Reject header block request, {request}")
        if self.sync_store.get_sync_mode():
            yield OutboundMessage(NodeType.FULL_NODE, Message("", None), Delivery.CLOSE)

    # FARMER PROTOCOL
    @api_request
    async def declare_proof_of_space(self, request: farmer_protocol.DeclareProofOfSpace) -> OutboundMessageGenerator:
        """
        Creates a block body and header, with the proof of space, coinbase, and fee targets provided
        by the farmer, and sends the hash of the header data back to the farmer.
        """
        plot_id: bytes32 = request.proof_of_space.get_plot_id()

        # Checks that the proof of space is valid
        quality_string: bytes = Verifier().validate_proof(
            plot_id,
            request.proof_of_space.size,
            request.challenge_hash,
            bytes(request.proof_of_space.proof),
        )
        assert len(quality_string) == 32

        # Grab best transactions from Mempool for given tip target
        async with self.blockchain.lock:
            peak: Optional[SubBlockRecord] = self.blockchain.get_peak()
            if peak is None:
                spend_bundle: Optional[SpendBundle] = None
            else:
                spend_bundle: Optional[SpendBundle] = await self.mempool_manager.create_bundle_from_mempool(
                    peak.header_hash
                )
        # TODO(mariano): make block
        foliage_sub_block_hash = bytes32(bytes([0] * 32))
        foliage_block_hash = bytes32(bytes([0] * 32))
        message = farmer_protocol.RequestSignedValues(
            quality_string,
            foliage_sub_block_hash,
            foliage_block_hash,
        )
        yield OutboundMessage(NodeType.FARMER, Message("request_signed_values", message), Delivery.RESPOND)

    @api_request
    async def signed_values(self, farmer_request: farmer_protocol.SignedValues) -> OutboundMessageGenerator:
        """
        Signature of header hash, by the harvester. This is enough to create an unfinished
        block, which only needs a Proof of Time to be finished. If the signature is valid,
        we call the unfinished_block routine.
        """
        candidate: Optional[UnfinishedBlock] = self.full_node_store.get_candidate_block(farmer_request.quality_string)
        if candidate is None:
            self.log.warning(f"Quality string {farmer_request.quality_string} not found in database")
            return

        fsb2 = dataclasses.replace(
            candidate.foliage_sub_block, foliage_sub_block_signature=farmer_request.foliage_sub_block_signature
        )
        fsb3 = dataclasses.replace(fsb2, foliage_block_signature=farmer_request.foliage_block_signature)
        new_candidate = dataclasses.replace(candidate, foliage_sub_block=fsb3)

        # Propagate to ourselves (which validates and does further propagations)
        request = full_node_protocol.RespondUnfinishedBlock(new_candidate)

        async for m in self.respond_unfinished_block(request):
            # Yield all new messages (propagation to peers)
            yield m

    # TIMELORD PROTOCOL
    @api_request
    async def proof_of_time_finished(self, request: timelord_protocol.ProofOfTimeFinished) -> OutboundMessageGenerator:
        """
        A proof of time, received by a peer timelord. We can use this to complete a block,
        and call the block routine (which handles propagation and verification of blocks).
        """
        if request.proof.witness_type == 0:
            async for msg in self._respond_compact_proof_of_time(request.proof):
                yield msg

        dict_key = (
            request.proof.challenge_hash,
            request.proof.number_of_iterations,
        )

        unfinished_block_obj: Optional[FullBlock] = await self.full_node_store.get_unfinished_block(dict_key)
        if not unfinished_block_obj:
            if request.proof.witness_type > 0:
                self.log.warning(f"Received a proof of time that we cannot use to complete a block {dict_key}")
            return

        new_full_block: FullBlock = FullBlock(
            unfinished_block_obj.proof_of_space,
            request.proof,
            unfinished_block_obj.header,
            unfinished_block_obj.transactions_generator,
            unfinished_block_obj.transactions_filter,
        )

        if self.sync_store.get_sync_mode():
            self.sync_store.add_potential_future_block(new_full_block)
        else:
            async for msg in self.respond_block(full_node_protocol.RespondBlock(new_full_block)):
                yield msg

    @api_request
    async def request_block(self, request_block: full_node_protocol.RequestBlock) -> OutboundMessageGenerator:
        block: Optional[FullBlock] = await self.block_store.get_block(request_block.header_hash)
        if block is not None:
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("respond_block", full_node_protocol.RespondBlock(block)),
                Delivery.RESPOND,
            )
            return
        reject = Message(
            "reject_block_request",
            full_node_protocol.RejectBlockRequest(request_block.height, request_block.header_hash),
        )
        yield OutboundMessage(NodeType.FULL_NODE, reject, Delivery.RESPOND)

    @api_request
    async def respond_block(self, respond_block: full_node_protocol.RespondBlock) -> OutboundMessageGenerator:
        """
        Receive a full block from a peer full node (or ourselves).
        """
        if self.sync_store.get_sync_mode():
            # This is a tip sent to us by another peer
            if self.sync_store.get_waiting_for_tips():
                # Add the block to our potential tips list
                self.sync_store.add_potential_tip(respond_block.block)
                return

            # This is a block we asked for during sync
            if self.sync_peers_handler is not None:
                async for req in self.sync_peers_handler.new_block(respond_block.block):
                    yield req
            return

        # Adds the block to seen, and check if it's seen before (which means header is in memory)
        header_hash = respond_block.block.header.get_hash()
        if self.blockchain.contains_block(header_hash):
            return

        prev_lca = self.blockchain.lca_block

        async with self.blockchain.lock:
            # Tries to add the block to the blockchain
            added, error_code = await self.blockchain.receive_block(respond_block.block, False, None, sync_mode=False)
            if added == ReceiveBlockResult.NEW_TIP:
                await self.mempool_manager.new_tips(await self.blockchain.get_full_tips())

        if added == ReceiveBlockResult.ALREADY_HAVE_BLOCK:
            return
        elif added == ReceiveBlockResult.INVALID_BLOCK:
            self.log.error(
                f"Block {header_hash} at height {respond_block.block.height} is invalid with code {error_code}."
            )
            assert error_code is not None
            raise ConsensusError(error_code, header_hash)

        elif added == ReceiveBlockResult.DISCONNECTED_BLOCK:
            self.log.info(f"Disconnected block {header_hash} at height {respond_block.block.height}")
            tip_height = min([head.height for head in self.blockchain.get_current_tips()])

            if respond_block.block.height > tip_height + self.config["sync_blocks_behind_threshold"]:
                async with self.blockchain.lock:
                    if self.sync_store.get_sync_mode():
                        return
                    await self.sync_store.clear_sync_info()
                    self.sync_store.add_potential_tip(respond_block.block)
                    self.sync_store.set_sync_mode(True)
                self.log.info(
                    f"We are too far behind this block. Our height is {tip_height} and block is at "
                    f"{respond_block.block.height}"
                )
                try:
                    # Performs sync, and catch exceptions so we don't close the connection
                    async for ret_msg in self._sync():
                        yield ret_msg
                except asyncio.CancelledError:
                    self.log.error("Syncing failed, CancelledError")
                except Exception as e:
                    tb = traceback.format_exc()
                    self.log.error(f"Error with syncing: {type(e)}{tb}")
                finally:
                    async for ret_msg in self._finish_sync():
                        yield ret_msg

            elif respond_block.block.height >= tip_height - 3:
                self.log.info(
                    f"We have received a disconnected block at height {respond_block.block.height}, "
                    f"current tip is {tip_height}"
                )
                msg = Message(
                    "request_block",
                    full_node_protocol.RequestBlock(
                        uint32(respond_block.block.height - 1),
                        respond_block.block.prev_header_hash,
                    ),
                )
                self.full_node_store.add_disconnected_block(respond_block.block)
                yield OutboundMessage(NodeType.FULL_NODE, msg, Delivery.RESPOND)
            return
        elif added == ReceiveBlockResult.NEW_TIP:
            # Only propagate blocks which extend the blockchain (becomes one of the heads)
            self.log.info(f"Updated heads, new heights: {[b.height for b in self.blockchain.get_current_tips()]}")

            difficulty = self.blockchain.get_next_difficulty(
                self.blockchain.headers[respond_block.block.prev_header_hash]
            )
            next_vdf_min_iters = self.blockchain.get_next_min_iters(respond_block.block)
            next_vdf_ips = uint64(
                next_vdf_min_iters * self.constants.MIN_ITERS_PROPORTION // self.constants.BLOCK_TIME_TARGET
            )
            self.log.info(f"Difficulty {difficulty} IPS {next_vdf_ips}")
            if next_vdf_ips != self.full_node_store.get_proof_of_time_estimate_ips():
                self.full_node_store.set_proof_of_time_estimate_ips(next_vdf_ips)
                rate_update = farmer_protocol.ProofOfTimeRate(next_vdf_ips)
                self.log.info(f"Sending proof of time rate {next_vdf_ips}")
                yield OutboundMessage(
                    NodeType.FARMER,
                    Message("proof_of_time_rate", rate_update),
                    Delivery.BROADCAST,
                )
                # Occasionally clear the seen list to keep it small
                await self.full_node_store.clear_seen_unfinished_blocks()

            challenge: Optional[Challenge] = self.blockchain.get_challenge(respond_block.block)
            assert challenge is not None
            challenge_hash: bytes32 = challenge.get_hash()
            farmer_request = farmer_protocol.ProofOfSpaceFinalized(
                challenge_hash,
                respond_block.block.height,
                respond_block.block.weight,
                difficulty,
            )
            timelord_request = timelord_protocol.ChallengeStart(
                challenge_hash,
                respond_block.block.weight,
            )
            # Tell timelord to stop previous challenge and start with new one
            yield OutboundMessage(
                NodeType.TIMELORD,
                Message("challenge_start", timelord_request),
                Delivery.BROADCAST,
            )
            # Tell peers about the new tip
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message(
                    "new_tip",
                    full_node_protocol.NewTip(
                        respond_block.block.height,
                        respond_block.block.weight,
                        respond_block.block.header_hash,
                    ),
                ),
                Delivery.BROADCAST_TO_OTHERS,
            )

            # Tell peer wallets about the new LCA, if it changed
            new_lca = self.blockchain.lca_block
            if new_lca != prev_lca:
                new_lca_req = wallet_protocol.NewLCA(
                    new_lca.header_hash,
                    new_lca.height,
                    new_lca.weight,
                )
                yield OutboundMessage(NodeType.WALLET, Message("new_lca", new_lca_req), Delivery.BROADCAST)

            # Tell farmer about the new block
            yield OutboundMessage(
                NodeType.FARMER,
                Message("proof_of_space_finalized", farmer_request),
                Delivery.BROADCAST,
            )

        elif added == ReceiveBlockResult.ADDED_AS_ORPHAN:
            self.log.info(f"Received orphan block of height {respond_block.block.height}")
        else:
            # Should never reach here, all the cases are covered
            raise RuntimeError(f"Invalid result from receive_block {added}")

        # This code path is reached if added == ADDED_AS_ORPHAN or NEW_TIP
        next_block: Optional[FullBlock] = self.full_node_store.get_disconnected_block_by_prev(
            respond_block.block.header_hash
        )

        # Recursively process the next block if we have it
        if next_block is not None:
            async for ret_msg in self.respond_block(full_node_protocol.RespondBlock(next_block)):
                yield ret_msg

        # Removes all temporary data for old blocks
        lowest_tip = min(tip.height for tip in self.blockchain.get_current_tips())
        clear_height = uint32(max(0, lowest_tip - 30))
        self.full_node_store.clear_candidate_blocks_below(clear_height)
        self.full_node_store.clear_disconnected_blocks_below(clear_height)
        await self.full_node_store.clear_unfinished_blocks_below(clear_height)
        self._state_changed("block")

    @api_request
    async def reject_block_request(self, reject: full_node_protocol.RejectBlockRequest) -> OutboundMessageGenerator:
        self.log.warning(f"Rejected block request {reject}")
        if self.sync_store.get_sync_mode():
            yield OutboundMessage(NodeType.FULL_NODE, Message("", None), Delivery.CLOSE)
        for _ in []:
            yield _

    @api_request
    async def request_mempool_transactions(
        self, request: full_node_protocol.RequestMempoolTransactions
    ) -> OutboundMessageGenerator:
        received_filter = PyBIP158(bytearray(request.filter))

        items: List[MempoolItem] = await self.mempool_manager.get_items_not_in_filter(received_filter)

        for item in items:
            transaction = full_node_protocol.RespondTransaction(item.spend_bundle)
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("respond_transaction", transaction),
                Delivery.RESPOND,
            )

    # WALLET PROTOCOL
    @api_request
    async def send_transaction(self, tx: wallet_protocol.SendTransaction) -> OutboundMessageGenerator:
        # Ignore if syncing
        if self.sync_store.get_sync_mode():
            status = MempoolInclusionStatus.FAILED
            error: Optional[Err] = Err.UNKNOWN
        else:
            async with self.blockchain.lock:
                cost, status, error = await self.mempool_manager.add_spendbundle(tx.transaction)
                if status == MempoolInclusionStatus.SUCCESS:
                    self.log.info(f"Added transaction to mempool: {tx.transaction.name()}")
                    # Only broadcast successful transactions, not pending ones. Otherwise it's a DOS
                    # vector.
                    fees = tx.transaction.fees()
                    assert fees >= 0
                    assert cost is not None
                    new_tx = full_node_protocol.NewTransaction(
                        tx.transaction.name(),
                        cost,
                        uint64(tx.transaction.fees()),
                    )
                    yield OutboundMessage(
                        NodeType.FULL_NODE,
                        Message("new_transaction", new_tx),
                        Delivery.BROADCAST_TO_OTHERS,
                    )
                else:
                    self.log.warning(
                        f"Wasn't able to add transaction with id {tx.transaction.name()}, "
                        f"status {status} error: {error}"
                    )

        error_name = error.name if error is not None else None
        if status == MempoolInclusionStatus.SUCCESS:
            response = wallet_protocol.TransactionAck(tx.transaction.name(), status, error_name)
        else:
            # If if failed/pending, but it previously succeeded (in mempool), this is idempotence, return SUCCESS
            if self.mempool_manager.get_spendbundle(tx.transaction.name()) is not None:
                response = wallet_protocol.TransactionAck(tx.transaction.name(), MempoolInclusionStatus.SUCCESS, None)
            else:
                response = wallet_protocol.TransactionAck(tx.transaction.name(), status, error_name)
        yield OutboundMessage(NodeType.WALLET, Message("transaction_ack", response), Delivery.RESPOND)

    @api_request
    async def request_all_proof_hashes(
        self, request: wallet_protocol.RequestAllProofHashes
    ) -> OutboundMessageGenerator:
        proof_hashes_map = await self.block_store.get_proof_hashes()
        curr = self.blockchain.lca_block

        hashes: List[Tuple[bytes32, Optional[uint64], Optional[uint64]]] = []
        while curr.height > 0:
            difficulty_update: Optional[uint64] = None
            iters_update: Optional[uint64] = None
            if curr.height % self.constants.DIFFICULTY_EPOCH == self.constants.DIFFICULTY_DELAY:
                difficulty_update = self.blockchain.get_next_difficulty(self.blockchain.headers[curr.prev_header_hash])
            if (curr.height + 1) % self.constants.DIFFICULTY_EPOCH == 0:
                iters_update = curr.data.total_iters
            hashes.append((proof_hashes_map[curr.header_hash], difficulty_update, iters_update))
            curr = self.blockchain.headers[curr.prev_header_hash]

        hashes.append(
            (
                proof_hashes_map[self.blockchain.genesis.header_hash],
                uint64(self.blockchain.genesis.weight),
                None,
            )
        )
        response = wallet_protocol.RespondAllProofHashes(list(reversed(hashes)))
        yield OutboundMessage(
            NodeType.WALLET,
            Message("respond_all_proof_hashes", response),
            Delivery.RESPOND,
        )

    @api_request
    async def request_all_header_hashes_after(
        self, request: wallet_protocol.RequestAllHeaderHashesAfter
    ) -> OutboundMessageGenerator:
        header_hash: Optional[bytes32] = self.blockchain.height_to_hash.get(request.starting_height, None)
        if header_hash is None:
            reject = wallet_protocol.RejectAllHeaderHashesAfterRequest(
                request.starting_height, request.previous_challenge_hash
            )
            yield OutboundMessage(
                NodeType.WALLET,
                Message("reject_all_header_hashes_after_request", reject),
                Delivery.RESPOND,
            )
            return
        block: Optional[FullBlock] = await self.block_store.get_block(header_hash)
        header_hash_again: Optional[bytes32] = self.blockchain.height_to_hash.get(request.starting_height, None)

        if (
            block is None
            or block.proof_of_space.challenge_hash != request.previous_challenge_hash
            or header_hash_again != header_hash
        ):
            reject = wallet_protocol.RejectAllHeaderHashesAfterRequest(
                request.starting_height, request.previous_challenge_hash
            )
            yield OutboundMessage(
                NodeType.WALLET,
                Message("reject_all_header_hashes_after_request", reject),
                Delivery.RESPOND,
            )
            return
        header_hashes: List[bytes32] = []
        for height in range(request.starting_height, self.blockchain.lca_block.height + 1):
            header_hashes.append(self.blockchain.height_to_hash[uint32(height)])
        response = wallet_protocol.RespondAllHeaderHashesAfter(
            request.starting_height, request.previous_challenge_hash, header_hashes
        )
        yield OutboundMessage(
            NodeType.WALLET,
            Message("respond_all_header_hashes_after", response),
            Delivery.RESPOND,
        )

    @api_request
    async def request_header(self, request: wallet_protocol.RequestHeader) -> OutboundMessageGenerator:
        full_block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
        if full_block is not None:
            header_block: Optional[HeaderBlock] = full_block.get_header_block()
            if header_block is not None and header_block.height == request.height:
                response = wallet_protocol.RespondHeader(header_block, full_block.transactions_filter)
                yield OutboundMessage(
                    NodeType.WALLET,
                    Message("respond_header", response),
                    Delivery.RESPOND,
                )
                return
        reject = wallet_protocol.RejectHeaderRequest(request.height, request.header_hash)
        yield OutboundMessage(
            NodeType.WALLET,
            Message("reject_header_request", reject),
            Delivery.RESPOND,
        )

    @api_request
    async def request_removals(self, request: wallet_protocol.RequestRemovals) -> OutboundMessageGenerator:
        block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
        if (
            block is None
            or block.height != request.height
            or block.height not in self.blockchain.height_to_hash
            or self.blockchain.height_to_hash[block.height] != block.header_hash
        ):
            reject = wallet_protocol.RejectRemovalsRequest(request.height, request.header_hash)
            yield OutboundMessage(
                NodeType.WALLET,
                Message("reject_removals_request", reject),
                Delivery.RESPOND,
            )
            return

        assert block is not None
        all_removals, _ = await block.tx_removals_and_additions()

        coins_map: List[Tuple[bytes32, Optional[Coin]]] = []
        proofs_map: List[Tuple[bytes32, bytes]] = []

        # If there are no transactions, respond with empty lists
        if block.transactions_generator is None:
            proofs: Optional[List]
            if request.coin_names is None:
                proofs = None
            else:
                proofs = []
            response = wallet_protocol.RespondRemovals(block.height, block.header_hash, [], proofs)
        elif request.coin_names is None or len(request.coin_names) == 0:
            for removal in all_removals:
                cr = await self.coin_store.get_coin_record(removal)
                assert cr is not None
                coins_map.append((cr.coin.name(), cr.coin))
            response = wallet_protocol.RespondRemovals(block.height, block.header_hash, coins_map, None)
        else:
            assert block.transactions_generator
            removal_merkle_set = MerkleSet()
            for coin_name in all_removals:
                removal_merkle_set.add_already_hashed(coin_name)
            assert removal_merkle_set.get_root() == block.header.data.removals_root
            for coin_name in request.coin_names:
                result, proof = removal_merkle_set.is_included_already_hashed(coin_name)
                proofs_map.append((coin_name, proof))
                if coin_name in all_removals:
                    cr = await self.coin_store.get_coin_record(coin_name)
                    assert cr is not None
                    coins_map.append((coin_name, cr.coin))
                    assert result
                else:
                    coins_map.append((coin_name, None))
                    assert not result
            response = wallet_protocol.RespondRemovals(block.height, block.header_hash, coins_map, proofs_map)

        yield OutboundMessage(
            NodeType.WALLET,
            Message("respond_removals", response),
            Delivery.RESPOND,
        )

    @api_request
    async def request_additions(self, request: wallet_protocol.RequestAdditions) -> OutboundMessageGenerator:
        block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
        if (
            block is None
            or block.height != request.height
            or block.height not in self.blockchain.height_to_hash
            or self.blockchain.height_to_hash[block.height] != block.header_hash
        ):
            reject = wallet_protocol.RejectAdditionsRequest(request.height, request.header_hash)
            yield OutboundMessage(
                NodeType.WALLET,
                Message("reject_additions_request", reject),
                Delivery.RESPOND,
            )
            return

        assert block is not None
        _, additions = await block.tx_removals_and_additions()
        puzzlehash_coins_map: Dict[bytes32, List[Coin]] = {}
        for coin in additions + [block.get_coinbase(), block.get_fees_coin()]:
            if coin.puzzle_hash in puzzlehash_coins_map:
                puzzlehash_coins_map[coin.puzzle_hash].append(coin)
            else:
                puzzlehash_coins_map[coin.puzzle_hash] = [coin]

        coins_map: List[Tuple[bytes32, List[Coin]]] = []
        proofs_map: List[Tuple[bytes32, bytes, Optional[bytes]]] = []

        if request.puzzle_hashes is None:
            for puzzle_hash, coins in puzzlehash_coins_map.items():
                coins_map.append((puzzle_hash, coins))
            response = wallet_protocol.RespondAdditions(block.height, block.header_hash, coins_map, None)
        else:
            # Create addition Merkle set
            addition_merkle_set = MerkleSet()
            # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
            for puzzle, coins in puzzlehash_coins_map.items():
                addition_merkle_set.add_already_hashed(puzzle)
                addition_merkle_set.add_already_hashed(hash_coin_list(coins))

            assert addition_merkle_set.get_root() == block.header.data.additions_root
            for puzzle_hash in request.puzzle_hashes:
                result, proof = addition_merkle_set.is_included_already_hashed(puzzle_hash)
                if puzzle_hash in puzzlehash_coins_map:
                    coins_map.append((puzzle_hash, puzzlehash_coins_map[puzzle_hash]))
                    hash_coin_str = hash_coin_list(puzzlehash_coins_map[puzzle_hash])
                    result_2, proof_2 = addition_merkle_set.is_included_already_hashed(hash_coin_str)
                    assert result
                    assert result_2
                    proofs_map.append((puzzle_hash, proof, proof_2))
                else:
                    coins_map.append((puzzle_hash, []))
                    assert not result
                    proofs_map.append((puzzle_hash, proof, None))
            response = wallet_protocol.RespondAdditions(block.height, block.header_hash, coins_map, proofs_map)

        yield OutboundMessage(
            NodeType.WALLET,
            Message("respond_additions", response),
            Delivery.RESPOND,
        )

    @api_request
    async def request_generator(self, request: wallet_protocol.RequestGenerator) -> OutboundMessageGenerator:
        full_block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
        if full_block is not None:
            if full_block.transactions_generator is not None:
                wrapper = GeneratorResponse(
                    full_block.height,
                    full_block.header_hash,
                    full_block.transactions_generator,
                )
                response = wallet_protocol.RespondGenerator(wrapper)
                yield OutboundMessage(
                    NodeType.WALLET,
                    Message("respond_generator", response),
                    Delivery.RESPOND,
                )
                return

        reject = wallet_protocol.RejectGeneratorRequest(request.height, request.header_hash)
        yield OutboundMessage(
            NodeType.WALLET,
            Message("reject_generator_request", reject),
            Delivery.RESPOND,
        )
