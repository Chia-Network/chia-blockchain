from hashlib import sha256
import secrets
import logging
import os
import os.path
from asyncio import Lock
from typing import List, Dict, Tuple
from blspy import PrivateKey, PublicKey, PrependSignature
from chiapos import DiskPlotter, DiskProver
from src.util.api_decorators import api_request
from src.util.ints import uint8
from src.types.protocols import plotter_protocol
from src.types.sized_bytes import bytes32
from src.types.proof_of_space import ProofOfSpace
from src.server.server import ChiaConnection

# TODO: use config file
PLOT_SIZE = 19
PLOT_FILENAME = "plot-1-" + str(PLOT_SIZE) + ".dat"


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


@api_request(plotter_handshake=plotter_protocol.PlotterHandshake.from_bin)
async def plotter_handshake(plotter_handshake: plotter_protocol.PlotterHandshake,
                            source_connection: ChiaConnection,
                            all_connections: List[ChiaConnection] = []):
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
    pool_pubkey: PublicKey = list(plotter_handshake.pool_pubkeys)[0]

    plot_seed: bytes32 = sha256(pool_pubkey.serialize() + public_key_ser).digest()
    plotter: DiskPlotter = DiskPlotter()
    plotter.create_plot_disk(PLOT_FILENAME, PLOT_SIZE, bytes([]), plot_seed)

    async with db.lock:
        db.prover = DiskProver(PLOT_FILENAME)
        db.pool_pubkey = pool_pubkey
        db.plot_seed = plot_seed
        db.sk = sk


@api_request(new_challenge=plotter_protocol.NewChallenge.from_bin)
async def new_challenge(new_challenge: plotter_protocol.NewChallenge,
                        source_connection: ChiaConnection,
                        all_connections: List[ChiaConnection] = []):
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
            qualities = prover.get_qualities_for_challenge(new_challenge.challenge_hash)
        except RuntimeError:
            db.prover = DiskProver(PLOT_FILENAME)
            qualities = prover.get_qualities_for_challenge(new_challenge.challenge_hash)
        for index, quality in enumerate(qualities):
            response_id = sha256(db.plot_seed + uint8(index).to_bytes(1, "big")).digest()
            db.challenge_hashes[response_id] = (new_challenge.challenge_hash, index)
            response: plotter_protocol.ChallengeResponse = plotter_protocol.ChallengeResponse(
                new_challenge.challenge_hash,
                response_id,
                quality
            )
            all_responses.append(response)

    for response in all_responses:
        await source_connection.send("challenge_response", response)


@api_request(request=plotter_protocol.RequestHeaderSignature.from_bin)
async def request_header_signature(request: plotter_protocol.RequestHeaderSignature,
                                   source_connection: ChiaConnection,
                                   all_connections: List[ChiaConnection] = []):
    """
    The farmer requests a signature on the header hash, for one of the proofs that we found.
    We look up the correct plot based on the response id, lookup the proof, and sign
    the header hash using the plot private key.
    """

    async with db.lock:
        try:
            # Using the response id, find the right plot and index from our solutions
            challenge_hash, index = db.challenge_hashes[request.response_id]
        except KeyError:
            log.warn(f"Response id {request.response_id} not found")
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
                                                        proof_xs)

            header_hash_signature: PrependSignature = db.sk.sign_prepend(request.header_hash)

            response: plotter_protocol.HeaderSignature = plotter_protocol.HeaderSignature(
                request.response_id,
                header_hash_signature,
                proof_of_space
            )
            await source_connection.send("header_signature", response)
            return


@api_request(request=plotter_protocol.RequestPartialProof.from_bin)
async def request_partial_proof(request: plotter_protocol.RequestPartialProof,
                                source_connection: ChiaConnection,
                                all_connections: List[ChiaConnection] = []):
    """
    The farmer requests a signature on the farmer_target, for one of the proofs that we found.
    We look up the correct plot based on the response id, lookup the proof, and sign
    the farmer target hash using the plot private key. This will be used as a pool share.
    """
    async with db.lock:
        try:
            # Using the response id, find the right plot and index from our solutions
            challenge_hash, index = db.challenge_hashes[request.response_id]
        except KeyError:
            log.warn(f"Response id {request.response_id} not found")
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
                                                        proof_xs)

            farmer_target_signature: PrependSignature = db.sk.sign_prepend(request.farmer_target_hash)

            response: plotter_protocol.PartialProof = plotter_protocol.PartialProof(
                request.response_id,
                farmer_target_signature,
                proof_of_space
            )
            await source_connection.send("partial_proof", response)
            return
