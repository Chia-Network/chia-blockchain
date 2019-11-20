import asyncio
import concurrent
import logging
import os
import time
from asyncio import Event
from hashlib import sha256
from secrets import token_bytes
from typing import AsyncGenerator, List, Optional, Set, Tuple

import yaml
from blspy import PrivateKey, Signature

from chiapos import Verifier
from definitions import ROOT_DIR
from src.blockchain import Blockchain, ReceiveBlockResult
from src.consensus.constants import constants
from src.consensus.pot_iterations import calculate_iterations
from src.consensus.weight_verifier import verify_weight
from src.database import FullNodeStore
from src.protocols import farmer_protocol, peer_protocol, timelord_protocol
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.server.server import ChiaServer
from src.types.body import Body
from src.types.challenge import Challenge
from src.types.fees_target import FeesTarget
from src.types.full_block import FullBlock
from src.types.header import Header, HeaderData
from src.types.header_block import HeaderBlock
from src.types.peer_info import PeerInfo
from src.types.sized_bytes import bytes32
from src.types.proof_of_space import ProofOfSpace
from src.util import errors
from src.util.api_decorators import api_request
from src.util.errors import (
    BlockNotInBlockchain,
    InvalidUnfinishedBlock,
    PeersDontHaveBlock,
)
from src.util.ints import uint32, uint64

log = logging.getLogger(__name__)


class FullNode:
    store: FullNodeStore
    blockchain: Blockchain

    def __init__(self, store: FullNodeStore, blockchain: Blockchain):
        config_filename = os.path.join(ROOT_DIR, "config", "config.yaml")
        self.config = yaml.safe_load(open(config_filename, "r"))["full_node"]
        self.store = store
        self.blockchain = blockchain
        self._bg_tasks: Set[asyncio.Task] = set()

    def _set_server(self, server: ChiaServer):
        self.server = server

    async def _send_tips_to_farmers(
        self, delivery: Delivery = Delivery.BROADCAST
    ) -> AsyncGenerator[OutboundMessage, None]:
        """
        Sends all of the current heads to all farmer peers. Also sends the latest
        estimated proof of time rate, so farmer can calulate which proofs are good.
        """
        requests: List[farmer_protocol.ProofOfSpaceFinalized] = []
        async with self.store.lock:
            for tip in self.blockchain.get_current_tips():
                assert tip.proof_of_time and tip.challenge
                challenge_hash = tip.challenge.get_hash()
                height = tip.challenge.height
                quality = tip.proof_of_space.verify_and_get_quality()
                if tip.height > 0:
                    difficulty: uint64 = await self.blockchain.get_next_difficulty(
                        tip.prev_header_hash
                    )
                else:
                    difficulty = tip.weight
                requests.append(
                    farmer_protocol.ProofOfSpaceFinalized(
                        challenge_hash, height, quality, difficulty
                    )
                )
            proof_of_time_rate: uint64 = await self.store.get_proof_of_time_estimate_ips()
        for request in requests:
            yield OutboundMessage(
                NodeType.FARMER, Message("proof_of_space_finalized", request), delivery
            )
        rate_update = farmer_protocol.ProofOfTimeRate(proof_of_time_rate)
        yield OutboundMessage(
            NodeType.FARMER, Message("proof_of_time_rate", rate_update), delivery
        )

    async def _send_challenges_to_timelords(
        self, delivery: Delivery = Delivery.BROADCAST
    ) -> AsyncGenerator[OutboundMessage, None]:
        """
        Sends all of the current heads (as well as Pos infos) to all timelord peers.
        """
        challenge_requests: List[timelord_protocol.ChallengeStart] = []
        pos_info_requests: List[timelord_protocol.ProofOfSpaceInfo] = []
        async with self.store.lock:
            tips: List[HeaderBlock] = self.blockchain.get_current_tips()
            for tip in tips:
                assert tip.challenge
                challenge_hash = tip.challenge.get_hash()
                challenge_requests.append(
                    timelord_protocol.ChallengeStart(
                        challenge_hash, tip.challenge.total_weight
                    )
                )

            tip_hashes = [tip.header_hash for tip in tips]
            tip_infos = [
                tup[0]
                for tup in list((await self.store.get_unfinished_blocks()).items())
                if tup[1].prev_header_hash in tip_hashes
            ]
            for chall, iters in tip_infos:
                pos_info_requests.append(
                    timelord_protocol.ProofOfSpaceInfo(chall, iters)
                )
        for challenge_msg in challenge_requests:
            yield OutboundMessage(
                NodeType.TIMELORD, Message("challenge_start", challenge_msg), delivery
            )
        for pos_info_msg in pos_info_requests:
            yield OutboundMessage(
                NodeType.TIMELORD, Message("proof_of_space_info", pos_info_msg), delivery
            )

    async def _on_connect(self) -> AsyncGenerator[OutboundMessage, None]:
        """
        Whenever we connect to another node, send them our current heads. Also send heads to farmers
        and challenges to timelords.
        """
        blocks: List[FullBlock] = []

        async with self.store.lock:
            heads: List[HeaderBlock] = self.blockchain.get_current_tips()
            for h in heads:
                block = await self.blockchain.get_block(h.header.get_hash())
                assert block
                blocks.append(block)
        for block in blocks:
            request = peer_protocol.Block(block)
            yield OutboundMessage(
                NodeType.FULL_NODE, Message("block", request), Delivery.RESPOND
            )

        # Update farmers and timelord with most recent information
        async for msg in self._send_challenges_to_timelords(Delivery.RESPOND):
            yield msg
        async for msg in self._send_tips_to_farmers(Delivery.RESPOND):
            yield msg

    def _num_needed_peers(self):
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
            async def on_connect():
                msg = Message("request_peers", peer_protocol.RequestPeers())
                yield OutboundMessage(NodeType.INTRODUCER, msg, Delivery.RESPOND)

            while True:
                if self._num_needed_peers():
                    if not await self.server.start_client(
                        introducer_peerinfo, on_connect
                    ):
                        continue
                await asyncio.sleep(self.config["introducer_connect_interval"])

        self._bg_tasks.add(asyncio.create_task(introducer_client()))

    def _shutdown(self):
        for task in self._bg_tasks:
            task.cancel()
        self._bg_tasks = set()

    async def _sync(self):
        """
        Performs a full sync of the blockchain.
            - Check which are the heaviest tips
            - Request headers for the heaviest
            - Verify the weight of the tip, using the headers
            - Blacklist peers that provide invalid stuff
            - Sync blockchain up to heads (request blocks in batches, and add to queue)
        """
        log.info("Starting to perform sync with peers.")
        log.info("Waiting to receive tips from peers.")
        # TODO: better way to tell that we have finished receiving tips
        await asyncio.sleep(5)
        highest_weight: uint64 = uint64(0)
        tip_block: FullBlock
        tip_height = 0
        caught_up = False

        # Based on responses from peers about the current heads, see which head is the heaviest
        # (similar to longest chain rule).

        async with self.store.lock:
            potential_tips: List[
                Tuple[bytes32, FullBlock]
            ] = await self.store.get_potential_tips_tuples()
            log.info(f"Have collected {len(potential_tips)} potential tips")
            for header_hash, block in potential_tips:
                if block.header_block.challenge is None:
                    raise ValueError(f"Invalid tip block {block.header_hash} received")
                if block.header_block.challenge.total_weight > highest_weight:
                    highest_weight = block.header_block.challenge.total_weight
                    tip_block = block
                    tip_height = block.header_block.challenge.height
            if highest_weight <= max(
                [t.weight for t in self.blockchain.get_current_tips()]
            ):
                log.info("Not performing sync, already caught up.")
                caught_up = True
        if caught_up:
            async for msg in self._finish_sync():
                yield msg
            return
        assert tip_block
        log.info(f"Tip block {tip_block.header_hash} tip height {tip_block.height}")

        # Now, we download all of the headers in order to verify the weight
        # TODO: use queue here, request a few at a time
        # TODO: send multiple API calls out at once
        timeout = 30
        sleep_interval = 3
        total_time_slept = 0
        headers: List[HeaderBlock] = []
        while total_time_slept < timeout:
            for start_height in range(
                0, tip_height + 1, self.config["max_headers_to_send"]
            ):
                end_height = min(
                    start_height + self.config["max_headers_to_send"], tip_height + 1
                )
                request = peer_protocol.RequestHeaderBlocks(
                    tip_block.header_block.header.get_hash(),
                    [uint64(h) for h in range(start_height, end_height)],
                )
                # TODO: should we ask the same peer as before, for the headers?
                yield OutboundMessage(
                    NodeType.FULL_NODE,
                    Message("request_header_blocks", request),
                    Delivery.RANDOM,
                )
            await asyncio.sleep(sleep_interval)
            total_time_slept += sleep_interval

            async with self.store.lock:
                received_all_headers = True
                local_headers = []

                for height in range(0, tip_height + 1):
                    if await self.store.get_potential_header(uint32(height)) is None:
                        received_all_headers = False
                        break
                    local_headers.append(
                        await self.store.get_potential_header(uint32(height))
                    )
                if received_all_headers:
                    headers = local_headers
                    break
        log.error(f"Downloaded headers up to tip height: {tip_height}")
        if not verify_weight(tip_block.header_block, headers):
            # TODO: ban peers that provided the invalid heads or proofs
            raise errors.InvalidWeight(
                f"Weight of {tip_block.header_block.header.get_hash()} not valid."
            )

        log.error(
            f"Validated weight of headers. Downloaded {len(headers)} headers, tip height {tip_height}"
        )
        assert tip_height + 1 == len(headers)

        async with self.store.lock:
            fork_point: HeaderBlock = self.blockchain.find_fork_point(headers)

        # TODO: optimize, send many requests at once, and for more blocks
        for height in range(fork_point.height + 1, tip_height + 1):
            # Only download from fork point (what we don't have)
            async with self.store.lock:
                have_block = (
                    await self.store.get_potential_tip(
                        headers[height].header.get_hash()
                    )
                    is not None
                )

            if not have_block:
                request_sync = peer_protocol.RequestSyncBlocks(
                    tip_block.header_block.header.header_hash, [uint64(height)]
                )
                async with self.store.lock:
                    await self.store.set_potential_blocks_received(
                        uint32(height), Event()
                    )
                found = False
                for _ in range(30):
                    yield OutboundMessage(
                        NodeType.FULL_NODE,
                        Message("request_sync_blocks", request_sync),
                        Delivery.RANDOM,
                    )
                    try:
                        await asyncio.wait_for(
                            (
                                await self.store.get_potential_blocks_received(
                                    uint32(height)
                                )
                            ).wait(),
                            timeout=2,
                        )
                        found = True
                        break
                    except concurrent.futures.TimeoutError:
                        log.info("Did not receive desired block")
                if not found:
                    raise PeersDontHaveBlock(
                        f"Did not receive desired block at height {height}"
                    )
            async with self.store.lock:
                # TODO: ban peers that provide bad blocks
                if have_block:
                    block = await self.store.get_potential_tip(
                        headers[height].header.get_hash()
                    )

                else:
                    block = await self.store.get_potential_block(uint32(height))
                assert block is not None

                start = time.time()
                result = await self.blockchain.receive_block(block)
                if (
                    result == ReceiveBlockResult.INVALID_BLOCK
                    or result == ReceiveBlockResult.DISCONNECTED_BLOCK
                ):
                    raise RuntimeError(f"Invalid block {block.header_hash}")
                log.info(
                    f"Took {time.time() - start} seconds to validate and add block {block.height}."
                )
                assert (
                    max([h.height for h in self.blockchain.get_current_tips()])
                    >= height
                )
                await self.store.set_proof_of_time_estimate_ips(
                    await self.blockchain.get_next_ips(block.header_hash)
                )
        log.info(f"Finished sync up to height {tip_height}")

        async for msg in self._finish_sync():
            yield msg

    async def _finish_sync(self):
        """
        Finalize sync by setting sync mode to False, clearing all sync information, and adding any final
        blocks that we have finalized recently.
        """
        async with self.store.lock:
            potential_fut_blocks = (
                await self.store.get_potential_future_blocks()
            ).copy()
            await self.store.set_sync_mode(False)
            await self.store.clear_sync_info()

        for block in potential_fut_blocks:
            async for msg in self.block(peer_protocol.Block(block)):
                yield msg

        # Update farmers and timelord with most recent information
        async for msg in self._send_challenges_to_timelords():
            yield msg
        async for msg in self._send_tips_to_farmers():
            yield msg

    @api_request
    async def request_header_blocks(
        self, request: peer_protocol.RequestHeaderBlocks
    ) -> AsyncGenerator[OutboundMessage, None]:
        """
        A peer requests a list of header blocks, by height. Used for syncing or light clients.
        """
        if len(request.heights) > self.config["max_headers_to_send"]:
            raise errors.TooManyheadersRequested(
                f"The max number of headers is {self.config['max_headers_to_send']},\
                                                but requested {len(request.heights)}"
            )

        async with self.store.lock:
            try:
                headers: List[
                    HeaderBlock
                ] = await self.blockchain.get_header_blocks_by_height(
                    request.heights, request.tip_header_hash
                )
            except KeyError:
                return
            except BlockNotInBlockchain as e:
                log.info(f"{e}")
                return

        response = peer_protocol.HeaderBlocks(request.tip_header_hash, headers)
        yield OutboundMessage(
            NodeType.FULL_NODE, Message("header_blocks", response), Delivery.RESPOND
        )

    @api_request
    async def header_blocks(
        self, request: peer_protocol.HeaderBlocks
    ) -> AsyncGenerator[OutboundMessage, None]:
        """
        Receive header blocks from a peer.
        """
        async with self.store.lock:
            for header_block in request.header_blocks:
                await self.store.add_potential_header(header_block)

        for _ in []:  # Yields nothing
            yield _

    @api_request
    async def request_sync_blocks(
        self, request: peer_protocol.RequestSyncBlocks
    ) -> AsyncGenerator[OutboundMessage, None]:
        """
        Responsd to a peers request for syncing blocks.
        """
        blocks: List[FullBlock] = []
        async with self.store.lock:
            tip_block: Optional[FullBlock] = await self.blockchain.get_block(
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
                    header_blocks: List[
                        HeaderBlock
                    ] = await self.blockchain.get_header_blocks_by_height(
                        request.heights, request.tip_header_hash
                    )
                    for header_block in header_blocks:
                        fetched = await self.blockchain.get_block(
                            header_block.header.get_hash()
                        )
                        assert fetched
                        blocks.append(fetched)
                except KeyError:
                    log.info("Do not have required blocks")
                    return
                except BlockNotInBlockchain as e:
                    log.info(f"{e}")
                    return
            else:
                # We don't have the blocks that the client is looking for
                log.info(
                    f"Peer requested tip {request.tip_header_hash} that we don't have"
                )
                return
        response = Message(
            "sync_blocks", peer_protocol.SyncBlocks(request.tip_header_hash, blocks)
        )
        yield OutboundMessage(NodeType.FULL_NODE, response, Delivery.RESPOND)

    @api_request
    async def sync_blocks(
        self, request: peer_protocol.SyncBlocks
    ) -> AsyncGenerator[OutboundMessage, None]:
        """
        We have received the blocks that we needed for syncing. Add them to processing queue.
        """
        # TODO: use an actual queue?
        async with self.store.lock:
            if not await self.store.get_sync_mode():
                log.warning("Receiving sync blocks when we are not in sync mode.")
                return

            for block in request.blocks:
                await self.store.add_potential_block(block)
                (await self.store.get_potential_blocks_received(block.height)).set()

        for _ in []:  # Yields nothing
            yield _

    @api_request
    async def request_header_hash(
        self, request: farmer_protocol.RequestHeaderHash
    ) -> AsyncGenerator[OutboundMessage, None]:
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
        assert quality_string

        async with self.store.lock:
            # Retrieves the correct head for the challenge
            heads: List[HeaderBlock] = self.blockchain.get_current_tips()
            target_head: Optional[HeaderBlock] = None
            for head in heads:
                assert head.challenge
                if head.challenge.get_hash() == request.challenge_hash:
                    target_head = head
            if target_head is None:
                # TODO: should we still allow the farmer to farm?
                log.warning(
                    f"Challenge hash: {request.challenge_hash} not in one of three heads"
                )
                return

            # TODO: use mempool to grab best transactions, for the selected head
            transactions_generator: bytes32 = sha256(b"").digest()
            # TODO: calculate the fees of these transactions
            fees: FeesTarget = FeesTarget(request.fees_target_puzzle_hash, uint64(0))
            aggregate_sig: Signature = PrivateKey.from_seed(b"12345").sign(b"anything")
            # TODO: calculate aggregate signature based on transactions
            # TODO: calculate cost of all transactions
            cost = uint64(0)

            # Creates a block with transactions, coinbase, and fees
            body: Body = Body(
                request.coinbase,
                request.coinbase_signature,
                fees,
                aggregate_sig,
                transactions_generator,
                cost,
            )

            # Creates the block header
            prev_header_hash: bytes32 = target_head.header.get_hash()
            timestamp: uint64 = uint64(int(time.time()))

            # TODO: use a real BIP158 filter based on transactions
            filter_hash: bytes32 = token_bytes(32)
            proof_of_space_hash: bytes32 = request.proof_of_space.get_hash()
            body_hash: Body = body.get_hash()
            extension_data: bytes32 = bytes32([0] * 32)
            block_header_data: HeaderData = HeaderData(
                prev_header_hash,
                timestamp,
                filter_hash,
                proof_of_space_hash,
                body_hash,
                extension_data,
            )

            block_header_data_hash: bytes32 = block_header_data.get_hash()

            # self.stores this block so we can submit it to the blockchain after it's signed by harvester
            await self.store.add_candidate_block(
                proof_of_space_hash, body, block_header_data, request.proof_of_space
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
    ) -> AsyncGenerator[OutboundMessage, None]:
        """
        Signature of header hash, by the harvester. This is enough to create an unfinished
        block, which only needs a Proof of Time to be finished. If the signature is valid,
        we call the unfinished_block routine.
        """
        async with self.store.lock:
            candidate: Optional[
                Tuple[Body, HeaderData, ProofOfSpace]
            ] = await self.store.get_candidate_block(header_signature.pos_hash)
            if candidate is None:
                log.warning(
                    f"PoS hash {header_signature.pos_hash} not found in database"
                )
                return
            # Verifies that we have the correct header and body self.stored
            block_body, block_header_data, pos = candidate

            assert block_header_data.get_hash() == header_signature.header_hash

            block_header: Header = Header(
                block_header_data, header_signature.header_signature
            )
            header: HeaderBlock = HeaderBlock(pos, None, None, block_header)
            unfinished_block_obj: FullBlock = FullBlock(header, block_body)

        # Propagate to ourselves (which validates and does further propagations)
        request = peer_protocol.UnfinishedBlock(unfinished_block_obj)
        log.error("Will call unf")
        async for m in self.unfinished_block(request):
            # Yield all new messages (propagation to peers)
            yield m

    # TIMELORD PROTOCOL
    @api_request
    async def proof_of_time_finished(
        self, request: timelord_protocol.ProofOfTimeFinished
    ) -> AsyncGenerator[OutboundMessage, None]:
        """
        A proof of time, received by a peer timelord. We can use this to complete a block,
        and call the block routine (which handles propagation and verification of blocks).
        """
        async with self.store.lock:
            dict_key = (
                request.proof.challenge_hash,
                request.proof.number_of_iterations,
            )

            unfinished_block_obj: Optional[
                FullBlock
            ] = await self.store.get_unfinished_block(dict_key)
            if not unfinished_block_obj:
                log.warning(
                    f"Received a proof of time that we cannot use to complete a block {dict_key}"
                )
                return
            prev_block: Optional[HeaderBlock] = await self.blockchain.get_header_block(
                unfinished_block_obj.prev_header_hash
            )
            difficulty: uint64 = await self.blockchain.get_next_difficulty(
                unfinished_block_obj.prev_header_hash
            )
            assert prev_block
            assert prev_block.challenge

        challenge: Challenge = Challenge(
            request.proof.challenge_hash,
            unfinished_block_obj.header_block.proof_of_space.get_hash(),
            request.proof.output.get_hash(),
            uint32(prev_block.challenge.height + 1),
            uint64(prev_block.challenge.total_weight + difficulty),
            uint64(
                prev_block.challenge.total_iters + request.proof.number_of_iterations
            ),
        )

        new_header_block = HeaderBlock(
            unfinished_block_obj.header_block.proof_of_space,
            request.proof,
            challenge,
            unfinished_block_obj.header_block.header,
        )
        new_full_block: FullBlock = FullBlock(
            new_header_block, unfinished_block_obj.body
        )

        async with self.store.lock:
            sync_mode = await self.store.get_sync_mode()

        if sync_mode:
            async with self.store.lock:
                await self.store.add_potential_future_block(new_full_block)
        else:
            async for msg in self.block(peer_protocol.Block(new_full_block)):
                yield msg

    # PEER PROTOCOL
    @api_request
    async def new_proof_of_time(
        self, new_proof_of_time: peer_protocol.NewProofOfTime
    ) -> AsyncGenerator[OutboundMessage, None]:
        """
        A proof of time, received by a peer full node. If we have the rest of the block,
        we can complete it. Otherwise, we just verify and propagate the proof.
        """
        finish_block: bool = False
        propagate_proof: bool = False
        async with self.store.lock:
            if await self.store.get_unfinished_block(
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
        self, unfinished_block: peer_protocol.UnfinishedBlock
    ) -> AsyncGenerator[OutboundMessage, None]:
        """
        We have received an unfinished block, either created by us, or from another peer.
        We can validate it and if it's a good block, propagate it to other peers and
        timelords.
        """
        log.error("CALED")
        async with self.store.lock:
            if not self.blockchain.is_child_of_head(unfinished_block.block):
                return

            if not await self.blockchain.validate_unfinished_block(
                unfinished_block.block
            ):
                raise InvalidUnfinishedBlock()

            prev_block: Optional[HeaderBlock] = await self.blockchain.get_header_block(
                unfinished_block.block.prev_header_hash
            )
            assert prev_block
            assert prev_block.challenge

            challenge_hash: bytes32 = prev_block.challenge.get_hash()
            difficulty: uint64 = await self.blockchain.get_next_difficulty(
                unfinished_block.block.header_block.prev_header_hash
            )
            vdf_ips: uint64 = await self.blockchain.get_next_ips(
                unfinished_block.block.header_block.prev_header_hash
            )

            iterations_needed: uint64 = calculate_iterations(
                unfinished_block.block.header_block.proof_of_space,
                difficulty,
                vdf_ips,
                constants["MIN_BLOCK_TIME"],
            )

            if await self.store.get_unfinished_block(
                (challenge_hash, iterations_needed)
            ) is not None:
                return

        expected_time: uint64 = uint64(
            int(iterations_needed / (await self.store.get_proof_of_time_estimate_ips()))
        )

        if expected_time > constants["PROPAGATION_DELAY_THRESHOLD"]:
            log.info(f"Block is slow, expected {expected_time} seconds, waiting")
            # If this block is slow, sleep to allow faster blocks to come out first
            await asyncio.sleep(3)

        async with self.store.lock:
            leader: Tuple[uint32, uint64] = self.store.get_unfinished_block_leader()
            if leader is None or unfinished_block.block.height > leader[0]:
                log.info(
                    f"This is the first block at height {unfinished_block.block.height}, so propagate."
                )
                # If this is the first block we see at this height, propagate
                self.store.set_unfinished_block_leader(
                    (unfinished_block.block.height, expected_time)
                )
            elif unfinished_block.block.height == leader[0]:
                if expected_time > leader[1] + constants["PROPAGATION_THRESHOLD"]:
                    # If VDF is expected to finish X seconds later than the best, don't propagate
                    log.info(
                        f"VDF will finish too late {expected_time} seconds, so don't propagate"
                    )
                    return
                elif expected_time < leader[1]:
                    log.info(
                        f"New best unfinished block at height {unfinished_block.block.height}"
                    )
                    # If this will be the first block to finalize, update our leader
                    self.store.set_unfinished_block_leader((leader[0], expected_time))
            else:
                # If we have seen an unfinished block at a greater or equal height, don't propagate
                log.info(f"Unfinished block at old height, so don't propagate")
                return

            await self.store.add_unfinished_block(
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
    async def block(
        self, block: peer_protocol.Block
    ) -> AsyncGenerator[OutboundMessage, None]:
        """
        Receive a full block from a peer full node (or ourselves).
        """

        header_hash = block.block.header_block.header.get_hash()

        async with self.store.lock:
            if await self.store.get_sync_mode():
                # Add the block to our potential tips list
                await self.store.add_potential_tip(block.block)
                return
            # Record our minimum height, and whether we have a full set of heads
            least_height: uint32 = min(
                [h.height for h in self.blockchain.get_current_tips()]
            )
            full_heads: bool = len(self.blockchain.get_current_tips()) == constants[
                "NUMBER_OF_HEADS"
            ]

            # Tries to add the block to the blockchain
            added: ReceiveBlockResult = await self.blockchain.receive_block(block.block)
        if added == ReceiveBlockResult.ALREADY_HAVE_BLOCK:
            return
        elif added == ReceiveBlockResult.INVALID_BLOCK:
            log.warning(
                f"Block {header_hash} at height {block.block.height} is invalid."
            )
            return
        elif added == ReceiveBlockResult.DISCONNECTED_BLOCK:
            log.warning(f"Disconnected block {header_hash}")
            async with self.store.lock:
                tip_height = max(
                    [head.height for head in self.blockchain.get_current_tips()]
                )

            if (
                block.block.height
                > tip_height + self.config["sync_blocks_behind_threshold"]
            ):
                async with self.store.lock:
                    await self.store.clear_sync_info()
                    await self.store.add_potential_tip(block.block)
                log.info(
                    f"We are too far behind this block. Our height is {tip_height} and block is at "
                    f"{block.block.height}"
                )
                # Perform a sync if we have to
                await self.store.set_sync_mode(True)
                try:
                    # Performs sync, and catch exceptions so we don't close the connection
                    async for msg in self._sync():
                        yield msg
                except asyncio.CancelledError:
                    log.warning("Syncing failed, CancelledError")
                except BaseException as e:
                    log.warning(f"Error {type(e)}{e} with syncing")
                finally:
                    async with self.store.lock:
                        await self.store.set_sync_mode(False)
                        await self.store.clear_sync_info()
                        return

            elif block.block.height > tip_height + 1:
                log.info(
                    f"We are a few blocks behind, our height is {tip_height} and block is at "
                    f"{block.block.height} so we will request these blocks."
                )
                while True:
                    # TODO: download a few blocks and add them to chain
                    # prev_block_hash = block.block.header_block.header.data.prev_header_hash
                    break
            return
        elif added == ReceiveBlockResult.ADDED_TO_HEAD:
            # Only propagate blocks which extend the blockchain (becomes one of the heads)
            # A deep reorg happens can be deteceted when we add a block to the heads, that has a worse
            # height than the worst one (assuming we had a full set of heads).
            deep_reorg: bool = (block.block.height < least_height) and full_heads
            ips_changed: bool = False
            async with self.store.lock:
                log.info(
                    f"Updated heads, new heights: {[b.height for b in self.blockchain.get_current_tips()]}"
                )

                difficulty = await self.blockchain.get_next_difficulty(
                    block.block.prev_header_hash
                )
                next_vdf_ips = await self.blockchain.get_next_ips(
                    block.block.header_hash
                )
                log.info(f"Difficulty {difficulty} IPS {next_vdf_ips}")
                if next_vdf_ips != await self.store.get_proof_of_time_estimate_ips():
                    await self.store.set_proof_of_time_estimate_ips(next_vdf_ips)
                    ips_changed = True
            if ips_changed:
                rate_update = farmer_protocol.ProofOfTimeRate(next_vdf_ips)
                log.error(f"Sending proof of time rate {next_vdf_ips}")
                yield OutboundMessage(
                    NodeType.FARMER,
                    Message("proof_of_time_rate", rate_update),
                    Delivery.BROADCAST,
                )
            if deep_reorg:
                reorg_msg = farmer_protocol.DeepReorgNotification()
                yield OutboundMessage(
                    NodeType.FARMER,
                    Message("deep_reorg", reorg_msg),
                    Delivery.BROADCAST,
                )

            assert block.block.header_block.proof_of_time
            assert block.block.header_block.challenge
            pos_quality = (
                block.block.header_block.proof_of_space.verify_and_get_quality()
            )

            farmer_request = farmer_protocol.ProofOfSpaceFinalized(
                block.block.header_block.challenge.get_hash(),
                block.block.header_block.challenge.height,
                pos_quality,
                difficulty,
            )
            timelord_request = timelord_protocol.ChallengeStart(
                block.block.header_block.challenge.get_hash(),
                block.block.header_block.challenge.total_weight,
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
            assert block.block.header_block.proof_of_time
            assert block.block.header_block.challenge
            log.info(
                f"Received orphan block of height {block.block.header_block.challenge.height}"
            )
        else:
            # Should never reach here, all the cases are covered
            assert False

    @api_request
    async def peers(
        self, request: peer_protocol.Peers
    ) -> AsyncGenerator[OutboundMessage, None]:
        conns = self.server.global_connections
        log.info(f"Received peer list: {request.peer_list}")
        for peer in request.peer_list:
            conns.peers.add(peer)

        # Pseudo-message to close the connection
        yield OutboundMessage(NodeType.INTRODUCER, Message("", None), Delivery.CLOSE)

        unconnected = conns.get_unconnected_peers()
        to_connect = unconnected[: self._num_needed_peers()]
        if not len(to_connect):
            return

        log.info(f"Trying to connect to peers: {to_connect}")
        tasks = []
        for peer in to_connect:
            tasks.append(asyncio.create_task(self.server.start_client(peer)))
        await asyncio.gather(*tasks)
