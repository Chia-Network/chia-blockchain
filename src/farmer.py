import logging
import asyncio
from typing import List, Dict, Set
from blspy import PrivateKey, Util
from src.util.api_decorators import api_request
from src.types.protocols import plotter_protocol, farmer_protocol
from src.server.server import ChiaConnection, PeerConnections
import secrets
from hashlib import sha256
from chiapos import Verifier
from src.types.sized_bytes import bytes32
from src.util.ints import uint32

# TODO: use config file
farmer_port = 8001
plotter_ip = "127.0.0.1"
plotter_port = 8000
farmer_sk = PrivateKey.from_seed(secrets.token_bytes(32))
farmer_target = sha256(farmer_sk.get_public_key().serialize()).digest()


class Database:
    pool_sks = [PrivateKey.from_seed(b'0'), PrivateKey.from_seed(b'1')]
    lock = asyncio.Lock()
    plotter_responses: Dict[bytes32, bytes32] = {}
    plotter_responses_challenge: Dict[bytes32, bytes32] = {}
    plotter_responses_quality: Dict[bytes32, bytes32] = {}
    pool_share_threshold = (2 ** 255)
    propagate_threshold = (2 ** 254)
    challenges: Dict[uint32, List[farmer_protocol.ProofOfSpaceFinalized]] = {}
    seen_challenges: Set[bytes32] = set()
    unfinished_challenges: Dict[uint32, List[bytes32]] = {}
    current_height: uint32 = uint32(0)


log = logging.getLogger(__name__)
db = Database()


@api_request(challenge_response=plotter_protocol.ChallengeResponse.from_bin)
async def challenge_response(challenge_response: plotter_protocol.ChallengeResponse,
                             source_connection: ChiaConnection,
                             all_connections: PeerConnections):
    """
    This is a response from the plotter, for a NewChallenge. Here we check if the proof
    of space is sufficiently good, and if so, we ask for either a header signature (to
    propagate to the blockchain), or a partial signature (to send to the pool), along
    with the actual proof.
    """

    quality: int = int.from_bytes(sha256(challenge_response.quality_string).digest(), "big")

    # TODO: Calculate the number of iterations using the difficulty, and compare to block time
    async with db.lock:
        if quality < (db.pool_share_threshold):
            # TODO: lookup the actual block hash
            header_hash: bytes32 = bytes32(secrets.token_bytes(32))
            db.plotter_responses[challenge_response.response_id] = header_hash
            db.plotter_responses_challenge[challenge_response.response_id] = challenge_response.challenge_hash
            db.plotter_responses_quality[challenge_response.response_id] = challenge_response.quality_string

            request = plotter_protocol.RequestHeaderSignature(challenge_response.response_id,
                                                              header_hash)

            request2 = plotter_protocol.RequestHeaderSignature(challenge_response.response_id,
                                                               sha256(farmer_target).digest())
            await source_connection.send("request_partial_proof", request2)

            if quality < (db.propagate_threshold):
                # TODO: wait a while if it's a good quality, but not so good.
                await source_connection.send("request_header_signature", request)


@api_request(response=plotter_protocol.HeaderSignature.from_bin)
async def header_signature(response: plotter_protocol.HeaderSignature,
                           source_connection: ChiaConnection,
                           all_connections: PeerConnections):
    """
    Receives a proof of space from a plotter, including a signature on the
    a block header hash, which is required for submitting a block to the blockchain.
    """

    plot_seed: bytes32 = sha256(response.proof.pool_pubkey.serialize() +
                                response.proof.plot_pubkey.serialize()).digest()
    async with db.lock:
        header_hash: bytes32 = db.plotter_responses[response.response_id]
        challenge = db.plotter_responses_challenge[response.response_id]
        quality_str = db.plotter_responses_quality[response.response_id]

    v: Verifier = Verifier()
    computed_quality_str = v.validate_proof(plot_seed, response.proof.size, bytes(challenge),
                                            response.proof.proof)
    assert(quality_str == computed_quality_str)

    assert(response.header_hash_signature.verify([Util.hash256(header_hash)],
                                                 [response.proof.plot_pubkey]))

    # TODO: Propagate header signature to network


@api_request(response=plotter_protocol.PartialProof.from_bin)
async def partial_proof(response: plotter_protocol.PartialProof,
                        source_connection: ChiaConnection,
                        all_connections: PeerConnections):
    """
    Receives a proof of space from a plotter, including a signature on the
    hash of the farmer payment target, which is used in a pool share, to tell
    the pool where to pay the farmer.
    """

    plot_seed: bytes32 = sha256(response.proof.pool_pubkey.serialize() +
                                response.proof.plot_pubkey.serialize()).digest()
    async with db.lock:
        challenge = db.plotter_responses_challenge[response.response_id]
        farmer_target_hash = sha256(farmer_target).digest()
        quality_str = db.plotter_responses_quality[response.response_id]

    v: Verifier = Verifier()
    computed_quality_str = v.validate_proof(plot_seed, response.proof.size, bytes(challenge),
                                            response.proof.proof)
    assert(quality_str == computed_quality_str)

    assert(response.farmer_target_signature.verify([Util.hash256(farmer_target_hash)],
                                                   [response.proof.plot_pubkey]))

    # TODO: Send partial to pool


@api_request(proof_of_space_finalized=farmer_protocol.ProofOfSpaceFinalized.from_bin)
async def proof_of_space_finalized(proof_of_space_finalized: farmer_protocol.ProofOfSpaceFinalized,
                                   source_connection: ChiaConnection,
                                   all_connections: PeerConnections):
    get_proofs: bool = False
    async with db.lock:
        if (proof_of_space_finalized.height >= db.current_height and
                proof_of_space_finalized.challenge_hash not in db.seen_challenges):
            get_proofs = True
            db.current_height = proof_of_space_finalized.height
        db.seen_challenges.add(proof_of_space_finalized.challenge_hash)
        if proof_of_space_finalized.height not in db.challenges:
            db.challenges[proof_of_space_finalized.height] = [proof_of_space_finalized]
        else:
            db.challenges[proof_of_space_finalized.height].append(proof_of_space_finalized)

    if get_proofs:
        async with await all_connections.get_lock():
            for connection in await all_connections.get_connections():
                if connection.get_connection_type() == "plotter":
                    await connection.send("new_challenge",
                                          plotter_protocol.NewChallenge(proof_of_space_finalized.challenge_hash))


@api_request(proof_of_space_arrived=farmer_protocol.ProofOfSpaceArrived.from_bin)
async def proof_of_space_arrived(proof_of_space_arrived: farmer_protocol.ProofOfSpaceArrived,
                                 source_connection: ChiaConnection,
                                 all_connections: PeerConnections):
    async with db.lock:
        if proof_of_space_arrived.height not in db.unfinished_challenges:
            db.unfinished_challenges[proof_of_space_arrived.height] = []
        else:
            db.unfinished_challenges[proof_of_space_arrived.height].append(
                    proof_of_space_arrived.quality_string)
