import logging
import asyncio
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Callable
import time
import concurrent

from blspy import PrependSignature, PrivateKey, PublicKey, Util

from chiapos import DiskProver
from src.protocols import harvester_protocol
from src.server.connection import PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.config import load_config, save_config
from src.util.api_decorators import api_request
from src.util.ints import uint8
from src.util.path import path_from_root
from src.util.plot_utils import load_plots

log = logging.getLogger(__name__)


class Harvester:
    config: Dict
    provers: Dict[str, DiskProver]
    failed_to_open_filenames: List[str]
    not_found_filenames: List[str]
    challenge_hashes: Dict[bytes32, Tuple[bytes32, str, uint8]]
    pool_pubkeys: List[PublicKey]
    root_path: Path
    _plot_notification_task: Optional[asyncio.Task]
    _is_shutdown: bool
    executor: concurrent.futures.ThreadPoolExecutor
    state_changed_callback: Optional[Callable]

    def __init__(self, config: Dict, plot_config: Dict, root_path: Path):
        self.config = config
        self.root_path = root_path

        # From filename to prover
        self.provers = {}
        self.failed_to_open_filenames = []
        self.not_found_filenames = []

        # From quality string to (challenge_hash, filename, index)
        self.challenge_hashes = {}
        self._is_shutdown = False
        self._plot_notification_task = None
        self.global_connections: Optional[PeerConnections] = None
        self.pool_pubkeys = []
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
        self.state_changed_callback = None
        self.server = None

    async def _start(self):
        self._plot_notification_task = asyncio.create_task(self._plot_notification())

    def _close(self):
        self._is_shutdown = True
        self.executor.shutdown(wait=True)

    async def _await_closed(self):
        await self._plot_notification_task

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback
        if self.global_connections is not None:
            self.global_connections.set_state_changed_callback(callback)

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    async def _plot_notification(self):
        """
        Log the plot filenames to console periodically
        """
        counter = 1
        while not self._is_shutdown:
            if counter % 600 == 0:
                found = False
                for filename, prover in self.provers.items():
                    log.info(f"Farming plot {filename} of size {prover.get_size()}")
                    found = True
                if not found:
                    log.warning(
                        "Not farming any plots on this harvester. Check your configuration."
                    )
            await asyncio.sleep(1)
            counter += 1

    def _get_plots(self) -> Tuple[List[Dict], List[str], List[str]]:
        response_plots: List[Dict] = []
        for path, prover in self.provers.items():
            plot_pk = PrivateKey.from_bytes(
                bytes.fromhex(self.plot_config["plots"][path]["sk"])
            ).get_public_key()
            pool_pk = PublicKey.from_bytes(
                bytes.fromhex(self.plot_config["plots"][path]["pool_pk"])
            )
            response_plots.append(
                {
                    "filename": str(path),
                    "size": prover.get_size(),
                    "plot-seed": prover.get_id(),
                    "memo": prover.get_memo(),
                    "plot_pk": bytes(plot_pk),
                    "pool_pk": bytes(pool_pk),
                }
            )
        return (response_plots, self.failed_to_open_filenames, self.not_found_filenames)

    def _refresh_plots(self, reload_config_file=True):
        (
            self.provers,
            self.failed_to_open_filenames,
            self.not_found_filenames,
        ) = load_plots(self.config, self.farmer_pubkeys, self.root_path)
        self._state_changed("plots")

    def _delete_plot(self, str_path: str):
        if str_path in self.provers:
            del self.provers[str_path]

        # Remove absolute and relative paths
        if Path(str_path).exists():
            Path(str_path).unlink()

        self._state_changed("plots")
        return True

    def _add_plot_directory(self, str_path: str) -> bool:
        config = load_config(self.root_path, "config.yaml")
        config["harvester"]["plot_directories"].append(str_path)
        save_config(self.root_path, "config.yaml", config)
        self._refresh_plots()
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
        which must be put into the plots, before the plotting process begins. We cannot
        use any plots which don't have one of the pool keys.
        """
        self.farmer_pubkeys = harvester_handshake.farmer_pubkeys
        self._refresh_plots(reload_config_file=False)
        if len(self.provers) == 0:
            log.warning(
                "Not farming any plots on this harvester. Check your configuration."
            )

    @api_request
    async def new_challenge(self, new_challenge: harvester_protocol.NewChallenge):
        """
        The harvester receives a new challenge from the farmer, and looks up the quality string
        for any proofs of space that are are found in the plots. If proofs are found, a
        ChallengeResponse message is sent for each of the proofs found.
        """
        start = time.time()
        challenge_size = len(new_challenge.challenge_hash)
        if challenge_size != 32:
            raise ValueError(
                f"Invalid challenge size {challenge_size}, 32 was expected"
            )

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
            filename: str, prover: DiskProver
        ) -> List[harvester_protocol.ChallengeResponse]:
            # Exectures a DiskProverLookup in a threadpool, and returns responses
            all_responses: List[harvester_protocol.ChallengeResponse] = []
            quality_strings = await loop.run_in_executor(
                self.executor, blocking_lookup, filename, prover
            )
            if quality_strings is not None:
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
            return all_responses

        awaitables = [
            lookup_challenge(filename, prover)
            for filename, prover in self.provers.items()
        ]

        # Concurrently executes all lookups on disk, to take advantage of multiple disk parallelism
        for sublist_awaitable in asyncio.as_completed(awaitables):
            for response in await sublist_awaitable:
                yield OutboundMessage(
                    NodeType.FARMER,
                    Message("challenge_response", response),
                    Delivery.RESPOND,
                )
        log.info(
            f"Time taken to lookup qualities in {len(self.provers)} plots: {time.time() - start}"
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
                try:
                    proof_xs = self.provers[filename].get_full_proof(
                        challenge_hash, index
                    )
                except RuntimeError:
                    self.provers[filename] = DiskProver(str(filename))
                    proof_xs = self.provers[filename].get_full_proof(
                        challenge_hash, index
                    )
            except KeyError:
                log.warning(f"KeyError plot {filename} does not exist.")
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
