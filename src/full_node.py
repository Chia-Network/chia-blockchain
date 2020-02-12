import asyncio
import concurrent
import logging
import time
from asyncio import Event
from secrets import token_bytes
from typing import AsyncGenerator, List, Optional, Tuple, Dict

from chiapos import Verifier

import src.protocols.wallet_protocol
from src.blockchain import Blockchain, ReceiveBlockResult
from src.consensus.block_rewards import calculate_base_fee
from src.consensus.constants import constants
from src.consensus.pot_iterations import calculate_iterations
from src.consensus.weight_verifier import verify_weight
from src.protocols.wallet_protocol import FullProofForHash, ProofHash
from src.store import FullNodeStore
from src.protocols import farmer_protocol, full_node_protocol, timelord_protocol
from src.util.bundle_tools import best_solution_program
from src.mempool_manager import MempoolManager
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.server.server import ChiaServer
from src.types.body import Body
from src.types.challenge import Challenge
from src.types.full_block import FullBlock
from src.types.hashable.Coin import Coin
from src.types.hashable.BLSSignature import BLSSignature
from src.util.Hash import std_hash
from src.types.hashable.SpendBundle import SpendBundle
from src.types.hashable.Program import Program
from src.types.header import Header, HeaderData
from src.types.header_block import HeaderBlock
from src.types.peer_info import PeerInfo
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.coin_store import CoinStore
from src.util import errors
from src.util.api_decorators import api_request
from src.util.errors import BlockNotInBlockchain, InvalidUnfinishedBlock
from src.util.ints import uint32, uint64

OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]


class FullNode:
    def __init__(
        self,
        store: FullNodeStore,
        blockchain: Blockchain,
        config: Dict,
        mempool_manager: MempoolManager,
        unspent_store: CoinStore,
        name: str = None,
    ):
        self.config: Dict = config
        self.store: FullNodeStore = store
        self.blockchain: Blockchain = blockchain
        self.mempool_manager: MempoolManager = mempool_manager
        self._shut_down = False  # Set to true to close all infinite loops
        self.server: Optional[ChiaServer] = None
        self.unspent_store: CoinStore = unspent_store
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

    def _set_server(self, server: ChiaServer):
        self.server = server

    async def _send_tips_to_farmers(
        self, delivery: Delivery = Delivery.BROADCAST
    ) -> OutboundMessageGenerator:
        """
        Sends all of the current heads to all farmer peers. Also sends the latest
        estimated proof of time rate, so farmer can calulate which proofs are good.
        """
        requests: List[farmer_protocol.ProofOfSpaceFinalized] = []
        async with self.store.lock:
            tips: List[Header] = self.blockchain.get_current_tips()
            for tip in tips:
                full_tip: Optional[FullBlock] = await self.store.get_block(
                    tip.header_hash
                )
                assert full_tip is not None
                challenge: Optional[Challenge] = self.blockchain.get_challenge(full_tip)
                assert challenge is not None
                challenge_hash = challenge.get_hash()
                if tip.height > 0:
                    difficulty: uint64 = self.blockchain.get_next_difficulty(
                        tip.prev_header_hash
                    )
                else:
                    difficulty = tip.weight
                requests.append(
                    farmer_protocol.ProofOfSpaceFinalized(
                        challenge_hash, tip.height, tip.weight, difficulty
                    )
                )
            full_block: Optional[FullBlock] = await self.store.get_block(
                tips[0].header_hash
            )
            assert full_block is not None
            proof_of_time_rate: uint64 = self.blockchain.get_next_ips(full_block)
        rate_update = farmer_protocol.ProofOfTimeRate(proof_of_time_rate)
        yield OutboundMessage(
            NodeType.FARMER, Message("proof_of_time_rate", rate_update), delivery
        )
        for request in requests:
            yield OutboundMessage(
                NodeType.FARMER, Message("proof_of_space_finalized", request), delivery
            )

    async def _send_challenges_to_timelords(
        self, delivery: Delivery = Delivery.BROADCAST
    ) -> OutboundMessageGenerator:
        """
        Sends all of the current heads (as well as Pos infos) to all timelord peers.
        """
        challenge_requests: List[timelord_protocol.ChallengeStart] = []
        pos_info_requests: List[timelord_protocol.ProofOfSpaceInfo] = []
        tips: List[Header] = self.blockchain.get_current_tips()
        tips_blocks: List[Optional[FullBlock]] = [
            await self.store.get_block(tip.header_hash) for tip in tips
        ]
        for tip in tips_blocks:
            assert tip is not None
            challenge = self.blockchain.get_challenge(tip)
            assert challenge is not None
            challenge_requests.append(
                timelord_protocol.ChallengeStart(challenge.get_hash(), tip.weight)
            )

        tip_hashes = [tip.header_hash for tip in tips]
        tip_infos = [
            tup[0]
            for tup in list((self.store.get_unfinished_blocks()).items())
            if tup[1].prev_header_hash in tip_hashes
        ]
        for chall, iters in tip_infos:
            pos_info_requests.append(timelord_protocol.ProofOfSpaceInfo(chall, iters))
        for challenge_msg in challenge_requests:
            yield OutboundMessage(
                NodeType.TIMELORD, Message("challenge_start", challenge_msg), delivery
            )
        for pos_info_msg in pos_info_requests:
            yield OutboundMessage(
                NodeType.TIMELORD,
                Message("proof_of_space_info", pos_info_msg),
                delivery,
            )

    async def _on_connect(self) -> OutboundMessageGenerator:
        """
        Whenever we connect to another node, send them our current heads. Also send heads to farmers
        and challenges to timelords.
        """
        blocks: List[FullBlock] = []

        tips: List[Header] = self.blockchain.get_current_tips()
        for t in tips:
            block = await self.store.get_block(t.get_hash())
            assert block
            blocks.append(block)
        for block in blocks:
            request = full_node_protocol.Block(block)
            yield OutboundMessage(
                NodeType.FULL_NODE, Message("block", request), Delivery.RESPOND
            )

        # Update farmers and timelord with most recent information
        async for msg in self._send_challenges_to_timelords(Delivery.RESPOND):
            yield msg
        async for msg in self._send_tips_to_farmers(Delivery.RESPOND):
            yield msg

    def _num_needed_peers(self) -> int:
        assert self.server is not None
        diff = self.config["target_peer_count"] - len(
            self.server.global_connections.get_full_node_connections()
        )
        return diff if diff >= 0 else 0

    def _start_bg_tasks(self):
        """
        Start a background task connecting periodically to the introducer and
        requesting the peer list.
        """
        introducer = self.config["introducer_peer"]
        introducer_peerinfo = PeerInfo(introducer["host"], introducer["port"])

        async def introducer_client():
            async def on_connect() -> OutboundMessageGenerator:
                msg = Message("request_peers", full_node_protocol.RequestPeers())
                yield OutboundMessage(NodeType.INTRODUCER, msg, Delivery.RESPOND)

            while not self._shut_down:
                # The first time connecting to introducer, keep trying to connect
                if self._num_needed_peers():
                    if not await self.server.start_client(
                        introducer_peerinfo, on_connect
                    ):
                        await asyncio.sleep(5)
                        continue
                await asyncio.sleep(self.config["introducer_connect_interval"])

        self.introducer_task = asyncio.create_task(introducer_client())

    def _shutdown(self):
        self._shut_down = True

    async def _sync(self) -> OutboundMessageGenerator:
        """
        Performs a full sync of the blockchain.
            - Check which are the heaviest tips
            - Request headers for the heaviest
            - Verify the weight of the tip, using the headers
            - Find the fork point to see where to start downloading blocks
            - Blacklist peers that provide invalid blocks
            - Sync blockchain up to heads (request blocks in batches)
        """
        self.log.info("Starting to perform sync with peers.")
        self.log.info("Waiting to receive tips from peers.")
        # TODO: better way to tell that we have finished receiving tips
        await asyncio.sleep(5)
        highest_weight: uint64 = uint64(0)
        tip_block: FullBlock
        tip_height = 0
        sync_start_time = time.time()

        # Based on responses from peers about the current heads, see which head is the heaviest
        # (similar to longest chain rule).

        potential_tips: List[
            Tuple[bytes32, FullBlock]
        ] = self.store.get_potential_tips_tuples()
        self.log.info(f"Have collected {len(potential_tips)} potential tips")
        for header_hash, potential_tip_block in potential_tips:
            if potential_tip_block.proof_of_time is None:
                raise ValueError(
                    f"Invalid tip block {potential_tip_block.header_hash} received"
                )
            if potential_tip_block.weight > highest_weight:
                highest_weight = potential_tip_block.weight
                tip_block = potential_tip_block
                tip_height = potential_tip_block.height
        if highest_weight <= max(
            [t.weight for t in self.blockchain.get_current_tips()]
        ):
            self.log.info("Not performing sync, already caught up.")
            return

        assert tip_block
        self.log.info(
            f"Tip block {tip_block.header_hash} tip height {tip_block.height}"
        )

        for height in range(0, tip_block.height + 1):
            self.store.set_potential_headers_received(uint32(height), Event())
            self.store.set_potential_blocks_received(uint32(height), Event())
            self.store.set_potential_hashes_received(Event())

        timeout = 200
        sleep_interval = 10
        total_time_slept = 0

        while True:
            if total_time_slept > timeout:
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
                phr = self.store.get_potential_hashes_received()
                assert phr is not None
                await asyncio.wait_for(
                    phr.wait(), timeout=sleep_interval,
                )
                break
            except concurrent.futures.TimeoutError:
                total_time_slept += sleep_interval
                self.log.warning("Did not receive desired header hashes")

        # Finding the fork point allows us to only download headers and blocks from the fork point
        header_hashes = self.store.get_potential_hashes()
        fork_point_height: uint32 = self.blockchain.find_fork_point(header_hashes)
        fork_point_hash: bytes32 = header_hashes[fork_point_height]
        self.log.info(f"Fork point: {fork_point_hash} at height {fork_point_height}")

        # Now, we download all of the headers in order to verify the weight, in batches
        headers: List[HeaderBlock] = []

        # Download headers in batches. We download a few batches ahead in case there are delays or peers
        # that don't have the headers that we need.
        last_request_time: float = 0
        highest_height_requested: uint32 = uint32(0)
        request_made: bool = False
        for height_checkpoint in range(
            fork_point_height + 1, tip_height + 1, self.config["max_headers_to_send"]
        ):
            end_height = min(
                height_checkpoint + self.config["max_headers_to_send"], tip_height + 1
            )

            total_time_slept = 0
            while True:
                if self._shut_down:
                    return
                if total_time_slept > timeout:
                    raise TimeoutError("Took too long to fetch blocks")

                # Request batches that we don't have yet
                for batch in range(0, self.config["num_sync_batches"]):
                    batch_start = (
                        height_checkpoint + batch * self.config["max_headers_to_send"]
                    )
                    batch_end = min(
                        batch_start + self.config["max_headers_to_send"], tip_height + 1
                    )

                    if batch_start > tip_height:
                        # We have asked for all blocks
                        break

                    blocks_missing = any(
                        [
                            not (
                                self.store.get_potential_headers_received(uint32(h))
                            ).is_set()
                            for h in range(batch_start, batch_end)
                        ]
                    )
                    if (
                        time.time() - last_request_time > sleep_interval
                        and blocks_missing
                    ) or (batch_end - 1) > highest_height_requested:
                        # If we are missing header blocks in this batch, and we haven't made a request in a while,
                        # Make a request for this batch. Also, if we have never requested this batch, make
                        # the request
                        if batch_end - 1 > highest_height_requested:
                            highest_height_requested = batch_end - 1

                        request_made = True
                        request_hb = full_node_protocol.RequestHeaderBlocks(
                            tip_block.header.get_hash(),
                            [uint32(h) for h in range(batch_start, batch_end)],
                        )
                        self.log.info(
                            f"Requesting header blocks {batch_start, batch_end}."
                        )
                        yield OutboundMessage(
                            NodeType.FULL_NODE,
                            Message("request_header_blocks", request_hb),
                            Delivery.RANDOM,
                        )
                if request_made:
                    # Reset the timer for requests, so we don't overload other peers with requests
                    last_request_time = time.time()
                    request_made = False

                # Wait for the first batch (the next "max_blocks_to_send" blocks to arrive)
                awaitables = [
                    (self.store.get_potential_headers_received(uint32(height))).wait()
                    for height in range(height_checkpoint, end_height)
                ]
                future = asyncio.gather(*awaitables, return_exceptions=True)
                try:
                    await asyncio.wait_for(future, timeout=sleep_interval)
                    break
                except concurrent.futures.TimeoutError:
                    try:
                        await future
                    except asyncio.CancelledError:
                        pass
                    total_time_slept += sleep_interval
                    self.log.info(f"Did not receive desired header blocks")

        for h in range(fork_point_height + 1, tip_height + 1):
            header = self.store.get_potential_header(uint32(h))
            assert header is not None
            headers.append(header)

        self.log.info(f"Downloaded headers up to tip height: {tip_height}")
        if not verify_weight(
            tip_block.header, headers, self.blockchain.headers[fork_point_hash],
        ):
            raise errors.InvalidWeight(
                f"Weight of {tip_block.header.get_hash()} not valid."
            )

        self.log.info(
            f"Validated weight of headers. Downloaded {len(headers)} headers, tip height {tip_height}"
        )
        assert tip_height == fork_point_height + len(headers)
        self.store.clear_potential_headers()
        headers.clear()

        # Download blocks in batches, and verify them as they come in. We download a few batches ahead,
        # in case there are delays.
        last_request_time = 0
        highest_height_requested = uint32(0)
        request_made = False

        for height_checkpoint in range(
            fork_point_height + 1, tip_height + 1, self.config["max_blocks_to_send"]
        ):
            end_height = min(
                height_checkpoint + self.config["max_blocks_to_send"], tip_height + 1
            )

            total_time_slept = 0
            while True:
                if self._shut_down:
                    return
                if total_time_slept > timeout:
                    raise TimeoutError("Took too long to fetch blocks")

                # Request batches that we don't have yet
                for batch in range(0, self.config["num_sync_batches"]):
                    batch_start = (
                        height_checkpoint + batch * self.config["max_blocks_to_send"]
                    )
                    batch_end = min(
                        batch_start + self.config["max_blocks_to_send"], tip_height + 1
                    )

                    if batch_start > tip_height:
                        # We have asked for all blocks
                        break

                    blocks_missing = any(
                        [
                            not (
                                self.store.get_potential_blocks_received(uint32(h))
                            ).is_set()
                            for h in range(batch_start, batch_end)
                        ]
                    )
                    if (
                        time.time() - last_request_time > sleep_interval
                        and blocks_missing
                    ) or (batch_end - 1) > highest_height_requested:
                        # If we are missing blocks in this batch, and we haven't made a request in a while,
                        # Make a request for this batch. Also, if we have never requested this batch, make
                        # the request
                        self.log.info(
                            f"Requesting sync blocks {[i for i in range(batch_start, batch_end)]}"
                        )
                        if batch_end - 1 > highest_height_requested:
                            highest_height_requested = batch_end - 1
                        request_made = True
                        request_sync = full_node_protocol.RequestSyncBlocks(
                            tip_block.header_hash,
                            [
                                uint32(height)
                                for height in range(batch_start, batch_end)
                            ],
                        )
                        yield OutboundMessage(
                            NodeType.FULL_NODE,
                            Message("request_sync_blocks", request_sync),
                            Delivery.RANDOM,
                        )
                if request_made:
                    # Reset the timer for requests, so we don't overload other peers with requests
                    last_request_time = time.time()
                    request_made = False

                # Wait for the first batch (the next "max_blocks_to_send" blocks to arrive)
                awaitables = [
                    (self.store.get_potential_blocks_received(uint32(height))).wait()
                    for height in range(height_checkpoint, end_height)
                ]
                future = asyncio.gather(*awaitables, return_exceptions=True)
                try:
                    await asyncio.wait_for(future, timeout=sleep_interval)
                    break
                except concurrent.futures.TimeoutError:
                    try:
                        await future
                    except asyncio.CancelledError:
                        pass
                    total_time_slept += sleep_interval
                    self.log.info("Did not receive desired blocks")

            # Verifies this batch, which we are guaranteed to have (since we broke from the above loop)
            blocks = []
            for height in range(height_checkpoint, end_height):
                b: Optional[FullBlock] = await self.store.get_potential_block(
                    uint32(height)
                )
                assert b is not None
                blocks.append(b)

            validation_start_time = time.time()
            prevalidate_results = await self.blockchain.pre_validate_blocks(blocks)
            index = 0
            for height in range(height_checkpoint, end_height):
                if self._shut_down:
                    return
                block: Optional[FullBlock] = await self.store.get_potential_block(
                    uint32(height)
                )
                assert block is not None

                # The block gets permanantly added to the blockchain
                validated, pos = prevalidate_results[index]
                index += 1

                async with self.store.lock:
                    result, header_block = await self.blockchain.receive_block(
                        block, validated, pos
                    )
                    if (
                        result == ReceiveBlockResult.INVALID_BLOCK
                        or result == ReceiveBlockResult.DISCONNECTED_BLOCK
                    ):
                        raise RuntimeError(f"Invalid block {block.header_hash}")

                    # Always immediately add the block to the database, after updating blockchain state
                    await self.store.add_block(block)

                assert (
                    max([h.height for h in self.blockchain.get_current_tips()])
                    >= height
                )
                self.store.set_proof_of_time_estimate_ips(
                    self.blockchain.get_next_ips(block)
                )
            self.log.info(
                f"Took {time.time() - validation_start_time} seconds to validate and add blocks "
                f"{height_checkpoint} to {end_height}."
            )
        assert max([h.height for h in self.blockchain.get_current_tips()]) == tip_height
        self.log.info(
            f"Finished sync up to height {tip_height}. Total time: "
            f"{round((time.time() - sync_start_time)/60, 2)} minutes."
        )

    async def _finish_sync(self) -> OutboundMessageGenerator:
        """
        Finalize sync by setting sync mode to False, clearing all sync information, and adding any final
        blocks that we have finalized recently.
        """
        potential_fut_blocks = (self.store.get_potential_future_blocks()).copy()
        self.store.set_sync_mode(False)

        async with self.store.lock:
            await self.store.clear_sync_info()

        for block in potential_fut_blocks:
            if self._shut_down:
                return
            async for msg in self.block(full_node_protocol.Block(block)):
                yield msg

        # Update farmers and timelord with most recent information
        async for msg in self._send_challenges_to_timelords():
            yield msg
        async for msg in self._send_tips_to_farmers():
            yield msg

    @api_request
    async def request_all_header_hashes(
        self, request: full_node_protocol.RequestAllHeaderHashes
    ) -> OutboundMessageGenerator:
        try:
            header_hashes = self.blockchain.get_header_hashes(request.tip_header_hash)
            message = Message(
                "all_header_hashes", full_node_protocol.AllHeaderHashes(header_hashes)
            )
            yield OutboundMessage(NodeType.FULL_NODE, message, Delivery.RESPOND)
        except ValueError:
            self.log.info("Do not have requested header hashes.")

    @api_request
    async def all_header_hashes(
        self, all_header_hashes: full_node_protocol.AllHeaderHashes
    ) -> OutboundMessageGenerator:
        assert len(all_header_hashes.header_hashes) > 0
        self.store.set_potential_hashes(all_header_hashes.header_hashes)
        phr = self.store.get_potential_hashes_received()
        assert phr is not None
        phr.set()
        for _ in []:  # Yields nothing
            yield _

    @api_request
    async def request_header_blocks(
        self, request: full_node_protocol.RequestHeaderBlocks
    ) -> OutboundMessageGenerator:
        """
        A peer requests a list of header blocks, by height. Used for syncing or light clients.
        """
        start = time.time()
        if len(request.heights) > self.config["max_headers_to_send"]:
            raise errors.TooManyheadersRequested(
                f"The max number of headers is {self.config['max_headers_to_send']},\
                                                but requested {len(request.heights)}"
            )

        try:
            header_hashes: List[
                HeaderBlock
            ] = self.blockchain.get_header_hashes_by_height(
                request.heights, request.tip_header_hash
            )
            header_blocks: List[HeaderBlock] = []
            for header_hash in header_hashes:
                full_block: Optional[FullBlock] = await self.store.get_block(
                    header_hash
                )
                assert full_block is not None
                header_block: Optional[HeaderBlock] = self.blockchain.get_header_block(
                    full_block
                )
                assert header_block is not None
                header_blocks.append(header_block)
            self.log.info(f"Got header blocks by height {time.time() - start}")
        except KeyError:
            return
        except BlockNotInBlockchain as e:
            self.log.info(f"{e}")
            return

        response = full_node_protocol.HeaderBlocks(
            request.tip_header_hash, header_blocks
        )
        yield OutboundMessage(
            NodeType.FULL_NODE, Message("header_blocks", response), Delivery.RESPOND
        )

    @api_request
    async def header_blocks(
        self, request: full_node_protocol.HeaderBlocks
    ) -> OutboundMessageGenerator:
        """
        Receive header blocks from a peer.
        """
        self.log.info(
            f"Received header blocks {request.header_blocks[0].height, request.header_blocks[-1].height}."
        )
        for header_block in request.header_blocks:
            self.store.add_potential_header(header_block)
            (self.store.get_potential_headers_received(header_block.height)).set()

        for _ in []:  # Yields nothing
            yield _

    @api_request
    async def request_sync_blocks(
        self, request: full_node_protocol.RequestSyncBlocks
    ) -> OutboundMessageGenerator:
        """
        Responsd to a peers request for syncing blocks.
        """
        blocks: List[FullBlock] = []
        async with self.store.lock:
            tip_block: Optional[FullBlock] = await self.store.get_block(
                request.tip_header_hash
            )
        if tip_block is not None:
            if len(request.heights) > self.config["max_blocks_to_send"]:
                raise errors.TooManyheadersRequested(
                    f"The max number of blocks is "
                    f"{self.config['max_blocks_to_send']},"
                    f"but requested {len(request.heights)}"
                )
            try:
                header_hashes: List[
                    HeaderBlock
                ] = self.blockchain.get_header_hashes_by_height(
                    request.heights, request.tip_header_hash
                )
                for header_hash in header_hashes:
                    fetched = await self.store.get_block(header_hash)
                    assert fetched is not None
                    blocks.append(fetched)
            except KeyError:
                self.log.info("Do not have required blocks")
                return
            except BlockNotInBlockchain as e:
                self.log.info(f"{e}")
                return
        else:
            # We don't have the blocks that the client is looking for
            self.log.info(
                f"Peer requested tip {request.tip_header_hash} that we don't have"
            )
            return
        response = Message(
            "sync_blocks",
            full_node_protocol.SyncBlocks(request.tip_header_hash, blocks),
        )
        yield OutboundMessage(NodeType.FULL_NODE, response, Delivery.RESPOND)

    @api_request
    async def sync_blocks(
        self, request: full_node_protocol.SyncBlocks
    ) -> OutboundMessageGenerator:
        """
        We have received the blocks that we needed for syncing. Add them to processing queue.
        """
        self.log.info(f"Received sync blocks {[b.height for b in request.blocks]}")

        if not self.store.get_sync_mode():
            self.log.warning("Receiving sync blocks when we are not in sync mode.")
            return

        for block in request.blocks:
            await self.store.add_potential_block(block)
            if (
                not self.store.get_sync_mode()
            ):  # We might have left sync mode after the previous await
                return
            (self.store.get_potential_blocks_received(block.height)).set()

        for _ in []:  # Yields nothing
            yield _

    @api_request
    async def request_header_hash(
        self, request: farmer_protocol.RequestHeaderHash
    ) -> OutboundMessageGenerator:
        """
        Creates a block body and header, with the proof of space, coinbase, and fee targets provided
        by the farmer, and sends the hash of the header data back to the farmer.
        """
        plot_seed: bytes32 = request.proof_of_space.get_plot_seed()

        # Checks that the proof of space is valid
        quality_string: bytes = Verifier().validate_proof(
            plot_seed,
            request.proof_of_space.size,
            request.challenge_hash,
            bytes(request.proof_of_space.proof),
        )
        assert len(quality_string) == 32

        # Retrieves the correct tip for the challenge
        tips: List[Header] = self.blockchain.get_current_tips()
        tips_blocks: List[Optional[FullBlock]] = [
            await self.store.get_block(tip.header_hash) for tip in tips
        ]
        target_tip_block: Optional[FullBlock] = None
        target_tip: Optional[Header] = None
        for tip in tips_blocks:
            assert tip is not None
            tip_challenge: Optional[Challenge] = self.blockchain.get_challenge(tip)
            assert tip_challenge is not None
            if tip_challenge.get_hash() == request.challenge_hash:
                target_tip_block = tip
                target_tip = tip.header
        if target_tip is None:
            self.log.warning(
                f"Challenge hash: {request.challenge_hash} not in one of three tips"
            )
            return

        assert target_tip is not None
        # Grab best transactions from Mempool for given tip target
        spend_bundle: Optional[
            SpendBundle
        ] = await self.mempool_manager.create_bundle_for_tip(target_tip)
        spend_bundle_fees = 0
        aggregate_sig: Optional[BLSSignature] = None
        solution_program: Optional[Program] = None

        if spend_bundle:
            solution_program = best_solution_program(spend_bundle)
            spend_bundle_fees = spend_bundle.fees()
            aggregate_sig = spend_bundle.aggregated_signature

        base_fee_reward = calculate_base_fee(target_tip.height)
        full_fee_reward = uint64(int(base_fee_reward + spend_bundle_fees))
        # Create fees coin
        fee_hash = std_hash(std_hash(target_tip.height))
        fees_coin = Coin(fee_hash, request.fees_target_puzzle_hash, full_fee_reward)

        # SpendBundle has all signatures already aggregated

        # TODO(straya): calculate cost of all transactions
        cost = uint64(0)

        extension_data: bytes32 = bytes32([0] * 32)

        # Creates a block with transactions, coinbase, and fees
        body: Body = Body(
            request.coinbase,
            request.coinbase_signature,
            fees_coin,
            solution_program,
            aggregate_sig,
            cost,
            extension_data,
        )
        # Creates the block header
        prev_header_hash: bytes32 = target_tip.get_hash()
        timestamp: uint64 = uint64(int(time.time()))

        # TODO(straya): use a real BIP158 filter based on transactions
        filter_hash: bytes32 = token_bytes(32)
        proof_of_space_hash: bytes32 = request.proof_of_space.get_hash()
        body_hash: Body = body.get_hash()
        difficulty = self.blockchain.get_next_difficulty(target_tip.header_hash)

        assert target_tip_block is not None
        vdf_ips: uint64 = self.blockchain.get_next_ips(target_tip_block)

        iterations_needed: uint64 = calculate_iterations(
            request.proof_of_space, difficulty, vdf_ips, constants["MIN_BLOCK_TIME"],
        )
        additions_root = token_bytes(32)  # TODO(straya)
        removal_root = token_bytes(32)  # TODO(straya)

        block_header_data: HeaderData = HeaderData(
            uint32(target_tip.height + 1),
            prev_header_hash,
            timestamp,
            filter_hash,
            proof_of_space_hash,
            body_hash,
            target_tip.weight + difficulty,
            uint64(target_tip.data.total_iters + iterations_needed),
            additions_root,
            removal_root,
        )

        block_header_data_hash: bytes32 = block_header_data.get_hash()

        # self.stores this block so we can submit it to the blockchain after it's signed by harvester
        self.store.add_candidate_block(
            proof_of_space_hash,
            body,
            block_header_data,
            request.proof_of_space,
            target_tip.height + 1,
        )

        message = farmer_protocol.HeaderHash(
            proof_of_space_hash, block_header_data_hash
        )
        yield OutboundMessage(
            NodeType.FARMER, Message("header_hash", message), Delivery.RESPOND
        )

    @api_request
    async def header_signature(
        self, header_signature: farmer_protocol.HeaderSignature
    ) -> OutboundMessageGenerator:
        """
        Signature of header hash, by the harvester. This is enough to create an unfinished
        block, which only needs a Proof of Time to be finished. If the signature is valid,
        we call the unfinished_block routine.
        """
        candidate: Optional[
            Tuple[Body, HeaderData, ProofOfSpace]
        ] = self.store.get_candidate_block(header_signature.pos_hash)
        if candidate is None:
            self.log.warning(
                f"PoS hash {header_signature.pos_hash} not found in database"
            )
            return
        # Verifies that we have the correct header and body self.stored
        block_body, block_header_data, pos = candidate

        assert block_header_data.get_hash() == header_signature.header_hash

        block_header: Header = Header(
            block_header_data, header_signature.header_signature
        )
        unfinished_block_obj: FullBlock = FullBlock(pos, None, block_header, block_body)

        # Propagate to ourselves (which validates and does further propagations)
        request = full_node_protocol.UnfinishedBlock(unfinished_block_obj)
        async for m in self.unfinished_block(request):
            # Yield all new messages (propagation to peers)
            yield m

    # TIMELORD PROTOCOL
    @api_request
    async def proof_of_time_finished(
        self, request: timelord_protocol.ProofOfTimeFinished
    ) -> OutboundMessageGenerator:
        """
        A proof of time, received by a peer timelord. We can use this to complete a block,
        and call the block routine (which handles propagation and verification of blocks).
        """
        dict_key = (
            request.proof.challenge_hash,
            request.proof.number_of_iterations,
        )

        unfinished_block_obj: Optional[FullBlock] = self.store.get_unfinished_block(
            dict_key
        )
        if not unfinished_block_obj:
            self.log.warning(
                f"Received a proof of time that we cannot use to complete a block {dict_key}"
            )
            return

        new_full_block: FullBlock = FullBlock(
            unfinished_block_obj.proof_of_space,
            request.proof,
            unfinished_block_obj.header,
            unfinished_block_obj.body,
        )

        if self.store.get_sync_mode():
            self.store.add_potential_future_block(new_full_block)
        else:
            async for msg in self.block(full_node_protocol.Block(new_full_block)):
                yield msg

    # PEER PROTOCOL
    @api_request
    async def new_proof_of_time(
        self, new_proof_of_time: full_node_protocol.NewProofOfTime
    ) -> OutboundMessageGenerator:
        """
        A proof of time, received by a peer full node. If we have the rest of the block,
        we can complete it. Otherwise, we just verify and propagate the proof.
        """
        finish_block: bool = False
        propagate_proof: bool = False
        if self.store.get_unfinished_block(
            (
                new_proof_of_time.proof.challenge_hash,
                new_proof_of_time.proof.number_of_iterations,
            )
        ):

            finish_block = True
        elif new_proof_of_time.proof.is_valid(constants["DISCRIMINANT_SIZE_BITS"]):
            propagate_proof = True

        if finish_block:
            request = timelord_protocol.ProofOfTimeFinished(new_proof_of_time.proof)
            async for msg in self.proof_of_time_finished(request):
                yield msg
        if propagate_proof:
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("new_proof_of_time", new_proof_of_time),
                Delivery.BROADCAST_TO_OTHERS,
            )

    @api_request
    async def unfinished_block(
        self, unfinished_block: full_node_protocol.UnfinishedBlock
    ) -> OutboundMessageGenerator:
        """
        We have received an unfinished block, either created by us, or from another peer.
        We can validate it and if it's a good block, propagate it to other peers and
        timelords.
        """
        # Adds the unfinished block to seen, and check if it's seen before
        if self.store.seen_unfinished_block(unfinished_block.block.header_hash):
            return

        if not self.blockchain.is_child_of_head(unfinished_block.block):
            return

        prev_full_block: Optional[FullBlock] = await self.store.get_block(
            unfinished_block.block.prev_header_hash
        )

        assert prev_full_block is not None
        if not await self.blockchain.validate_unfinished_block(
            unfinished_block.block, prev_full_block
        ):
            raise InvalidUnfinishedBlock()

        challenge = self.blockchain.get_challenge(prev_full_block)
        assert challenge is not None
        challenge_hash = challenge.get_hash()
        iterations_needed: uint64 = uint64(
            unfinished_block.block.header.data.total_iters
            - prev_full_block.header.data.total_iters
        )

        if (
            self.store.get_unfinished_block((challenge_hash, iterations_needed))
            is not None
        ):
            return

        expected_time: uint64 = uint64(
            int(iterations_needed / (self.store.get_proof_of_time_estimate_ips()))
        )

        if expected_time > constants["PROPAGATION_DELAY_THRESHOLD"]:
            self.log.info(f"Block is slow, expected {expected_time} seconds, waiting")
            # If this block is slow, sleep to allow faster blocks to come out first
            await asyncio.sleep(5)

        leader: Tuple[uint32, uint64] = self.store.get_unfinished_block_leader()
        if leader is None or unfinished_block.block.height > leader[0]:
            self.log.info(
                f"This is the first unfinished block at height {unfinished_block.block.height}, so propagate."
            )
            # If this is the first block we see at this height, propagate
            self.store.set_unfinished_block_leader(
                (unfinished_block.block.height, expected_time)
            )
        elif unfinished_block.block.height == leader[0]:
            if expected_time > leader[1] + constants["PROPAGATION_THRESHOLD"]:
                # If VDF is expected to finish X seconds later than the best, don't propagate
                self.log.info(
                    f"VDF will finish too late {expected_time} seconds, so don't propagate"
                )
                return
            elif expected_time < leader[1]:
                self.log.info(
                    f"New best unfinished block at height {unfinished_block.block.height}"
                )
                # If this will be the first block to finalize, update our leader
                self.store.set_unfinished_block_leader((leader[0], expected_time))
        else:
            # If we have seen an unfinished block at a greater or equal height, don't propagate
            self.log.info(f"Unfinished block at old height, so don't propagate")
            return

        self.store.add_unfinished_block(
            (challenge_hash, iterations_needed), unfinished_block.block
        )

        timelord_request = timelord_protocol.ProofOfSpaceInfo(
            challenge_hash, iterations_needed
        )

        yield OutboundMessage(
            NodeType.TIMELORD,
            Message("proof_of_space_info", timelord_request),
            Delivery.BROADCAST,
        )
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("unfinished_block", unfinished_block),
            Delivery.BROADCAST_TO_OTHERS,
        )

    @api_request
    async def transaction(
        self, tx: full_node_protocol.NewTransaction
    ) -> OutboundMessageGenerator:
        """
        Receives a full transaction from peer.
        If tx is added to mempool, send tx_id to others. (maybe_transaction)
        """
        async with self.unspent_store.lock:
            added, error = await self.mempool_manager.add_spendbundle(tx.transaction)
            if added:
                maybeTX = full_node_protocol.TransactionId(tx.transaction.name())
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message("maybe_transaction", maybeTX),
                    Delivery.BROADCAST_TO_OTHERS,
                )
            else:
                self.log.warning(
                    f"Wasn't able to add transaction with id {tx.transaction.name()}, error: {error}"
                )
                return

    @api_request
    async def maybe_transaction(
        self, tx_id: full_node_protocol.TransactionId
    ) -> OutboundMessageGenerator:
        """
        Receives a transaction_id, ignore if we've seen it already.
        Request a full transaction if we haven't seen it previously_id:
        """
        if self.mempool_manager.seen(tx_id.transaction_id):
            self.log.info(f"tx_id({tx_id.transaction_id}) already seen")
            return
        else:
            requestTX = full_node_protocol.RequestTransaction(tx_id.transaction_id)
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("request_transaction", requestTX),
                Delivery.RESPOND,
            )

    @api_request
    async def request_transaction(
        self, tx_id: full_node_protocol.RequestTransaction
    ) -> OutboundMessageGenerator:
        """ Peer has request a full transaction from us. """
        spend_bundle = await self.mempool_manager.get_spendbundle(tx_id.transaction_id)
        if spend_bundle is None:
            return

        transaction = full_node_protocol.NewTransaction(spend_bundle)
        yield OutboundMessage(
            NodeType.FULL_NODE, Message("transaction", transaction), Delivery.RESPOND,
        )

        self.log.info(f"sending transaction (tx_id: {spend_bundle.name()}) to peer")

    @api_request
    async def block(self, block: full_node_protocol.Block) -> OutboundMessageGenerator:
        """
        Receive a full block from a peer full node (or ourselves).
        """
        header_hash = block.block.header.get_hash()

        # Adds the block to seen, and check if it's seen before
        if self.blockchain.contains_block(header_hash):
            return

        if self.store.get_sync_mode():
            # Add the block to our potential tips list
            self.store.add_potential_tip(block.block)
            return

        prevalidate_block = await self.blockchain.pre_validate_blocks([block.block])
        val, pos = prevalidate_block[0]

        async with self.store.lock:
            # Tries to add the block to the blockchain
            added, replaced = await self.blockchain.receive_block(block.block, val, pos)
            if added == ReceiveBlockResult.ADDED_TO_HEAD:
                await self.mempool_manager.new_tips(
                    await self.blockchain.get_full_tips()
                )

        if added == ReceiveBlockResult.ALREADY_HAVE_BLOCK:
            return
        elif added == ReceiveBlockResult.INVALID_BLOCK:
            self.log.warning(
                f"Block {header_hash} at height {block.block.height} is invalid."
            )
            return
        elif added == ReceiveBlockResult.DISCONNECTED_BLOCK:
            self.log.warning(f"Disconnected block {header_hash}")
            tip_height = min(
                [head.height for head in self.blockchain.get_current_tips()]
            )

            if (
                block.block.height
                > tip_height + self.config["sync_blocks_behind_threshold"]
            ):
                async with self.store.lock:
                    if self.store.get_sync_mode():
                        return
                    await self.store.clear_sync_info()
                    self.store.add_potential_tip(block.block)
                    self.store.set_sync_mode(True)
                self.log.info(
                    f"We are too far behind this block. Our height is {tip_height} and block is at "
                    f"{block.block.height}"
                )
                try:
                    # Performs sync, and catch exceptions so we don't close the connection
                    async for ret_msg in self._sync():
                        yield ret_msg
                except asyncio.CancelledError:
                    self.log.error("Syncing failed, CancelledError")
                except BaseException as e:
                    self.log.error(f"Error {type(e)}{e} with syncing")
                finally:
                    async for ret_msg in self._finish_sync():
                        yield ret_msg

            elif block.block.height >= tip_height - 3:
                self.log.info(
                    f"We have received a disconnected block at height {block.block.height}, current tip is {tip_height}"
                )
                msg = Message(
                    "request_block",
                    full_node_protocol.RequestBlock(block.block.prev_header_hash),
                )
                self.store.add_disconnected_block(block.block)
                yield OutboundMessage(NodeType.FULL_NODE, msg, Delivery.RESPOND)
            return
        elif added == ReceiveBlockResult.ADDED_TO_HEAD:
            # Only propagate blocks which extend the blockchain (becomes one of the heads)
            self.log.info(
                f"Updated heads, new heights: {[b.height for b in self.blockchain.get_current_tips()]}"
            )

            difficulty = self.blockchain.get_next_difficulty(
                block.block.prev_header_hash
            )
            next_vdf_ips = self.blockchain.get_next_ips(block.block)
            self.log.info(f"Difficulty {difficulty} IPS {next_vdf_ips}")
            if next_vdf_ips != self.store.get_proof_of_time_estimate_ips():
                self.store.set_proof_of_time_estimate_ips(next_vdf_ips)
                rate_update = farmer_protocol.ProofOfTimeRate(next_vdf_ips)
                self.log.info(f"Sending proof of time rate {next_vdf_ips}")
                yield OutboundMessage(
                    NodeType.FARMER,
                    Message("proof_of_time_rate", rate_update),
                    Delivery.BROADCAST,
                )
                self.store.clear_seen_unfinished_blocks()

            challenge: Optional[Challenge] = self.blockchain.get_challenge(block.block)
            assert challenge is not None
            challenge_hash: bytes32 = challenge.get_hash()
            farmer_request = farmer_protocol.ProofOfSpaceFinalized(
                challenge_hash, block.block.height, block.block.weight, difficulty,
            )
            timelord_request = timelord_protocol.ChallengeStart(
                challenge_hash, block.block.weight,
            )
            # Tell timelord to stop previous challenge and start with new one
            yield OutboundMessage(
                NodeType.TIMELORD,
                Message("challenge_start", timelord_request),
                Delivery.BROADCAST,
            )

            # Tell full nodes about the new block
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("block", block),
                Delivery.BROADCAST_TO_OTHERS,
            )

            # Tell farmer about the new block
            yield OutboundMessage(
                NodeType.FARMER,
                Message("proof_of_space_finalized", farmer_request),
                Delivery.BROADCAST,
            )

        elif added == ReceiveBlockResult.ADDED_AS_ORPHAN:
            self.log.info(f"Received orphan block of height {block.block.height}")
        else:
            # Should never reach here, all the cases are covered
            raise RuntimeError(f"Invalid result from receive_block {added}")

        # This code path is reached if added == ADDED_AS_ORPHAN or ADDED_TO_HEAD
        next_block: Optional[FullBlock] = self.store.get_disconnected_block_by_prev(
            block.block.header_hash
        )

        # Recursively process the next block if we have it
        if next_block is not None:
            async for ret_msg in self.block(full_node_protocol.Block(next_block)):
                yield ret_msg

        # Removes all temporary data for old blocks
        lowest_tip = min(tip.height for tip in self.blockchain.get_current_tips())
        clear_height = uint32(max(0, lowest_tip - 30))
        self.store.clear_candidate_blocks_below(clear_height)
        self.store.clear_unfinished_blocks_below(clear_height)
        self.store.clear_disconnected_blocks_below(clear_height)

    @api_request
    async def request_block(
        self, request_block: full_node_protocol.RequestBlock
    ) -> OutboundMessageGenerator:
        block: Optional[FullBlock] = await self.store.get_block(
            request_block.header_hash
        )
        if block is not None:
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("block", full_node_protocol.Block(block)),
                Delivery.RESPOND,
            )

    @api_request
    async def peers(
        self, request: full_node_protocol.Peers
    ) -> OutboundMessageGenerator:
        if self.server is None:
            return
        conns = self.server.global_connections
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
            tasks.append(asyncio.create_task(self.server.start_client(peer)))
        await asyncio.gather(*tasks)

    @api_request
    async def request_proof_hashes(
        self, request: src.protocols.wallet_protocol.ProofHash
    ) -> OutboundMessageGenerator:
        self.log.info(f"Received request for proof hash: {request}")
        reply = ProofHash(std_hash(b"deadbeef"))
        yield OutboundMessage(
            NodeType.WALLET, Message("proof_hash", reply), Delivery.RESPOND
        )

    @api_request
    async def request_full_proof_for_hash(
        self, request: src.protocols.wallet_protocol.ProofHash
    ) -> OutboundMessageGenerator:
        self.log.info(f"Received request for full proof for hash: {request}")
        proof = FullProofForHash(std_hash(b"test"), std_hash(b"test"))
        yield OutboundMessage(
            NodeType.WALLET, Message("full_proof_for_hash", proof), Delivery.RESPOND
        )

    @api_request
    async def wallet_transaction(self, spend_bundle: SpendBundle) -> OutboundMessageGenerator:
        added, error = self.mempool_manager.add_spendbundle(spend_bundle)
        if added:
            yield OutboundMessage(
                NodeType.WALLET, Message("transaction_ack", spend_bundle.name()), Delivery.RESPOND
            )
            yield OutboundMessage(
                NodeType.FULL_NODE, Message("maybe_transaction", spend_bundle.name()), Delivery.BROADCAST
            )