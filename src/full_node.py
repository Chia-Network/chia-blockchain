import logging
import time
import asyncio
import collections
import yaml
import concurrent
from secrets import token_bytes
from hashlib import sha256
from chiapos import Verifier
from blspy import Signature, PrivateKey
from asyncio import Lock, sleep, Event
from typing import Dict, List, Tuple, Optional, AsyncGenerator, Counter
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
from src.types.proof_of_space import ProofOfSpace
from src.types.full_block import FullBlock
from src.types.fees_target import FeesTarget
from src.consensus.weight_verifier import verify_weight
from src.consensus.pot_iterations import calculate_iterations
from src.consensus.constants import constants
from src.blockchain import Blockchain, ReceiveBlockResult
from src.server.outbound_message import OutboundMessage, Delivery, NodeType, Message
from src.util.errors import BlockNotInBlockchain, PeersDontHaveBlock, InvalidUnfinishedBlock


class Database:
    # This protects all other resources
    lock: Lock = Lock()
    blockchain: Blockchain = Blockchain()
    full_blocks: Dict[str, FullBlock] = {
        FullBlock.from_bytes(constants["GENESIS_BLOCK"]).trunk_block.header.header_hash:
        FullBlock.from_bytes(constants["GENESIS_BLOCK"])}

    sync_mode: bool = True
    # Block headers and blocks which we think might be heads, but we haven't verified yet.
    # All these are used during sync mode
    potential_heads: Counter[bytes32] = collections.Counter()
    potential_heads_full_blocks: Dict[bytes32, FullBlock] = collections.Counter()
    # Headers/trunks downloaded for the during sync, by height
    potential_trunks: Dict[uint32, TrunkBlock] = {}
    # Blocks downloaded during sync, by height
    potential_blocks: Dict[uint32, FullBlock] = {}
    # Event, which gets set whenever we receive the block at each height. Waited for by sync().
    potential_blocks_received: Dict[uint32, Event] = {}

    # These are the blocks that we created, but don't have the PoS from farmer yet,
    # keyed from the proof of space hash
    candidate_blocks: Dict[bytes32, Tuple[BlockBody, BlockHeaderData, ProofOfSpace]] = {}

    # These are the blocks that we created, have PoS, but not PoT yet, keyed from the
    # block header hash
    unfinished_blocks: Dict[Tuple[bytes32, uint64], FullBlock] = {}
    # Latest height with unfinished blocks, and expected timestamp of the finishing
    unfinished_blocks_leader: Tuple[uint32, uint64] = (uint32(0), uint64(9999999999))

    proof_of_time_estimate_ips: uint64 = uint64(1500)


config = yaml.safe_load(open("src/config/full_node.yaml", "r"))
log = logging.getLogger(__name__)
db = Database()


async def send_heads_to_farmers() -> AsyncGenerator[OutboundMessage, None]:
    """
    Sends all of the current heads to all farmer peers. Also sends the latest
    estimated proof of time rate, so farmer can calulate which proofs are good.
    """
    requests: List[farmer_protocol.ProofOfSpaceFinalized] = []
    async with db.lock:
        for head in db.blockchain.get_current_heads():
            prev_challenge_hash = head.proof_of_time.output.challenge_hash
            challenge_hash = head.challenge.get_hash()
            height = head.challenge.height
            quality = head.proof_of_space.verify_and_get_quality(prev_challenge_hash)
            difficulty: uint64 = db.blockchain.get_difficulty(head.header.get_hash())
            requests.append(farmer_protocol.ProofOfSpaceFinalized(challenge_hash, height,
                                                                  quality, difficulty))
        proof_of_time_rate: uint64 = db.proof_of_time_estimate_ips
    for request in requests:
        yield OutboundMessage(NodeType.FARMER, Message("proof_of_space_finalized", request), Delivery.BROADCAST)
    rate_update = farmer_protocol.ProofOfTimeRate(proof_of_time_rate)
    yield OutboundMessage(NodeType.FARMER, Message("proof_of_time_rate", rate_update), Delivery.BROADCAST)


async def send_challenges_to_timelords() -> AsyncGenerator[OutboundMessage, None]:
    """
    Sends all of the current heads to all timelord peers.
    """
    requests: List[timelord_protocol.ChallengeStart] = []
    async with db.lock:
        for head in db.blockchain.get_current_heads():
            challenge_hash = head.challenge.get_hash()
            requests.append(timelord_protocol.ChallengeStart(challenge_hash))
    for request in requests:
        yield OutboundMessage(NodeType.TIMELORD, Message("challenge_start", request), Delivery.BROADCAST)


async def proof_of_time_estimate_interval():
    """
    Periodic function that updates our estimate of the PoT rate, based on the last few blocks.
    """
    while True:
        estimated_ips: Optional[uint64] = db.blockchain.get_vdf_rate_estimate()
        async with db.lock:
            if estimated_ips is not None:
                db.proof_of_time_estimate_ips = estimated_ips
                log.info(f"Updated proof of time estimate to {estimated_ips} iterations per second.")
        await sleep(config['update_pot_estimate_interval'])


async def on_connect() -> AsyncGenerator[OutboundMessage, None]:
    """
    Whenever we connect to another full node, send them our current heads.
    """
    blocks: List[FullBlock] = []
    async with db.lock:
        heads: List[TrunkBlock] = db.blockchain.get_current_heads()
        for h in heads:
            blocks.append(db.full_blocks[h.header.get_hash()])
    for block in blocks:
        request = peer_protocol.Block(block)
        yield OutboundMessage(NodeType.FULL_NODE, Message("block", request), Delivery.RESPOND)


async def sync():
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
    tip_block: FullBlock = None
    tip_height = 0

    # Based on responses from peers about the current heads, see which head is the heaviest
    # (similar to longest chain rule).
    async with db.lock:
        potential_heads = db.potential_heads.items()
        log.info(f"Have collected {len(potential_heads)} potential heads")
        for header_hash, _ in potential_heads:
            block = db.potential_heads_full_blocks[header_hash]
            if block.trunk_block.challenge.total_weight > highest_weight:
                highest_weight = block.trunk_block.challenge.total_weight
                tip_block = block
                tip_height = block.trunk_block.challenge.height
        if highest_weight <= max([t.challenge.total_weight for t in db.blockchain.get_current_heads()]):
            log.info("Not performing sync, already caught up.")
            db.sync_mode = False
            db.potential_heads.clear()
            db.potential_heads_full_blocks.clear()
            db.potential_trunks.clear()
            db.potential_blocks.clear()
            db.potential_blocks_received.clear()
            return

    # Now, we download all of the headers in order to verify the weight
    # TODO: use queue here, request a few at a time
    # TODO: send multiple API calls out at once
    timeout = 20
    sleep_interval = 3
    total_time_slept = 0
    trunks = []
    while total_time_slept < timeout:
        for start_height in range(0, tip_height + 1, config['max_trunks_to_send']):
            end_height = min(start_height + config['max_trunks_to_send'], tip_height + 1)
            request = peer_protocol.RequestTrunkBlocks(tip_block.trunk_block.header.get_hash(),
                                                       [h for h in range(start_height, end_height)])
            # TODO: should we ask the same peer as before, for the trunks?
            yield OutboundMessage(NodeType.FULL_NODE, Message("request_trunk_blocks", request), Delivery.RANDOM)
        await asyncio.sleep(sleep_interval)
        total_time_slept += sleep_interval
        async with db.lock:
            received_all_trunks = True
            local_trunks = []
            for height in range(0, tip_height + 1):
                if height not in db.potential_trunks:
                    received_all_trunks = False
                    break
                local_trunks.append(db.potential_trunks[uint32(height)])
            if received_all_trunks:
                trunks = local_trunks
                break
    if not verify_weight(tip_block.trunk_block, trunks):
        # TODO: ban peers that provided the invalid heads or proofs
        raise errors.InvalidWeight(f"Weight of {tip_block.trunk_block.header.get_hash()} not valid.")

    log.error(f"Downloaded trunks up to tip height: {tip_height}")
    assert tip_height + 1 == len(trunks)

    async with db.lock:
        fork_point: TrunkBlock = db.blockchain.find_fork_point(trunks)

    # TODO: optimize, send many requests at once, and for more blocks
    for height in range(fork_point.challenge.height + 1, tip_height + 1):
        # Only download from fork point (what we don't have)
        async with db.lock:
            have_block = trunks[height].header.get_hash() in db.potential_heads_full_blocks

        if not have_block:
            request = peer_protocol.RequestSyncBlocks(tip_block.trunk_block.header.header_hash, [height])
            async with db.lock:
                db.potential_blocks_received[uint32(height)] = Event()
            found = False
            for _ in range(30):
                yield OutboundMessage(NodeType.FULL_NODE, Message("request_sync_blocks", request), Delivery.RANDOM)
                try:
                    await asyncio.wait_for(db.potential_blocks_received[uint32(height)].wait(), timeout=2)
                    found = True
                    break
                except concurrent.futures._base.TimeoutError:
                    log.info("Did not receive desired block")
            if not found:
                raise PeersDontHaveBlock(f"Did not receive desired block at height {height}")
        async with db.lock:
            # TODO: ban peers that provide bad blocks
            if have_block:
                block = db.potential_heads_full_blocks[trunks[height].header.get_hash()]
            else:
                block = db.potential_blocks[uint32(height)]

            start = time.time()
            db.blockchain.receive_block(block)
            log.info(f"Took {time.time() - start}")
            assert max([h.challenge.height for h in db.blockchain.get_current_heads()]) >= height
            db.full_blocks[block.trunk_block.header.get_hash()] = block

    async with db.lock:
        log.info(f"Finished sync up to height {tip_height}")
        db.potential_heads.clear()
        db.potential_heads_full_blocks.clear()
        db.potential_trunks.clear()
        db.potential_blocks.clear()
        db.potential_blocks_received.clear()
        db.sync_mode = False


@api_request
async def request_trunk_blocks(request: peer_protocol.RequestTrunkBlocks) \
            -> AsyncGenerator[OutboundMessage, None]:
    """
    A peer requests a list of trunk blocks, by height. Used for syncing or light clients.
    """
    if len(request.heights) > config['max_trunks_to_send']:
        raise errors.TooManyTrunksRequested(f"The max number of trunks is {config['max_trunks_to_send']},\
                                             but requested {len(request.heights)}")
    async with db.lock:
        try:
            trunks: List[TrunkBlock] = db.blockchain.get_trunk_blocks_by_height(request.heights,
                                                                                request.tip_header_hash)
        except KeyError:
            log.info("Do not have required blocks")
            return
        except BlockNotInBlockchain as e:
            log.info(f"{e}")
            return

    response = peer_protocol.TrunkBlocks(request.tip_header_hash, trunks)
    yield OutboundMessage(NodeType.FULL_NODE, Message("trunk_blocks", response), Delivery.RESPOND)


@api_request
async def trunk_blocks(request: peer_protocol.TrunkBlocks) \
            -> AsyncGenerator[OutboundMessage, None]:
    """
    Receive trunk blocks from a peer.
    """
    async with db.lock:
        for trunk_block in request.trunk_blocks:
            db.potential_trunks[trunk_block.challenge.height] = trunk_block

    for _ in []:  # Yields nothing
        yield _


@api_request
async def request_sync_blocks(request: peer_protocol.RequestSyncBlocks) -> AsyncGenerator[OutboundMessage, None]:
    """
    Responsd to a peers request for syncing blocks.
    """
    blocks: List[FullBlock] = []
    async with db.lock:
        if request.tip_header_hash in db.full_blocks:
            if len(request.heights) > config['max_blocks_to_send']:
                raise errors.TooManyTrunksRequested(f"The max number of blocks is {config['max_blocks_to_send']},"
                                                    f"but requested {len(request.heights)}")
            try:
                trunk_blocks: List[TrunkBlock] = db.blockchain.get_trunk_blocks_by_height(request.heights,
                                                                                          request.tip_header_hash)
                blocks = [db.full_blocks[t.header.get_hash()] for t in trunk_blocks]
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
async def sync_blocks(request: peer_protocol.SyncBlocks) -> AsyncGenerator[OutboundMessage, None]:
    """
    We have received the blocks that we needed for syncing. Add them to processing queue.
    """
    # TODO: use an actual queue?
    async with db.lock:
        if not db.sync_mode:
            log.warning("Receiving sync blocks when we are not in sync mode.")
            return

        for block in request.blocks:
            db.potential_blocks[block.trunk_block.challenge.height] = block
            db.potential_blocks_received[block.trunk_block.challenge.height].set()

    for _ in []:  # Yields nothing
        yield _


@api_request
async def request_header_hash(request: farmer_protocol.RequestHeaderHash) -> AsyncGenerator[OutboundMessage, None]:
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

    async with db.lock:
        # Retrieves the correct head for the challenge
        heads: List[TrunkBlock] = db.blockchain.get_current_heads()
        target_head: Optional[TrunkBlock] = None
        for head in heads:
            if head.challenge.get_hash() == request.challenge_hash:
                target_head = head
        if target_head is None:
            # TODO: should we still allow the farmer to farm?
            log.warning(f"Challenge hash: {request.challenge_hash} not in one of three heads")
            return

        # TODO: use mempool to grab best transactions, for the selected head
        transactions_generator: bytes32 = sha256(b"").digest()
        # TODO: calculate the fees of these transactions
        fees: FeesTarget = FeesTarget(request.fees_target_puzzle_hash, 0)
        aggregate_sig: Signature = PrivateKey.from_seed(b"12345").sign(b"anything")
        # TODO: calculate aggregate signature based on transactions

        # Creates a block with transactions, coinbase, and fees
        body: BlockBody = BlockBody(request.coinbase, request.coinbase_signature,
                                    fees, aggregate_sig, transactions_generator)

        # Creates the block header
        prev_header_hash: bytes32 = target_head.header.get_hash()
        timestamp: uint64 = uint64(time.time())

        # TODO: use a real BIP158 filter based on transactions
        filter_hash: bytes32 = token_bytes(32)
        proof_of_space_hash: bytes32 = request.proof_of_space.get_hash()
        body_hash: BlockBody = body.get_hash()
        extension_data: bytes32 = bytes32([0] * 32)
        block_header_data: BlockHeaderData = BlockHeaderData(prev_header_hash, timestamp,
                                                             filter_hash, proof_of_space_hash,
                                                             body_hash, extension_data)

        block_header_data_hash: bytes32 = block_header_data.get_hash()

        # Stores this block so we can submit it to the blockchain after it's signed by plotter
        db.candidate_blocks[proof_of_space_hash] = (body, block_header_data, request.proof_of_space)

    message = farmer_protocol.HeaderHash(proof_of_space_hash, block_header_data_hash)
    yield OutboundMessage(NodeType.FARMER, Message("header_hash", message), Delivery.RESPOND)


@api_request
async def header_signature(header_signature: farmer_protocol.HeaderSignature) -> AsyncGenerator[OutboundMessage, None]:
    """
    Signature of header hash, by the plotter. This is enough to create an unfinished
    block, which only needs a Proof of Time to be finished. If the signature is valid,
    we call the unfinished_block routine.
    """
    async with db.lock:
        if header_signature.pos_hash not in db.candidate_blocks:
            log.warning(f"PoS hash {header_signature.pos_hash} not found in database")
            return
        # Verifies that we have the correct header and body stored
        block_body, block_header_data, pos = db.candidate_blocks[header_signature.pos_hash]

        assert block_header_data.get_hash() == header_signature.header_hash

        block_header: BlockHeader = BlockHeader(block_header_data, header_signature.header_signature)
        trunk: TrunkBlock = TrunkBlock(pos, None, None, block_header)
        unfinished_block_obj: FullBlock = FullBlock(trunk, block_body)

    # Propagate to ourselves (which validates and does further propagations)
    request = peer_protocol.UnfinishedBlock(unfinished_block_obj)
    async for m in unfinished_block(request):
        # Yield all new messages (propagation to peers)
        yield m


# TIMELORD PROTOCOL
@api_request
async def proof_of_time_finished(request: timelord_protocol.ProofOfTimeFinished) -> \
        AsyncGenerator[OutboundMessage, None]:
    """
    A proof of time, received by a peer timelord. We can use this to complete a block,
    and call the block routine (which handles propagation and verification of blocks).
    """
    async with db.lock:
        dict_key = (request.proof.output.challenge_hash, request.proof.output.number_of_iterations)
        if dict_key not in db.unfinished_blocks:
            log.warning(f"Received a proof of time that we cannot use to complete a block {dict_key}")
            return
        unfinished_block_obj: FullBlock = db.unfinished_blocks[dict_key]
        prev_block: TrunkBlock = db.blockchain.get_trunk_block(unfinished_block_obj.trunk_block.prev_header_hash)
        difficulty: uint64 = db.blockchain.get_next_difficulty(unfinished_block_obj.trunk_block.prev_header_hash)

    challenge: Challenge = Challenge(unfinished_block_obj.trunk_block.proof_of_space.get_hash(),
                                     request.proof.output.get_hash(),
                                     prev_block.challenge.height + 1,
                                     prev_block.challenge.total_weight + difficulty,
                                     prev_block.challenge.total_iters + request.proof.output.number_of_iterations)

    new_trunk_block = TrunkBlock(unfinished_block_obj.trunk_block.proof_of_space,
                                 request.proof,
                                 challenge,
                                 unfinished_block_obj.trunk_block.header)
    new_full_block: FullBlock = FullBlock(new_trunk_block, unfinished_block_obj.body)

    async for msg in block(peer_protocol.Block(new_full_block)):
        yield msg


# PEER PROTOCOL

@api_request
async def new_proof_of_time(new_proof_of_time: peer_protocol.NewProofOfTime) -> AsyncGenerator[OutboundMessage, None]:
    """
    A proof of time, received by a peer full node. If we have the rest of the block,
    we can complete it. Otherwise, we just verify and propagate the proof.
    """
    finish_block: bool = False
    propagate_proof: bool = False
    async with db.lock:
        if (new_proof_of_time.proof.output.challenge_hash,
                new_proof_of_time.proof.output.number_of_iterations) in db.unfinished_blocks:
            finish_block = True
        elif new_proof_of_time.proof.is_valid(constants["DISCRIMINANT_SIZE_BITS"]):
            propagate_proof = True
    if finish_block:
        request = timelord_protocol.ProofOfTimeFinished(new_proof_of_time.proof)
        async for msg in proof_of_time_finished(request):
            yield msg
    if propagate_proof:
        # TODO: perhaps don't propagate everything, this is a DoS vector
        yield OutboundMessage(NodeType.FULL_NODE, Message("new_proof_of_time", new_proof_of_time),
                              Delivery.BROADCAST_TO_OTHERS)


@api_request
async def unfinished_block(unfinished_block: peer_protocol.UnfinishedBlock) -> AsyncGenerator[OutboundMessage, None]:
    """
    We have received an unfinished block, either created by us, or from another peer.
    We can validate it and if it's a good block, propagate it to other peers and
    timelords.
    """
    async with db.lock:
        if not db.blockchain.is_child_of_head(unfinished_block.block):
            return

        if not db.blockchain.validate_unfinished_block(unfinished_block.block):
            raise InvalidUnfinishedBlock()

        prev_block: TrunkBlock = db.blockchain.get_trunk_block(
            unfinished_block.block.trunk_block.prev_header_hash)

        challenge_hash: bytes32 = prev_block.challenge.get_hash()
        difficulty: uint64 = db.blockchain.get_next_difficulty(
            unfinished_block.block.trunk_block.prev_header_hash)

        iterations_needed: uint64 = calculate_iterations(unfinished_block.block.trunk_block.proof_of_space,
                                                         challenge_hash, difficulty)

        if (challenge_hash, iterations_needed) in db.unfinished_blocks:
            log.info(f"\tHave already seen unfinished block {(challenge_hash, iterations_needed)}")
            return

    expected_time: uint64 = uint64(iterations_needed / db.proof_of_time_estimate_ips)

    if expected_time > constants["PROPAGATION_DELAY_THRESHOLD"]:
        # If this block is slow, sleep to allow faster blocks to come out first
        await asyncio.sleep(2)

    async with db.lock:
        if unfinished_block.block.height > db.unfinished_blocks_leader[0]:
            # If this is the first block we see at this height, propagate
            db.unfinished_blocks_leader = (unfinished_block.block.height, expected_time)
        elif unfinished_block.block.height == db.unfinished_blocks_leader[0]:
            if expected_time > db.unfinished_blocks_leader[1] + constants["PROPAGATION_THRESHOLD"]:
                # If VDF is expected to finish X seconds later than the best, don't propagate
                return
            elif expected_time < db.unfinished_blocks_leader[1]:
                # If this will be the first block to finalize, update our leader
                db.unfinished_blocks_leader = (db.unfinished_blocks_leader[0], expected_time)
        else:
            # If we have seen an unfinished block at a greater or equal height, don't propagate
            # TODO: should we?
            return

        db.unfinished_blocks[(challenge_hash, iterations_needed)] = unfinished_block.block

    timelord_request = timelord_protocol.ProofOfSpaceInfo(challenge_hash, iterations_needed)
    yield OutboundMessage(NodeType.TIMELORD, Message("proof_of_space_info", timelord_request), Delivery.BROADCAST)
    yield OutboundMessage(NodeType.FULL_NODE, Message("unfinished_block", unfinished_block),
                          Delivery.BROADCAST_TO_OTHERS)


@api_request
async def block(block: peer_protocol.Block) -> AsyncGenerator[OutboundMessage, None]:
    """
    Receive a full block from a peer full node (or ourselves).
    """

    header_hash = block.block.trunk_block.header.get_hash()

    async with db.lock:
        if db.sync_mode:
            # Add the block to our potential heads list
            db.potential_heads[header_hash] += 1
            db.potential_heads_full_blocks[header_hash] = block.block
            return

        added: ReceiveBlockResult = db.blockchain.receive_block(block.block)

    if added == ReceiveBlockResult.ALREADY_HAVE_BLOCK:
        log.info(f"\tAlready have block {header_hash} height {block.block.trunk_block.challenge.height}")
        return
    elif added == ReceiveBlockResult.INVALID_BLOCK:
        log.warning(f"\tBlock {header_hash} at height {block.block.trunk_block.challenge.height} is invalid.")
    elif added == ReceiveBlockResult.DISCONNECTED_BLOCK:
        async with db.lock:
            tip_height = max([head.challenge.height for head in db.blockchain.get_current_heads()])
        if block.block.trunk_block.challenge.height > tip_height + config["sync_blocks_behind_threshold"]:
            async with db.lock:
                db.potential_heads.clear()
                db.potential_heads[header_hash] += 1
                db.potential_heads_full_blocks[header_hash] = block.block
            log.info(f"We are too far behind this block. Our height is {tip_height} and block is at"
                     f"{block.block.trunk_block.challenge.height}")
            # Perform a sync if we have to
            db.sync_mode = True
            try:
                # Performs sync, and catch exceptions so we don't close the connection
                async for msg in sync():
                    yield msg
            except asyncio.CancelledError:
                log.warning("Syncing failed")
            except BaseException as e:
                log.warning(f"Error {e} with syncing")
            finally:
                return

        elif block.block.trunk_block.challenge.height > tip_height + 1:
            log.info(f"We are a few blocks behind, our height is {tip_height} and block is at"
                     f"{block.block.trunk_block.challenge.height} so we will request these blocks.")
            while True:
                # TODO: download a few blocks and add them to chain
                # prev_block_hash = block.block.trunk_block.header.data.prev_header_hash
                break
        return

    async with db.lock:
        db.full_blocks[header_hash] = block.block

    if added == ReceiveBlockResult.ADDED_TO_HEAD:
        # Only propagate blocks which extend the blockchain (one of the heads)
        difficulty = db.blockchain.get_difficulty(header_hash)

        pos_quality = block.block.trunk_block.proof_of_space.verify_and_get_quality(
            block.block.trunk_block.proof_of_time.output.challenge_hash
        )
        farmer_request = farmer_protocol.ProofOfSpaceFinalized(block.block.trunk_block.challenge.get_hash(),
                                                               block.block.trunk_block.challenge.height,
                                                               pos_quality,
                                                               difficulty)
        timelord_request = timelord_protocol.ChallengeStart(block.block.trunk_block.challenge.get_hash())
        timelord_request_end = timelord_protocol.ChallengeStart(block.block.trunk_block.proof_of_time.
                                                                output.challenge_hash)
        # Tell timelord to stop previous challenge and start with new one
        yield OutboundMessage(NodeType.TIMELORD, Message("challenge_end", timelord_request_end), Delivery.BROADCAST)
        yield OutboundMessage(NodeType.TIMELORD, Message("challenge_start", timelord_request), Delivery.BROADCAST)

        # Tell full nodes about the new block
        yield OutboundMessage(NodeType.FULL_NODE, Message("block", block), Delivery.BROADCAST_TO_OTHERS)

        # Tell farmer about the new block
        yield OutboundMessage(NodeType.FARMER, Message("proof_of_space_finalized", farmer_request), Delivery.BROADCAST)
    else:
        # Note(Florin): This is a hack...
        log.info("I've received a block, stopping the challenge to free up the VDF server...")
        log.info(f"Height of received block = {block.block.trunk_block.challenge.height}")
        timelord_request_end = timelord_protocol.ChallengeStart(block.block.trunk_block.proof_of_time.
                                                                output.challenge_hash)
        yield OutboundMessage(NodeType.TIMELORD, Message("challenge_end", timelord_request_end), Delivery.BROADCAST)
