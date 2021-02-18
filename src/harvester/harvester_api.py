import asyncio
import time
from pathlib import Path
from typing import Callable, List, Tuple

from blspy import AugSchemeMPL, G2Element

from src.consensus.pot_iterations import (
    calculate_sp_interval_iters,
    calculate_iterations_quality,
)
from src.harvester.harvester import Harvester
from src.plotting.plot_tools import PlotInfo
from src.protocols import harvester_protocol
from src.protocols.farmer_protocol import FarmingInfo
from src.protocols.protocol_message_types import ProtocolMessageTypes
from src.server.outbound_message import make_msg
from src.server.ws_connection import WSChiaConnection
from src.types.blockchain_format.proof_of_space import ProofOfSpace
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.api_decorators import api_request, peer_required
from src.util.ints import uint8, uint64, uint32


class HarvesterAPI:
    harvester: Harvester

    def __init__(self, harvester: Harvester):
        self.harvester = harvester

    def _set_state_changed_callback(self, callback: Callable):
        self.harvester.state_changed_callback = callback

    @api_request
    async def harvester_handshake(self, harvester_handshake: harvester_protocol.HarvesterHandshake):
        """
        Handshake between the harvester and farmer. The harvester receives the pool public keys,
        as well as the farmer pks, which must be put into the plots, before the plotting process begins.
        We cannot use any plots which have different keys in them.
        """
        self.harvester.farmer_public_keys = harvester_handshake.farmer_public_keys
        self.harvester.pool_public_keys = harvester_handshake.pool_public_keys

        await self.harvester.refresh_plots()

        if len(self.harvester.provers) == 0:
            self.harvester.log.warning("Not farming any plots on this harvester. Check your configuration.")
            return

        self.harvester._state_changed("plots")

    @peer_required
    @api_request
    async def new_signage_point_harvester(
        self, new_challenge: harvester_protocol.NewSignagePointHarvester, peer: WSChiaConnection
    ):
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
        if len(self.harvester.pool_public_keys) == 0 or len(self.harvester.farmer_public_keys) == 0:
            # This means that we have not received the handshake yet
            return

        start = time.time()
        assert len(new_challenge.challenge_hash) == 32

        # Refresh plots to see if there are any new ones
        if start - self.harvester.last_load_time > 120:
            await self.harvester.refresh_plots()
            self.harvester.last_load_time = time.time()

        loop = asyncio.get_running_loop()

        def blocking_lookup(filename: Path, plot_info: PlotInfo) -> List[Tuple[bytes32, ProofOfSpace]]:
            # Uses the DiskProver object to lookup qualities. This is a blocking call,
            # so it should be run in a thread pool.
            try:
                sp_challenge_hash = ProofOfSpace.calculate_pos_challenge(
                    plot_info.prover.get_id(),
                    new_challenge.challenge_hash,
                    new_challenge.sp_hash,
                )
                try:
                    quality_strings = plot_info.prover.get_qualities_for_challenge(sp_challenge_hash)
                except Exception as e:
                    self.harvester.log.error(f"Error using prover object {e}")
                    return []

                responses: List[Tuple[bytes32, ProofOfSpace]] = []
                if quality_strings is not None:
                    # Found proofs of space (on average 1 is expected per plot)
                    for index, quality_str in enumerate(quality_strings):
                        required_iters: uint64 = calculate_iterations_quality(
                            self.harvester.constants.DIFFICULTY_CONSTANT_FACTOR,
                            quality_str,
                            plot_info.prover.get_size(),
                            new_challenge.difficulty,
                            new_challenge.sp_hash,
                        )
                        sp_interval_iters = calculate_sp_interval_iters(
                            self.harvester.constants, new_challenge.sub_slot_iters
                        )
                        if required_iters < sp_interval_iters:
                            # Found a very good proof of space! will fetch the whole proof from disk,
                            # then send to farmer
                            try:
                                proof_xs = plot_info.prover.get_full_proof(sp_challenge_hash, index)
                            except RuntimeError:
                                self.harvester.log.error(f"Exception fetching full proof for {filename}")
                                continue

                            plot_public_key = ProofOfSpace.generate_plot_public_key(
                                plot_info.local_sk.get_g1(), plot_info.farmer_public_key
                            )
                            responses.append(
                                (
                                    quality_str,
                                    ProofOfSpace(
                                        sp_challenge_hash,
                                        plot_info.pool_public_key,
                                        plot_info.pool_contract_puzzle_hash,
                                        plot_public_key,
                                        uint8(plot_info.prover.get_size()),
                                        proof_xs,
                                    ),
                                )
                            )
                return responses
            except Exception as e:
                self.harvester.log.error(f"Unknown error: {e}")
                return []

        async def lookup_challenge(filename: Path, plot_info: PlotInfo) -> List[harvester_protocol.NewProofOfSpace]:
            # Executes a DiskProverLookup in a thread pool, and returns responses
            all_responses: List[harvester_protocol.NewProofOfSpace] = []
            if self.harvester._is_shutdown:
                return []
            proofs_of_space_and_q: List[Tuple[bytes32, ProofOfSpace]] = await loop.run_in_executor(
                self.harvester.executor, blocking_lookup, filename, plot_info
            )
            for quality_str, proof_of_space in proofs_of_space_and_q:
                all_responses.append(
                    harvester_protocol.NewProofOfSpace(
                        new_challenge.challenge_hash,
                        new_challenge.sp_hash,
                        quality_str.hex() + str(filename.resolve()),
                        proof_of_space,
                        new_challenge.signage_point_index,
                    )
                )
            return all_responses

        awaitables = []
        passed = 0
        total = 0
        for try_plot_filename, try_plot_info in self.harvester.provers.items():
            if try_plot_filename.exists():
                # Passes the plot filter (does not check sp filter yet though, since we have not reached sp)
                # This is being executed at the beginning of the slot
                total += 1
                if ProofOfSpace.passes_plot_filter(
                    self.harvester.constants,
                    try_plot_info.prover.get_id(),
                    new_challenge.challenge_hash,
                    new_challenge.sp_hash,
                ):
                    passed += 1
                    awaitables.append(lookup_challenge(try_plot_filename, try_plot_info))

        # Concurrently executes all lookups on disk, to take advantage of multiple disk parallelism
        total_proofs_found = 0
        for sublist_awaitable in asyncio.as_completed(awaitables):
            for response in await sublist_awaitable:
                total_proofs_found += 1
                msg = make_msg(ProtocolMessageTypes.new_proof_of_space, response)
                await peer.send_message(msg)

        now = uint64(int(time.time()))
        farming_info = FarmingInfo(
            new_challenge.challenge_hash,
            new_challenge.sp_hash,
            now,
            uint32(passed),
            uint32(total_proofs_found),
            uint32(total),
        )
        pass_msg = make_msg(ProtocolMessageTypes.farming_info, farming_info)
        await peer.send_message(pass_msg)
        self.harvester.log.info(
            f"{len(awaitables)} plots were eligible for farming {new_challenge.challenge_hash.hex()[:10]}..."
            f" Found {total_proofs_found} proofs. Time: {time.time() - start:.5f} s. "
            f"Total {len(self.harvester.provers)} plots"
        )

    @api_request
    async def request_signatures(self, request: harvester_protocol.RequestSignatures):
        """
        The farmer requests a signature on the header hash, for one of the proofs that we found.
        A signature is created on the header hash using the harvester private key. This can also
        be used for pooling.
        """
        plot_filename = Path(request.plot_identifier[64:]).resolve()
        try:
            plot_info = self.harvester.provers[plot_filename]
        except KeyError:
            self.harvester.log.warning(f"KeyError plot {plot_filename} does not exist.")
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
            request.challenge_hash,
            request.sp_hash,
            local_sk.get_g1(),
            plot_info.farmer_public_key,
            message_signatures,
        )

        return make_msg(ProtocolMessageTypes.respond_signatures, response)
