import logging
import time
from secrets import token_bytes
from hashlib import sha256
from chiapos import Verifier
from blspy import Util, Signature, PrivateKey
from asyncio import Lock
from typing import Dict, List, Tuple, Optional
from src.util.api_decorators import api_request
from src.protocols import farmer_protocol
from src.protocols import timelord_protocol
from src.util.ints import uint32, uint64
from src.server.chia_connection import ChiaConnection
from src.server.peer_connections import PeerConnections
from src.types.sized_bytes import bytes32
from src.types.block_body import BlockBody
from src.types.trunk_block import TrunkBlock
from src.types.block_header import BlockHeaderData, BlockHeader
from src.types.proof_of_space import ProofOfSpace
from src.consensus.pot_iterations import calculate_iterations
from src.types.full_block import FullBlock
from src.types.fees_target import FeesTarget
from src.blockchain import Blockchain


# TODO: use config file
full_node_port = 8002
farmer_ip = "127.0.0.1"
farmer_port = 8001
timelord_ip = "127.0.0.1"
timelord_port = 8003


class Database:
    lock: Lock = Lock()
    blockchain: Blockchain = Blockchain()  # Should be stored in memory
    bodies: Dict[uint32, List[BlockBody]] = {}

    # These are the blocks that we created, but don't have the PoS from farmer yet,
    # keyed from the proof of space hash
    candidate_blocks: Dict[bytes32, Tuple[BlockBody, BlockHeaderData, ProofOfSpace]] = {}

    # These are the blocks that we created, have PoS, but not PoT yet, keyed from the
    # block header hash
    unfinished_blocks: Dict[bytes32, FullBlock] = {}
    proof_of_time_estimate_ips: uint64 = uint64(3000)


log = logging.getLogger(__name__)
db = Database()


async def send_heads_to_farmers(all_connections: PeerConnections):
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
            print("Proof of space:", head.proof_of_space, prev_challenge_hash)
            quality = head.proof_of_space.verify_and_get_quality(prev_challenge_hash)
            difficulty: uint64 = db.blockchain.get_difficulty(head.header.get_hash())
            requests.append(farmer_protocol.ProofOfSpaceFinalized(challenge_hash, height,
                                                                  quality, difficulty))
        proof_of_time_rate: uint64 = db.proof_of_time_estimate_ips
    async with await all_connections.get_lock():
        for connection in await all_connections.get_connections():
            if connection.get_connection_type() == "farmer":
                for request in requests:
                    await connection.send("proof_of_space_finalized", request)

                await connection.send("proof_of_time_rate",
                                      farmer_protocol.ProofOfTimeRate(proof_of_time_rate))


async def send_challenges_to_timelords(all_connections: PeerConnections):
    """
    Sends all of the current heads to all timelord peers.
    """
    requests: List[timelord_protocol.ChallengeStart] = []
    async with db.lock:
        for head in db.blockchain.get_current_heads():
            challenge_hash = head.challenge.get_hash()
            requests.append(timelord_protocol.ChallengeStart(challenge_hash))
    async with await all_connections.get_lock():
        for connection in await all_connections.get_connections():
            if connection.get_connection_type() == "timelord":
                for request in requests:
                    await connection.send("challenge_start", request)


@api_request
async def request_header_hash(request: farmer_protocol.RequestHeaderHash,
                              source_connection: ChiaConnection,
                              all_connections: PeerConnections):
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
            log.warn(f"Challenge hash: {request.challenge_hash} not in one of three heads")
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

    await source_connection.send("header_hash", farmer_protocol.HeaderHash(proof_of_space_hash,
                                                                           block_header_data_hash))


@api_request
async def header_signature(header_signature: farmer_protocol.HeaderSignature,
                           source_connection: ChiaConnection,
                           all_connections: PeerConnections):
    async with db.lock:
        if header_signature.pos_hash not in db.candidate_blocks:
            log.warn(f"PoS hash {header_signature.pos_hash} not found in database")
            return
        # Verifies that we have the correct header and body stored
        block_body, block_header_data, pos = db.candidate_blocks[header_signature.pos_hash]
        log.warn(f"Calculated has: {block_header_data.get_hash()} {header_signature.header_hash}")
        assert block_header_data.get_hash() == header_signature.header_hash

        # Verifiesthe plotter's signature
        # TODO: remove redundant checks after they are added to Blockchain class
        assert header_signature.header_signature.verify([Util.hash256(header_signature.header_hash)],
                                                        [pos.plot_pubkey])

        block_header: BlockHeader = BlockHeader(block_header_data, header_signature.header_signature)

        assert db.blockchain.block_can_be_added(block_header, block_body)

        trunk: TrunkBlock = TrunkBlock(pos, None, None, block_header)
        unfinished_block: FullBlock = FullBlock(trunk, block_body)

        # TODO: verify block using blockchain class, including coinbase rewards

        db.unfinished_blocks[unfinished_block.trunk_block.header.get_hash()] = unfinished_block

        log.info(f"Created unfinished block: {unfinished_block}")
        log.info(f"{unfinished_block.serialize()}")

        # TODO: propagate to full nodes and to timelords, so they can add the PoT
        prev_block: TrunkBlock = db.blockchain.get_trunk_block(block_header_data.prev_header_hash)

        challenge_hash: bytes32 = prev_block.challenge.get_hash()
        difficulty: uint64 = db.blockchain.get_next_difficulty(block_header_data.prev_header_hash)

    iterations_needed: uint64 = calculate_iterations(pos, challenge_hash, difficulty)

    request = timelord_protocol.ProofOfSpaceInfo(challenge_hash, iterations_needed)
    async with await all_connections.get_lock():
        for connection in await all_connections.get_connections():
            if connection.get_connection_type() == "timelord":
                await connection.send("proof_of_space_info", request)
