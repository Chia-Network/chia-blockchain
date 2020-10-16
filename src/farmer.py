import asyncio
import logging
from typing import Dict, List, Optional, Callable, Set, Tuple

from blspy import G1Element, G2Element, AugSchemeMPL

from src.server.server import ChiaServer
from src.server.ws_connection import WSChiaConnection
from src.util.keychain import Keychain

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_iterations_quality,
    calculate_sp_interval_iters,
)
from src.protocols import farmer_protocol, harvester_protocol
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.types.pool_target import PoolTarget
from src.util.api_decorators import api_request
from src.util.ints import uint32, uint64
from src.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk
from src.util.chech32 import decode_puzzle_hash

log = logging.getLogger(__name__)


"""
HARVESTER PROTOCOL (FARMER <-> HARVESTER)
"""


class Farmer:
    def __init__(
        self,
        farmer_config: Dict,
        pool_config: Dict,
        keychain: Keychain,
        consensus_constants: ConsensusConstants,
    ):
        self.config = farmer_config
        # Keep track of all sps, keyed on challenge chain signage point hash
        self.sps: Dict[bytes32, farmer_protocol.NewSignagePoint] = {}

        # Keep track of harvester plot identifier (str), target sp index, and PoSpace for each challenge
        self.proofs_of_space: Dict[bytes32, List[Tuple[str, ProofOfSpace]]] = {}

        # Quality string to plot identifier and challenge_hash, for use with harvester.RequestSignatures
        self.quality_str_to_identifiers: Dict[bytes32, Tuple[str, bytes32]] = {}

        # number of responses to each signage point
        self.number_of_responses: Dict[bytes32, int] = {}

        # A dictionary of keys to time added. These keys refer to keys in the above 4 dictionaries. This is used
        # to periodically clear the memory
        self.cache_add_time: Dict[bytes32, uint64] = {}

        self.cache_clear_task: asyncio.Task
        self.constants = consensus_constants
        self._shut_down = False
        self.server: Optional[ChiaServer] = None
        self.keychain = keychain
        self.state_changed_callback: Optional[Callable] = None
        self.log = log

        if len(self._get_public_keys()) == 0:
            error_str = "No keys exist. Please run 'chia keys generate' or open the UI."
            raise RuntimeError(error_str)

        # This is the farmer configuration
        self.wallet_target = decode_puzzle_hash(self.config["xch_target_address"])
        self.pool_public_keys = [G1Element.from_bytes(bytes.fromhex(pk)) for pk in self.config["pool_public_keys"]]

        # This is the pool configuration, which should be moved out to the pool once it exists
        self.pool_target = decode_puzzle_hash(pool_config["xch_target_address"])
        self.pool_sks_map: Dict = {}
        for key in self._get_private_keys():
            self.pool_sks_map[bytes(key.get_g1())] = key

        assert len(self.wallet_target) == 32
        assert len(self.pool_target) == 32
        if len(self.pool_sks_map) == 0:
            error_str = "No keys exist. Please run 'chia keys generate' or open the UI."
            raise RuntimeError(error_str)

    async def _start(self):
        self.cache_clear_task = asyncio.create_task(self._periodically_clear_cache_task())

    def _close(self):
        self._shut_down = True

    async def _await_closed(self):
        await self.cache_clear_task

    async def _on_connect(self, peer: WSChiaConnection):
        # Sends a handshake to the harvester
        h_msg = harvester_protocol.HarvesterHandshake(
            self._get_public_keys(), self.pool_public_keys
        )
        msg = Message("harvester_handshake", h_msg)
        await peer.send_message(msg)

        if self.current_weight in self.challenges:
            for posf in self.challenges[self.current_weight]:
                message = harvester_protocol.NewChallenge(posf.challenge_hash)
                msg = Message("new_challenge", message)
                await peer.send_message(msg)

    def _set_server(self, server):
        self.server = server

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    def _get_public_keys(self):
        return [child_sk.get_g1() for child_sk in self._get_private_keys()]

    def _get_private_keys(self):
        all_sks = self.keychain.get_all_private_keys()
        return [master_sk_to_farmer_sk(sk) for sk, _ in all_sks] + [
            master_sk_to_pool_sk(sk) for sk, _ in all_sks
        ]

    async def _get_required_iters(
        self, challenge_hash: bytes32, quality_string: bytes32, plot_size: uint8
    ):
        weight: uint128 = self.challenge_to_weight[challenge_hash]
        difficulty: uint64 = uint64(0)
        for posf in self.challenges[weight]:
            if posf.challenge_hash == challenge_hash:
                difficulty = posf.difficulty
        if difficulty == 0:
            raise RuntimeError("Did not find challenge")

        estimate_min = (
            self.proof_of_time_estimate_ips
            * self.constants.BLOCK_TIME_TARGET
            / self.constants.MIN_ITERS_PROPORTION
        )
        estimate_min = uint64(int(estimate_min))
        number_iters: uint64 = calculate_iterations_quality(
            quality_string,
            plot_size,
            difficulty,
            estimate_min,
        )
        return number_iters
