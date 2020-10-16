from pathlib import Path
from typing import Optional

from blspy import AugSchemeMPL, G2Element
from chiapos import DiskProver

from src.harvester import Harvester
from src.plotting.plot_tools import PlotInfo
from src.protocols import harvester_protocol
from src.server.outbound_message import Message
from src.server.ws_connection import WSChiaConnection
from src.types.proof_of_space import ProofOfSpace
from src.util.api_decorators import api_request
from src.util.ints import uint8


class HarvesterAPI:
    harvester: Harvester

    def __init__(self, harvester):
        self.harvester = harvester

    @api_request
    async def harvester_handshake(
        self,
        harvester_handshake: harvester_protocol.HarvesterHandshake,
        peer: WSChiaConnection,
    ):
        """
        Handshake between the harvester and farmer. The harvester receives the pool public keys,
        as well as the farmer pks, which must be put into the plots, before the plotting process begins.
        We cannot use any plots which have different keys in them.
        """
        self.harvester.farmer_public_keys = harvester_handshake.farmer_public_keys
        self.harvester.pool_public_keys = harvester_handshake.pool_public_keys

        await self.harvester._refresh_plots()

        if len(self.harvester.provers) == 0:
            self.harvester.log.warning(
                "Not farming any plots on this harvester. Check your configuration."
            )
            return

        for new_challenge in self.harvester.cached_challenges:
            async for msg in self.harvester._new_challenge(new_challenge):
                await peer.send_message(msg)

        self.harvester.cached_challenges = []
        self.harvester._state_changed("plots")

    @api_request
    async def new_challenge(
        self, new_challenge: harvester_protocol.NewChallenge, peer: WSChiaConnection
    ):
        async for msg in self.harvester._new_challenge(new_challenge):
            await peer.send_message(msg)

    @api_request
    async def request_proof_of_space(
        self, request: harvester_protocol.RequestProofOfSpace, peer: WSChiaConnection
    ):
        """
        The farmer requests a proof of space, for one of the plots.
        We look up the correct plot based on the plot id and response number, lookup the proof,
        and return it.
        """
        response: Optional[harvester_protocol.RespondProofOfSpace] = None
        challenge_hash = request.challenge_hash
        filename = Path(request.plot_id).resolve()
        index = request.response_number
        proof_xs: bytes
        plot_info = self.harvester.provers[filename]

        try:
            try:
                proof_xs = plot_info.prover.get_full_proof(challenge_hash, index)
            except RuntimeError:
                prover = DiskProver(str(filename))
                self.harvester.provers[filename] = PlotInfo(
                    prover,
                    plot_info.pool_public_key,
                    plot_info.farmer_public_key,
                    plot_info.plot_public_key,
                    plot_info.local_sk,
                    plot_info.file_size,
                    plot_info.time_modified,
                )
                proof_xs = self.harvester.provers[filename].prover.get_full_proof(
                    challenge_hash, index
                )
        except KeyError:
            self.harvester.log.warning(f"KeyError plot {filename} does not exist.")

        plot_info = self.harvester.provers[filename]
        plot_public_key = ProofOfSpace.generate_plot_public_key(
            plot_info.local_sk.get_g1(), plot_info.farmer_public_key
        )

        proof_of_space: ProofOfSpace = ProofOfSpace(
            challenge_hash,
            plot_info.pool_public_key,
            plot_public_key,
            uint8(self.harvester.provers[filename].prover.get_size()),
            proof_xs,
        )
        response = harvester_protocol.RespondProofOfSpace(
            request.plot_id,
            request.response_number,
            proof_of_space,
        )
        if response:
            msg = Message("respond_proof_of_space", response)
            return msg

    @api_request
    async def request_signature(
        self, request: harvester_protocol.RequestSignature, peer: WSChiaConnection
    ):
        """
        The farmer requests a signature on the header hash, for one of the proofs that we found.
        A signature is created on the header hash using the harvester private key. This can also
        be used for pooling.
        """
        plot_info = None
        try:
            plot_info = self.harvester.provers[Path(request.plot_id).resolve()]
        except KeyError:
            self.harvester.log.warning(
                f"KeyError plot {request.plot_id} does not exist."
            )
            return

        local_sk = plot_info.local_sk
        agg_pk = ProofOfSpace.generate_plot_public_key(
            local_sk.get_g1(), plot_info.farmer_public_key
        )

        # This is only a partial signature. When combined with the farmer's half, it will
        # form a complete PrependSignature.
        signature: G2Element = AugSchemeMPL.sign(local_sk, request.message, agg_pk)

        response: harvester_protocol.RespondSignature = (
            harvester_protocol.RespondSignature(
                request.plot_id,
                request.message,
                local_sk.get_g1(),
                plot_info.farmer_public_key,
                signature,
            )
        )

        msg = Message("respond_signature", response)
        return msg
