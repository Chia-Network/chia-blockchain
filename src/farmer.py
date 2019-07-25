import logging
import asyncio
from typing import List, Dict
from blspy import PrivateKey, Util
from src.util.api_decorators import api_request
from src.types.protocols import plotter_protocol
from src.server.server import ChiaConnection
import secrets
from hashlib import sha256
from chiapos import Verifier
from src.types.sized_bytes import bytes32


class Database:
    farmer_sk = PrivateKey.from_seed(secrets.token_bytes(32))
    farmer_target = b"Pay me at this address! TODO, use a real address"
    pool_sks = [PrivateKey.from_seed(b'0'), PrivateKey.from_seed(b'1')]
    lock = asyncio.Lock()
    plotter_responses: Dict[bytes32, bytes32] = {}
    plotter_responses_challenge: Dict[bytes32, bytes32] = {}
    pos_verifier = Verifier()
    pool_share_threshold = (2 ** 255)
    propagate_threshold = (2 ** 254)


log = logging.getLogger(__name__)
db = Database()


@api_request(challenge_response=plotter_protocol.ChallengeResponse.from_bin)
async def challenge_response(challenge_response: plotter_protocol.ChallengeResponse,
                             source_connection: ChiaConnection,
                             all_connections: List[ChiaConnection] = []):
    """
    This is a response from the plotter, for a NewChallenge. Here we check if the proof
    of space is sufficiently good, and if so, we ask for either a header signature (to
    propagate to the blockchain), or a partial signature (to send to the pool), along
    with the actual proof.
    """

    quality: int = int.from_bytes(sha256(challenge_response.quality).digest(), "big")

    # TODO: Calculate the number of iterations using the difficulty, and compare to block time
    async with db.lock:
        if quality < (db.pool_share_threshold):
            # TODO: lookup the actual block hash
            header_hash: bytes32 = bytes32(secrets.token_bytes(32))
            db.plotter_responses[challenge_response.response_id] = header_hash
            db.plotter_responses_challenge[challenge_response.response_id] = challenge_response.challenge_hash

            request = plotter_protocol.RequestHeaderSignature(challenge_response.response_id,
                                                              header_hash)

            request2 = plotter_protocol.RequestHeaderSignature(challenge_response.response_id,
                                                               sha256(db.farmer_target).digest())
            await source_connection.send("request_partial_proof", request2)

            if quality < (db.propagate_threshold):
                # TODO: wait a while if it's a good quality, but not so good.
                await source_connection.send("request_header_signature", request)


@api_request(response=plotter_protocol.HeaderSignature.from_bin)
async def header_signature(response: plotter_protocol.HeaderSignature,
                           source_connection: ChiaConnection,
                           all_connections: List[ChiaConnection] = []):

    plot_seed: bytes32 = sha256(response.proof.pool_pubkey.serialize() +
                                response.proof.plot_pubkey.serialize()).digest()
    async with db.lock:
        header_hash: bytes32 = db.plotter_responses[response.response_id]
        challenge = db.plotter_responses_challenge[response.response_id]

    v: Verifier = Verifier()
    assert v.validate_proof(plot_seed, response.proof.size, bytes(challenge),
                            response.proof.proof)

    assert(response.header_hash_signature.verify([Util.hash256(header_hash)],
                                                 [response.proof.plot_pubkey]))

    # TODO: Propagate header signature to network


@api_request(response=plotter_protocol.PartialProof.from_bin)
async def partial_proof(response: plotter_protocol.PartialProof,
                        source_connection: ChiaConnection,
                        all_connections: List[ChiaConnection] = []):
    plot_seed: bytes32 = sha256(response.proof.pool_pubkey.serialize() +
                                response.proof.plot_pubkey.serialize()).digest()
    async with db.lock:
        challenge = db.plotter_responses_challenge[response.response_id]
        farmer_target_hash = sha256(db.farmer_target).digest()

    v: Verifier = Verifier()
    assert v.validate_proof(plot_seed, response.proof.size, bytes(challenge),
                            response.proof.proof)

    assert(response.farmer_target_signature.verify([Util.hash256(farmer_target_hash)],
                                                   [response.proof.plot_pubkey]))

    # TODO: Send partial to pool
