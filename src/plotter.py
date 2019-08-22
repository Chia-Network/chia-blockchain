from hashlib import sha256
import logging
import os
import os.path
from asyncio import Lock
from typing import Dict, Tuple, Optional
from blspy import PrivateKey, PublicKey, PrependSignature, Util
from chiapos import DiskPlotter, DiskProver
from src.util.api_decorators import api_request
from src.util.ints import uint8
from src.protocols import plotter_protocol
from src.types.sized_bytes import bytes32
from src.types.proof_of_space import ProofOfSpace
from src.server.outbound_message import OutboundMessage


# TODO: use config file
# SECRET_KEY: PrivateKey =
POOL_PK: PublicKey = PrivateKey.from_seed(b'pool key 0').get_public_key()
PLOTS = {f"plot-{n}-19.dat": (19, PrivateKey.from_seed(b'plot sk' + bytes([n])), POOL_PK) for n in range(8)}
plotter_port = 8000


# TODO: store on disk
class Database:
    # From filename to prover
    provers: Dict[str, DiskProver] = {}
    lock: Lock = Lock()
    # From quality to (challenge_hash, filename, index)
    challenge_hashes: Dict[bytes32, Tuple[bytes32, str, uint8]] = {}


db: Database = Database()
log = logging.getLogger(__name__)


@api_request
async def plotter_handshake(plotter_handshake: plotter_protocol.PlotterHandshake):
    """
    Handshake between the plotter and farmer. The plotter receives the pool public keys,
    which must be put into the plots, before the plotting process begins. We cannot
    use any plots which don't have one of the pool keys.
    """
    for filename, (k, sk, pool_pubkey) in PLOTS.items():
        # Only use plots that correct pools associated with them
        if pool_pubkey in plotter_handshake.pool_pubkeys:
            if not os.path.isfile(filename):
                # Create  temporary PoSpace object, to call the calculate_plot_seed function
                plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(pool_pubkey, sk.get_public_key())
                plotter: DiskPlotter = DiskPlotter()
                plotter.create_plot_disk(filename, k, bytes([]), plot_seed)
            else:
                # TODO: check plots are correct
                pass
            async with db.lock:
                db.provers[filename] = DiskProver(filename)
        else:
            log.warn(f"Plot {filename} has an invalid pool key.")


@api_request
async def new_challenge(new_challenge: plotter_protocol.NewChallenge):
    """
    The plotter receives a new challenge from the farmer, and looks up the quality
    for any proofs of space that are are found in the plots. If proofs are found, a
    ChallengeResponse message is sent for each of the proofs found.
    """

    if len(new_challenge.challenge_hash) != 32:
        raise ValueError("Invalid challenge size")

    all_responses = []
    async with db.lock:
        for filename, prover in db.provers.items():
            try:
                quality_strings = prover.get_qualities_for_challenge(new_challenge.challenge_hash)
            except RuntimeError:
                log.warn("Error using prover object. Reinitializing prover object.")
                db.provers[filename] = DiskProver(filename)
                quality_strings = prover.get_qualities_for_challenge(new_challenge.challenge_hash)
            for index, quality_string in enumerate(quality_strings):
                quality = sha256(new_challenge.challenge_hash + quality_string).digest()
                db.challenge_hashes[quality] = (new_challenge.challenge_hash, filename, index)
                response: plotter_protocol.ChallengeResponse = plotter_protocol.ChallengeResponse(
                    new_challenge.challenge_hash,
                    quality,
                    prover.get_size()
                )
                all_responses.append(response)

    for response in all_responses:
        yield OutboundMessage("farmer", "challenge_response", response, True, False)


@api_request
async def request_proof_of_space(request: plotter_protocol.RequestProofOfSpace):
    """
    The farmer requests a signature on the header hash, for one of the proofs that we found.
    We look up the correct plot based on the quality, lookup the proof, and return it.
    """
    response: Optional[plotter_protocol.RespondProofOfSpace] = None
    async with db.lock:
        try:
            # Using the quality find the right plot and index from our solutions
            challenge_hash, filename, index = db.challenge_hashes[request.quality]
        except KeyError:
            log.warn(f"Quality {request.quality} not found")
            return
        if index is not None:
            try:
                proof_xs: bytes = db.provers[filename].get_full_proof(challenge_hash, index)
            except RuntimeError:
                db.provers[filename] = DiskProver(filename)
                proof_xs: bytes = db.provers[filename].get_full_proof(challenge_hash, index)

            proof_of_space: ProofOfSpace = ProofOfSpace(PLOTS[filename][2],
                                                        PLOTS[filename][1].get_public_key(),
                                                        uint8(PLOTS[filename][0]),
                                                        list(proof_xs))

            response = plotter_protocol.RespondProofOfSpace(
                request.quality,
                proof_of_space
            )
    if response:
        yield OutboundMessage("farmer", "respond_proof_of_space", response, True, False)


@api_request
async def request_header_signature(request: plotter_protocol.RequestHeaderSignature):
    """
    The farmer requests a signature on the header hash, for one of the proofs that we found.
    A signature is created on the header hash using the plot private key.
    """

    async with db.lock:
        _, filename, _ = db.challenge_hashes[request.quality]

    header_hash_signature: PrependSignature = PLOTS[filename][1].sign_prepend(request.header_hash)
    assert(header_hash_signature.verify([Util.hash256(request.header_hash)], [PLOTS[filename][1].get_public_key()]))

    response: plotter_protocol.RespondHeaderSignature = plotter_protocol.RespondHeaderSignature(
        request.quality,
        header_hash_signature,
    )
    yield OutboundMessage("farmer", "respond_header_signature", response, True, False)


@api_request
async def request_partial_proof(request: plotter_protocol.RequestPartialProof):
    """
    The farmer requests a signature on the farmer_target, for one of the proofs that we found.
    We look up the correct plot based on the quality, lookup the proof, and sign
    the farmer target hash using the plot private key. This will be used as a pool share.
    """
    async with db.lock:
        _, filename, _ = db.challenge_hashes[request.quality]
        farmer_target_signature: PrependSignature = PLOTS[filename][1].sign_prepend(request.farmer_target_hash)

        response: plotter_protocol.RespondPartialProof = plotter_protocol.RespondPartialProof(
            request.quality,
            farmer_target_signature
        )
    yield OutboundMessage("farmer", "respond_partial_proof", response, True, False)
