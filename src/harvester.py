import logging
import asyncio
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Callable, Set
import time
import concurrent

from blspy import G1Element, G2Element, AugSchemeMPL

from chiapos import DiskProver
from src.protocols import harvester_protocol
from src.server.connection import PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.proof_of_space import ProofOfSpace
from src.util.config import load_config, save_config
from src.util.api_decorators import api_request
from src.util.ints import uint8
from src.plotting.plot_tools import load_plots, PlotInfo
from src.consensus.constants import constants as consensus_constants

log = logging.getLogger(__name__)


class Harvester:
    config: Dict
    provers: Dict[Path, PlotInfo]
    failed_to_open_filenames: Set[Path]
    no_key_filenames: Set[Path]
    farmer_public_keys: List[G1Element]
    pool_public_keys: List[G1Element]
    cached_challenges: List[harvester_protocol.NewChallenge]
    root_path: Path
    _is_shutdown: bool
    executor: concurrent.futures.ThreadPoolExecutor
    state_changed_callback: Optional[Callable]
    constants: Dict
    _refresh_lock: asyncio.Lock

    def __init__(self, root_path: Path, override_constants={}):
        self.root_path = root_path

        # From filename to prover
        self.provers = {}
        self.failed_to_open_filenames = set()
        self.no_key_filenames = set()

        self._is_shutdown = False
        self.global_connections: Optional[PeerConnections] = None
        self.farmer_public_keys = []
        self.pool_public_keys = []
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        self.state_changed_callback = None
        self.server = None
        self.constants = consensus_constants.copy()
        self.cached_challenges = []
        for key, value in override_constants.items():
            self.constants[key] = value

    async def _start(self):
        self._refresh_lock = asyncio.Lock()

    def _close(self):
        self._is_shutdown = True
        self.executor.shutdown(wait=True)

    async def _await_closed(self):
        pass

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback
        if self.global_connections is not None:
            self.global_connections.set_state_changed_callback(callback)

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    def _get_plots(self) -> Tuple[List[Dict], List[str], List[str]]:
        response_plots: List[Dict] = []
        for path, plot_info in self.provers.items():
            prover = plot_info.prover
            response_plots.append(
                {
                    "filename": str(path),
                    "size": prover.get_size(),
                    "plot-seed": prover.get_id(),
                    "pool_public_key": plot_info.pool_public_key,
                    "farmer_public_key": plot_info.farmer_public_key,
                    "plot_public_key": plot_info.plot_public_key,
                    "local_sk": plot_info.local_sk,
                    "file_size": plot_info.file_size,
                    "time_modified": plot_info.time_modified,
                }
            )

        return (
            response_plots,
            [str(s) for s in self.failed_to_open_filenames],
            [str(s) for s in self.no_key_filenames],
        )

    async def _refresh_plots(self):
        async with self._refresh_lock:
            (
                changed,
                self.provers,
                self.failed_to_open_filenames,
                self.no_key_filenames,
            ) = load_plots(
                self.provers,
                self.failed_to_open_filenames,
                self.farmer_public_keys,
                self.pool_public_keys,
                self.root_path,
            )
        if changed:
            self._state_changed("plots")

    def _delete_plot(self, str_path: str):
        path = Path(str_path).resolve()
        if path in self.provers:
            del self.provers[path]

        # Remove absolute and relative paths
        if path.exists():
            path.unlink()

        self._state_changed("plots")
        return True

    async def _add_plot_directory(self, str_path: str) -> bool:
        config = load_config(self.root_path, "config.yaml")
        if str(Path(str_path).resolve()) not in config["harvester"]["plot_directories"]:
            config["harvester"]["plot_directories"].append(
                str(Path(str_path).resolve())
            )
            save_config(self.root_path, "config.yaml", config)
            await self._refresh_plots()
        return True

    def _set_global_connections(self, global_connections: Optional[PeerConnections]):
        self.global_connections = global_connections

    def _set_server(self, server):
        self.server = server

    @api_request
    async def harvester_handshake(
        self, harvester_handshake: harvester_protocol.HarvesterHandshake
    ):
        """
        Handshake between the harvester and farmer. The harvester receives the pool public keys,
        as well as the farmer pks, which must be put into the plots, before the plotting process begins.
        We cannot use any plots which have different keys in them.
        """
        self.farmer_public_keys = harvester_handshake.farmer_public_keys
        self.pool_public_keys = harvester_handshake.pool_public_keys

        await self._refresh_plots()

        if len(self.provers) == 0:
            log.warning(
                "Not farming any plots on this harvester. Check your configuration."
            )
            return

        for new_challenge in self.cached_challenges:
            async for msg in self.new_challenge(new_challenge):
                yield msg
        self.cached_challenges = []
        self._state_changed("plots")

    @api_request
    async def new_challenge(self, new_challenge: harvester_protocol.NewChallenge):
        """
        The harvester receives a new challenge from the farmer, and looks up the quality string
        for any proofs of space that are are found in the plots. If proofs are found, a
        ChallengeResponse message is sent for each of the proofs found.
        """
        if len(self.pool_public_keys) == 0 or len(self.farmer_public_keys) == 0:
            self.cached_challenges = self.cached_challenges[:5]
            self.cached_challenges.insert(0, new_challenge)
            return

        start = time.time()
        assert len(new_challenge.challenge_hash) == 32

        # Refresh plots to see if there are any new ones
        await self._refresh_plots()

        loop = asyncio.get_running_loop()

        def blocking_lookup(filename: Path, prover: DiskProver) -> Optional[List]:
            # Uses the DiskProver object to lookup qualities. This is a blocking call,
            # so it should be run in a threadpool.
            try:
                quality_strings = prover.get_qualities_for_challenge(
                    new_challenge.challenge_hash
                )
            except RuntimeError:
                log.error("Error using prover object. Reinitializing prover object.")
                try:
                    self.prover = DiskProver(str(filename))
                    quality_strings = self.prover.get_qualities_for_challenge(
                        new_challenge.challenge_hash
                    )
                except RuntimeError:
                    log.error(
                        f"Retry-Error using prover object on {filename}. Giving up."
                    )
                    quality_strings = None
            return quality_strings

        async def lookup_challenge(
            filename: Path, prover: DiskProver
        ) -> List[harvester_protocol.ChallengeResponse]:
            # Exectures a DiskProverLookup in a threadpool, and returns responses
            all_responses: List[harvester_protocol.ChallengeResponse] = []
            quality_strings = await loop.run_in_executor(
                self.executor, blocking_lookup, filename, prover
            )
            if quality_strings is not None:
                for index, quality_str in enumerate(quality_strings):
                    response: harvester_protocol.ChallengeResponse = harvester_protocol.ChallengeResponse(
                        new_challenge.challenge_hash,
                        str(filename),
                        uint8(index),
                        quality_str,
                        prover.get_size(),
                    )
                    all_responses.append(response)
            return all_responses

        awaitables = []
        for filename, plot_info in self.provers.items():
            if ProofOfSpace.can_create_proof(
                plot_info.prover.get_id(),
                new_challenge.challenge_hash,
                self.constants["NUMBER_ZERO_BITS_CHALLENGE_SIG"],
            ):
                awaitables.append(lookup_challenge(filename, plot_info.prover))

        # Concurrently executes all lookups on disk, to take advantage of multiple disk parallelism
        for sublist_awaitable in asyncio.as_completed(awaitables):
            for response in await sublist_awaitable:
                yield OutboundMessage(
                    NodeType.FARMER,
                    Message("challenge_response", response),
                    Delivery.RESPOND,
                )
        log.info(
            f"{len(awaitables)} plots were eligible for farming for this challenge, time: {time.time() - start}. "
            f"Total {len(self.provers)} plots"
        )

    @api_request
    async def request_proof_of_space(
        self, request: harvester_protocol.RequestProofOfSpace
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
        plot_info = self.provers[filename]

        try:
            try:
                proof_xs = plot_info.prover.get_full_proof(challenge_hash, index)
            except RuntimeError:
                prover = DiskProver(str(filename))
                self.provers[filename] = PlotInfo(
                    prover,
                    plot_info.pool_public_key,
                    plot_info.farmer_public_key,
                    plot_info.plot_public_key,
                    plot_info.local_sk,
                    plot_info.file_size,
                    plot_info.time_modified,
                )
                proof_xs = self.provers[filename].prover.get_full_proof(
                    challenge_hash, index
                )
        except KeyError:
            log.warning(f"KeyError plot {filename} does not exist.")

        plot_info = self.provers[filename]
        plot_public_key = ProofOfSpace.generate_plot_public_key(
            plot_info.local_sk.get_g1(), plot_info.farmer_public_key
        )

        proof_of_space: ProofOfSpace = ProofOfSpace(
            challenge_hash,
            plot_info.pool_public_key,
            plot_public_key,
            uint8(self.provers[filename].prover.get_size()),
            proof_xs,
        )
        response = harvester_protocol.RespondProofOfSpace(
            request.plot_id, request.response_number, proof_of_space,
        )
        if response:
            yield OutboundMessage(
                NodeType.FARMER,
                Message("respond_proof_of_space", response),
                Delivery.RESPOND,
            )

    @api_request
    async def request_signature(self, request: harvester_protocol.RequestSignature):
        """
        The farmer requests a signature on the header hash, for one of the proofs that we found.
        A signature is created on the header hash using the harvester private key. This can also
        be used for pooling.
        """
        plot_info = self.provers[Path(request.plot_id).resolve()]

        local_sk = plot_info.local_sk
        agg_pk = ProofOfSpace.generate_plot_public_key(
            local_sk.get_g1(), plot_info.farmer_public_key
        )

        # This is only a partial signature. When combined with the farmer's half, it will
        # form a complete PrependSignature.
        signature: G2Element = AugSchemeMPL.sign(local_sk, request.message, agg_pk)

        response: harvester_protocol.RespondSignature = harvester_protocol.RespondSignature(
            request.plot_id,
            request.message,
            local_sk.get_g1(),
            plot_info.farmer_public_key,
            signature,
        )

        yield OutboundMessage(
            NodeType.FARMER, Message("respond_signature", response), Delivery.RESPOND,
        )
