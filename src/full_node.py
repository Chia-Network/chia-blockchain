import logging
import time
import asyncio
import collections
from secrets import token_bytes
from hashlib import sha256
from chiapos import Verifier
from blspy import Util, Signature, PrivateKey
from asyncio import Lock, sleep, Event
from typing import Dict, List, Tuple, Optional, AsyncGenerator, Counter
from src.util.api_decorators import api_request
from src.util.ints import uint64
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
from src.types.peer_info import PeerInfo
from src.consensus.weight_verifier import verify_weight
from src.consensus.pot_iterations import calculate_iterations
from src.consensus.constants import DIFFICULTY_TARGET
from src.blockchain import Blockchain
from src.server.outbound_message import OutboundMessage, Delivery, NodeType, Message


# TODO: use config file
host = "127.0.0.1"
port = 8002
farmer_peer = PeerInfo("127.0.0.1", 8001, sha256(b"farmer:127.0.0.1:8001").digest())
timelord_peer = PeerInfo("127.0.0.1", 8003, sha256(b"timelord:127.0.0.1:8003").digest())
initial_peers = [PeerInfo("127.0.0.1", 8002, sha256(b"full_node:127.0.0.1:8002").digest()),
                 PeerInfo("127.0.0.1", 8004, sha256(b"full_node:127.0.0.1:8004").digest()),
                 PeerInfo("127.0.0.1", 8005, sha256(b"full_node:127.0.0.1:8005").digest())]
update_pot_estimate_interval: int = 30
genesis_block: FullBlock = Blockchain.get_genesis_block()

# Don't send any more than these number of trunks and blocks, in one message
max_trunks_to_send = 100
max_blocks_to_send = 10


class Database:
    lock: Lock = Lock()
    blockchain: Blockchain = Blockchain()  # Should be stored in memory
    full_blocks: Dict[str, FullBlock] = {genesis_block.trunk_block.header.header_hash: genesis_block}

    sync_mode: bool = True
    # Block headers for blocks which we think might be heads, but we haven't verified yet
    potential_heads: Counter[str] = collections.Counter()
    # Headers/trunks downloaded for the during sync, by height
    potential_trunks: Dict[uint64, TrunkBlock] = {}
    # Blocks downloaded during sync, by height
    potential_blocks: Dict[uint64, FullBlock] = {}
    potential_blocks_received: Dict[uint64, Event] = {}

    # These are the blocks that we created, but don't have the PoS from farmer yet,
    # keyed from the proof of space hash
    candidate_blocks: Dict[bytes32, Tuple[BlockBody, BlockHeaderData, ProofOfSpace]] = {}

    # These are the blocks that we created, have PoS, but not PoT yet, keyed from the
    # block header hash
    unfinished_blocks: Dict[Tuple[bytes32, int], FullBlock] = {}
    proof_of_time_estimate_ips: uint64 = uint64(1500)


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
        await sleep(update_pot_estimate_interval)


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

    # Wait for us to receive heads from peers
    for _ in range(4):
        await asyncio.sleep(2)
        async with db.lock:
            log.warning("Still waiting to receive tips from peers.")
            # TODO: better way to tell that we have finished receiving tips
            if sum(db.potential_heads.values()) > 10:
                break

    highest_weight: uint64 = uint64(0)
    tip_block: FullBlock = None
    tip_height = 0

    # Based on responses from peers about the current heads, see which head is the heaviest
    # (similar to longest chain rule).
    async with db.lock:
        for header_hash, _ in db.potential_heads:
            block = db.full_blocks[header_hash]
            if block.trunk_block.challenge.weight > highest_weight:
                highest_weight = block.trunk_block.challenge.weight
                tip_block = block
                tip_height = block.trunk_block.challenge.height
        if highest_weight <= max([t.challenge.total_weight for t in db.blockchain.get_current_heads()]):
            log.info("Not performing sync, already caught up")
            db.sync_mode = False
            return

    # Now, we download all of the headers in order to verify the weight
    # TODO: use queue here, request a few at a time
    # TODO: send multiple API calls out at once
    timeout = 20
    sleep_interval = 3
    total_time_slept = 0
    trunks = []
    while total_time_slept < timeout:
        request = peer_protocol.RequestTrunkBlocks(tip_block.trunk_block.header.hash(),
                                                   [h for h in range(0, tip_height)])
        # TODO: should we ask the same peer as before, for the trunks?
        yield OutboundMessage(NodeType.FULL_NODE, Message("request_trunk_blocks", request), Delivery.RANDOM)
        await asyncio.sleep(sleep_interval)
        total_time_slept += sleep_interval
        async with db.lock:
            received_all_trunks = True
            local_trunks = []
            for height in range(0, tip_height):
                if height not in db.potential_trunks:
                    received_all_trunks = False
                    break
                local_trunks.append(db.potential_trunks[uint64(height)])
            if received_all_trunks:
                trunks = local_trunks
                break

    if not verify_weight(tip_block.trunk_block, trunks):
        # TODO: ban peers that provided the invalid heads or proofs
        raise errors.InvalidWeight(f"Weight of {tip_block.trunk_block.header.hash()} not valid.")

    for height in range(0, tip_height):
        # Only download from fork point (what we don't have)
        async with db.lock:
            if trunks[height].header.hash() in db.full_blocks:
                continue
        request = peer_protocol.RequestSyncBlocks(tip_block.trunk_block.header.header_hash, [1])
        async with db.lock:
            db.potential_blocks_received[uint64(height)] = Event()
        yield OutboundMessage(NodeType.FULL_NODE, Message("request_sync_blocks", request), Delivery.RANDOM)

        await asyncio.wait_for(db.potential_blocks_received[uint64(height)].wait(), timeout=10)

        async with db.lock:
            # TODO: ban peers that provide bad blocks
            assert db.blockchain.add_block(db.potential_blocks[uint64(height)])
            log.error(f"ADDED BLOCK AT HEIGHT: {height}")
    async with db.lock:
        db.sync_mode = False


@api_request
async def request_trunk_blocks(request: peer_protocol.RequestTrunkBlocks) \
            -> AsyncGenerator[OutboundMessage, None]:
    """
    A peer requests a list of trunk blocks, by height. Used for syncing or light clients.
    """
    if len(request.heights) > max_trunks_to_send:
        raise errors.TooManyTrunksRequested(f"The max number of trunks is {max_trunks_to_send},\
                                             but requested {len(request.heights)}")
    async with db.lock:
        trunks: List[TrunkBlock] = db.blockchain.get_trunk_blocks_by_height(request.heights, request.tip_header_hash)
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

    # Yield nothing
    for _ in []:
        yield _


@api_request
async def request_sync_blocks(request: peer_protocol.RequestSyncBlocks) -> AsyncGenerator[OutboundMessage, None]:
    """
    Responsd to a peers request for syncing blocks.
    """
    async with db.lock:
        if request.tip_header_hash not in db.full_blocks:
            # We don't have the blocks that the client is looking for
            log.info("Peer requested tip {request.tip_header_hash} that we don't have")
            return
        if len(request.heights) > max_blocks_to_send:
            raise errors.TooManyTrunksRequested(f"The max number of blocks is {max_blocks_to_send},\
                                                but requested {len(request.heights)}")
        blocks = db.blockchain.get_blocks_by_height(request.heights, request.tip_header_hash)

    response = peer_protocol.SyncBlocks(request.tip_header_hash, blocks)
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

    # Yield nothing
    for _ in []:
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
        # prev_header_hash: bytes32 = bytes32([0] * 32)
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

        # Verifies the plotter's signature
        # TODO: remove redundant checks after they are added to Blockchain class
        assert header_signature.header_signature.verify([Util.hash256(header_signature.header_hash)],
                                                        [pos.plot_pubkey])

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
        elif new_proof_of_time.proof.is_valid():
            propagate_proof = True
    if finish_block:
        request = timelord_protocol.ProofOfTimeFinished(new_proof_of_time.proof)
        async for msg in proof_of_time_finished(request):
            yield msg
    if propagate_proof:
        # TODO: perhaps don't propagate everything, this is a DoS vector
        yield OutboundMessage(NodeType.FULL_NODE, Message("new_proof_of_time", new_proof_of_time), Delivery.BROADCAST)


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

        # TODO(alex): verify block using blockchain class, including coinbase rewards
        prev_block: TrunkBlock = db.blockchain.get_trunk_block(
            unfinished_block.block.trunk_block.prev_header_hash)

        challenge_hash: bytes32 = prev_block.challenge.get_hash()
        difficulty: uint64 = db.blockchain.get_next_difficulty(
            unfinished_block.block.trunk_block.prev_header_hash)

        iterations_needed: uint64 = calculate_iterations(unfinished_block.block.trunk_block.proof_of_space,
                                                         challenge_hash, difficulty)

        if (challenge_hash, iterations_needed) in db.unfinished_blocks:
            log.info(f"Have already seen unfinished block {(challenge_hash, iterations_needed)}")
            return

        expected_time: float = iterations_needed / db.proof_of_time_estimate_ips

        # TODO(alex): tweak this
        log.info(f"Expected finish time: {expected_time}")
        if expected_time > 10 * DIFFICULTY_TARGET:
            return

        db.unfinished_blocks[(challenge_hash, iterations_needed)] = unfinished_block.block

    timelord_request = timelord_protocol.ProofOfSpaceInfo(challenge_hash, iterations_needed)
    yield OutboundMessage(NodeType.TIMELORD, Message("proof_of_space_info", timelord_request), Delivery.BROADCAST)
    yield OutboundMessage(NodeType.FULL_NODE, Message("unfinished_block", unfinished_block), Delivery.BROADCAST)


@api_request
async def block(block: peer_protocol.Block) -> AsyncGenerator[OutboundMessage, None]:
    """
    Receive a full block from a peer full node (or ourselves).
    Pseudocode:
    if we have block:
        return
    if we don't care about block:
        return
    if block invalid:
        return
    Store block
    if block actually good:
        propagate to other full nodes
        propagate challenge to farmers
        propagate challenge to timelords
    """
    propagate: bool = False
    header_hash = block.block.trunk_block.header.get_hash()

    async with db.lock:
        if db.sync_mode:
            # Add the block to our potential heads list
            db.full_blocks[header_hash] = block.block
            db.potential_heads[header_hash] += 1
            return

        if header_hash in db.full_blocks:
            log.info(f"Already have block {header_hash}")
            return
        # TODO(alex): Check if we care about this block, we don't want to add random
        # disconnected blocks. For example if it's on one of the heads, or if it's an older
        # block that we need
        added = db.blockchain.add_block(block.block)
        db.full_blocks[header_hash] = block.block
        if not added:
            log.info("Block not added!!")
            # TODO(alex): is this correct? What if we already have it?
            return
        propagate = True
        difficulty = db.blockchain.get_difficulty(header_hash)
    if propagate:
        # TODO(alex): don't reverify, just get the quality
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
        yield OutboundMessage(NodeType.FULL_NODE, Message("block", block), Delivery.BROADCAST)

        # Tell farmer about the new block
        yield OutboundMessage(NodeType.FARMER, Message("proof_of_space_finalized", farmer_request), Delivery.BROADCAST)
