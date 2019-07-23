from hashlib import sha256
import secrets
import logging
import os
import os.path
from typing import List, Optional
from blspy import PrivateKey, PublicKey, InsecureSignature
from chiapos import DiskPlotter, DiskProver
from .util.api_decorators import api_request
from .util.ints import uint32, uint8
from .types.protocols import plotter_protocol
from .types.sized_bytes import bytes32
from src.server.server import ChiaConnection


PLOT_SIZE = 16
PLOT_FILENAME = "plot-1.dat"
get_connections = None
pool_pubkey = None
plots = {}

log = logging.getLogger(__name__)


def get_quality_id(plot_seed: bytes32, index: uint8) -> uint32:
    return uint32(index + (int.from_bytes(plot_seed[:3], "big") << 8))


def quality_id_matches(plot_seed: bytes32, quality_id: uint32) -> Optional[uint8]:
    index = uint8(quality_id % 256)
    if (int.from_bytes(plot_seed[:3], "big") << 8) != (quality_id - index):
        return None
    return index


@api_request(plotter_handshake=plotter_protocol.PlotterHandshake.from_bin)
async def plotter_handshake(plotter_handshake: plotter_protocol.PlotterHandshake,
                            source_connection: ChiaConnection,
                            all_connections: List[ChiaConnection] = []):
    log.info(f"Calling plotter_handshake {plotter_handshake}")
    global pool_pubkey
    if os.path.isfile(PLOT_FILENAME) and pool_pubkey != plotter_handshake.pool_pubkey:
        os.remove((PLOT_FILENAME))

    # TODO: Check if we have enough disk space

    # Uses python secure random number generation
    seed = secrets.token_bytes(32)

    # Creates a private key and stores it in memory
    private_key: PrivateKey = PrivateKey.from_seed(seed)

    # TODO: store the private key and plot id on disk
    public_key_ser = private_key.get_public_key().serialize()
    pool_pubkey = plotter_handshake.pool_pubkey
    plot_seed: bytes = sha256(plotter_handshake.pool_pubkey.serialize() + public_key_ser).digest()
    plotter = DiskPlotter()
    plotter.create_plot_disk(PLOT_FILENAME, PLOT_SIZE, bytes([]), plot_seed)
    plots[plot_seed] = (private_key, DiskProver(PLOT_FILENAME))


@api_request(new_challenge=plotter_protocol.NewChallenge.from_bin)
async def new_challenge(new_challenge: plotter_protocol.NewChallenge,
                        source_connection: ChiaConnection,
                        all_connections: List[ChiaConnection] = []):
    log.info(f"Calling new_challenge {new_challenge}")
    if len(new_challenge.challenge_hash) != 32:
        raise ValueError("Invalid challenge size")

    # TODO: Create an ID based on plot id and index
    all_responses = []
    for plot_seed, (_, prover) in plots.items():
        log.info(f"Challenge hash: {new_challenge.challenge_hash}")
        qualities = prover.get_qualities_for_challenge(new_challenge.challenge_hash)
        for index, quality in enumerate(qualities):
            response_id = get_quality_id(plot_seed, uint8(index))
            response: plotter_protocol.ChallengeResponse = plotter_protocol.ChallengeResponse(
                new_challenge.challenge_hash,
                response_id,
                quality
            )
            all_responses.append(response)

    log.info(f"Found qualities {all_responses}")

    for response in all_responses:
        await source_connection.send("challenge_response", response)


@api_request(request=plotter_protocol.RequestProofOfSpace.from_bin)
async def request_proof_of_space(request: plotter_protocol.RequestProofOfSpace,
                                 source_connection: ChiaConnection,
                                 all_connections: List[ChiaConnection] = []):
    log.info(f"Calling request_proof_of_space {request}")
    for plot_seed, (sk, prover) in plots.items():
        # Using the response id, find the right plot and index from our solutions
        index: Optional[uint8] = quality_id_matches(plot_seed, request.response_id)
        if index is not None:
            proof_of_space: bytes = prover.get_full_proof(request.challenge_hash, index)

            agg_pubkey = PublicKey.aggregate_insecure([pool_pubkey, sk.get_public_key()])
            # We use a basic "insecure" signature here, which can be aggregated with
            # the pools signature
            plotter_signature_share: InsecureSignature = sk.sign_insecure(
                agg_pubkey.serialize() + request.block_hash)

            response: plotter_protocol.ProofOfSpaceResponse = plotter_protocol.ProofOfSpaceResponse(
                request.block_hash,
                plotter_signature_share,
                proof_of_space
            )
            await source_connection.send("proof_of_space_response", response)
            return
