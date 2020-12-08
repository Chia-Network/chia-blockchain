import asyncio
import logging
from typing import Dict, List, Optional, Callable, Tuple

from blspy import G1Element

from src.server.ws_connection import WSChiaConnection
from src.util.keychain import Keychain

from src.consensus.constants import ConsensusConstants

from src.protocols import farmer_protocol, harvester_protocol
from src.server.outbound_message import Message, NodeType
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
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
        self.sps: Dict[bytes32, List[farmer_protocol.NewSignagePoint]] = {}

        # Keep track of harvester plot identifier (str), target sp index, and PoSpace for each challenge
        self.proofs_of_space: Dict[bytes32, List[Tuple[str, ProofOfSpace]]] = {}

        # Quality string to plot identifier and challenge_hash, for use with harvester.RequestSignatures
        self.quality_str_to_identifiers: Dict[bytes32, Tuple[str, bytes32, bytes32]] = {}

        # number of responses to each signage point
        self.number_of_responses: Dict[bytes32, int] = {}

        # A dictionary of keys to time added. These keys refer to keys in the above 4 dictionaries. This is used
        # to periodically clear the memory
        self.cache_add_time: Dict[bytes32, uint64] = {}

        self.cache_clear_task: asyncio.Task
        self.constants = consensus_constants
        self._shut_down = False
        self.server = None
        self.keychain = keychain
        self.state_changed_callback: Optional[Callable] = None
        self.log = log

        if len(self.get_public_keys()) == 0:
            error_str = "No keys exist. Please run 'chia keys generate' or open the UI."
            raise RuntimeError(error_str)

        # This is the farmer configuration
        self.wallet_target = decode_puzzle_hash(self.config["xch_target_address"])
        self.pool_public_keys = [G1Element.from_bytes(bytes.fromhex(pk)) for pk in self.config["pool_public_keys"]]

        # This is the pool configuration, which should be moved out to the pool once it exists
        self.pool_target = decode_puzzle_hash(pool_config["xch_target_address"])
        self.pool_sks_map: Dict = {}
        for key in self.get_private_keys():
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

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    async def on_connect(self, peer: WSChiaConnection):
        # Sends a handshake to the harvester
        msg = harvester_protocol.HarvesterHandshake(
            self.get_public_keys(),
            self.pool_public_keys,
        )
        if peer.connection_type is NodeType.HARVESTER:
            msg = Message("harvester_handshake", msg)
            await peer.send_message(msg)

    def set_server(self, server):
        self.server = server

    def state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    def get_public_keys(self):
        return [child_sk.get_g1() for child_sk in self.get_private_keys()]

    def get_private_keys(self):
        all_sks = self.keychain.get_all_private_keys()
        return [master_sk_to_farmer_sk(sk) for sk, _ in all_sks] + [master_sk_to_pool_sk(sk) for sk, _ in all_sks]

    async def _periodically_clear_cache_task(self):
        time_slept: uint64 = uint64(0)
        while not self._shut_down:
            if time_slept > self.constants.SUB_SLOT_TIME_TARGET * 3:
                removed_keys: List[bytes32] = []
                for key, add_time in self.cache_add_time.items():
                    self.sps.pop(key, None)
                    self.proofs_of_space.pop(key, None)
                    self.quality_str_to_identifiers.pop(key, None)
                    self.number_of_responses.pop(key, None)
                    removed_keys.append(key)
                for key in removed_keys:
                    self.cache_add_time.pop(key, None)
                time_slept = uint64(0)
            time_slept += 0.1
            await asyncio.sleep(0.1)
