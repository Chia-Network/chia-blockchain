import logging
import os
import os.path
from typing import Dict, Optional, Tuple

from blspy import PrependSignature, PrivateKey, PublicKey, Util
from yaml import safe_load

from chiapos import DiskProver
from definitions import ROOT_DIR
from src.protocols import harvester_protocol
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request
from src.util.ints import uint8

log = logging.getLogger(__name__)


class Harvester:
    def __init__(self):
        config_filename = os.path.join(ROOT_DIR, "src", "config", "config.yaml")
        plot_config_filename = os.path.join(ROOT_DIR, "src", "config", "plots.yaml")
        key_config_filename = os.path.join(ROOT_DIR, "src", "config", "keys.yaml")

        if not os.path.isfile(key_config_filename):
            raise RuntimeError(
                "Keys not generated. Run ./src/scripts/regenerate_keys.py."
            )
        if not os.path.isfile(plot_config_filename):
            raise RuntimeError(
                "Plots not generated. Run ./src/scripts/create_plots.py."
            )

        self.config = safe_load(open(config_filename, "r"))["harvester"]
        self.key_config = safe_load(open(key_config_filename, "r"))
        self.plot_config = safe_load(open(plot_config_filename, "r"))

        # From filename to prover
        self.provers: Dict[str, DiskProver] = {}

        # From quality to (challenge_hash, filename, index)
        self.challenge_hashes: Dict[bytes32, Tuple[bytes32, str, uint8]] = {}

    @api_request
    async def harvester_handshake(
        self, harvester_handshake: harvester_protocol.HarvesterHandshake
    ):
        """
        Handshake between the harvester and farmer. The harvester receives the pool public keys,
        which must be put into the plots, before the plotting process begins. We cannot
        use any plots which don't have one of the pool keys.
        """
        for partial_filename, plot_config in self.plot_config["plots"].items():
            if "plot_root" in self.config:
                filename = os.path.join(self.config["plot_root"], partial_filename)
            else:
                filename = os.path.join(ROOT_DIR, "plots", partial_filename)
            pool_pubkey = PublicKey.from_bytes(bytes.fromhex(plot_config["pool_pk"]))

            # Only use plots that correct pools associated with them
            if pool_pubkey in harvester_handshake.pool_pubkeys:
                if os.path.isfile(filename):
                    self.provers[partial_filename] = DiskProver(filename)
                else:
                    log.warn(f"Plot at {filename} does not exist.")

            else:
                log.warning(
                    f"Plot {filename} has a pool key that is not in the farmer's pool_pk list."
                )

    @api_request
    async def new_challenge(self, new_challenge: harvester_protocol.NewChallenge):
        """
        The harvester receives a new challenge from the farmer, and looks up the quality
        for any proofs of space that are are found in the plots. If proofs are found, a
        ChallengeResponse message is sent for each of the proofs found.
        """

        if len(new_challenge.challenge_hash) != 32:
            raise ValueError("Invalid challenge size")
        all_responses = []
        for filename, prover in self.provers.items():
            try:
                quality_strings = prover.get_qualities_for_challenge(
                    new_challenge.challenge_hash
                )
            except RuntimeError:
                log.warning("Error using prover object. Reinitializing prover object.")
                self.provers[filename] = DiskProver(filename)
                quality_strings = prover.get_qualities_for_challenge(
                    new_challenge.challenge_hash
                )
            for index, quality_str in enumerate(quality_strings):
                quality = ProofOfSpace.quality_str_to_quality(
                    new_challenge.challenge_hash, quality_str
                )
                self.challenge_hashes[quality] = (
                    new_challenge.challenge_hash,
                    filename,
                    uint8(index),
                )
                response: harvester_protocol.ChallengeResponse = harvester_protocol.ChallengeResponse(
                    new_challenge.challenge_hash, quality, prover.get_size()
                )
                all_responses.append(response)
        for response in all_responses:
            yield OutboundMessage(
                NodeType.FARMER,
                Message("challenge_response", response),
                Delivery.RESPOND,
            )

    @api_request
    async def request_proof_of_space(
        self, request: harvester_protocol.RequestProofOfSpace
    ):
        """
        The farmer requests a signature on the header hash, for one of the proofs that we found.
        We look up the correct plot based on the quality, lookup the proof, and return it.
        """
        response: Optional[harvester_protocol.RespondProofOfSpace] = None
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

            pool_pubkey = PublicKey.from_bytes(
                bytes.fromhex(self.plot_config["plots"][filename]["pool_pk"])
            )
            plot_pubkey = PrivateKey.from_bytes(
                bytes.fromhex(self.plot_config["plots"][filename]["sk"])
            ).get_public_key()
            proof_of_space: ProofOfSpace = ProofOfSpace(
                challenge_hash,
                pool_pubkey,
                plot_pubkey,
                uint8(self.provers[filename].get_size()),
                [uint8(b) for b in proof_xs],
            )

            response = harvester_protocol.RespondProofOfSpace(
                request.quality, proof_of_space
            )
        if response:
            yield OutboundMessage(
                NodeType.FARMER,
                Message("respond_proof_of_space", response),
                Delivery.RESPOND,
            )

    @api_request
    async def request_header_signature(
        self, request: harvester_protocol.RequestHeaderSignature
    ):
        """
        The farmer requests a signature on the header hash, for one of the proofs that we found.
        A signature is created on the header hash using the plot private key.
        """

        _, filename, _ = self.challenge_hashes[request.quality]

        plot_sk = PrivateKey.from_bytes(
            bytes.fromhex(self.plot_config["plots"][filename]["sk"])
        )
        header_hash_signature: PrependSignature = plot_sk.sign_prepend(
            request.header_hash
        )
        assert header_hash_signature.verify(
            [Util.hash256(request.header_hash)], [plot_sk.get_public_key()]
        )

        response: harvester_protocol.RespondHeaderSignature = harvester_protocol.RespondHeaderSignature(
            request.quality, header_hash_signature,
        )
        yield OutboundMessage(
            NodeType.FARMER,
            Message("respond_header_signature", response),
            Delivery.RESPOND,
        )

    @api_request
    async def request_partial_proof(
        self, request: harvester_protocol.RequestPartialProof
    ):
        """
        The farmer requests a signature on the farmer_target, for one of the proofs that we found.
        We look up the correct plot based on the quality, lookup the proof, and sign
        the farmer target hash using the plot private key. This will be used as a pool share.
        """
        _, filename, _ = self.challenge_hashes[request.quality]
        plot_sk = PrivateKey.from_bytes(
            bytes.fromhex(self.plot_config["plots"][filename]["sk"])
        )
        farmer_target_signature: PrependSignature = plot_sk.sign_prepend(
            request.farmer_target_hash
        )

        response: harvester_protocol.RespondPartialProof = harvester_protocol.RespondPartialProof(
            request.quality, farmer_target_signature
        )
        yield OutboundMessage(
            NodeType.FARMER,
            Message("respond_partial_proof", response),
            Delivery.RESPOND,
        )
