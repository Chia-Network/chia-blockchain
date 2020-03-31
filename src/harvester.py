import logging
import asyncio
from pathlib import Path
from typing import Dict, Optional, Tuple

from blspy import PrependSignature, PrivateKey, PublicKey, Util

from chiapos import DiskProver
from src.protocols import harvester_protocol
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request
from src.util.ints import uint8
from src.util.path import path_from_root

log = logging.getLogger(__name__)


class Harvester:
    def __init__(self, config: Dict, plot_config: Dict):
        self.config: Dict = config
        self.plot_config: Dict = plot_config

        # From filename to prover
        self.provers: Dict[Path, DiskProver] = {}

        # From quality string to (challenge_hash, filename, index)
        self.challenge_hashes: Dict[bytes32, Tuple[bytes32, Path, uint8]] = {}
        self._plot_notification_task = asyncio.create_task(self._plot_notification())
        self._is_shutdown: bool = False

    async def _plot_notification(self):
        """
        Log the plot filenames to console periodically
        """
        counter = 1
        while not self._is_shutdown:
            if counter % 600 == 0:
                for filename, prover in self.provers.items():
                    log.info(f"Farming plot {filename} of size {prover.get_size()}")
            await asyncio.sleep(1)
            counter += 1

    def _shutdown(self):
        self._is_shutdown = True

    async def _await_shutdown(self):
        await self._plot_notification_task

    @api_request
    async def harvester_handshake(
        self, harvester_handshake: harvester_protocol.HarvesterHandshake
    ):
        """
        Handshake between the harvester and farmer. The harvester receives the pool public keys,
        which must be put into the plots, before the plotting process begins. We cannot
        use any plots which don't have one of the pool keys.
        """
        for partial_filename_str, plot_config in self.plot_config["plots"].items():
            plot_root = path_from_root(self.config.get("plot_root", "."))
            partial_filename = path_from_root(partial_filename_str, plot_root)
            potential_filenames = [
                partial_filename,
                path_from_root(partial_filename_str, plot_root),
            ]
            pool_pubkey = PublicKey.from_bytes(bytes.fromhex(plot_config["pool_pk"]))

            # Only use plots that correct pools associated with them
            if pool_pubkey not in harvester_handshake.pool_pubkeys:
                log.warning(
                    f"Plot {partial_filename} has a pool key that is not in the farmer's pool_pk list."
                )
                continue

            found = False
            failed_to_open = False
            for filename in potential_filenames:
                if filename.exists():
                    try:
                        self.provers[partial_filename_str] = DiskProver(str(filename))
                    except ValueError:
                        log.error(f"Failed to open file {filename}.")
                        failed_to_open = True
                        break
                    log.info(
                        f"Farming plot {filename} of size {self.provers[partial_filename_str].get_size()}"
                    )
                    found = True
                    break
            if not found and not failed_to_open:
                log.warning(f"Plot at {potential_filenames} does not exist.")

    @api_request
    async def new_challenge(self, new_challenge: harvester_protocol.NewChallenge):
        """
        The harvester receives a new challenge from the farmer, and looks up the quality string
        for any proofs of space that are are found in the plots. If proofs are found, a
        ChallengeResponse message is sent for each of the proofs found.
        """

        challenge_size = len(new_challenge.challenge_hash)
        if challenge_size != 32:
            raise ValueError(
                f"Invalid challenge size {challenge_size}, 32 was expected"
            )
        all_responses = []
        for filename, prover in self.provers.items():
            try:
                quality_strings = prover.get_qualities_for_challenge(
                    new_challenge.challenge_hash
                )
            except RuntimeError:
                log.error("Error using prover object. Reinitializing prover object.")
                try:
                    self.provers[filename] = DiskProver(str(filename))
                    quality_strings = prover.get_qualities_for_challenge(
                        new_challenge.challenge_hash
                    )
                except RuntimeError:
                    log.error(
                        f"Retry-Error using prover object on {filename}. Giving up."
                    )
                    quality_strings = None

            for index, quality_str in enumerate(quality_strings):
                self.challenge_hashes[quality_str] = (
                    new_challenge.challenge_hash,
                    filename,
                    uint8(index),
                )
                response: harvester_protocol.ChallengeResponse = harvester_protocol.ChallengeResponse(
                    new_challenge.challenge_hash, quality_str, prover.get_size()
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
            # Using the quality string, find the right plot and index from our solutions
            challenge_hash, filename, index = self.challenge_hashes[
                request.quality_string
            ]
        except KeyError:
            log.warning(f"Quality string {request.quality_string} not found")
            return
        if index is not None:
            proof_xs: bytes
            try:
                proof_xs = self.provers[filename].get_full_proof(challenge_hash, index)
            except RuntimeError:
                self.provers[filename] = DiskProver(str(filename))
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
                proof_xs,
            )

            response = harvester_protocol.RespondProofOfSpace(
                request.quality_string, proof_of_space
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
        if request.quality_string not in self.challenge_hashes:
            return

        _, filename, _ = self.challenge_hashes[request.quality_string]

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
            request.quality_string, header_hash_signature,
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
        _, filename, _ = self.challenge_hashes[request.quality_string]
        plot_sk = PrivateKey.from_bytes(
            bytes.fromhex(self.plot_config["plots"][filename]["sk"])
        )
        farmer_target_signature: PrependSignature = plot_sk.sign_prepend(
            request.farmer_target_hash
        )

        response: harvester_protocol.RespondPartialProof = harvester_protocol.RespondPartialProof(
            request.quality_string, farmer_target_signature
        )
        yield OutboundMessage(
            NodeType.FARMER,
            Message("respond_partial_proof", response),
            Delivery.RESPOND,
        )
