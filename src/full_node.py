import logging
import time
import asyncio
import yaml
import concurrent
from secrets import token_bytes
from hashlib import sha256
from chiapos import Verifier
from blspy import Signature, PrivateKey
from asyncio import Event
from typing import List, Optional, AsyncGenerator, Tuple
from src.util.api_decorators import api_request
from src.util.ints import uint64, uint32
from src.util import errors
from src.protocols import farmer_protocol
from src.protocols import timelord_protocol
from src.protocols import peer_protocol
from src.types.sized_bytes import bytes32
from src.types.block_body import BlockBody
from src.types.trunk_block import TrunkBlock
from src.types.challenge import Challenge
from src.types.block_header import BlockHeaderData, BlockHeader
from src.types.full_block import FullBlock
from src.types.fees_target import FeesTarget
from src.consensus.weight_verifier import verify_weight
from src.consensus.pot_iterations import calculate_iterations
from src.consensus.constants import constants
from src.blockchain import Blockchain, ReceiveBlockResult
from src.server.outbound_message import OutboundMessage, Delivery, NodeType, Message
from src.util.errors import BlockNotInBlockchain, PeersDontHaveBlock, InvalidUnfinishedBlock
from src.store.full_node_store import FullNodeStore


log = logging.getLogger(__name__)


class FullNode:
    store: FullNodeStore
    blockchain: Blockchain
    config = yaml.safe_load(open("src/config/full_node.yaml", "r"))

    def __init__(self, store: FullNodeStore, blockchain: Blockchain):
        self.store = store
        self.blockchain = blockchain

    async def send_heads_to_farmers(self) -> AsyncGenerator[OutboundMessage, None]:
        """
        Sends all of the current heads to all farmer peers. Also sends the latest
        estimated proof of time rate, so farmer can calulate which proofs are good.
        """
        requests: List[farmer_protocol.ProofOfSpaceFinalized] = []
        async with (await self.store.get_lock()):
            for head in self.blockchain.get_current_heads():
                assert head.proof_of_time and head.challenge
                prev_challenge_hash = head.proof_of_time.output.challenge_hash
                challenge_hash = head.challenge.get_hash()
                height = head.challenge.height
                quality = head.proof_of_space.verify_and_get_quality(prev_challenge_hash)
                if head.height > 0:
                    difficulty: uint64 = await self.blockchain.get_next_difficulty(head.prev_header_hash)
                else:
                    difficulty = head.weight
                requests.append(farmer_protocol.ProofOfSpaceFinalized(challenge_hash, height,
                                                                      quality, difficulty))
            proof_of_time_rate: uint64 = await self.store.get_proof_of_time_estimate_ips()
        for request in requests:
            yield OutboundMessage(NodeType.FARMER, Message("proof_of_space_finalized", request), Delivery.BROADCAST)
        rate_update = farmer_protocol.ProofOfTimeRate(proof_of_time_rate)
        yield OutboundMessage(NodeType.FARMER, Message("proof_of_time_rate", rate_update), Delivery.BROADCAST)

    async def send_challenges_to_timelords(self) -> AsyncGenerator[OutboundMessage, None]:
        """
        Sends all of the current heads to all timelord peers.
        """
        requests: List[timelord_protocol.ChallengeStart] = []
        async with (await self.store.get_lock()):
            for head in self.blockchain.get_current_heads():
                assert head.challenge
                challenge_hash = head.challenge.get_hash()
                requests.append(timelord_protocol.ChallengeStart(challenge_hash, head.challenge.height))

        for request in requests:
            yield OutboundMessage(NodeType.TIMELORD, Message("challenge_start", request), Delivery.BROADCAST)

    async def on_connect(self) -> AsyncGenerator[OutboundMessage, None]:
        """
        Whenever we connect to another full node, send them our current heads.
        """
        blocks: List[FullBlock] = []

        async with (await self.store.get_lock()):
            heads: List[TrunkBlock] = self.blockchain.get_current_heads()
            for h in heads:
                block = await self.blockchain.get_block(h.header.get_hash())
                assert block
                blocks.append(block)
        for block in blocks:
            request = peer_protocol.Block(block)
            yield OutboundMessage(NodeType.FULL_NODE, Message("block", request), Delivery.RESPOND)

    async def sync(self):
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

        # Based on responses from peers about the current heads, see which head is the heaviest
        # (similar to longest chain rule).
        async with (await self.store.get_lock()):
            potential_heads = (await self.store.get_potential_heads()).items()
            log.info(f"Have collected {len(potential_heads)} potential heads")
            for header_hash, _ in potential_heads:
                block = await self.store.get_potential_heads_full_block(header_hash)
                if block.trunk_block.challenge.total_weight > highest_weight:
                    highest_weight = block.trunk_block.challenge.total_weight
                    tip_block = block
                    tip_height = block.trunk_block.challenge.height
            if highest_weight <= max([t.weight for t in self.blockchain.get_current_heads()]):
                log.info("Not performing sync, already caught up.")
                await self.store.set_sync_mode(False)
                await self.store.clear_sync_information()
                return
        assert tip_block

        # Now, we download all of the headers in order to verify the weight
        # TODO: use queue here, request a few at a time
        # TODO: send multiple API calls out at once
        timeout = 20
        sleep_interval = 3
        total_time_slept = 0
        trunks: List[TrunkBlock] = []
        while total_time_slept < timeout:
            for start_height in range(0, tip_height + 1, self.config['max_trunks_to_send']):
                end_height = min(start_height + self.config['max_trunks_to_send'], tip_height + 1)
                request = peer_protocol.RequestTrunkBlocks(tip_block.trunk_block.header.get_hash(),
                                                           [uint64(h) for h in range(start_height, end_height)])
                # TODO: should we ask the same peer as before, for the trunks?
                yield OutboundMessage(NodeType.FULL_NODE, Message("request_trunk_blocks", request), Delivery.RANDOM)
            await asyncio.sleep(sleep_interval)
            total_time_slept += sleep_interval
            async with (await self.store.get_lock()):
                received_all_trunks = True
                local_trunks = []
                for height in range(0, tip_height + 1):
                    if await self.store.get_potential_trunk(uint32(height)) is None:
                        received_all_trunks = False
                        break
                    local_trunks.append(await self.store.get_potential_trunk(uint32(height)))
                if received_all_trunks:
                    trunks = local_trunks
                    break
        if not verify_weight(tip_block.trunk_block, trunks):
            # TODO: ban peers that provided the invalid heads or proofs
            raise errors.InvalidWeight(f"Weight of {tip_block.trunk_block.header.get_hash()} not valid.")

        log.error(f"Downloaded trunks up to tip height: {tip_height}")
        log.error(f"Tip height: {len(trunks)}")
        assert tip_height + 1 == len(trunks)

        async with (await self.store.get_lock()):
            fork_point: TrunkBlock = self.blockchain.find_fork_point(trunks)

        # TODO: optimize, send many requests at once, and for more blocks
        for height in range(fork_point.height + 1, tip_height + 1):
            # Only download from fork point (what we don't have)
            async with (await self.store.get_lock()):
                have_block = await self.store.get_potential_heads_full_block(trunks[height].header.get_hash()) \
                    is not None

            if not have_block:
                request_sync = peer_protocol.RequestSyncBlocks(tip_block.trunk_block.header.header_hash,
                                                               [uint64(height)])
                async with (await self.store.get_lock()):
                    await self.store.set_potential_blocks_received(uint32(height), Event())
                found = False
                for _ in range(30):
                    yield OutboundMessage(NodeType.FULL_NODE, Message("request_sync_blocks", request_sync),
                                          Delivery.RANDOM)
                    try:
                        await asyncio.wait_for((await self.store.get_potential_blocks_received(uint32(height))).wait(),
                                               timeout=2)
                        found = True
                        break
                    except concurrent.futures.TimeoutError:
                        log.info("Did not receive desired block")
                if not found:
                    raise PeersDontHaveBlock(f"Did not receive desired block at height {height}")
            async with (await self.store.get_lock()):
                # TODO: ban peers that provide bad blocks
                if have_block:
                    block = await self.store.get_potential_heads_full_block(trunks[height].header.get_hash())
                else:
                    block = await self.store.get_potential_block(uint32(height))
                assert block

                start = time.time()
                await self.blockchain.receive_block(block)
                log.info(f"Took {time.time() - start}")
                assert max([h.height for h in self.blockchain.get_current_heads()]) >= height
                # db.full_blocks[block.trunk_block.header.get_hash()] = block
                await self.store.set_proof_of_time_estimate_ips(await self.blockchain.get_next_ips(block.header_hash))

        async with (await self.store.get_lock()):
            log.info(f"Finishead sync up to height {tip_height}")
            await self.store.set_sync_mode(False)
            await self.store.clear_sync_information()

    @api_request
    async def request_trunk_blocks(self, request: peer_protocol.RequestTrunkBlocks) \
            -> AsyncGenerator[OutboundMessage, None]:
        """
        A peer requests a list of trunk blocks, by height. Used for syncing or light clients.
        """
        if len(request.heights) > self.config['max_trunks_to_send']:
            raise errors.TooManyTrunksRequested(f"The max number of trunks is {self.config['max_trunks_to_send']},\
                                                but requested {len(request.heights)}")
        log.info("Getting lock")
        async with (await self.store.get_lock()):
            try:
                log.info("Getting trunks")
                trunks: List[TrunkBlock] = await self.blockchain.get_trunk_blocks_by_height(request.heights,
                                                                                            request.tip_header_hash)
                log.info("Got trunks")
            except KeyError:
                log.info("Do not have required blocks")
                return
            except BlockNotInBlockchain as e:
                log.info(f"{e}")
                return

        response = peer_protocol.TrunkBlocks(request.tip_header_hash, trunks)
        yield OutboundMessage(NodeType.FULL_NODE, Message("trunk_blocks", response), Delivery.RESPOND)

    @api_request
    async def trunk_blocks(self, request: peer_protocol.TrunkBlocks) \
            -> AsyncGenerator[OutboundMessage, None]:
        """
        Receive trunk blocks from a peer.
        """
        async with (await self.store.get_lock()):
            for trunk_block in request.trunk_blocks:
                await self.store.add_potential_trunk(trunk_block)

        for _ in []:  # Yields nothing
            yield _

    @api_request
    async def request_sync_blocks(self, request: peer_protocol.RequestSyncBlocks) \
            -> AsyncGenerator[OutboundMessage, None]:
        """
        Responsd to a peers request for syncing blocks.
        """
        blocks: List[FullBlock] = []
        async with (await self.store.get_lock()):
            tip_block: Optional[FullBlock] = await self.blockchain.get_block(request.tip_header_hash)
            if tip_block is not None:
                if len(request.heights) > self.config['max_blocks_to_send']:
                    raise errors.TooManyTrunksRequested(f"The max number of blocks is "
                                                        f"{self.config['max_blocks_to_send']},"
                                                        f"but requested {len(request.heights)}")
                try:
                    trunk_blocks: List[TrunkBlock] = await self.blockchain.get_trunk_blocks_by_height(
                            request.heights, request.tip_header_hash)
                    for trunk_block in trunk_blocks:
                        fetched = await self.blockchain.get_block(trunk_block.header.get_hash())
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
                log.info(f"Peer requested tip {request.tip_header_hash} that we don't have")
                return
        response = Message("sync_blocks", peer_protocol.SyncBlocks(request.tip_header_hash, blocks))
        yield OutboundMessage(NodeType.FULL_NODE, response, Delivery.RESPOND)

    @api_request
    async def sync_blocks(self, request: peer_protocol.SyncBlocks) -> AsyncGenerator[OutboundMessage, None]:
        """
        We have received the blocks that we needed for syncing. Add them to processing queue.
        """
        # TODO: use an actual queue?
        async with (await self.store.get_lock()):
            if not await self.store.get_sync_mode():
                log.warning("Receiving sync blocks when we are not in sync mode.")
                return

            for block in request.blocks:
                await self.store.add_potential_block(block)
                (await self.store.get_potential_blocks_received(block.height)).set()

        for _ in []:  # Yields nothing
            yield _

    @api_request
    async def request_header_hash(self, request: farmer_protocol.RequestHeaderHash) \
            -> AsyncGenerator[OutboundMessage, None]:
        """
        Creates a block body and header, with the proof of space, coinbase, and fee targets provided
        by the farmer, and sends the hash of the header data back to the farmer.
        """
        plot_seed: bytes32 = request.proof_of_space.get_plot_seed()

        # Checks that the proof of space is valid
        quality_string: bytes = Verifier().validate_proof(plot_seed, request.proof_of_space.size,
                                                          request.challenge_hash,
                                                          bytes(request.proof_of_space.proof))
        assert quality_string

        async with (await self.store.get_lock()):
            # Retrieves the correct head for the challenge
            heads: List[TrunkBlock] = self.blockchain.get_current_heads()
            target_head: Optional[TrunkBlock] = None
            for head in heads:
                assert head.challenge
                if head.challenge.get_hash() == request.challenge_hash:
                    target_head = head
            if target_head is None:
                # TODO: should we still allow the farmer to farm?
                log.warning(f"Challenge hash: {request.challenge_hash} not in one of three heads")
                return

            # TODO: use mempool to grab best transactions, for the selected head
            transactions_generator: bytes32 = sha256(b"").digest()
            # TODO: calculate the fees of these transactions
            fees: FeesTarget = FeesTarget(request.fees_target_puzzle_hash, uint64(0))
            aggregate_sig: Signature = PrivateKey.from_seed(b"12345").sign(b"anything")
            # TODO: calculate aggregate signature based on transactions

            # Creates a block with transactions, coinbase, and fees
            body: BlockBody = BlockBody(request.coinbase, request.coinbase_signature,
                                        fees, aggregate_sig, transactions_generator)

            # Creates the block header
            prev_header_hash: bytes32 = target_head.header.get_hash()
            timestamp: uint64 = uint64(int(time.time()))

            # TODO: use a real BIP158 filter based on transactions
            filter_hash: bytes32 = token_bytes(32)
            proof_of_space_hash: bytes32 = request.proof_of_space.get_hash()
            body_hash: BlockBody = body.get_hash()
            extension_data: bytes32 = bytes32([0] * 32)
            block_header_data: BlockHeaderData = BlockHeaderData(prev_header_hash, timestamp,
                                                                 filter_hash, proof_of_space_hash,
                                                                 body_hash, extension_data)

            block_header_data_hash: bytes32 = block_header_data.get_hash()

            # self.stores this block so we can submit it to the blockchain after it's signed by plotter
            await self.store.add_candidate_block(proof_of_space_hash, (body, block_header_data, request.proof_of_space))

        message = farmer_protocol.HeaderHash(proof_of_space_hash, block_header_data_hash)
        yield OutboundMessage(NodeType.FARMER, Message("header_hash", message), Delivery.RESPOND)

    @api_request
    async def header_signature(self, header_signature: farmer_protocol.HeaderSignature) \
            -> AsyncGenerator[OutboundMessage, None]:
        """
        Signature of header hash, by the plotter. This is enough to create an unfinished
        block, which only needs a Proof of Time to be finished. If the signature is valid,
        we call the unfinished_block routine.
        """
        async with (await self.store.get_lock()):
            if (await self.store.get_candidate_block(header_signature.pos_hash)) is None:
                log.warning(f"PoS hash {header_signature.pos_hash} not found in database")
                return
            # Verifies that we have the correct header and body self.stored
            block_body, block_header_data, pos = await self.store.get_candidate_block(header_signature.pos_hash)

            assert block_header_data.get_hash() == header_signature.header_hash

            block_header: BlockHeader = BlockHeader(block_header_data, header_signature.header_signature)
            trunk: TrunkBlock = TrunkBlock(pos, None, None, block_header)
            unfinished_block_obj: FullBlock = FullBlock(trunk, block_body)

        # Propagate to ourselves (which validates and does further propagations)
        request = peer_protocol.UnfinishedBlock(unfinished_block_obj)
        async for m in self.unfinished_block(request):
            # Yield all new messages (propagation to peers)
            yield m

    # TIMELORD PROTOCOL
    @api_request
    async def proof_of_time_finished(self, request: timelord_protocol.ProofOfTimeFinished) -> \
            AsyncGenerator[OutboundMessage, None]:
        """
        A proof of time, received by a peer timelord. We can use this to complete a block,
        and call the block routine (which handles propagation and verification of blocks).
        """
        async with (await self.store.get_lock()):
            dict_key = (request.proof.output.challenge_hash, request.proof.output.number_of_iterations)

            unfinished_block_obj: Optional[FullBlock] = await self.store.get_unfinished_block(dict_key)
            if not unfinished_block_obj:
                log.warning(f"Received a proof of time that we cannot use to complete a block {dict_key}")
                return
            prev_block: Optional[TrunkBlock] = await self.blockchain.get_trunk_block(
                    unfinished_block_obj.prev_header_hash)
            difficulty: uint64 = await self.blockchain.get_next_difficulty(unfinished_block_obj.prev_header_hash)
            assert prev_block
            assert prev_block.challenge

        challenge: Challenge = Challenge(unfinished_block_obj.trunk_block.proof_of_space.get_hash(),
                                         request.proof.output.get_hash(),
                                         uint32(prev_block.challenge.height + 1),
                                         uint64(prev_block.challenge.total_weight + difficulty),
                                         uint64(prev_block.challenge.total_iters +
                                                request.proof.output.number_of_iterations))

        new_trunk_block = TrunkBlock(unfinished_block_obj.trunk_block.proof_of_space,
                                     request.proof,
                                     challenge,
                                     unfinished_block_obj.trunk_block.header)
        new_full_block: FullBlock = FullBlock(new_trunk_block, unfinished_block_obj.body)

        async for msg in self.block(peer_protocol.Block(new_full_block)):
            yield msg

    # PEER PROTOCOL
    @api_request
    async def new_proof_of_time(self, new_proof_of_time: peer_protocol.NewProofOfTime) \
            -> AsyncGenerator[OutboundMessage, None]:
        """
        A proof of time, received by a peer full node. If we have the rest of the block,
        we can complete it. Otherwise, we just verify and propagate the proof.
        """
        finish_block: bool = False
        propagate_proof: bool = False
        async with (await self.store.get_lock()):
            if (await self.store.get_unfinished_block((new_proof_of_time.proof.output.challenge_hash,
                                                       new_proof_of_time.proof.output.number_of_iterations))):
                finish_block = True
            elif new_proof_of_time.proof.is_valid(constants["DISCRIMINANT_SIZE_BITS"]):
                propagate_proof = True
        if finish_block:
            request = timelord_protocol.ProofOfTimeFinished(new_proof_of_time.proof)
            async for msg in self.proof_of_time_finished(request):
                yield msg
        if propagate_proof:
            # TODO: perhaps don't propagate everything, this is a DoS vector
            yield OutboundMessage(NodeType.FULL_NODE, Message("new_proof_of_time", new_proof_of_time),
                                  Delivery.BROADCAST_TO_OTHERS)

    @api_request
    async def unfinished_block(self, unfinished_block: peer_protocol.UnfinishedBlock) \
            -> AsyncGenerator[OutboundMessage, None]:
        """
        We have received an unfinished block, either created by us, or from another peer.
        We can validate it and if it's a good block, propagate it to other peers and
        timelords.
        """
        async with (await self.store.get_lock()):
            if not self.blockchain.is_child_of_head(unfinished_block.block):
                return

            if not await self.blockchain.validate_unfinished_block(unfinished_block.block):
                raise InvalidUnfinishedBlock()

            prev_block: Optional[TrunkBlock] = await self.blockchain.get_trunk_block(
                    unfinished_block.block.prev_header_hash)
            assert prev_block
            assert prev_block.challenge

            challenge_hash: bytes32 = prev_block.challenge.get_hash()
            difficulty: uint64 = await self.blockchain.get_next_difficulty(
                unfinished_block.block.trunk_block.prev_header_hash)
            vdf_ips: uint64 = await self.blockchain.get_next_ips(
                unfinished_block.block.trunk_block.prev_header_hash)

            iterations_needed: uint64 = calculate_iterations(unfinished_block.block.trunk_block.proof_of_space,
                                                             challenge_hash, difficulty, vdf_ips,
                                                             constants["MIN_BLOCK_TIME"])

            if await self.store.get_unfinished_block((challenge_hash, iterations_needed)):
                return

        expected_time: uint64 = uint64(int(iterations_needed / (await self.store.get_proof_of_time_estimate_ips())))

        if expected_time > constants["PROPAGATION_DELAY_THRESHOLD"]:
            log.info(f"Block is slow, expected {expected_time} seconds, waiting")
            # If this block is slow, sleep to allow faster blocks to come out first
            await asyncio.sleep(3)

        async with (await self.store.get_lock()):
            leader: Tuple[uint32, uint64] = await self.store.get_unfinished_block_leader()
            if unfinished_block.block.height > leader[0]:
                log.info(f"This is the first block at height {unfinished_block.block.height}, so propagate.")
                # If this is the first block we see at this height, propagate
                await self.store.set_unfinished_block_leader((unfinished_block.block.height, expected_time))
            elif unfinished_block.block.height == leader[0]:
                if expected_time > leader[1] + constants["PROPAGATION_THRESHOLD"]:
                    # If VDF is expected to finish X seconds later than the best, don't propagate
                    log.info(f"VDF will finish too late {expected_time} seconds, so don't propagate")
                    return
                elif expected_time < leader[1]:
                    log.info(f"New best unfinished block at height {unfinished_block.block.height}")
                    # If this will be the first block to finalize, update our leader
                    await self.store.set_unfinished_block_leader((leader[0], expected_time))
            else:
                # If we have seen an unfinished block at a greater or equal height, don't propagate
                log.info(f"Unfinished block at old height, so don't propagate")
                return

            await self.store.add_unfinished_block((challenge_hash, iterations_needed), unfinished_block.block)

        timelord_request = timelord_protocol.ProofOfSpaceInfo(challenge_hash, iterations_needed)

        yield OutboundMessage(NodeType.TIMELORD, Message("proof_of_space_info", timelord_request), Delivery.BROADCAST)
        yield OutboundMessage(NodeType.FULL_NODE, Message("unfinished_block", unfinished_block),
                              Delivery.BROADCAST_TO_OTHERS)

    @api_request
    async def block(self, block: peer_protocol.Block) -> AsyncGenerator[OutboundMessage, None]:
        """
        Receive a full block from a peer full node (or ourselves).
        """

        header_hash = block.block.trunk_block.header.get_hash()

        async with (await self.store.get_lock()):
            if await self.store.get_sync_mode():
                # Add the block to our potential heads list
                await self.store.add_potential_head(header_hash)
                await self.store.add_potential_heads_full_block(block.block)
                return

            added: ReceiveBlockResult = await self.blockchain.receive_block(block.block)

        if added == ReceiveBlockResult.ALREADY_HAVE_BLOCK:
            return
        elif added == ReceiveBlockResult.INVALID_BLOCK:
            log.warning(f"Block {header_hash} at height {block.block.height} is invalid.")
            return
        elif added == ReceiveBlockResult.DISCONNECTED_BLOCK:
            log.warning(f"Disconnected block")
            async with (await self.store.get_lock()):
                tip_height = max([head.height for head in self.blockchain.get_current_heads()])
            if block.block.height > tip_height + self.config["sync_blocks_behind_threshold"]:
                async with (await self.store.get_lock()):
                    await self.store.clear_sync_information()
                    await self.store.add_potential_head(header_hash)
                    await self.store.add_potential_heads_full_block(block.block)
                log.info(f"We are too far behind this block. Our height is {tip_height} and block is at "
                         f"{block.block.height}")
                # Perform a sync if we have to
                await self.store.set_sync_mode(True)
                try:
                    # Performs sync, and catch exceptions so we don't close the connection
                    async for msg in self.sync():
                        yield msg
                except asyncio.CancelledError:
                    log.warning("Syncing failed, CancelledError")
                except BaseException as e:
                    log.warning(f"Error {e} with syncing")
                finally:
                    return

            elif block.block.height > tip_height + 1:
                log.info(f"We are a few blocks behind, our height is {tip_height} and block is at "
                         f"{block.block.height} so we will request these blocks.")
                while True:
                    # TODO: download a few blocks and add them to chain
                    # prev_block_hash = block.block.trunk_block.header.data.prev_header_hash
                    break
            return
        elif added == ReceiveBlockResult.ADDED_TO_HEAD:
            # Only propagate blocks which extend the blockchain (one of the heads)
            ips_changed: bool = False
            async with (await self.store.get_lock()):
                log.info(f"\tUpdated heads, new heights: {[b.height for b in self.blockchain.get_current_heads()]}")
                difficulty = await self.blockchain.get_next_difficulty(block.block.prev_header_hash)
                next_vdf_ips = await self.blockchain.get_next_ips(block.block.header_hash)
                log.info(f"Difficulty {difficulty} IPS {next_vdf_ips}")
                if next_vdf_ips != await self.store.get_proof_of_time_estimate_ips():
                    await self.store.set_proof_of_time_estimate_ips(next_vdf_ips)
                    ips_changed = True
            if ips_changed:
                rate_update = farmer_protocol.ProofOfTimeRate(next_vdf_ips)
                log.error(f"Sending proof of time rate {next_vdf_ips}")
                yield OutboundMessage(NodeType.FARMER, Message("proof_of_time_rate", rate_update),
                                      Delivery.BROADCAST)
            assert block.block.trunk_block.proof_of_time
            assert block.block.trunk_block.challenge
            pos_quality = block.block.trunk_block.proof_of_space.verify_and_get_quality(
                block.block.trunk_block.proof_of_time.output.challenge_hash
            )
            farmer_request = farmer_protocol.ProofOfSpaceFinalized(block.block.trunk_block.challenge.get_hash(),
                                                                   block.block.trunk_block.challenge.height,
                                                                   pos_quality,
                                                                   difficulty)
            timelord_request = timelord_protocol.ChallengeStart(block.block.trunk_block.challenge.get_hash(),
                                                                block.block.trunk_block.challenge.height)
            timelord_request_end = timelord_protocol.ChallengeEnd(block.block.trunk_block.proof_of_time.
                                                                  output.challenge_hash)
            # Tell timelord to stop previous challenge and start with new one
            yield OutboundMessage(NodeType.TIMELORD, Message("challenge_end", timelord_request_end), Delivery.BROADCAST)
            yield OutboundMessage(NodeType.TIMELORD, Message("challenge_start", timelord_request), Delivery.BROADCAST)

            # Tell full nodes about the new block
            yield OutboundMessage(NodeType.FULL_NODE, Message("block", block), Delivery.BROADCAST_TO_OTHERS)

            # Tell farmer about the new block
            yield OutboundMessage(NodeType.FARMER, Message("proof_of_space_finalized", farmer_request),
                                  Delivery.BROADCAST)
        elif added == ReceiveBlockResult.ADDED_AS_ORPHAN:
            assert block.block.trunk_block.proof_of_time
            assert block.block.trunk_block.challenge
            log.info("I've received an orphan, stopping the proof of time challenge.")
            log.info(f"Height of the orphan block is {block.block.trunk_block.challenge.height}")
            timelord_request_end = timelord_protocol.ChallengeEnd(block.block.trunk_block.proof_of_time.
                                                                  output.challenge_hash)
            yield OutboundMessage(NodeType.TIMELORD, Message("challenge_end", timelord_request_end), Delivery.BROADCAST)
        else:
            # Should never reach here, all the cases are covered
            assert False
