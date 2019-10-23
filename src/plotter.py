import logging
import os
import os.path
from yaml import safe_load
from asyncio import Lock
from typing import Dict, Tuple, Optional
from blspy import PrivateKey, PublicKey, PrependSignature, Util
from chiapos import DiskPlotter, DiskProver
from src.util.api_decorators import api_request
from src.util.ints import uint8
from src.protocols import plotter_protocol
from src.types.sized_bytes import bytes32
from src.types.proof_of_space import ProofOfSpace
from src.server.outbound_message import OutboundMessage, Delivery, Message, NodeType


log = logging.getLogger(__name__)


class Plotter:
    def __init__(self):
        self.config = safe_load(open("src/config/plotter.yaml", "r"))
        self.lock: Lock = Lock()

        # From filename to prover
        self.provers: Dict[str, DiskProver] = {}

        # From quality to (challenge_hash, filename, index)
        self.challenge_hashes: Dict[bytes32, Tuple[bytes32, str, uint8]] = {}

    @api_request
    async def plotter_handshake(self, plotter_handshake: plotter_protocol.PlotterHandshake):
        """
        Handshake between the plotter and farmer. The plotter receives the pool public keys,
        which must be put into the plots, before the plotting process begins. We cannot
        use any plots which don't have one of the pool keys.
        """
        for filename, plot_config in self.config['plots'].items():
            sk = PrivateKey.from_bytes(bytes.fromhex(plot_config['sk']))
            pool_pubkey = PublicKey.from_bytes(bytes.fromhex(plot_config['pool_pk']))
            # Only use plots that correct pools associated with them
            if pool_pubkey in plotter_handshake.pool_pubkeys:
                if not os.path.isfile(filename):
                    # Create  temporary PoSpace object, to call the calculate_plot_seed function
                    plot_seed: bytes32 = ProofOfSpace.calculate_plot_seed(pool_pubkey, sk.get_public_key())
                    plotter: DiskPlotter = DiskPlotter()
                    plotter.create_plot_disk(filename, plot_config['k'], bytes([]), plot_seed)
                else:
                    # TODO: check plots are correct
                    pass
                async with self.lock:
                    self.provers[filename] = DiskProver(filename)
            else:
                log.warning(f"Plot {filename} has an invalid pool key.")

    @api_request
    async def new_challenge(self, new_challenge: plotter_protocol.NewChallenge):
        """
        The plotter receives a new challenge from the farmer, and looks up the quality
        for any proofs of space that are are found in the plots. If proofs are found, a
        ChallengeResponse message is sent for each of the proofs found.
        """

        if len(new_challenge.challenge_hash) != 32:
            raise ValueError("Invalid challenge size")

        all_responses = []
        async with self.lock:
            for filename, prover in self.provers.items():
                try:
                    quality_strings = prover.get_qualities_for_challenge(new_challenge.challenge_hash)
                except RuntimeError:
                    log.warning("Error using prover object. Reinitializing prover object.")
                    self.provers[filename] = DiskProver(filename)
                    quality_strings = prover.get_qualities_for_challenge(new_challenge.challenge_hash)
                for index, quality_str in enumerate(quality_strings):
                    quality = ProofOfSpace.quality_str_to_quality(new_challenge.challenge_hash, quality_str)
                    self.challenge_hashes[quality] = (new_challenge.challenge_hash, filename, uint8(index))
                    response: plotter_protocol.ChallengeResponse = plotter_protocol.ChallengeResponse(
                        new_challenge.challenge_hash,
                        quality,
                        prover.get_size()
                    )
                    all_responses.append(response)

        for response in all_responses:
            yield OutboundMessage(NodeType.FARMER, Message("challenge_response", response), Delivery.RESPOND)

    @api_request
    async def request_proof_of_space(self, request: plotter_protocol.RequestProofOfSpace):
        """
        The farmer requests a signature on the header hash, for one of the proofs that we found.
        We look up the correct plot based on the quality, lookup the proof, and return it.
        """
        response: Optional[plotter_protocol.RespondProofOfSpace] = None
        async with self.lock:
            try:
                # Using the quality find the right plot and index from our solutions
                challenge_hash, filename, index = self.challenge_hashes[request.quality]
            except KeyError:
                log.warning(f"Quality {request.quality} not found")
                return
            if index is not None:
                proof_xs: bytes
                try:
                    proof_xs = self.provers[filename].get_full_proof(challenge_hash, index)
                except RuntimeError:
                    self.provers[filename] = DiskProver(filename)
                    proof_xs = self.provers[filename].get_full_proof(challenge_hash, index)

                pool_pubkey = PublicKey.from_bytes(bytes.fromhex(self.config['plots'][filename]['pool_pk']))
                plot_pubkey = PrivateKey.from_bytes(bytes.fromhex(self.config['plots'][filename]['sk'])) \
                    .get_public_key()
                proof_of_space: ProofOfSpace = ProofOfSpace(pool_pubkey,
                                                            plot_pubkey,
                                                            uint8(self.config['plots'][filename]['k']),
                                                            [uint8(b) for b in proof_xs])

                response = plotter_protocol.RespondProofOfSpace(
                    request.quality,
                    proof_of_space
                )
        if response:
            yield OutboundMessage(NodeType.FARMER, Message("respond_proof_of_space", response), Delivery.RESPOND)

    @api_request
    async def request_header_signature(self, request: plotter_protocol.RequestHeaderSignature):
        """
        The farmer requests a signature on the header hash, for one of the proofs that we found.
        A signature is created on the header hash using the plot private key.
        """

        async with self.lock:
            _, filename, _ = self.challenge_hashes[request.quality]

        plot_sk = PrivateKey.from_bytes(bytes.fromhex(self.config['plots'][filename]['sk']))
        header_hash_signature: PrependSignature = plot_sk.sign_prepend(request.header_hash)
        assert(header_hash_signature.verify([Util.hash256(request.header_hash)], [plot_sk.get_public_key()]))

        response: plotter_protocol.RespondHeaderSignature = plotter_protocol.RespondHeaderSignature(
            request.quality,
            header_hash_signature,
        )
        yield OutboundMessage(NodeType.FARMER, Message("respond_header_signature", response), Delivery.RESPOND)

    @api_request
    async def request_partial_proof(self, request: plotter_protocol.RequestPartialProof):
        """
        The farmer requests a signature on the farmer_target, for one of the proofs that we found.
        We look up the correct plot based on the quality, lookup the proof, and sign
        the farmer target hash using the plot private key. This will be used as a pool share.
        """
        async with self.lock:
            _, filename, _ = self.challenge_hashes[request.quality]
            plot_sk = PrivateKey.from_bytes(bytes.fromhex(self.config['plots'][filename]['sk']))
            farmer_target_signature: PrependSignature = plot_sk.sign_prepend(request.farmer_target_hash)

            response: plotter_protocol.RespondPartialProof = plotter_protocol.RespondPartialProof(
                request.quality,
                farmer_target_signature
            )
        yield OutboundMessage(NodeType.FARMER, Message("respond_partial_proof", response), Delivery.RESPOND)
