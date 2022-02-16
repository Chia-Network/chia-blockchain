import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import traceback

import aiohttp
from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey

import chia.server.ws_connection as ws  # lgtm [py/import-and-import-from]
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.consensus.constants import ConsensusConstants
from chia.daemon.keychain_proxy import (
    KeychainProxy,
    KeychainProxyConnectionFailure,
    connect_to_keychain_and_validate,
    wrap_local_keychain,
)
from chia.pools.pool_config import PoolWalletConfig, load_pool_config
from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.pool_protocol import (
    ErrorResponse,
    get_current_authentication_token,
    GetFarmerResponse,
    PoolErrorCode,
    PostFarmerPayload,
    PostFarmerRequest,
    PutFarmerPayload,
    PutFarmerRequest,
    AuthenticationPayload,
)
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import NodeType, make_msg
from chia.server.server import ssl_context_for_root
from chia.server.ws_connection import WSChiaConnection
from chia.ssl.create_ssl import get_mozilla_ca_crt
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config, save_config, config_path_for_filename
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.util.keychain import Keychain
from chia.wallet.derive_keys import (
    master_sk_to_farmer_sk,
    master_sk_to_pool_sk,
    master_sk_to_wallet_sk,
    find_authentication_sk,
    find_owner_sk,
)
from chia.wallet.puzzles.singleton_top_layer import SINGLETON_MOD

singleton_mod_hash = SINGLETON_MOD.get_tree_hash()

log = logging.getLogger(__name__)

UPDATE_POOL_INFO_INTERVAL: int = 3600
UPDATE_POOL_FARMER_INFO_INTERVAL: int = 300
UPDATE_HARVESTER_CACHE_INTERVAL: int = 90

"""
HARVESTER PROTOCOL (FARMER <-> HARVESTER)
"""


class HarvesterCacheEntry:
    def __init__(self):
        self.data: Optional[dict] = None
        self.last_update: float = 0

    def bump_last_update(self):
        self.last_update = time.time()

    def set_data(self, data):
        self.data = data
        self.bump_last_update()

    def needs_update(self, update_interval: int):
        return time.time() - self.last_update > update_interval

    def expired(self, update_interval: int):
        return time.time() - self.last_update > update_interval * 10


class Farmer:
    def __init__(
        self,
        root_path: Path,
        farmer_config: Dict,
        pool_config: Dict,
        consensus_constants: ConsensusConstants,
        local_keychain: Optional[Keychain] = None,
    ):
        self.keychain_proxy: Optional[KeychainProxy] = None
        self.local_keychain = local_keychain
        self._root_path = root_path
        self.config = farmer_config
        self.pool_config = pool_config
        # Keep track of all sps, keyed on challenge chain signage point hash
        self.sps: Dict[bytes32, List[farmer_protocol.NewSignagePoint]] = {}

        # Keep track of harvester plot identifier (str), target sp index, and PoSpace for each challenge
        self.proofs_of_space: Dict[bytes32, List[Tuple[str, ProofOfSpace]]] = {}

        # Quality string to plot identifier and challenge_hash, for use with harvester.RequestSignatures
        self.quality_str_to_identifiers: Dict[bytes32, Tuple[str, bytes32, bytes32, bytes32]] = {}

        # number of responses to each signage point
        self.number_of_responses: Dict[bytes32, int] = {}

        # A dictionary of keys to time added. These keys refer to keys in the above 4 dictionaries. This is used
        # to periodically clear the memory
        self.cache_add_time: Dict[bytes32, uint64] = {}

        # Interval to request plots from connected harvesters
        self.update_harvester_cache_interval = UPDATE_HARVESTER_CACHE_INTERVAL

        self.cache_clear_task: Optional[asyncio.Task] = None
        self.update_pool_state_task: Optional[asyncio.Task] = None
        self.constants = consensus_constants
        self._shut_down = False
        self.server: Any = None
        self.state_changed_callback: Optional[Callable] = None
        self.log = log
        self.started = False
        self.harvester_handshake_task: Optional[asyncio.Task] = None

        # From p2_singleton_puzzle_hash to pool state dict
        self.pool_state: Dict[bytes32, Dict] = {}

        # From p2_singleton to auth PrivateKey
        self.authentication_keys: Dict[bytes32, PrivateKey] = {}

        # Last time we updated pool_state based on the config file
        self.last_config_access_time: uint64 = uint64(0)

        self.harvester_cache: Dict[str, Dict[str, HarvesterCacheEntry]] = {}

    async def ensure_keychain_proxy(self) -> KeychainProxy:
        if not self.keychain_proxy:
            if self.local_keychain:
                self.keychain_proxy = wrap_local_keychain(self.local_keychain, log=self.log)
            else:
                self.keychain_proxy = await connect_to_keychain_and_validate(self._root_path, self.log)
                if not self.keychain_proxy:
                    raise KeychainProxyConnectionFailure("Failed to connect to keychain service")
        return self.keychain_proxy

    async def get_all_private_keys(self):
        keychain_proxy = await self.ensure_keychain_proxy()
        return await keychain_proxy.get_all_private_keys()

    async def setup_keys(self) -> bool:
        no_keys_error_str = "No keys exist. Please run 'chia keys generate' or open the UI."
        self.all_root_sks: List[PrivateKey] = [sk for sk, _ in await self.get_all_private_keys()]
        self._private_keys = [master_sk_to_farmer_sk(sk) for sk in self.all_root_sks] + [
            master_sk_to_pool_sk(sk) for sk in self.all_root_sks
        ]

        if len(self.get_public_keys()) == 0:
            log.warning(no_keys_error_str)
            return False

        config = load_config(self._root_path, "config.yaml")
        if "xch_target_address" not in self.config:
            self.config = config["farmer"]
        if "xch_target_address" not in self.pool_config:
            self.pool_config = config["pool"]
        if "xch_target_address" not in self.config or "xch_target_address" not in self.pool_config:
            log.debug("xch_target_address missing in the config")
            return False

        # This is the farmer configuration
        self.farmer_target_encoded = self.config["xch_target_address"]
        self.farmer_target = decode_puzzle_hash(self.farmer_target_encoded)

        self.pool_public_keys = [G1Element.from_bytes(bytes.fromhex(pk)) for pk in self.config["pool_public_keys"]]

        # This is the self pooling configuration, which is only used for original self-pooled plots
        self.pool_target_encoded = self.pool_config["xch_target_address"]
        self.pool_target = decode_puzzle_hash(self.pool_target_encoded)
        self.pool_sks_map: Dict = {}
        for key in self.get_private_keys():
            self.pool_sks_map[bytes(key.get_g1())] = key

        assert len(self.farmer_target) == 32
        assert len(self.pool_target) == 32
        if len(self.pool_sks_map) == 0:
            log.warning(no_keys_error_str)
            return False

        return True

    async def _start(self):
        async def start_task():
            # `Farmer.setup_keys` returns `False` if there are no keys setup yet. In this case we just try until it
            # succeeds or until we need to shut down.
            while not self._shut_down:
                if await self.setup_keys():
                    self.update_pool_state_task = asyncio.create_task(self._periodically_update_pool_state_task())
                    self.cache_clear_task = asyncio.create_task(self._periodically_clear_cache_and_refresh_task())
                    log.debug("start_task: initialized")
                    self.started = True
                    return
                await asyncio.sleep(1)

        asyncio.create_task(start_task())

    def _close(self):
        self._shut_down = True

    async def _await_closed(self):
        if self.cache_clear_task is not None:
            await self.cache_clear_task
        if self.update_pool_state_task is not None:
            await self.update_pool_state_task
        self.started = False

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    async def on_connect(self, peer: WSChiaConnection):
        self.state_changed("add_connection", {})

        async def handshake_task():
            # Wait until the task in `Farmer._start` is done so that we have keys available for the handshake. Bail out
            # early if we need to shut down or if the harvester is not longer connected.
            while not self.started and not self._shut_down and peer in self.server.get_connections():
                await asyncio.sleep(1)

            if self._shut_down:
                log.debug("handshake_task: shutdown")
                self.harvester_handshake_task = None
                return

            if peer not in self.server.get_connections():
                log.debug("handshake_task: disconnected")
                self.harvester_handshake_task = None
                return

            # Sends a handshake to the harvester
            handshake = harvester_protocol.HarvesterHandshake(
                self.get_public_keys(),
                self.pool_public_keys,
            )
            msg = make_msg(ProtocolMessageTypes.harvester_handshake, handshake)
            await peer.send_message(msg)
            self.harvester_handshake_task = None

        if peer.connection_type is NodeType.HARVESTER:
            self.harvester_handshake_task = asyncio.create_task(handshake_task())

    def set_server(self, server):
        self.server = server

    def state_changed(self, change: str, data: Dict[str, Any]):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change, data)

    def handle_failed_pool_response(self, p2_singleton_puzzle_hash: bytes32, error_message: str):
        self.log.error(error_message)
        self.pool_state[p2_singleton_puzzle_hash]["pool_errors_24h"].append(
            ErrorResponse(uint16(PoolErrorCode.REQUEST_FAILED.value), error_message).to_json_dict()
        )

    def on_disconnect(self, connection: ws.WSChiaConnection):
        self.log.info(f"peer disconnected {connection.get_peer_logging()}")
        self.state_changed("close_connection", {})

    async def _pool_get_pool_info(self, pool_config: PoolWalletConfig) -> Optional[Dict]:
        try:
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.get(
                    f"{pool_config.pool_url}/pool_info", ssl=ssl_context_for_root(get_mozilla_ca_crt(), log=self.log)
                ) as resp:
                    if resp.ok:
                        response: Dict = json.loads(await resp.text())
                        self.log.info(f"GET /pool_info response: {response}")
                        return response
                    else:
                        self.handle_failed_pool_response(
                            pool_config.p2_singleton_puzzle_hash,
                            f"Error in GET /pool_info {pool_config.pool_url}, {resp.status}",
                        )

        except Exception as e:
            self.handle_failed_pool_response(
                pool_config.p2_singleton_puzzle_hash, f"Exception in GET /pool_info {pool_config.pool_url}, {e}"
            )

        return None

    async def _pool_get_farmer(
        self, pool_config: PoolWalletConfig, authentication_token_timeout: uint8, authentication_sk: PrivateKey
    ) -> Optional[Dict]:
        authentication_token = get_current_authentication_token(authentication_token_timeout)
        message: bytes32 = std_hash(
            AuthenticationPayload(
                "get_farmer", pool_config.launcher_id, pool_config.target_puzzle_hash, authentication_token
            )
        )
        signature: G2Element = AugSchemeMPL.sign(authentication_sk, message)
        get_farmer_params = {
            "launcher_id": pool_config.launcher_id.hex(),
            "authentication_token": authentication_token,
            "signature": bytes(signature).hex(),
        }
        try:
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.get(
                    f"{pool_config.pool_url}/farmer",
                    params=get_farmer_params,
                    ssl=ssl_context_for_root(get_mozilla_ca_crt(), log=self.log),
                ) as resp:
                    if resp.ok:
                        response: Dict = json.loads(await resp.text())
                        self.log.info(f"GET /farmer response: {response}")
                        if "error_code" in response:
                            self.pool_state[pool_config.p2_singleton_puzzle_hash]["pool_errors_24h"].append(response)
                        return response
                    else:
                        self.handle_failed_pool_response(
                            pool_config.p2_singleton_puzzle_hash,
                            f"Error in GET /farmer {pool_config.pool_url}, {resp.status}",
                        )
        except Exception as e:
            self.handle_failed_pool_response(
                pool_config.p2_singleton_puzzle_hash, f"Exception in GET /farmer {pool_config.pool_url}, {e}"
            )
        return None

    async def _pool_post_farmer(
        self, pool_config: PoolWalletConfig, authentication_token_timeout: uint8, owner_sk: PrivateKey
    ) -> Optional[Dict]:
        auth_sk: Optional[PrivateKey] = self.get_authentication_sk(pool_config)
        assert auth_sk is not None
        post_farmer_payload: PostFarmerPayload = PostFarmerPayload(
            pool_config.launcher_id,
            get_current_authentication_token(authentication_token_timeout),
            auth_sk.get_g1(),
            pool_config.payout_instructions,
            None,
        )
        assert owner_sk.get_g1() == pool_config.owner_public_key
        signature: G2Element = AugSchemeMPL.sign(owner_sk, post_farmer_payload.get_hash())
        post_farmer_request = PostFarmerRequest(post_farmer_payload, signature)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{pool_config.pool_url}/farmer",
                    json=post_farmer_request.to_json_dict(),
                    ssl=ssl_context_for_root(get_mozilla_ca_crt(), log=self.log),
                ) as resp:
                    if resp.ok:
                        response: Dict = json.loads(await resp.text())
                        self.log.info(f"POST /farmer response: {response}")
                        if "error_code" in response:
                            self.pool_state[pool_config.p2_singleton_puzzle_hash]["pool_errors_24h"].append(response)
                        return response
                    else:
                        self.handle_failed_pool_response(
                            pool_config.p2_singleton_puzzle_hash,
                            f"Error in POST /farmer {pool_config.pool_url}, {resp.status}",
                        )
        except Exception as e:
            self.handle_failed_pool_response(
                pool_config.p2_singleton_puzzle_hash, f"Exception in POST /farmer {pool_config.pool_url}, {e}"
            )
        return None

    async def _pool_put_farmer(
        self, pool_config: PoolWalletConfig, authentication_token_timeout: uint8, owner_sk: PrivateKey
    ) -> Optional[Dict]:
        auth_sk: Optional[PrivateKey] = self.get_authentication_sk(pool_config)
        assert auth_sk is not None
        put_farmer_payload: PutFarmerPayload = PutFarmerPayload(
            pool_config.launcher_id,
            get_current_authentication_token(authentication_token_timeout),
            auth_sk.get_g1(),
            pool_config.payout_instructions,
            None,
        )
        assert owner_sk.get_g1() == pool_config.owner_public_key
        signature: G2Element = AugSchemeMPL.sign(owner_sk, put_farmer_payload.get_hash())
        put_farmer_request = PutFarmerRequest(put_farmer_payload, signature)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    f"{pool_config.pool_url}/farmer",
                    json=put_farmer_request.to_json_dict(),
                    ssl=ssl_context_for_root(get_mozilla_ca_crt(), log=self.log),
                ) as resp:
                    if resp.ok:
                        response: Dict = json.loads(await resp.text())
                        self.log.info(f"PUT /farmer response: {response}")
                        if "error_code" in response:
                            self.pool_state[pool_config.p2_singleton_puzzle_hash]["pool_errors_24h"].append(response)
                        return response
                    else:
                        self.handle_failed_pool_response(
                            pool_config.p2_singleton_puzzle_hash,
                            f"Error in PUT /farmer {pool_config.pool_url}, {resp.status}",
                        )
        except Exception as e:
            self.handle_failed_pool_response(
                pool_config.p2_singleton_puzzle_hash, f"Exception in PUT /farmer {pool_config.pool_url}, {e}"
            )
        return None

    def get_authentication_sk(self, pool_config: PoolWalletConfig) -> Optional[PrivateKey]:
        if pool_config.p2_singleton_puzzle_hash in self.authentication_keys:
            return self.authentication_keys[pool_config.p2_singleton_puzzle_hash]
        auth_sk: Optional[PrivateKey] = find_authentication_sk(self.all_root_sks, pool_config.owner_public_key)
        if auth_sk is not None:
            self.authentication_keys[pool_config.p2_singleton_puzzle_hash] = auth_sk
        return auth_sk

    async def update_pool_state(self):
        config = load_config(self._root_path, "config.yaml")
        pool_config_list: List[PoolWalletConfig] = load_pool_config(self._root_path)
        for pool_config in pool_config_list:
            p2_singleton_puzzle_hash = pool_config.p2_singleton_puzzle_hash

            try:
                authentication_sk: Optional[PrivateKey] = self.get_authentication_sk(pool_config)

                if authentication_sk is None:
                    self.log.error(f"Could not find authentication sk for {p2_singleton_puzzle_hash}")
                    continue
                if p2_singleton_puzzle_hash not in self.pool_state:
                    self.pool_state[p2_singleton_puzzle_hash] = {
                        "points_found_since_start": 0,
                        "points_found_24h": [],
                        "points_acknowledged_since_start": 0,
                        "points_acknowledged_24h": [],
                        "next_farmer_update": 0,
                        "next_pool_info_update": 0,
                        "current_points": 0,
                        "current_difficulty": None,
                        "pool_errors_24h": [],
                        "authentication_token_timeout": None,
                    }
                    self.log.info(f"Added pool: {pool_config}")
                pool_state = self.pool_state[p2_singleton_puzzle_hash]
                pool_state["pool_config"] = pool_config

                # Skip state update when self pooling
                if pool_config.pool_url == "":
                    continue

                enforce_https = config["full_node"]["selected_network"] == "mainnet"
                if enforce_https and not pool_config.pool_url.startswith("https://"):
                    self.log.error(f"Pool URLs must be HTTPS on mainnet {pool_config.pool_url}")
                    continue

                # TODO: Improve error handling below, inform about unexpected failures
                if time.time() >= pool_state["next_pool_info_update"]:
                    # Makes a GET request to the pool to get the updated information
                    pool_info = await self._pool_get_pool_info(pool_config)
                    if pool_info is not None and "error_code" not in pool_info:
                        pool_state["authentication_token_timeout"] = pool_info["authentication_token_timeout"]
                        pool_state["next_pool_info_update"] = time.time() + UPDATE_POOL_INFO_INTERVAL
                        # Only update the first time from GET /pool_info, gets updated from GET /farmer later
                        if pool_state["current_difficulty"] is None:
                            pool_state["current_difficulty"] = pool_info["minimum_difficulty"]

                if time.time() >= pool_state["next_farmer_update"]:
                    authentication_token_timeout = pool_state["authentication_token_timeout"]

                    async def update_pool_farmer_info() -> Tuple[Optional[GetFarmerResponse], Optional[bool]]:
                        # Run a GET /farmer to see if the farmer is already known by the pool
                        response = await self._pool_get_farmer(
                            pool_config, authentication_token_timeout, authentication_sk
                        )
                        farmer_response: Optional[GetFarmerResponse] = None
                        farmer_known: Optional[bool] = None
                        if response is not None:
                            if "error_code" not in response:
                                farmer_response = GetFarmerResponse.from_json_dict(response)
                                if farmer_response is not None:
                                    pool_state["current_difficulty"] = farmer_response.current_difficulty
                                    pool_state["current_points"] = farmer_response.current_points
                                    pool_state["next_farmer_update"] = time.time() + UPDATE_POOL_FARMER_INFO_INTERVAL
                            else:
                                farmer_known = response["error_code"] != PoolErrorCode.FARMER_NOT_KNOWN.value
                                self.log.error(
                                    "update_pool_farmer_info failed: "
                                    f"{response['error_code']}, {response['error_message']}"
                                )

                        return farmer_response, farmer_known

                    if authentication_token_timeout is not None:
                        farmer_info, farmer_is_known = await update_pool_farmer_info()
                        if farmer_info is None and farmer_is_known is not None and not farmer_is_known:
                            # Make the farmer known on the pool with a POST /farmer
                            owner_sk_and_index: Optional[PrivateKey, uint32] = find_owner_sk(
                                self.all_root_sks, pool_config.owner_public_key
                            )
                            assert owner_sk_and_index is not None
                            post_response = await self._pool_post_farmer(
                                pool_config, authentication_token_timeout, owner_sk_and_index[0]
                            )
                            if post_response is not None and "error_code" not in post_response:
                                self.log.info(
                                    f"Welcome message from {pool_config.pool_url}: "
                                    f"{post_response['welcome_message']}"
                                )
                                # Now we should be able to update the local farmer info
                                farmer_info, farmer_is_known = await update_pool_farmer_info()
                                if farmer_info is None and not farmer_is_known:
                                    self.log.error("Failed to update farmer info after POST /farmer.")

                        # Update the payout instructions on the pool if required
                        if (
                            farmer_info is not None
                            and pool_config.payout_instructions.lower() != farmer_info.payout_instructions.lower()
                        ):
                            owner_sk_and_index: Optional[PrivateKey, uint32] = find_owner_sk(
                                self.all_root_sks, pool_config.owner_public_key
                            )
                            assert owner_sk_and_index is not None
                            put_farmer_response_dict = await self._pool_put_farmer(
                                pool_config, authentication_token_timeout, owner_sk_and_index[0]
                            )
                            try:
                                # put_farmer_response: PutFarmerResponse = PutFarmerResponse.from_json_dict(
                                #     put_farmer_response_dict
                                # )
                                # if put_farmer_response.payout_instructions:
                                #     self.log.info(
                                #         f"Farmer information successfully updated on the pool {pool_config.pool_url}"
                                #     )
                                # TODO: Fix Streamable implementation and recover the above.
                                if put_farmer_response_dict["payout_instructions"]:
                                    self.log.info(
                                        f"Farmer information successfully updated on the pool {pool_config.pool_url}"
                                    )
                                else:
                                    raise Exception
                            except Exception:
                                self.log.error(
                                    f"Failed to update farmer information on the pool {pool_config.pool_url}"
                                )

                    else:
                        self.log.warning(
                            f"No pool specific authentication_token_timeout has been set for {p2_singleton_puzzle_hash}"
                            f", check communication with the pool."
                        )

            except Exception as e:
                tb = traceback.format_exc()
                self.log.error(f"Exception in update_pool_state for {pool_config.pool_url}, {e} {tb}")

    def get_public_keys(self):
        return [child_sk.get_g1() for child_sk in self._private_keys]

    def get_private_keys(self):
        return self._private_keys

    async def get_reward_targets(self, search_for_private_key: bool) -> Dict:
        if search_for_private_key:
            all_sks = await self.get_all_private_keys()
            stop_searching_for_farmer, stop_searching_for_pool = False, False
            for i in range(500):
                if stop_searching_for_farmer and stop_searching_for_pool and i > 0:
                    break
                for sk, _ in all_sks:
                    ph = create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(i)).get_g1())

                    if ph == self.farmer_target:
                        stop_searching_for_farmer = True
                    if ph == self.pool_target:
                        stop_searching_for_pool = True
            return {
                "farmer_target": self.farmer_target_encoded,
                "pool_target": self.pool_target_encoded,
                "have_farmer_sk": stop_searching_for_farmer,
                "have_pool_sk": stop_searching_for_pool,
            }
        return {
            "farmer_target": self.farmer_target_encoded,
            "pool_target": self.pool_target_encoded,
        }

    def set_reward_targets(self, farmer_target_encoded: Optional[str], pool_target_encoded: Optional[str]):
        config = load_config(self._root_path, "config.yaml")
        if farmer_target_encoded is not None:
            self.farmer_target_encoded = farmer_target_encoded
            self.farmer_target = decode_puzzle_hash(farmer_target_encoded)
            config["farmer"]["xch_target_address"] = farmer_target_encoded
        if pool_target_encoded is not None:
            self.pool_target_encoded = pool_target_encoded
            self.pool_target = decode_puzzle_hash(pool_target_encoded)
            config["pool"]["xch_target_address"] = pool_target_encoded
        save_config(self._root_path, "config.yaml", config)

    async def set_payout_instructions(self, launcher_id: bytes32, payout_instructions: str):
        for p2_singleton_puzzle_hash, pool_state_dict in self.pool_state.items():
            if launcher_id == pool_state_dict["pool_config"].launcher_id:
                config = load_config(self._root_path, "config.yaml")
                new_list = []
                pool_list = config["pool"].get("pool_list", [])
                if pool_list is not None:
                    for list_element in pool_list:
                        if hexstr_to_bytes(list_element["launcher_id"]) == bytes(launcher_id):
                            list_element["payout_instructions"] = payout_instructions
                        new_list.append(list_element)

                config["pool"]["pool_list"] = new_list
                save_config(self._root_path, "config.yaml", config)
                # Force a GET /farmer which triggers the PUT /farmer if it detects the changed instructions
                pool_state_dict["next_farmer_update"] = 0
                return

        self.log.warning(f"Launcher id: {launcher_id} not found")

    async def generate_login_link(self, launcher_id: bytes32) -> Optional[str]:
        for pool_state in self.pool_state.values():
            pool_config: PoolWalletConfig = pool_state["pool_config"]
            if pool_config.launcher_id == launcher_id:

                authentication_sk: Optional[PrivateKey] = self.get_authentication_sk(pool_config)
                if authentication_sk is None:
                    self.log.error(f"Could not find authentication sk for {pool_config.p2_singleton_puzzle_hash}")
                    continue
                authentication_token_timeout = pool_state["authentication_token_timeout"]
                authentication_token = get_current_authentication_token(authentication_token_timeout)
                message: bytes32 = std_hash(
                    AuthenticationPayload(
                        "get_login", pool_config.launcher_id, pool_config.target_puzzle_hash, authentication_token
                    )
                )
                signature: G2Element = AugSchemeMPL.sign(authentication_sk, message)
                return (
                    pool_config.pool_url
                    + f"/login?launcher_id={launcher_id.hex()}&authentication_token={authentication_token}"
                    f"&signature={bytes(signature).hex()}"
                )

        return None

    async def update_cached_harvesters(self) -> bool:
        # First remove outdated cache entries
        self.log.debug(f"update_cached_harvesters cache entries: {len(self.harvester_cache)}")
        remove_hosts = []
        for host, host_cache in self.harvester_cache.items():
            remove_peers = []
            for peer_id, peer_cache in host_cache.items():
                # If the peer cache is expired it means the harvester didn't respond for too long
                if peer_cache.expired(self.update_harvester_cache_interval):
                    remove_peers.append(peer_id)
            for key in remove_peers:
                del host_cache[key]
            if len(host_cache) == 0:
                self.log.debug(f"update_cached_harvesters remove host: {host}")
                remove_hosts.append(host)
        for key in remove_hosts:
            del self.harvester_cache[key]
        # Now query each harvester and update caches
        updated = False
        for connection in self.server.get_connections(NodeType.HARVESTER):
            cache_entry = await self.get_cached_harvesters(connection)
            if cache_entry.needs_update(self.update_harvester_cache_interval):
                self.log.debug(f"update_cached_harvesters update harvester: {connection.peer_node_id}")
                cache_entry.bump_last_update()
                response = await connection.request_plots(
                    harvester_protocol.RequestPlots(), timeout=self.update_harvester_cache_interval
                )
                if response is not None:
                    if isinstance(response, harvester_protocol.RespondPlots):
                        new_data: Dict = response.to_json_dict()
                        if cache_entry.data != new_data:
                            updated = True
                            self.log.debug(f"update_cached_harvesters cache updated: {connection.peer_node_id}")
                        else:
                            self.log.debug(f"update_cached_harvesters no changes for: {connection.peer_node_id}")
                        cache_entry.set_data(new_data)
                    else:
                        self.log.error(
                            f"Invalid response from harvester:"
                            f"peer_host {connection.peer_host}, peer_node_id {connection.peer_node_id}"
                        )
                else:
                    self.log.error(
                        f"Harvester '{connection.peer_host}/{connection.peer_node_id}' did not respond: "
                        f"(version mismatch or time out {UPDATE_HARVESTER_CACHE_INTERVAL}s)"
                    )
        return updated

    async def get_cached_harvesters(self, connection: WSChiaConnection) -> HarvesterCacheEntry:
        host_cache = self.harvester_cache.get(connection.peer_host)
        if host_cache is None:
            host_cache = {}
            self.harvester_cache[connection.peer_host] = host_cache
        node_cache = host_cache.get(connection.peer_node_id.hex())
        if node_cache is None:
            node_cache = HarvesterCacheEntry()
            host_cache[connection.peer_node_id.hex()] = node_cache
        return node_cache

    async def get_harvesters(self) -> Dict:
        harvesters: List = []
        for connection in self.server.get_connections(NodeType.HARVESTER):
            self.log.debug(f"get_harvesters host: {connection.peer_host}, node_id: {connection.peer_node_id}")
            cache_entry = await self.get_cached_harvesters(connection)
            if cache_entry.data is not None:
                harvester_object: dict = dict(cache_entry.data)
                harvester_object["connection"] = {
                    "node_id": connection.peer_node_id.hex(),
                    "host": connection.peer_host,
                    "port": connection.peer_port,
                }
                harvesters.append(harvester_object)
            else:
                self.log.debug(f"get_harvesters no cache: {connection.peer_host}, node_id: {connection.peer_node_id}")

        return {"harvesters": harvesters}

    async def _periodically_update_pool_state_task(self):
        time_slept: uint64 = uint64(0)
        config_path: Path = config_path_for_filename(self._root_path, "config.yaml")
        while not self._shut_down:
            # Every time the config file changes, read it to check the pool state
            stat_info = config_path.stat()
            if stat_info.st_mtime > self.last_config_access_time:
                # If we detect the config file changed, refresh private keys first just in case
                self.all_root_sks: List[PrivateKey] = [sk for sk, _ in await self.get_all_private_keys()]
                self.last_config_access_time = stat_info.st_mtime
                await self.update_pool_state()
                time_slept = uint64(0)
            elif time_slept > 60:
                await self.update_pool_state()
                time_slept = uint64(0)
            time_slept += 1
            await asyncio.sleep(1)

    async def _periodically_clear_cache_and_refresh_task(self):
        time_slept: uint64 = uint64(0)
        refresh_slept = 0
        while not self._shut_down:
            try:
                if time_slept > self.constants.SUB_SLOT_TIME_TARGET:
                    now = time.time()
                    removed_keys: List[bytes32] = []
                    for key, add_time in self.cache_add_time.items():
                        if now - float(add_time) > self.constants.SUB_SLOT_TIME_TARGET * 3:
                            self.sps.pop(key, None)
                            self.proofs_of_space.pop(key, None)
                            self.quality_str_to_identifiers.pop(key, None)
                            self.number_of_responses.pop(key, None)
                            removed_keys.append(key)
                    for key in removed_keys:
                        self.cache_add_time.pop(key, None)
                    time_slept = uint64(0)
                    log.debug(
                        f"Cleared farmer cache. Num sps: {len(self.sps)} {len(self.proofs_of_space)} "
                        f"{len(self.quality_str_to_identifiers)} {len(self.number_of_responses)}"
                    )
                time_slept += 1
                refresh_slept += 1
                # Periodically refresh GUI to show the correct download/upload rate.
                if refresh_slept >= 30:
                    self.state_changed("add_connection", {})
                    refresh_slept = 0

                # Handles harvester plots cache cleanup and updates
                if await self.update_cached_harvesters():
                    self.state_changed("new_plots", await self.get_harvesters())
            except Exception:
                log.error(f"_periodically_clear_cache_and_refresh_task failed: {traceback.format_exc()}")

            await asyncio.sleep(1)
