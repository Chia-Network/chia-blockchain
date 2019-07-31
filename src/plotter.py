from hashlib import sha256
import secrets
import logging
import os
import os.path
from asyncio import Lock
from typing import Dict, Tuple
from blspy import PrivateKey, PublicKey, PrependSignature
from chiapos import DiskPlotter, DiskProver
from src.util.api_decorators import api_request
from src.util.ints import uint8
from src.protocols import plotter_protocol
from src.types.sized_bytes import bytes32
from src.types.proof_of_space import ProofOfSpace
from src.server.chia_connection import ChiaConnection
from src.server.peer_connections import PeerConnections

# TODO: use config file
PLOT_SIZE = 19
PLOT_FILENAME = "plot-1-" + str(PLOT_SIZE) + ".dat"
plotter_port = 8000


# TODO: store on disk
# TODO: generalize to multiple plots
class Database:
    pool_pubkey: PublicKey = None
    sk: PrivateKey = None
    plot_seed: bytes32 = None
    prover: DiskProver = None
    lock: Lock = Lock()
    challenge_hashes: Dict[bytes32, Tuple[bytes32, uint8]] = {}


db: Database = Database()
log = logging.getLogger(__name__)


@api_request
async def plotter_handshake(plotter_handshake: plotter_protocol.PlotterHandshake,
                            source_connection: ChiaConnection,
                            all_connections: PeerConnections):
    """
    Handshake between the plotter and farmer. The plotter receives the pool public keys,
    which must be put into the plots, before the plotting process begins. We cannot
    use any plots which don't have one of the pool keys.
    """

    if os.path.isfile(PLOT_FILENAME) and db.pool_pubkey in plotter_handshake.pool_pubkeys:
        return

    # TODO: Don't plot here; instead, filter active plots based on pks

    # Uses python secure random number generation
    seed: bytes32 = secrets.token_bytes(32)

    # Creates a private key and stores it in memory
    sk: PrivateKey = PrivateKey.from_seed(seed)

    public_key_ser = sk.get_public_key().serialize()
    pool_pubkey: PublicKey = plotter_handshake.pool_pubkeys[0]

    plot_seed: bytes32 = sha256(pool_pubkey.serialize() + public_key_ser).digest()
    plotter: DiskPlotter = DiskPlotter()
    plotter.create_plot_disk(PLOT_FILENAME, PLOT_SIZE, bytes([]), plot_seed)

    async with db.lock:
        db.prover = DiskProver(PLOT_FILENAME)
        db.pool_pubkey = pool_pubkey
        db.plot_seed = plot_seed
        db.sk = sk


@api_request
async def new_challenge(new_challenge: plotter_protocol.NewChallenge,
                        source_connection: ChiaConnection,
                        all_connections: PeerConnections):
    """
    The plotter receives a new challenge from the farmer, and looks up the quality
    for any proofs of space that are are found in the plots. If proofs are found, a
    ChallengeResponse message is sent for each of the proofs found.
    """

    if len(new_challenge.challenge_hash) != 32:
        raise ValueError("Invalid challenge size")

    # TODO: Check that the DiskProver object is fine, otherwise create a new one
    all_responses = []
    async with db.lock:
        prover = db.prover
        try:
            quality_strings = prover.get_qualities_for_challenge(new_challenge.challenge_hash)
        except RuntimeError:
            log.warn("Error using prover object. Reinitializing prover object.")
            db.prover = DiskProver(PLOT_FILENAME)
            quality_strings = prover.get_qualities_for_challenge(new_challenge.challenge_hash)
        for index, quality_string in enumerate(quality_strings):
            quality = sha256(new_challenge.challenge_hash + quality_string).digest()
            db.challenge_hashes[quality] = (new_challenge.challenge_hash, index)
            response: plotter_protocol.ChallengeResponse = plotter_protocol.ChallengeResponse(
                new_challenge.challenge_hash,
                quality
            )
            all_responses.append(response)

    for response in all_responses:
        await source_connection.send("challenge_response", response)


@api_request
async def request_proof_of_space(request: plotter_protocol.RequestProofOfSpace,
                                 source_connection: ChiaConnection,
                                 all_connections: PeerConnections):
    """
    The farmer requests a signature on the header hash, for one of the proofs that we found.
    We look up the correct plot based on the quality, lookup the proof, and return it.
    """

    async with db.lock:
        try:
            # Using the quality find the right plot and index from our solutions
            challenge_hash, index = db.challenge_hashes[request.quality]
        except KeyError:
            log.warn(f"Quality {request.quality} not found")
            return
        if index is not None:
            try:
                proof_xs: bytes = db.prover.get_full_proof(challenge_hash, index)
            except RuntimeError:
                db.prover = DiskProver(PLOT_FILENAME)
                proof_xs: bytes = db.prover.get_full_proof(challenge_hash, index)

            proof_of_space: ProofOfSpace = ProofOfSpace(db.pool_pubkey,
                                                        db.sk.get_public_key(),
                                                        uint8(db.prover.get_size()),
                                                        list(proof_xs))

            response: plotter_protocol.RespondProofOfSpace = plotter_protocol.RespondProofOfSpace(
                request.quality,
                proof_of_space
            )
            await source_connection.send("respond_proof_of_space", response)
            return


@api_request
async def request_header_signature(request: plotter_protocol.RequestHeaderSignature,
                                   source_connection: ChiaConnection,
                                   all_connections: PeerConnections):
    """
    The farmer requests a signature on the header hash, for one of the proofs that we found.
    A signature is created on the header hash using the plot private key.
    """

    async with db.lock:
        # TODO: when we have multiple plots, use the right sk based on request.quality
        assert request.quality in db.challenge_hashes

        header_hash_signature: PrependSignature = db.sk.sign_prepend(request.header_hash)

        response: plotter_protocol.RespondHeaderSignature = plotter_protocol.RespondHeaderSignature(
            request.quality,
            header_hash_signature,
        )
        await source_connection.send("respond_header_signature", response)
        return


@api_request
async def request_partial_proof(request: plotter_protocol.RequestPartialProof,
                                source_connection: ChiaConnection,
                                all_connections: PeerConnections):
    """
    The farmer requests a signature on the farmer_target, for one of the proofs that we found.
    We look up the correct plot based on the quality, lookup the proof, and sign
    the farmer target hash using the plot private key. This will be used as a pool share.
    """
    async with db.lock:
        # TODO: when we have multiple plots, use the right sk based on request.quality
        farmer_target_signature: PrependSignature = db.sk.sign_prepend(request.farmer_target_hash)

        response: plotter_protocol.RespondPartialProof = plotter_protocol.RespondPartialProof(
            request.quality,
            farmer_target_signature
        )
        await source_connection.send("respond_partial_proof", response)
        return
