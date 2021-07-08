import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import traceback

import aiohttp
from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey

import hddcoin.server.ws_connection as ws  # lgtm [py/import-and-import-from]
from hddcoin.consensus.coinbase import create_puzzlehash_for_pk
from hddcoin.consensus.constants import ConsensusConstants
from hddcoin.pools.pool_config import PoolWalletConfig, load_pool_config
from hddcoin.protocols import farmer_protocol, harvester_protocol
from hddcoin.protocols.pool_protocol import (
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
from hddcoin.protocols.protocol_message_types import ProtocolMessageTypes
from hddcoin.server.outbound_message import NodeType, make_msg
from hddcoin.server.ws_connection import WSHDDcoinConnection
from hddcoin.types.blockchain_format.proof_of_space import ProofOfSpace
from hddcoin.types.blockchain_format.sized_bytes import bytes32
from hddcoin.util.bech32m import decode_puzzle_hash
from hddcoin.util.config import load_config, save_config, config_path_for_filename
from hddcoin.util.hash import std_hash
from hddcoin.util.ints import uint8, uint16, uint32, uint64
from hddcoin.util.keychain import Keychain
from hddcoin.wallet.derive_keys import (
    master_sk_to_farmer_sk,
    master_sk_to_pool_sk,
    master_sk_to_wallet_sk,
    find_authentication_sk,
    find_owner_sk,
)
from hddcoin.wallet.puzzles.singleton_top_layer import SINGLETON_MOD

singleton_mod_hash = SINGLETON_MOD.get_tree_hash()

log = logging.getLogger(__name__)

UPDATE_POOL_INFO_INTERVAL: int = 3600
UPDATE_POOL_FARMER_INFO_INTERVAL: int = 300

"""
HARVESTER PROTOCOL (FARMER <-> HARVESTER)
"""


class Farmer:
    def __init__(
        self,
        root_path: Path,
        farmer_config: Dict,
        pool_config: Dict,
        keychain: Keychain,
        consensus_constants: ConsensusConstants,
    ):
        self._root_path = root_path
        self.config = farmer_config
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

        self.cache_clear_task: asyncio.Task
        self.update_pool_state_task: asyncio.Task
        self.constants = consensus_constants
        self._shut_down = False
        self.server: Any = None
        self.keychain = keychain
        self.state_changed_callback: Optional[Callable] = None
        self.log = log
        self.all_root_sks: List[PrivateKey] = [sk for sk, _ in self.keychain.get_all_private_keys()]

        self._private_keys = [master_sk_to_farmer_sk(sk) for sk in self.all_root_sks] + [
            master_sk_to_pool_sk(sk) for sk in self.all_root_sks
        ]

        if len(self.get_public_keys()) == 0:
            error_str = "No keys exist. Please run 'hddcoin keys generate' or open the UI."
            raise RuntimeError(error_str)

        # This is the farmer configuration
        self.farmer_target_encoded = self.config["hdd_target_address"]
        self.farmer_target = decode_puzzle_hash(self.farmer_target_encoded)

        self.pool_public_keys = [G1Element.from_bytes(bytes.fromhex(pk)) for pk in self.config["pool_public_keys"]]

        # This is the self pooling configuration, which is only used for original self-pooled plots
        self.pool_target_encoded = pool_config["hdd_target_address"]
        self.pool_target = decode_puzzle_hash(self.pool_target_encoded)
        self.pool_sks_map: Dict = {}
        for key in self.get_private_keys():
            self.pool_sks_map[bytes(key.get_g1())] = key

        assert len(self.farmer_target) == 32
        assert len(self.pool_target) == 32
        if len(self.pool_sks_map) == 0:
            error_str = "No keys exist. Please run 'hddcoin keys generate' or open the UI."
            raise RuntimeError(error_str)

        # The variables below are for use with an actual pool

        # From p2_singleton_puzzle_hash to pool state dict
        self.pool_state: Dict[bytes32, Dict] = {}

        # From public key bytes to PrivateKey
        self.authentication_keys: Dict[bytes, PrivateKey] = {}

        # Last time we updated pool_state based on the config file
        self.last_config_access_time: uint64 = uint64(0)

    async def _start(self):
        self.update_pool_state_task = asyncio.create_task(self._periodically_update_pool_state_task())
        self.cache_clear_task = asyncio.create_task(self._periodically_clear_cache_and_refresh_task())

    def _close(self):
        self._shut_down = True

    async def _await_closed(self):
        await self.cache_clear_task
        await self.update_pool_state_task

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    async def on_connect(self, peer: WSHDDcoinConnection):
        # Sends a handshake to the harvester
        self.state_changed("add_connection", {})
        handshake = harvester_protocol.HarvesterHandshake(
            self.get_public_keys(),
            self.pool_public_keys,
        )
        if peer.connection_type is NodeType.HARVESTER:
            msg = make_msg(ProtocolMessageTypes.harvester_handshake, handshake)
            await peer.send_message(msg)

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

    def on_disconnect(self, connection: ws.WSHDDcoinConnection):
        self.log.info(f"peer disconnected {connection.get_peer_info()}")
        self.state_changed("close_connection", {})

    async def _pool_get_pool_info(self, pool_config: PoolWalletConfig) -> Optional[Dict]:
        try:
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.get(f"{pool_config.pool_url}/pool_info") as resp:
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
        assert authentication_sk.get_g1() == pool_config.authentication_public_key
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
                async with session.get(f"{pool_config.pool_url}/farmer", params=get_farmer_params) as resp:
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
        post_farmer_payload: PostFarmerPayload = PostFarmerPayload(
            pool_config.launcher_id,
            get_current_authentication_token(authentication_token_timeout),
            pool_config.authentication_public_key,
            pool_config.payout_instructions,
            None,
        )
        assert owner_sk.get_g1() == pool_config.owner_public_key
        signature: G2Element = AugSchemeMPL.sign(owner_sk, post_farmer_payload.get_hash())
        post_farmer_request = PostFarmerRequest(post_farmer_payload, signature)
        post_farmer_body = json.dumps(post_farmer_request.to_json_dict())

        headers = {
            "content-type": "application/json;",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{pool_config.pool_url}/farmer", data=post_farmer_body, headers=headers
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
        put_farmer_payload: PutFarmerPayload = PutFarmerPayload(
            pool_config.launcher_id,
            get_current_authentication_token(authentication_token_timeout),
            pool_config.authentication_public_key,
            pool_config.payout_instructions,
            None,
        )
        assert owner_sk.get_g1() == pool_config.owner_public_key
        signature: G2Element = AugSchemeMPL.sign(owner_sk, put_farmer_payload.get_hash())
        put_farmer_request = PutFarmerRequest(put_farmer_payload, signature)
        put_farmer_body = json.dumps(put_farmer_request.to_json_dict())

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(f"{pool_config.pool_url}/farmer", data=put_farmer_body) as resp:
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

    async def update_pool_state(self):
        pool_config_list: List[PoolWalletConfig] = load_pool_config(self._root_path)
        for pool_config in pool_config_list:
            p2_singleton_puzzle_hash = pool_config.p2_singleton_puzzle_hash

            try:
                authentication_sk: Optional[PrivateKey] = await find_authentication_sk(
                    self.all_root_sks, pool_config.authentication_public_key
                )
                if authentication_sk is None:
                    self.log.error(f"Could not find authentication sk for pk: {pool_config.authentication_public_key}")
                    continue
                if p2_singleton_puzzle_hash not in self.pool_state:
                    self.authentication_keys[bytes(pool_config.authentication_public_key)] = authentication_sk
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

                    async def update_pool_farmer_info() -> Optional[dict]:
                        # Run a GET /farmer to see if the farmer is already known by the pool
                        response = await self._pool_get_farmer(
                            pool_config, authentication_token_timeout, authentication_sk
                        )
                        if response is not None and "error_code" not in response:
                            farmer_info: GetFarmerResponse = GetFarmerResponse.from_json_dict(response)
                            pool_state["current_difficulty"] = farmer_info.current_difficulty
                            pool_state["current_points"] = farmer_info.current_points
                            pool_state["next_farmer_update"] = time.time() + UPDATE_POOL_FARMER_INFO_INTERVAL
                        return response

                    if authentication_token_timeout is not None:
                        update_response = await update_pool_farmer_info()
                        is_error = update_response is not None and "error_code" in update_response
                        if is_error and update_response["error_code"] == PoolErrorCode.FARMER_NOT_KNOWN.value:
                            # Make the farmer known on the pool with a POST /farmer
                            owner_sk = await find_owner_sk(self.all_root_sks, pool_config.owner_public_key)
                            post_response = await self._pool_post_farmer(
                                pool_config, authentication_token_timeout, owner_sk
                            )
                            if post_response is not None and "error_code" not in post_response:
                                self.log.info(
                                    f"Welcome message from {pool_config.pool_url}: "
                                    f"{post_response['welcome_message']}"
                                )
                                # Now we should be able to update the local farmer info
                                update_response = await update_pool_farmer_info()
                                if update_response is not None and "error_code" in update_response:
                                    self.log.error(
                                        f"Failed to update farmer info after POST /farmer: "
                                        f"{update_response['error_code']}, "
                                        f"{update_response['error_message']}"
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

    def get_reward_targets(self, search_for_private_key: bool) -> Dict:
        if search_for_private_key:
            all_sks = self.keychain.get_all_private_keys()
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
            config["farmer"]["hdd_target_address"] = farmer_target_encoded
        if pool_target_encoded is not None:
            self.pool_target_encoded = pool_target_encoded
            self.pool_target = decode_puzzle_hash(pool_target_encoded)
            config["pool"]["hdd_target_address"] = pool_target_encoded
        save_config(self._root_path, "config.yaml", config)

    async def set_payout_instructions(self, launcher_id: bytes32, payout_instructions: str):
        for p2_singleton_puzzle_hash, pool_state_dict in self.pool_state.items():
            if launcher_id == pool_state_dict["pool_config"].launcher_id:
                config = load_config(self._root_path, "config.yaml")
                new_list = []
                for list_element in config["pool"]["pool_list"]:
                    if bytes.fromhex(list_element["launcher_id"]) == bytes(launcher_id):
                        list_element["payout_instructions"] = payout_instructions
                    new_list.append(list_element)

                config["pool"]["pool_list"] = new_list
                save_config(self._root_path, "config.yaml", config)
                await self.update_pool_state()
                return

        self.log.warning(f"Launcher id: {launcher_id} not found")

    async def generate_login_link(self, launcher_id: bytes32) -> Optional[str]:
        for pool_state in self.pool_state.values():
            pool_config: PoolWalletConfig = pool_state["pool_config"]
            if pool_config.launcher_id == launcher_id:
                authentication_sk: Optional[PrivateKey] = await find_authentication_sk(
                    self.all_root_sks, pool_config.authentication_public_key
                )
                if authentication_sk is None:
                    self.log.error(f"Could not find authentication sk for pk: {pool_config.authentication_public_key}")
                    continue
                assert authentication_sk.get_g1() == pool_config.authentication_public_key
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

    async def get_plots(self) -> Dict:
        rpc_response = {}
        for connection in self.server.get_connections():
            if connection.connection_type == NodeType.HARVESTER:
                peer_host = connection.peer_host
                peer_port = connection.peer_port
                peer_full = f"{peer_host}:{peer_port}"
                response = await connection.request_plots(harvester_protocol.RequestPlots(), timeout=5)
                if response is None:
                    self.log.error(
                        "Harvester did not respond. You might need to update harvester to the latest version"
                    )
                    continue
                if not isinstance(response, harvester_protocol.RespondPlots):
                    self.log.error(f"Invalid response from harvester: {peer_host}:{peer_port}")
                    continue
                rpc_response[peer_full] = response.to_json_dict()
        return rpc_response

    async def _periodically_update_pool_state_task(self):
        time_slept: uint64 = uint64(0)
        config_path: Path = config_path_for_filename(self._root_path, "config.yaml")
        while not self._shut_down:
            # Every time the config file changes, read it to check the pool state
            stat_info = config_path.stat()
            if stat_info.st_mtime > self.last_config_access_time:
                # If we detect the config file changed, refresh private keys first just in case
                self.all_root_sks: List[PrivateKey] = [sk for sk, _ in self.keychain.get_all_private_keys()]
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
            await asyncio.sleep(1)
