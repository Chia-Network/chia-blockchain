import logging
import asyncio
from typing import List, Dict, Set, Tuple, Any
from blspy import PrivateKey, Util, PrependSignature
from src.util.api_decorators import api_request
from src.types.proof_of_space import ProofOfSpace
from src.types.coinbase import CoinbaseInfo
from src.types.protocols import plotter_protocol, farmer_protocol
from src.server.server import ChiaConnection, PeerConnections
import secrets
from hashlib import sha256
from chiapos import Verifier
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.util.block_rewards import calculate_block_reward

# TODO: use config file
farmer_port = 8001
plotter_ip = "127.0.0.1"
plotter_port = 8000
farmer_sk = PrivateKey.from_seed(secrets.token_bytes(32))
farmer_target = sha256(farmer_sk.get_public_key().serialize()).digest()


class Database:
    pool_sks = [PrivateKey.from_seed(b'0'), PrivateKey.from_seed(b'1')]
    pool_target = sha256(PrivateKey.from_seed(b'0').get_public_key().serialize()).digest()
    lock = asyncio.Lock()
    plotter_responses_header_hash: Dict[bytes32, bytes32] = {}
    plotter_responses_challenge: Dict[bytes32, bytes32] = {}
    plotter_responses_proofs: Dict[bytes32, ProofOfSpace] = {}
    plotter_responses_proof_hash_to_qual: Dict[bytes32, bytes32] = {}
    pool_share_threshold = 1.5 * (2 ** 255)
    propagate_threshold = 1.8 * (2 ** 254)
    challenges: Dict[uint32, List[farmer_protocol.ProofOfSpaceFinalized]] = {}
    challenge_to_height: Dict[bytes32, uint32] = {}
    current_heads: List[Tuple[bytes32, uint32]] = []
    seen_challenges: Set[bytes32] = set()
    unfinished_challenges: Dict[uint32, List[bytes32]] = {}
    current_height: uint32 = uint32(0)
    coinbase_rewards: Dict[uint32, Any] = {}
    proof_of_time_estimate_ips: uint64 = uint64(1000)


log = logging.getLogger(__name__)
db = Database()


"""
PLOTTER PROTOCOL (FARMER <-> PLOTTER)
"""


@api_request(challenge_response=plotter_protocol.ChallengeResponse.from_bin)
async def challenge_response(challenge_response: plotter_protocol.ChallengeResponse,
                             source_connection: ChiaConnection,
                             all_connections: PeerConnections):
    """
    This is a response from the plotter, for a NewChallenge. Here we check if the proof
    of space is sufficiently good, and if so, we ask for the whole proof.
    """

    quality: int = int.from_bytes(challenge_response.quality, "big")

    # TODO: Calculate the number of iterations using the difficulty, and compare to block time
    async with db.lock:
        if quality < db.pool_share_threshold or quality < db.propagate_threshold:
            db.plotter_responses_challenge[challenge_response.quality] = challenge_response.challenge_hash
            request = plotter_protocol.RequestProofOfSpace(challenge_response.quality)
            await source_connection.send("request_proof_of_space", request)


@api_request(response=plotter_protocol.RespondProofOfSpace.from_bin)
async def respond_proof_of_space(response: plotter_protocol.RespondProofOfSpace,
                                 source_connection: ChiaConnection,
                                 all_connections: PeerConnections):
    """
    This is a response from the plotter with a proof of space. We check it's validy,
    and request a pool partial, a header signature, or both, if the proof is good enough.
    """

    async with db.lock:
        assert response.proof.pool_pubkey in [sk.get_public_key() for sk in db.pool_sks]

    plot_seed: bytes32 = sha256(response.proof.pool_pubkey.serialize() +
                                response.proof.plot_pubkey.serialize()).digest()
    async with db.lock:
        challenge_hash: bytes32 = db.plotter_responses_challenge[response.quality]

    v: Verifier = Verifier()
    computed_quality_str = v.validate_proof(plot_seed, response.proof.size, bytes(challenge_hash),
                                            response.proof.proof)
    computed_quality = sha256(challenge_hash + computed_quality_str).digest()
    assert response.quality == computed_quality

    async with db.lock:
        db.plotter_responses_proofs[response.quality] = response.proof
        db.plotter_responses_proof_hash_to_qual[sha256(response.proof.as_bin()).digest()] = response.quality

    quality_num: int = int.from_bytes(response.quality, "big")
    if quality_num < db.pool_share_threshold:
        request = plotter_protocol.RequestPartialProof(response.quality,
                                                       sha256(farmer_target).digest())
        await source_connection.send("request_partial_proof", request)
    if quality_num < db.propagate_threshold:

        new_proof_height: uint32 = db.challenge_to_height[challenge_hash]
        if new_proof_height not in db.coinbase_rewards:
            log.error(f"Don't have coinbase transaction for height {new_proof_height}, cannot submit PoS")
            return

        coinbase, signature = db.coinbase_rewards[new_proof_height]
        request = farmer_protocol.RequestHeaderHash(challenge_hash, coinbase,
                                                    signature, farmer_target, response.proof)

        async with await all_connections.get_lock():
            for connection in await all_connections.get_connections():
                if connection.get_connection_type() == "full_node":
                    await connection.send("request_header_hash", request)


@api_request(response=plotter_protocol.HeaderSignature.from_bin)
async def header_signature(response: plotter_protocol.HeaderSignature,
                           source_connection: ChiaConnection,
                           all_connections: PeerConnections):
    """
    Receives a signature on a block header hash, which is required for submitting
    a block to the blockchain.
    """
    async with db.lock:
        header_hash: bytes32 = db.plotter_responses_header_hash[response.quality]
        proof_of_space: bytes32 = db.plotter_responses_proofs[response.quality]
        plot_pubkey = db.plotter_responses_proofs[response.quality].plot_pubkey

        assert response.header_hash_signature.verify([Util.hash256(header_hash)],
                                                     [plot_pubkey])

        # TODO: wait a while if it's a good quality, but not so good.
        pos_hash: bytes32 = sha256(proof_of_space.as_bin()).digest()
    request = farmer_protocol.HeaderSignature(pos_hash, header_hash, response.header_hash_signature)

    async with await all_connections.get_lock():
        for connection in await all_connections.get_connections():
            if connection.get_connection_type() == "full_node":
                await connection.send("header_signature", request)


@api_request(response=plotter_protocol.PartialProof.from_bin)
async def partial_proof(response: plotter_protocol.PartialProof,
                        source_connection: ChiaConnection,
                        all_connections: PeerConnections):
    """
    Receives a signature on the hash of the farmer payment target, which is used in a pool
    share, to tell the pool where to pay the farmer.
    """

    async with db.lock:
        farmer_target_hash = sha256(farmer_target).digest()
        plot_pubkey = db.plotter_responses_proofs[response.quality].plot_pubkey

    assert response.farmer_target_signature.verify([Util.hash256(farmer_target_hash)],
                                                   [plot_pubkey])
    # TODO: Send partial to pool


"""
FARMER PROTOCOL (FARMER <-> FULL NODE)
"""


@api_request(response=farmer_protocol.HeaderHash.from_bin)
async def header_hash(response: farmer_protocol.HeaderHash,
                      source_connection: ChiaConnection,
                      all_connections: PeerConnections):
    """
    Full node responds with the hash of the created header
    """
    header_hash: bytes32 = response.header_hash

    async with db.lock:
        quality: bytes32 = db.plotter_responses_proof_hash_to_qual[response.pos_hash]
        db.plotter_responses_header_hash[quality] = header_hash

    request = plotter_protocol.RequestHeaderSignature(quality, header_hash)

    async with await all_connections.get_lock():
        for connection in await all_connections.get_connections():
            if connection.get_connection_type() == "plotter":
                # TODO: only send to the plotter who made the proof of space, not all plotters
                await connection.send("request_header_signature", request)


@api_request(proof_of_space_finalized=farmer_protocol.ProofOfSpaceFinalized.from_bin)
async def proof_of_space_finalized(proof_of_space_finalized: farmer_protocol.ProofOfSpaceFinalized,
                                   source_connection: ChiaConnection,
                                   all_connections: PeerConnections):
    """
    Full node notifies farmer that a proof of space has been completed. It gets added to the
    challenges list at that height, and height is updated if necessary
    """
    get_proofs: bool = False
    async with db.lock:
        if (proof_of_space_finalized.height >= db.current_height and
                proof_of_space_finalized.challenge_hash not in db.seen_challenges):
            # Only get proofs for new challenges, at a current or new height
            get_proofs = True
            if (proof_of_space_finalized.height > db.current_height):
                db.current_height = proof_of_space_finalized.height

                # TODO: ask the pool for this information
                coinbase: CoinbaseInfo = CoinbaseInfo(db.current_height, calculate_block_reward(db.current_height),
                                                      db.pool_target)
                coinbase_signature: PrependSignature = db.pool_sks[0].sign_prepend(coinbase.as_bin())
                db.coinbase_rewards[db.current_height] = (coinbase, coinbase_signature)

            log.info(f"Current height set to {db.current_height}")
        db.seen_challenges.add(proof_of_space_finalized.challenge_hash)
        if proof_of_space_finalized.height not in db.challenges:
            db.challenges[proof_of_space_finalized.height] = [proof_of_space_finalized]
        else:
            db.challenges[proof_of_space_finalized.height].append(proof_of_space_finalized)
        db.challenge_to_height[proof_of_space_finalized.challenge_hash] = proof_of_space_finalized.height

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
    """
    Full node notifies the farmer that a new proof of space was created. The farmer can use this
    information to decide whether to propagate a proof.
    """
    async with db.lock:
        if proof_of_space_arrived.height not in db.unfinished_challenges:
            db.unfinished_challenges[proof_of_space_arrived.height] = []
        else:
            db.unfinished_challenges[proof_of_space_arrived.height].append(
                    proof_of_space_arrived.quality_string)


@api_request(deep_reorg_notification=farmer_protocol.DeepReorgNotification.from_bin)
async def deep_reorg_notification(deep_reorg_notification: farmer_protocol.DeepReorgNotification,
                                  source_connection: ChiaConnection,
                                  all_connections: PeerConnections):
    # TODO: implement
    log.error(f"Deep reorg notification not implemented.")


@api_request(proof_of_time_rate=farmer_protocol.ProofOfTimeRate.from_bin)
async def proof_of_time_rate(proof_of_time_rate: farmer_protocol.ProofOfTimeRate,
                             source_connection: ChiaConnection,
                             all_connections: PeerConnections):
    async with db.lock:
        db.proof_of_time_estimate_ips = proof_of_time_rate.pot_estimate_ips
