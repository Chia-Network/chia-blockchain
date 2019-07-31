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
from src.util.ints import uint32, uint64
from src.server.chia_connection import ChiaConnection
from src.server.peer_connections import PeerConnections
from src.types.sized_bytes import bytes32
from src.util.block_rewards import calculate_block_reward
from src.types.block_body import BlockBody
from src.types.foliage_block import FoliageBlock
from src.types.block_header import BlockHeaderData, BlockHeader
from src.types.proof_of_space import ProofOfSpace
from src.types.classgroup import ClassgroupElement
from src.types.challenge import Challenge
from src.types.full_block import FullBlock
from src.types.proof_of_time import ProofOfTime, ProofOfTimeOutput
from src.types.fees_target import FeesTarget
from src.blockchain import Blockchain


# TODO: use config file
full_node_port = 8002
farmer_ip = "127.0.0.1"
farmer_port = 8001


class Database:
    lock: Lock = Lock()
    blockchain: Blockchain = Blockchain()  # Should be stored in memory
    bodies: Dict[uint32, List[BlockBody]] = {}
    candidate_blocks: Dict[bytes32, Tuple[BlockBody, BlockHeaderData, ProofOfSpace]] = {}


log = logging.getLogger(__name__)
db = Database()


@api_request
async def request_header_hash(request: farmer_protocol.RequestHeaderHash,
                              source_connection: ChiaConnection,
                              all_connections: PeerConnections):
    """
    Creates a block body and header, with the proof of space, coinbase, and fee targets provided
    by the farmer, and sends the hash of the header data back to the farmer.
    """
    plot_seed: bytes32 = sha256(request.proof_of_space.pool_pubkey.serialize() +
                                request.proof_of_space.plot_pubkey.serialize()).digest()

    # Checks that the proof of space is valid
    quality_string: bytes = Verifier().validate_proof(plot_seed, request.proof_of_space.size,
                                                      request.challenge_hash,
                                                      bytes(request.proof_of_space.proof))
    assert quality_string

    async with db.lock:
        # Retrieves the correct head for the challenge
        heads: List[FoliageBlock] = db.blockchain.get_current_heads()
        target_head: Optional[FoliageBlock] = None
        for head in heads:
            if sha256(head.challenge.serialize()).digest() == request.challenge_hash:
                target_head = head
        if target_head is None:
            log.warn(f"Challenge hash: {request.challenge_hash} not in one of three heads")
            # TODO: remove hack
            # retur

        # Checks that the coinbase is well formed
        # TODO: remove redundant checks after they are added to Blockchain class
        # assert request.coinbase.height >= min([b.challenge.height for b in heads])
        assert (calculate_block_reward(request.coinbase.height) ==
                request.coinbase.amount)

        # TODO: move this logic to the Blockchain class?
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
        # previous_header_hash: bytes32 = sha256(target_head.header).digest()
        previous_header_hash: bytes32 = bytes32([0] * 32)
        timestamp: uint64 = uint64(time.time())

        # TODO: use a real BIP158 filter based on transactions
        filter_hash: bytes32 = token_bytes(32)
        proof_of_space_hash: bytes32 = sha256(request.proof_of_space.serialize()).digest()
        body_hash: BlockBody = sha256(body.serialize()).digest()
        extension_data: bytes32 = bytes32([0] * 32)
        block_header_data: BlockHeaderData = BlockHeaderData(previous_header_hash, timestamp,
                                                             filter_hash, proof_of_space_hash,
                                                             body_hash, extension_data)

        block_header_data_hash: bytes32 = sha256(block_header_data.serialize()).digest()

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
        assert sha256(block_header_data.serialize()).digest() == header_signature.header_hash

        # Verifiesthe plotter's signature
        # TODO: remove redundant checks after they are added to Blockchain class
        assert header_signature.header_signature.verify([Util.hash256(header_signature.header_hash)], [pos.plot_pubkey])

        block_header: BlockHeader = BlockHeader(block_header_data, header_signature.header_signature)

        assert db.blockchain.block_can_be_added(block_header, block_body)

        pot_output = ProofOfTimeOutput(bytes32([0]*32), 0, ClassgroupElement(0, 0))
        pot_proof = ProofOfTime(pot_output, 1, [ClassgroupElement(0, 0)])

        chall: Challenge = Challenge(sha256(pos.serialize()).digest(), sha256(pot_output.serialize()).digest(), 0, 0)
        foliage: FoliageBlock = FoliageBlock(pos, pot_output, pot_proof, chall, block_header)
        genesis_block: FullBlock = FullBlock(foliage, block_body)

        log.error(f"FULL GENESIS BLOC: {genesis_block.serialize()}")

        # TODO: propagate to full nodes and to timelords
