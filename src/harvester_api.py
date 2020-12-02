import asyncio
import dataclasses
import time
from pathlib import Path
from typing import Optional, Callable, List, Tuple

from blspy import AugSchemeMPL, G2Element, G1Element
from chiapos import DiskProver

from src.consensus.pot_iterations import calculate_sp_interval_iters, calculate_iterations_quality
from src.harvester import Harvester
from src.plotting.plot_tools import PlotInfo
from src.protocols import harvester_protocol
from src.server.outbound_message import Message
from src.server.ws_connection import WSChiaConnection
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request, peer_required
from src.util.ints import uint8, uint64


class HarvesterAPI:
    harvester: Harvester

    def __init__(self, harvester):
        self.harvester = harvester
        self.farmer_public_keys: List[G1Element] = []
        self.pool_public_keys: List[G1Element] = []

    def _set_state_changed_callback(self, callback: Callable):
        self.harvester.state_changed_callback = callback

    @api_request
    async def harvester_handshake(self, harvester_handshake: harvester_protocol.HarvesterHandshake):
        """
        Handshake between the harvester and farmer. The harvester receives the pool public keys,
        as well as the farmer pks, which must be put into the plots, before the plotting process begins.
        We cannot use any plots which have different keys in them.
        """
        self.farmer_public_keys = harvester_handshake.farmer_public_keys
        self.pool_public_keys = harvester_handshake.pool_public_keys

        await self.harvester.refresh_plots()

        if len(self.harvester.provers) == 0:
            self.harvester.log.warning("Not farming any plots on this harvester. Check your configuration.")
            return

        self.harvester._state_changed("plots")

    @peer_required
    @api_request
    async def new_signage_point(self, new_challenge: harvester_protocol.NewSignagePoint, peer: WSChiaConnection):
        """
        The harvester receives a new signage point from the farmer, this happens at the start of each slot.
        The harvester does a few things:
        1. The harvester applies the plot filter for each of the plots, to select the proportion which are eligible
        for this signage point and challenge.
        2. The harvester gets the qualities for each plot. This is approximately 7 reads per plot which qualifies.
        Note that each plot may have 0, 1, 2, etc qualities for that challenge: but on average it will have 1.
        3. Checks the required_iters for each quality and the given signage point, to see which are eligible for
        inclusion (required_iters < sp_interval_iters).
        4. Looks up the full proof of space in the plot for each quality, approximately 64 reads per quality
        5. Returns the proof of space to the farmer
        """
        if len(self.pool_public_keys) == 0 or len(self.farmer_public_keys) == 0:
            # This means that we have not received the handshake yet
            return

        start = time.time()
        assert len(new_challenge.challenge_hash) == 32

        # Refresh plots to see if there are any new ones
        await self.harvester.refresh_plots()

        loop = asyncio.get_running_loop()

        def blocking_lookup(filename: Path, plot_info: PlotInfo, prover: DiskProver) -> List[ProofOfSpace]:
            # Uses the DiskProver object to lookup qualities. This is a blocking call,
            # so it should be run in a thread pool.
            try:
                sp_challenge_hash = ProofOfSpace.calculate_new_challenge_hash(
                    plot_info.prover.get_id(), new_challenge.challenge_hash, new_challenge.sp_hash
                )
                quality_strings = prover.get_qualities_for_challenge(sp_challenge_hash)
            except Exception:
                self.harvester.log.error("Error using prover object. Reinitializing prover object.")
                self.harvester.provers[filename] = dataclasses.replace(plot_info, prover=DiskProver(str(filename)))
                return []

            responses: List[ProofOfSpace] = []
            if quality_strings is not None:
                # Found proofs of space (on average 1 is expected per plot)
                for index, quality_str in enumerate(quality_strings):
                    required_iters: uint64 = calculate_iterations_quality(
                        quality_str, prover.get_size(), new_challenge.difficulty, new_challenge.sp_hash
                    )
                    sp_interval_iters = calculate_sp_interval_iters(
                        self.harvester.constants, new_challenge.sub_slot_iters
                    )
                    if required_iters < sp_interval_iters:
                        # Found a very good proof of space! will fetch the whole proof from disk, then send to farmer
                        try:
                            proof_xs = prover.get_full_proof(sp_challenge_hash, index)
                        except RuntimeError:
                            self.harvester.log.error(f"Exception fetching full proof for {filename}")
                            continue

                        plot_public_key = ProofOfSpace.generate_plot_public_key(
                            plot_info.local_sk.get_g1(), plot_info.farmer_public_key
                        )
                        responses.append(
                            ProofOfSpace(
                                sp_challenge_hash,
                                plot_info.pool_public_key,
                                None,
                                plot_public_key,
                                uint8(prover.get_size()),
                                proof_xs,
                            )
                        )
            return responses

        async def lookup_challenge(filename: Path, prover: DiskProver) -> List[harvester_protocol.NewProofOfSpace]:
            # Executes a DiskProverLookup in a thread pool, and returns responses
            all_responses: List[harvester_protocol.NewProofOfSpace] = []
            proofs_of_space: List[ProofOfSpace] = await loop.run_in_executor(
                self.harvester.executor, blocking_lookup, filename, prover
            )
            for proof_of_space in proofs_of_space:
                all_responses.append(
                    harvester_protocol.NewProofOfSpace(
                        new_challenge.challenge_hash, prover.get_id(), proof_of_space, new_challenge.signage_point_index
                    )
                )
            return all_responses

        awaitables = []
        for try_plot_filename, try_plot_info in self.harvester.provers.items():
            if try_plot_filename.exists():
                # Passes the plot filter (does not check sp filter yet though, since we have not reached sp)
                # This is being executed at the beginning of the slot
                if ProofOfSpace.passes_plot_filter(
                    self.harvester.constants,
                    try_plot_info.prover.get_id(),
                    new_challenge.challenge_hash,
                    new_challenge.sp_hash,
                ):
                    awaitables.append(lookup_challenge(try_plot_filename, try_plot_info.prover))

        # Concurrently executes all lookups on disk, to take advantage of multiple disk parallelism
        total_proofs_found = 0
        for sublist_awaitable in asyncio.as_completed(awaitables):
            for response in await sublist_awaitable:
                total_proofs_found += 1
                msg = Message("challenge_response", response)
                await peer.send_message(msg)
        self.harvester.log.info(
            f"{len(awaitables)} plots were eligible for farming {new_challenge.challenge_hash.hex()[:10]}..."
            f" Found {total_proofs_found} proofs. Time: {time.time() - start}. "
            f"Total {len(self.harvester.provers)} plots"
        )

    @api_request
    async def request_signatures(self, request: harvester_protocol.RequestSignatures):
        """
        The farmer requests a signature on the header hash, for one of the proofs that we found.
        A signature is created on the header hash using the harvester private key. This can also
        be used for pooling.
        """
        try:
            plot_info = self.harvester.provers[Path(request.plot_identifier).resolve()]
        except KeyError:
            self.harvester.log.warning(f"KeyError plot {request.plot_identifier} does not exist.")
            return

        local_sk = plot_info.local_sk
        agg_pk = ProofOfSpace.generate_plot_public_key(local_sk.get_g1(), plot_info.farmer_public_key)

        # This is only a partial signature. When combined with the farmer's half, it will
        # form a complete PrependSignature.
        message_signatures: List[Tuple[bytes32, G2Element]] = []
        for message in request.messages:
            signature: G2Element = AugSchemeMPL.sign(local_sk, message, agg_pk)
            message_signatures.append((message, signature))

        response: harvester_protocol.RespondSignatures = harvester_protocol.RespondSignatures(
            request.plot_identifier,
            request.sp_hash,
            local_sk.get_g1(),
            plot_info.farmer_public_key,
            message_signatures,
        )

        msg = Message("respond_signatures", response)
        return msg
