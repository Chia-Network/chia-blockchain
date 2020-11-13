import asyncio
import logging
import traceback
import time
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional, Callable, Tuple, List
import aiosqlite
from blspy import G2Element
from chiabip158 import PyBIP158
import dataclasses

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_sp_iters,
    calculate_ip_iters,
    is_overflow_sub_block,
    calculate_iterations_quality,
)
from src.full_node.block_store import BlockStore
from src.full_node.blockchain import Blockchain, ReceiveBlockResult
from src.full_node.coin_store import CoinStore
from src.full_node.deficit import calculate_deficit
from src.full_node.difficulty_adjustment import (
    finishes_sub_epoch,
    get_next_ips,
    get_next_difficulty,
    get_ips_and_difficulty,
)
from src.full_node.full_node_store import FullNodeStore
from src.full_node.make_sub_epoch_summary import make_sub_epoch_summary
from src.full_node.mempool_manager import MempoolManager
from src.full_node.signage_point import SignagePoint
from src.full_node.sub_block_record import SubBlockRecord
from src.full_node.sync_peers_handler import SyncPeersHandler
from src.full_node.sync_store import SyncStore
from src.protocols import (
    introducer_protocol,
    farmer_protocol,
    full_node_protocol,
    timelord_protocol,
    wallet_protocol,
)
from src.server.connection import PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.server.server import ChiaServer
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.types.mempool_item import MempoolItem
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock
from src.util.api_decorators import api_request
from src.full_node.block_creation import create_unfinished_block, unfinished_block_to_full_block
from src.util.errors import ConsensusError
from src.util.ints import uint32, uint64, uint128, uint8
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
        self.full_node_store = await FullNodeStore.create(self.constants)
        self.sync_store = await SyncStore.create()
        self.coin_store = await CoinStore.create(self.connection)
        self.log.info("Initializing blockchain from disk")
        self.blockchain = await Blockchain.create(self.coin_store, self.block_store, self.constants)
        self.mempool_manager = MempoolManager(self.coin_store, self.constants)
        if self.blockchain.get_peak() is None:
            self.log.info("Initialized with empty blockchain")
        else:
            self.log.info(
                f"Blockchain initialized to peak {self.blockchain.get_peak().header_hash} height"
                f" {self.blockchain.get_peak().height}"
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
        async for _ in []:
            yield _
        # TODO(mariano/florin)
        # challenge_requests: List[timelord_protocol.ChallengeStart] = []
        # pos_info_requests: List[timelord_protocol.ProofOfSpaceInfo] = []
        # tips: List[Header] = self.blockchain.get_current_tips()
        # tips_blocks: List[Optional[FullBlock]] = [await self.block_store.get_block(tip.header_hash) for tip in tips]
        # for tip in tips_blocks:
        #     assert tip is not None
        #     challenge = self.blockchain.get_challenge(tip)
        #     assert challenge is not None
        #     challenge_requests.append(timelord_protocol.ChallengeStart(challenge.get_hash(), tip.weight))
        #
        # tip_hashes = [tip.header_hash for tip in tips]
        # tip_infos = [
        #     (tup[0], tup[1])
        #     for tup in list((await self.full_node_store.get_unfinished_blocks()).items())
        #     if tup[1].prev_header_hash in tip_hashes
        # ]
        # for ((chall, iters), _) in tip_infos:
        #     pos_info_requests.append(timelord_protocol.ProofOfSpaceInfo(chall, iters))
        #
        # # Sends our best unfinished block (proof of space) to peer
        # # TODO(mariano) send all unf blocks
        # for ((_, iters), block) in sorted(tip_infos, key=lambda t: t[0][1]):
        #     if block.height < self.full_node_store.get_unfinished_block_leader()[0]:
        #         continue
        #     unfinished_block_msg = full_node_protocol.NewUnfinishedBlock(
        #         block.prev_header_hash, iters, block.header_hash
        #     )
        #     yield OutboundMessage(
        #         NodeType.FULL_NODE,
        #         Message("new_unfinished_block", unfinished_block_msg),
        #         delivery,
        #     )
        #     break
        # for challenge_msg in challenge_requests:
        #     yield OutboundMessage(NodeType.TIMELORD, Message("challenge_start", challenge_msg), delivery)
        # for pos_info_msg in pos_info_requests:
        #     yield OutboundMessage(
        #         NodeType.TIMELORD,
        #         Message("proof_of_space_info", pos_info_msg),
        #         delivery,
        #     )

    async def _on_connect(self) -> OutboundMessageGenerator:
        """
        Whenever we connect to another node / wallet, send them our current heads. Also send heads to farmers
        and challenges to timelords.
        """
        peak_full: FullBlock = await self.blockchain.get_full_peak()
        peak: SubBlockRecord = self.blockchain.sub_blocks[peak_full.header_hash]
        request_node = full_node_protocol.NewPeak(
            peak.header_hash,
            peak.sub_block_height,
            peak.weight,
            peak.sub_block_height,
            peak_full.reward_chain_sub_block.get_unfinished().get_hash(),
        )
        yield OutboundMessage(NodeType.FULL_NODE, Message("new_peak", request_node), Delivery.RESPOND)

        # If connected to a wallet, send the LCA
        request_wallet = wallet_protocol.NewPeak(
            peak.header_hash, peak.sub_block_height, peak.weight, peak.sub_block_height
        )
        yield OutboundMessage(NodeType.WALLET, Message("new_peak", request_wallet), Delivery.RESPOND)

        # Send filter to node and request mempool items that are not in it
        my_filter = self.mempool_manager.get_filter()
        mempool_request = full_node_protocol.RequestMempoolTransactions(my_filter)

        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("request_mempool_transactions", mempool_request),
            Delivery.RESPOND,
        )
        # Update timelord with most recent information
        # TODO(mariano/florin): update

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
        # self.sync_peers_handler = None
        # self.sync_store.set_waiting_for_tips(True)
        # # TODO: better way to tell that we have finished receiving tips
        # # TODO: fix DOS issue. Attacker can request syncing to an invalid blockchain
        # await asyncio.sleep(2)
        # highest_weight: uint128 = uint128(0)
        # tip_block: FullBlock
        # tip_height = 0
        # sync_start_time = time.time()
        #
        # # Based on responses from peers about the current heads, see which head is the heaviest
        # # (similar to longest chain rule).
        # self.sync_store.set_waiting_for_tips(False)
        #
        # potential_tips: List[Tuple[bytes32, FullBlock]] = self.sync_store.get_potential_tips_tuples()
        # self.log.info(f"Have collected {len(potential_tips)} potential tips")
        # if self._shut_down:
        #     return
        #
        # for header_hash, potential_tip_block in potential_tips:
        #     if potential_tip_block.proof_of_time is None:
        #         raise ValueError(f"Invalid tip block {potential_tip_block.header_hash} received")
        #     if potential_tip_block.weight > highest_weight:
        #         highest_weight = potential_tip_block.weight
        #         tip_block = potential_tip_block
        #         tip_height = potential_tip_block.height
        # if highest_weight <= max([t.weight for t in self.blockchain.get_current_tips()]):
        #     self.log.info("Not performing sync, already caught up.")
        #     return
        #
        # assert tip_block
        # self.log.info(f"Tip block {tip_block.header_hash} tip height {tip_block.height}")
        #
        # self.sync_store.set_potential_hashes_received(asyncio.Event())
        #
        # sleep_interval = 10
        # total_time_slept = 0
        #
        # # TODO: verify weight here once we have the correct protocol messages (interative flyclient)
        # while True:
        #     if total_time_slept > 30:
        #         raise TimeoutError("Took too long to fetch header hashes.")
        #     if self._shut_down:
        #         return
        #     # Download all the header hashes and find the fork point
        #     request = full_node_protocol.RequestAllHeaderHashes(tip_block.header_hash)
        #     yield OutboundMessage(
        #         NodeType.FULL_NODE,
        #         Message("request_all_header_hashes", request),
        #         Delivery.RANDOM,
        #     )
        #     try:
        #         phr = self.sync_store.get_potential_hashes_received()
        #         assert phr is not None
        #         await asyncio.wait_for(
        #             phr.wait(),
        #             timeout=sleep_interval,
        #         )
        #         break
        #     # https://github.com/python/cpython/pull/13528
        #     except (concurrent.futures.TimeoutError, asyncio.TimeoutError):
        #         total_time_slept += sleep_interval
        #         self.log.warning("Did not receive desired header hashes")
        #
        # # Finding the fork point allows us to only download headers and blocks from the fork point
        # header_hashes = self.sync_store.get_potential_hashes()
        #
        # async with self.blockchain.lock:
        #     # Lock blockchain so we can copy over the headers without any reorgs
        #     fork_point_height: uint32 = self.blockchain.find_fork_point_alternate_chain(header_hashes)
        #
        # fork_point_hash: bytes32 = header_hashes[fork_point_height]
        # self.log.info(f"Fork point: {fork_point_hash} at height {fork_point_height}")
        #
        # assert self.global_connections is not None
        # peers = [
        #     con.node_id
        #     for con in self.global_connections.get_connections()
        #     if (con.node_id is not None and con.connection_type == NodeType.FULL_NODE)
        # ]
        #
        # self.sync_peers_handler = SyncPeersHandler(self.sync_store, peers, fork_point_height, self.blockchain)
        #
        # # Start processing blocks that we have received (no block yet)
        # block_processor = SyncBlocksProcessor(
        #     self.sync_store,
        #     fork_point_height,
        #     uint32(tip_height),
        #     self.blockchain,
        # )
        # block_processor_task = asyncio.create_task(block_processor.process())
        # lca = self.blockchain.lca_block
        # while not self.sync_peers_handler.done():
        #     # Periodically checks for done, timeouts, shutdowns, new peers or disconnected peers.
        #     if self._shut_down:
        #         block_processor.shut_down()
        #         break
        #     if block_processor_task.done():
        #         break
        #     async for msg in self.sync_peers_handler.monitor_timeouts():
        #         yield msg  # Disconnects from peers that are not responding
        #
        #     cur_peers = [
        #         con.node_id
        #         for con in self.global_connections.get_connections()
        #         if (con.node_id is not None and con.connection_type == NodeType.FULL_NODE)
        #     ]
        #     for node_id in cur_peers:
        #         if node_id not in peers:
        #             self.sync_peers_handler.new_node_connected(node_id)
        #     for node_id in peers:
        #         if node_id not in cur_peers:
        #             # Disconnected peer, removes requests that are being sent to it
        #             self.sync_peers_handler.node_disconnected(node_id)
        #     peers = cur_peers
        #
        #     async for msg in self.sync_peers_handler._add_to_request_sets():
        #         yield msg  # Send more requests if we can
        #
        #     new_lca = self.blockchain.lca_block
        #     if new_lca != lca:
        #         new_lca_req = wallet_protocol.NewLCA(
        #             new_lca.header_hash,
        #             new_lca.height,
        #             new_lca.weight,
        #         )
        #         yield OutboundMessage(NodeType.WALLET, Message("new_lca", new_lca_req), Delivery.BROADCAST)
        #
        #     self._state_changed("sub_block")
        #     await asyncio.sleep(5)
        #
        # # Awaits for all blocks to be processed, a timeout to happen, or the node to shutdown
        # await block_processor_task
        # block_processor_task.result()  # If there was a timeout, this will raise TimeoutError
        # if self._shut_down:
        #     return
        #
        # current_tips = self.blockchain.get_current_tips()
        # assert max([h.height for h in current_tips]) == tip_height
        #
        # self.full_node_store.set_proof_of_time_estimate_ips(
        #     (
        #         self.blockchain.get_next_min_iters(tip_block)
        #         * self.constants.MIN_ITERS_PROPORTION
        #         // self.constants.BLOCK_TIME_TARGET
        #     )
        # )
        #
        # self.log.info(
        #     f"Finished sync up to height {tip_height}. Total time: "
        #     f"{round((time.time() - sync_start_time)/60, 2)} minutes."
        # )

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
            async for msg in self.respond_sub_block(full_node_protocol.RespondSubBlock(block)):
                yield msg

        # Update timelords with most recent information
        async for msg in self._send_challenges_to_timelords():
            yield msg

        peak: SubBlockRecord = self.blockchain.get_peak()
        request_wallet = wallet_protocol.NewPeak(
            peak.header_hash, peak.sub_block_height, peak.weight, peak.sub_block_height
        )
        yield OutboundMessage(NodeType.WALLET, Message("new_peak", request_wallet), Delivery.BROADCAST)
        self._state_changed("sub_block")

    @api_request
    async def new_peak(self, request: full_node_protocol.NewPeak) -> OutboundMessageGenerator:
        """
        A peer notifies us that they have added a new peak to their blockchain. If we don't have it,
        we can ask for it.
        """
        # Check if we have this block in the blockchain
        if self.blockchain.contains_sub_block(request.header_hash):
            return

        # TODO: potential optimization, don't request blocks that we have already sent out
        request_transactions: bool = (
            self.full_node_store.get_unfinished_block(request.unfinished_reward_block_hash) is None
        )
        message = Message(
            "request_sub_block",
            full_node_protocol.RequestSubBlock(request.sub_block_height, request_transactions),
        )
        yield OutboundMessage(NodeType.FULL_NODE, message, Delivery.RESPOND)

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
            request_tx = full_node_protocol.RequestTransaction(transaction.transaction_id)
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("request_transaction", request_tx),
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
                    f"Was not able to add transaction with id {tx.transaction.name()}, {status} error: {error}"
                )
                return

    @api_request
    async def request_proof_of_weight(self, tx: full_node_protocol.RequestProofOfWeight) -> OutboundMessageGenerator:
        # TODO(mariano/almog)
        pass

    @api_request
    async def respond_proof_of_weight(self, tx: full_node_protocol.RespondProofOfWeight) -> OutboundMessageGenerator:
        # TODO(mariano/almog)
        pass

    @api_request
    async def request_sub_block(self, request_block: full_node_protocol.RequestSubBlock) -> OutboundMessageGenerator:
        if request_block.height not in self.blockchain.height_to_hash:
            return
        block: Optional[FullBlock] = await self.block_store.get_full_block(
            self.blockchain.height_to_hash[request_block.height]
        )
        if block is not None:
            if not request_block.include_transaction_block:
                block = dataclasses.replace(block, transactions_generator=None)
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("respond_block", full_node_protocol.RespondSubBlock(block)),
                Delivery.RESPOND,
            )
            return
        return

    @api_request
    async def respond_sub_block(
        self, respond_sub_block: full_node_protocol.RespondSubBlock
    ) -> OutboundMessageGenerator:
        """
        Receive a full block from a peer full node (or ourselves).
        """
        sub_block: FullBlock = respond_sub_block.sub_block
        if self.sync_store.get_sync_mode():
            # This is a tip sent to us by another peer
            if self.sync_store.get_waiting_for_tips():
                # Add the block to our potential tips list
                self.sync_store.add_potential_tip(sub_block)
                return

            # This is a block we asked for during sync
            if self.sync_peers_handler is not None:
                async for req in self.sync_peers_handler.new_block(sub_block):
                    yield req
            return

        # Adds the block to seen, and check if it's seen before (which means header is in memory)
        header_hash = sub_block.header.get_hash()
        if self.blockchain.contains_sub_block(header_hash):
            return

        if sub_block.transactions_generator is None:
            # This is the case where we already had the unfinished block, and asked for this sub-block without
            # the transactions (since we already had them). Therefore, here we add the transactions.
            unfinished_rh: bytes32 = sub_block.reward_chain_sub_block.get_unfinished().get_hash()
            unf_block: Optional[UnfinishedBlock] = self.full_node_store.get_unfinished_block(unfinished_rh)
            if unf_block is not None and unf_block.transactions_generator is not None:
                sub_block = dataclasses.replace(sub_block, transactions_generator=unf_block.transactions_generator)

        async with self.blockchain.lock:
            # Tries to add the block to the blockchain
            added, error_code, fork_height = await self.blockchain.receive_block(sub_block, False)
            if added == ReceiveBlockResult.NEW_PEAK:
                await self.mempool_manager.new_peak(await self.blockchain.get_peak())

        if added == ReceiveBlockResult.ALREADY_HAVE_BLOCK:
            return
        elif added == ReceiveBlockResult.INVALID_BLOCK:
            self.log.error(f"Block {header_hash} at height {sub_block.height} is invalid with code {error_code}.")
            assert error_code is not None
            raise ConsensusError(error_code, header_hash)

        elif added == ReceiveBlockResult.DISCONNECTED_BLOCK:
            self.log.info(f"Disconnected block {header_hash} at height {sub_block.height}")
            peak_height = self.blockchain.get_peak().height

            if sub_block.height > peak_height + self.config["sync_blocks_behind_threshold"]:
                async with self.blockchain.lock:
                    if self.sync_store.get_sync_mode():
                        return
                    await self.sync_store.clear_sync_info()
                    self.sync_store.add_potential_tip(sub_block)
                    # TODO: only set sync mode after verifying weight proof, to prevent dos attack
                    self.sync_store.set_sync_mode(True)
                self.log.info(
                    f"We are too far behind this block. Our height is {peak_height} and block is at "
                    f"{sub_block.height}"
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

            elif sub_block.height >= peak_height - 5:
                # Allows shallow reorgs by simply requesting the previous height repeatedly
                # TODO: replace with fetching multiple blocks at once
                self.log.info(
                    f"We have received a disconnected block at height {sub_block.height}, "
                    f"current peak is {peak_height}"
                )
                msg = Message(
                    "request_block",
                    full_node_protocol.RequestSubBlock(uint32(sub_block.height - 1), True),
                )
                self.full_node_store.add_disconnected_block(sub_block)
                yield OutboundMessage(NodeType.FULL_NODE, msg, Delivery.RESPOND)
            return
        elif added == ReceiveBlockResult.NEW_PEAK:
            # Only propagate blocks which extend the blockchain (becomes one of the heads)
            new_peak: SubBlockRecord = self.blockchain.get_peak()
            self.log.info(f"Updated peak to {new_peak} at height {new_peak.height}, " f"forked at {fork_height}")

            difficulty = self.blockchain.get_next_difficulty(new_peak, False)
            sub_slot_iters = self.blockchain.get_next_slot_iters(new_peak, False)
            self.log.info(f"Difficulty {difficulty} slot iterations {sub_slot_iters}")

            # Find the sub slot of the peak
            curr = sub_block
            while len(curr.finished_sub_slots) == 0:
                curr = await self.blockchain.get_full_block(curr.prev_header_hash)
                assert curr is not None
            peak_sub_slot = curr.finished_sub_slots[-1]
            peak_sub_slot_iters = new_peak.total_iters - calculate_ip_iters(
                self.constants, new_peak.ips, new_peak.required_iters
            )
            is_overflow: bool = is_overflow_sub_block(self.constants, new_peak.ips, new_peak.required_iters)
            if is_overflow:
                # Find the previous sub-slots end of slot
                if len(curr.finished_sub_slots) >= 2:
                    prev_sub_slot = curr.finished_sub_slots[-2]
                else:
                    curr = await self.blockchain.get_full_block(curr.prev_header_hash)
                    while len(curr.finished_sub_slots) == 0:
                        curr = await self.blockchain.get_full_block(curr.prev_header_hash)
                        assert curr is not None
                    prev_sub_slot = curr.finished_sub_slots[-1]

                # If overflow, guaranteed to have the same slot iters for previous slot
                prev_sub_slot_iters = peak_sub_slot_iters - sub_slot_iters
            else:
                prev_sub_slot = None
                prev_sub_slot_iters = None

            added_eos: Optional[EndOfSubSlotBundle] = self.full_node_store.new_peak(
                new_peak,
                peak_sub_slot,
                peak_sub_slot_iters,
                prev_sub_slot,
                prev_sub_slot_iters,
                fork_height != sub_block.height - 1,
                self.blockchain.sub_blocks,
            )
            # If there were pending end of slots that happen after this peak, broadcast them if they are added
            if added_eos is not None:
                broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                    added_eos.challenge_chain.get_hash(),
                    uint8(0),
                    added_eos.reward_chain.end_of_slot_vdf.challenge_hash,
                )
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message("new_signage_point_or_end_of_sub_slot", broadcast),
                    Delivery.BROADCAST,
                )

            if new_peak.height % 1000 == 0:
                # Occasionally clear the seen list to keep it small
                self.full_node_store.clear_seen_unfinished_blocks()

            timelord_new_peak: timelord_protocol.NewPeak = timelord_protocol.NewPeak(
                sub_block.reward_chain_sub_block, difficulty, new_peak.deficit, new_peak.ips, 123123
            )

            # Tell timelord about the new peak
            yield OutboundMessage(
                NodeType.TIMELORD,
                Message("new_peak", timelord_new_peak),
                Delivery.BROADCAST,
            )

            # Tell full nodes about the new peak
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message(
                    "new_peak",
                    full_node_protocol.NewPeak(
                        sub_block.header_hash,
                        sub_block.height,
                        sub_block.weight,
                        fork_height,
                        sub_block.reward_chain_sub_block.get_unfinished().get_hash(),
                    ),
                ),
                Delivery.BROADCAST_TO_OTHERS,
            )
            # Tell wallets about the new peak
            yield OutboundMessage(
                NodeType.WALLET,
                Message(
                    "new_peak",
                    wallet_protocol.NewPeak(
                        sub_block.header_hash,
                        sub_block.height,
                        sub_block.weight,
                        fork_height,
                    ),
                ),
                Delivery.BROADCAST,
            )

        elif added == ReceiveBlockResult.ADDED_AS_ORPHAN:
            self.log.info(f"Received orphan block of height {sub_block.height}")
        else:
            # Should never reach here, all the cases are covered
            raise RuntimeError(f"Invalid result from receive_block {added}")

        # This code path is reached if added == ADDED_AS_ORPHAN or NEW_TIP
        next_block: Optional[FullBlock] = self.full_node_store.get_disconnected_block_by_prev(sub_block.header_hash)

        # TODO: revisit full node store cache to see if other things can be added

        # Recursively process the next block if we have it
        if next_block is not None:
            async for ret_msg in self.respond_sub_block(full_node_protocol.RespondSubBlock(next_block)):
                yield ret_msg

        # Removes all temporary data for old blocks
        clear_height = uint32(max(0, self.blockchain.get_peak().height - 50))
        self.full_node_store.clear_candidate_blocks_below(clear_height)
        self.full_node_store.clear_disconnected_blocks_below(clear_height)
        self.full_node_store.clear_unfinished_blocks_below(clear_height)
        self._state_changed("sub_block")

    @api_request
    async def new_unfinished_sub_block(
        self, new_unfinished_sub_block: full_node_protocol.NewUnfinishedSubBlock
    ) -> OutboundMessageGenerator:
        if self.full_node_store.get_unfinished_block(new_unfinished_sub_block.unfinished_reward_hash) is not None:
            return
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message(
                "request_unfinished_sub_block",
                full_node_protocol.RequestUnfinishedSubBlock(new_unfinished_sub_block.unfinished_reward_hash),
            ),
            Delivery.RESPOND,
        )

    @api_request
    async def request_unfinished_sub_block(
        self, request_unfinished_sub_block: full_node_protocol.RequestUnfinishedSubBlock
    ) -> OutboundMessageGenerator:
        unfinished_block: Optional[UnfinishedBlock] = self.full_node_store.get_unfinished_block(
            request_unfinished_sub_block.unfinished_reward_hash
        )
        if unfinished_block is not None:
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message(
                    "respond_unfinished_block",
                    full_node_protocol.RespondUnfinishedSubBlock(unfinished_block),
                ),
                Delivery.RESPOND,
            )

    @api_request
    async def respond_unfinished_sub_block(
        self, respond_unfinished_sub_block: full_node_protocol.RespondUnfinishedSubBlock
    ) -> OutboundMessageGenerator:
        """
        We have received an unfinished sub-block, either created by us, or from another peer.
        We can validate it and if it's a good block, propagate it to other peers and
        timelords.
        """
        block = respond_unfinished_sub_block.unfinished_sub_block
        # Adds the unfinished block to seen, and check if it's seen before, to prevent
        # processing it twice. This searches for the exact version of the unfinished block (there can be many different
        # foliages for the same trunk). Note that it does not require that this block was successfully processed
        if self.full_node_store.seen_unfinished_block(block.header_hash):
            return

        # This searched for the trunk hash (unfinished reward hash). If we have already added a block with the same
        # hash, return
        if self.full_node_store.get_unfinished_block(block.reward_chain_sub_block.get_hash()) is not None:
            return

        if block.height > 0 and not self.blockchain.contains_sub_block(block.prev_header_hash):
            # No need to request the parent, since the peer will send it to us anyway, via NewPeak
            self.log.info(f"Received a disconnected unfinished block at height {block.height}")
            return

        peak: Optional[SubBlockRecord] = self.blockchain.get_peak()
        if peak is not None:
            peak_sp = calculate_sp_iters(self.constants, peak.ips, peak.required_iters)
            peak_ip_iters = calculate_ip_iters(self.constants, peak.ips, peak.required_iters)
            sp_iters = peak.total_iters - (peak_ip_iters - peak_sp)
            if block.total_iters < sp_iters:
                # This means this unfinished block is pretty far behind, it will not add weight to our chain
                return

        async with self.blockchain.lock:
            # TODO: pre-validate VDFs outside of lock
            error_code: Optional[Err] = await self.blockchain.validate_unfinished_block(
                block
            )
            if error_code is not None:
                raise ConsensusError(error_code)

        assert required_iters is not None

        if (
            await (
                self.full_node_store.get_unfinished_block(
                    (challenge_hash, iterations_needed)
                )
            )
            is not None
        ):
            return

        expected_time: uint64 = uint64(
            int(
                iterations_needed
                / (self.full_node_store.get_proof_of_time_estimate_ips())
            )
        )

        if expected_time > self.constants.PROPAGATION_DELAY_THRESHOLD:
            self.log.info(f"Block is slow, expected {expected_time} seconds, waiting")
            # If this block is slow, sleep to allow faster blocks to come out first
            await asyncio.sleep(5)

        timelord_request = timelord_protocol.NewUnfinishedSubBlock(
            block.reward_chain_sub_block,
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage_sub_block,
            ses,
        )

        yield OutboundMessage(
            NodeType.TIMELORD,
            Message("new_unfinished_sub_block", timelord_request),
            Delivery.BROADCAST,
        )

        full_node_request = full_node_protocol.NewUnfinishedSubBlock(block.reward_chain_sub_block.get_hash())
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("new_unfinished_sub_block", full_node_request),
            Delivery.BROADCAST_TO_OTHERS,
        )
        self._state_changed("sub_block")

    @api_request
    async def new_signage_point_or_end_of_sub_slot(
        self, new_sp: full_node_protocol.NewSignagePointOrEndOfSubSlot
    ) -> OutboundMessageGenerator:
        if (
            self.full_node_store.get_signage_point_by_index(
                new_sp.challenge_hash, new_sp.index_from_challenge, new_sp.last_rc_infusion
            )
            is not None
        ):
            return

        full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
            new_sp.challenge_hash, new_sp.index_from_challenge, new_sp.last_rc_infusion
        )
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("request_signage_point_or_end_of_sub_slot", full_node_request),
            Delivery.RESPOND,
        )

    @api_request
    async def request_signage_point_or_end_of_sub_slot(
        self, request: full_node_protocol.RequestSignagePointOrEndOfSubSlot
    ) -> OutboundMessageGenerator:
        if request.index_from_challenge == 0:
            sub_slot: Optional[Tuple[EndOfSubSlotBundle, int]] = self.full_node_store.get_sub_slot(
                request.challenge_hash
            )
            if sub_slot is not None:
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message("respond_end_of_slot", full_node_protocol.RespondEndOfSubSlot(sub_slot[0])),
                    Delivery.RESPOND,
                )
            else:
                self.log.warning("")
        else:
            sp: Optional[SignagePoint] = self.full_node_store.get_signage_point_by_index(
                request.challenge_hash, request.index_from_challenge, request.last_rc_infusion
            )
            if sp is not None:
                full_node_response = full_node_protocol.RespondSignagePoint(
                    request.index_from_challenge,
                    sp.cc_vdf,
                    sp.cc_proof,
                    sp.rc_vdf,
                    sp.rc_proof,
                )
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message("respond_signage_point", full_node_response),
                    Delivery.RESPOND,
                )

    @api_request
    async def respond_signage_point(self, request: full_node_protocol.RespondSignagePoint) -> OutboundMessageGenerator:
        # TODO
        async for _ in []:
            yield _

    @api_request
    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot
    ) -> OutboundMessageGenerator:

        added = self.full_node_store.new_finished_sub_slot(
            request.end_of_slot_bundle, self.blockchain.sub_blocks, self.blockchain.get_peak()
        )

        if added:
            broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                request.end_of_slot_bundle.challenge_chain.get_hash(),
                uint8(0),
                request.end_of_slot_bundle.reward_chain.end_of_slot_vdf.challenge_hash,
            )
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("new_signage_point_or_end_of_sub_slot", broadcast),
                Delivery.BROADCAST_TO_OTHERS,
            )

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

    # FARMER PROTOCOL
    @api_request
    async def declare_proof_of_space(self, request: farmer_protocol.DeclareProofOfSpace) -> OutboundMessageGenerator:
        """
        Creates a block body and header, with the proof of space, coinbase, and fee targets provided
        by the farmer, and sends the hash of the header data back to the farmer.
        """
        if request.pool_target is None or request.pool_signature is None:
            raise ValueError("Adaptable pool protocol not yet available.")

        # Checks that the proof of space is a response to a recent challenge and valid SP
        pos_sub_slot: Optional[Tuple[EndOfSubSlotBundle, int]] = self.full_node_store.get_sub_slot(
            request.proof_of_space.challenge_hash
        )
        sp_vdfs: Optional[SignagePoint] = self.full_node_store.get_signage_point(request.challenge_chain_sp)

        if sp_vdfs is None or pos_sub_slot is None:
            self.log.warning(f"Received proof of space for an unknown signage point: {request}")
            return

        # Now we know that the proof of space has a signage point either:
        # 1. In the previous sub-slot of the peak (overflow)
        # 2. In the same sub-slot as the peak
        # 3. In a future sub-slot that we already know of

        # Checks that the proof of space is valid
        quality_string: Optional[bytes32] = request.proof_of_space.verify_and_get_quality_string(
            self.constants, request.challenge_chain_sp, request.challenge_chain_sp_signature
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
        if pos_sub_slot[0].challenge_chain.new_difficulty is not None:
            difficulty = pos_sub_slot[0].challenge_chain.new_difficulty
            ips = pos_sub_slot[0].challenge_chain.new_ips
        else:
            if peak.height == 0:
                difficulty = self.constants.DIFFICULTY_STARTING
                ips = self.constants.IPS_STARTING
            else:
                difficulty = uint64(peak.weight - self.blockchain.sub_blocks[peak.prev_hash].weight)
                ips = peak.ips

        required_iters: uint64 = calculate_iterations_quality(
            quality_string,
            request.proof_of_space.size,
            difficulty,
        )
        sp_iters: uint64 = calculate_sp_iters(self.constants, ips, required_iters)
        ip_iters: uint64 = calculate_ip_iters(self.constants, ips, required_iters)
        total_iters_pos_slot: uint128 = pos_sub_slot[2]

        def get_plot_sig(to_sign, _) -> G2Element:
            if to_sign == request.challenge_chain_sp:
                return request.challenge_chain_sp_signature
            if to_sign == request.reward_chain_sp:
                return request.reward_chain_sp_signature
            return G2Element.infinity()

        finished_sub_slots: List[EndOfSubSlotBundle] = self.full_node_store.get_finished_sub_slots(
            peak, self.blockchain.sub_blocks, request.proof_of_space.challenge_hash
        )

        unfinished_block: Optional[UnfinishedBlock] = create_unfinished_block(
            self.constants,
            total_iters_pos_slot,
            sp_iters,
            ip_iters,
            request.proof_of_space,
            pos_sub_slot[0].challenge_chain.get_hash(),
            request.farmer_puzzle_hash,
            request.pool_target,
            get_plot_sig,
            get_plot_sig,
            uint64(int(time.time())),
            b"",
            spend_bundle,
            peak,
            self.blockchain.sub_blocks,
            finished_sub_slots,
            sp_vdfs,
        )
        self.full_node_store.add_candidate_block(quality_string, unfinished_block)

        message = farmer_protocol.RequestSignedValues(
            quality_string,
            unfinished_block.foliage_sub_block.get_hash(),
            unfinished_block.foliage_block.get_hash(),
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
            candidate.foliage_sub_block,
            foliage_sub_block_signature=farmer_request.foliage_sub_block_signature,
        )
        fsb3 = dataclasses.replace(fsb2, foliage_block_signature=farmer_request.foliage_block_signature)
        new_candidate = dataclasses.replace(candidate, foliage_sub_block=fsb3)

        # Propagate to ourselves (which validates and does further propagations)
        request = full_node_protocol.RespondUnfinishedSubBlock(new_candidate)

        async for m in self.respond_unfinished_sub_block(request):
            # Yield all new messages (propagation to peers)
            yield m

    # TIMELORD PROTOCOL
    @api_request
    async def new_infusion_point_vdf(self, request: timelord_protocol.NewInfusionPointVDF) -> OutboundMessageGenerator:
        # Lookup unfinished blocks
        unfinished_block: Optional[UnfinishedBlock] = self.full_node_store.get_unfinished_block(
            request.unfinished_reward_hash
        )

        if unfinished_block is None:
            self.log.warning(
                f"Do not have unfinished reward chain block {request.unfinished_reward_hash}, cannot finish."
            )

        prev_sb: Optional[SubBlockRecord] = None
        if request.reward_chain_ip_vdf.challenge_hash == self.constants.FIRST_RC_CHALLENGE:
            # Genesis
            assert unfinished_block.height == 0
        else:
            # Find the prev block
            curr: Optional[SubBlockRecord] = self.blockchain.get_peak()
            if curr is None:
                self.log.warning(f"Have no blocks in chain, so can not complete block {unfinished_block.height}")
                return
            num_sb_checked = 0
            while num_sb_checked < 10:
                if curr.reward_infusion_new_challenge == request.reward_chain_ip_vdf.challenge_hash:
                    # Found our prev block
                    prev_sb = curr
                    break
                curr = self.blockchain.sub_blocks.get(curr.prev_hash, None)
                if curr is None:
                    return
                num_sb_checked += 1

            # If not found, cache keyed on prev block
            if prev_sb is None:
                self.full_node_store.add_to_future_ip(request)
                return

        ips, difficulty = get_ips_and_difficulty(
            self.constants, unfinished_block, self.blockchain.height_to_hash, prev_sb, self.blockchain.sub_blocks
        )
        q_str: Optional[bytes32] = unfinished_block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
            self.constants,
        )
        assert q_str is not None  # We have previously validated this
        required_iters: uint64 = calculate_iterations_quality(
            q_str,
            unfinished_block.reward_chain_sub_block.proof_of_space.size,
            difficulty,
        )
        overflow = is_overflow_sub_block(self.constants, ips, required_iters)
        if overflow:
            finished_sub_slots = self.full_node_store.get_finished_sub_slots(
                prev_sb,
                self.blockchain.sub_blocks,
                unfinished_block.reward_chain_sub_block.proof_of_space.challenge_hash,
                True,
            )
        else:
            finished_sub_slots = unfinished_block.finished_sub_slots

        block: FullBlock = unfinished_block_to_full_block(
            unfinished_block,
            request.challenge_chain_ip_vdf,
            request.challenge_chain_ip_proof,
            request.reward_chain_ip_vdf,
            request.reward_chain_ip_proof,
            request.infused_challenge_chain_ip_vdf,
            request.infused_challenge_chain_ip_proof,
            finished_sub_slots,
            prev_sb,
            difficulty,
        )

        async for msg in self.respond_sub_block(full_node_protocol.RespondSubBlock(block)):
            yield msg

    @api_request
    async def new_signage_point_vdf(self, request: timelord_protocol.NewSignagePointVDF) -> OutboundMessageGenerator:
        full_node_message = full_node_protocol.RespondSignagePoint(
            request.index_from_challenge,
            request.challenge_chain_sp_vdf,
            request.challenge_chain_sp_proof,
            request.reward_chain_sp_vdf,
            request.reward_chain_sp_proof,
        )
        async for msg in self.respond_signage_point(full_node_message):
            yield msg

    @api_request
    async def new_end_of_sub_slot_vdf(self, request: timelord_protocol.NewEndOfSubSlotVDF) -> OutboundMessageGenerator:
        # Calls our own internal message to handle the end of sub slot, and potentially broadcasts to other peers.
        full_node_message = full_node_protocol.RespondEndOfSubSlot(request.end_of_sub_slot_bundle)
        async for msg in self.respond_end_of_sub_slot(full_node_message):
            yield msg

    # WALLET PROTOCOL
    # @api_request
    # async def send_transaction(self, tx: wallet_protocol.SendTransaction) -> OutboundMessageGenerator:
    #     # Ignore if syncing
    #     if self.sync_store.get_sync_mode():
    #         status = MempoolInclusionStatus.FAILED
    #         error: Optional[Err] = Err.UNKNOWN
    #     else:
    #         async with self.blockchain.lock:
    #             cost, status, error = await self.mempool_manager.add_spendbundle(tx.transaction)
    #             if status == MempoolInclusionStatus.SUCCESS:
    #                 self.log.info(f"Added transaction to mempool: {tx.transaction.name()}")
    #                 # Only broadcast successful transactions, not pending ones. Otherwise it's a DOS
    #                 # vector.
    #                 fees = tx.transaction.fees()
    #                 assert fees >= 0
    #                 assert cost is not None
    #                 new_tx = full_node_protocol.NewTransaction(
    #                     tx.transaction.name(),
    #                     cost,
    #                     uint64(tx.transaction.fees()),
    #                 )
    #                 yield OutboundMessage(
    #                     NodeType.FULL_NODE,
    #                     Message("new_transaction", new_tx),
    #                     Delivery.BROADCAST_TO_OTHERS,
    #                 )
    #             else:
    #                 self.log.warning(
    #                     f"Wasn't able to add transaction with id {tx.transaction.name()}, "
    #                     f"status {status} error: {error}"
    #                 )
    #
    #     error_name = error.name if error is not None else None
    #     if status == MempoolInclusionStatus.SUCCESS:
    #         response = wallet_protocol.TransactionAck(tx.transaction.name(), status, error_name)
    #     else:
    #         # If if failed/pending, but it previously succeeded (in mempool), this is idempotence, return SUCCESS
    #         if self.mempool_manager.get_spendbundle(tx.transaction.name()) is not None:
    #             response = wallet_protocol.TransactionAck(tx.transaction.name(), MempoolInclusionStatus.SUCCESS, None)
    #         else:
    #             response = wallet_protocol.TransactionAck(tx.transaction.name(), status, error_name)
    #     yield OutboundMessage(NodeType.WALLET, Message("transaction_ack", response), Delivery.RESPOND)
    #
    # @api_request
    # async def request_header(self, request: wallet_protocol.RequestHeader) -> OutboundMessageGenerator:
    #     full_block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
    #     if full_block is not None:
    #         header_block: Optional[HeaderBlock] = full_block.get_header_block()
    #         if header_block is not None and header_block.height == request.height:
    #             response = wallet_protocol.RespondHeader(header_block, full_block.transactions_filter)
    #             yield OutboundMessage(
    #                 NodeType.WALLET,
    #                 Message("respond_header", response),
    #                 Delivery.RESPOND,
    #             )
    #             return
    #     reject = wallet_protocol.RejectHeaderRequest(request.height, request.header_hash)
    #     yield OutboundMessage(
    #         NodeType.WALLET,
    #         Message("reject_header_request", reject),
    #         Delivery.RESPOND,
    #     )
    #
    # @api_request
    # async def request_removals(self, request: wallet_protocol.RequestRemovals) -> OutboundMessageGenerator:
    #     block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
    #     if (
    #         block is None
    #         or block.height != request.height
    #         or block.height not in self.blockchain.height_to_hash
    #         or self.blockchain.height_to_hash[block.height] != block.header_hash
    #     ):
    #         reject = wallet_protocol.RejectRemovalsRequest(request.height, request.header_hash)
    #         yield OutboundMessage(
    #             NodeType.WALLET,
    #             Message("reject_removals_request", reject),
    #             Delivery.RESPOND,
    #         )
    #         return
    #
    #     assert block is not None
    #     all_removals, _ = await block.tx_removals_and_additions()
    #
    #     coins_map: List[Tuple[bytes32, Optional[Coin]]] = []
    #     proofs_map: List[Tuple[bytes32, bytes]] = []
    #
    #     # If there are no transactions, respond with empty lists
    #     if block.transactions_generator is None:
    #         proofs: Optional[List]
    #         if request.coin_names is None:
    #             proofs = None
    #         else:
    #             proofs = []
    #         response = wallet_protocol.RespondRemovals(block.height, block.header_hash, [], proofs)
    #     elif request.coin_names is None or len(request.coin_names) == 0:
    #         for removal in all_removals:
    #             cr = await self.coin_store.get_coin_record(removal)
    #             assert cr is not None
    #             coins_map.append((cr.coin.name(), cr.coin))
    #         response = wallet_protocol.RespondRemovals(block.height, block.header_hash, coins_map, None)
    #     else:
    #         assert block.transactions_generator
    #         removal_merkle_set = MerkleSet()
    #         for coin_name in all_removals:
    #             removal_merkle_set.add_already_hashed(coin_name)
    #         assert removal_merkle_set.get_root() == block.header.data.removals_root
    #         for coin_name in request.coin_names:
    #             result, proof = removal_merkle_set.is_included_already_hashed(coin_name)
    #             proofs_map.append((coin_name, proof))
    #             if coin_name in all_removals:
    #                 cr = await self.coin_store.get_coin_record(coin_name)
    #                 assert cr is not None
    #                 coins_map.append((coin_name, cr.coin))
    #                 assert result
    #             else:
    #                 coins_map.append((coin_name, None))
    #                 assert not result
    #         response = wallet_protocol.RespondRemovals(block.height, block.header_hash, coins_map, proofs_map)
    #
    #     yield OutboundMessage(
    #         NodeType.WALLET,
    #         Message("respond_removals", response),
    #         Delivery.RESPOND,
    #     )
    #
    # @api_request
    # async def request_additions(self, request: wallet_protocol.RequestAdditions) -> OutboundMessageGenerator:
    #     block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
    #     if (
    #         block is None
    #         or block.height != request.height
    #         or block.height not in self.blockchain.height_to_hash
    #         or self.blockchain.height_to_hash[block.height] != block.header_hash
    #     ):
    #         reject = wallet_protocol.RejectAdditionsRequest(request.height, request.header_hash)
    #         yield OutboundMessage(
    #             NodeType.WALLET,
    #             Message("reject_additions_request", reject),
    #             Delivery.RESPOND,
    #         )
    #         return
    #
    #     assert block is not None
    #     _, additions = await block.tx_removals_and_additions()
    #     puzzlehash_coins_map: Dict[bytes32, List[Coin]] = {}
    #     for coin in additions + [block.get_coinbase(), block.get_fees_coin()]:
    #         if coin.puzzle_hash in puzzlehash_coins_map:
    #             puzzlehash_coins_map[coin.puzzle_hash].append(coin)
    #         else:
    #             puzzlehash_coins_map[coin.puzzle_hash] = [coin]
    #
    #     coins_map: List[Tuple[bytes32, List[Coin]]] = []
    #     proofs_map: List[Tuple[bytes32, bytes, Optional[bytes]]] = []
    #
    #     if request.puzzle_hashes is None:
    #         for puzzle_hash, coins in puzzlehash_coins_map.items():
    #             coins_map.append((puzzle_hash, coins))
    #         response = wallet_protocol.RespondAdditions(block.height, block.header_hash, coins_map, None)
    #     else:
    #         # Create addition Merkle set
    #         addition_merkle_set = MerkleSet()
    #         # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
    #         for puzzle, coins in puzzlehash_coins_map.items():
    #             addition_merkle_set.add_already_hashed(puzzle)
    #             addition_merkle_set.add_already_hashed(hash_coin_list(coins))
    #
    #         assert addition_merkle_set.get_root() == block.header.data.additions_root
    #         for puzzle_hash in request.puzzle_hashes:
    #             result, proof = addition_merkle_set.is_included_already_hashed(puzzle_hash)
    #             if puzzle_hash in puzzlehash_coins_map:
    #                 coins_map.append((puzzle_hash, puzzlehash_coins_map[puzzle_hash]))
    #                 hash_coin_str = hash_coin_list(puzzlehash_coins_map[puzzle_hash])
    #                 result_2, proof_2 = addition_merkle_set.is_included_already_hashed(hash_coin_str)
    #                 assert result
    #                 assert result_2
    #                 proofs_map.append((puzzle_hash, proof, proof_2))
    #             else:
    #                 coins_map.append((puzzle_hash, []))
    #                 assert not result
    #                 proofs_map.append((puzzle_hash, proof, None))
    #         response = wallet_protocol.RespondAdditions(block.height, block.header_hash, coins_map, proofs_map)
    #
    #     yield OutboundMessage(
    #         NodeType.WALLET,
    #         Message("respond_additions", response),
    #         Delivery.RESPOND,
    #     )
    #
    # @api_request
    # async def request_generator(self, request: wallet_protocol.RequestGenerator) -> OutboundMessageGenerator:
    #     full_block: Optional[FullBlock] = await self.block_store.get_block(request.header_hash)
    #     if full_block is not None:
    #         if full_block.transactions_generator is not None:
    #             wrapper = GeneratorResponse(
    #                 full_block.height,
    #                 full_block.header_hash,
    #                 full_block.transactions_generator,
    #             )
    #             response = wallet_protocol.RespondGenerator(wrapper)
    #             yield OutboundMessage(
    #                 NodeType.WALLET,
    #                 Message("respond_generator", response),
    #                 Delivery.RESPOND,
    #             )
    #             return
    #
    #     reject = wallet_protocol.RejectGeneratorRequest(request.height, request.header_hash)
    #     yield OutboundMessage(
    #         NodeType.WALLET,
    #         Message("reject_generator_request", reject),
    #         Delivery.RESPOND,
    #     )
