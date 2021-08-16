import asyncio
import json
import logging
import socket
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, Union

from blspy import PrivateKey

from chia.consensus.constants import ConsensusConstants
from chia.pools.pool_puzzles import SINGLETON_LAUNCHER_HASH
from chia.protocols import wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import RespondToCoinUpdates, CoinState, RespondToPhUpdates
from chia.server.node_discovery import WalletPeers
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32
from chia.util.keychain import Keychain
from chia.util.lru_cache import LRUCache
from chia.util.path import mkdir, path_from_root

from chia.wallet.settings.settings_objects import BackupInitialized
from chia.wallet.simple_wallet.simple_wallet_state_manager import SimpleWalletStateManager
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.backup_utils import open_backup_file
from chia.wallet.wallet_action import WalletAction
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.util.profiler import profile_task


class SimpleWalletNode:
    key_config: Dict
    config: Dict
    constants: ConsensusConstants
    server: Optional[ChiaServer]
    log: logging.Logger
    wallet_peers: WalletPeers
    # Maintains the state of the wallet (blockchain and transactions), handles DB connections
    wallet_state_manager: Optional[SimpleWalletStateManager]

    # How far away from LCA we must be to perform a full sync. Before then, do a short sync,
    # which is consecutive requests for the previous block
    short_sync_threshold: int
    _shut_down: bool
    root_path: Path
    state_changed_callback: Optional[Callable]
    syncing: bool
    full_node_peer: Optional[PeerInfo]
    peer_task: Optional[asyncio.Task]
    logged_in: bool
    wallet_peers_initialized: bool

    def __init__(
        self,
        config: Dict,
        keychain: Keychain,
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = None,
    ):
        self.config = config
        self.constants = consensus_constants
        self.root_path = root_path
        self.log = logging.getLogger(name if name else __name__)
        # Normal operation data
        self.cached_blocks: Dict = {}
        self.future_block_hashes: Dict = {}
        self.keychain = keychain

        # Sync data
        self._shut_down = False
        self.proof_hashes: List = []
        self.header_hashes: List = []
        self.header_hashes_error = False
        self.short_sync_threshold = 15  # Change the test when changing this
        self.potential_blocks_received: Dict = {}
        self.potential_header_hashes: Dict = {}
        self.state_changed_callback = None
        self.wallet_state_manager = None
        self.backup_initialized = False  # Delay first launch sync after user imports backup info or decides to skip
        self.server = None
        self.wsm_close_task = None
        self.sync_task: Optional[asyncio.Task] = None
        self.logged_in_fingerprint: Optional[int] = None
        self.peer_task = None
        self.logged_in = False
        self.wallet_peers_initialized = False
        self.last_new_peak_messages = LRUCache(5)

    def get_key_for_fingerprint(self, fingerprint: Optional[int]) -> Optional[PrivateKey]:
        private_keys = self.keychain.get_all_private_keys()
        if len(private_keys) == 0:
            self.log.warning("No keys present. Create keys with the UI, or with the 'chia keys' program.")
            return None

        private_key: Optional[PrivateKey] = None
        if fingerprint is not None:
            for sk, _ in private_keys:
                if sk.get_g1().get_fingerprint() == fingerprint:
                    private_key = sk
                    break
        else:
            private_key = private_keys[0][0]  # If no fingerprint, take the first private key
        return private_key

    async def _start(
        self,
        fingerprint: Optional[int] = None,
        new_wallet: bool = False,
        backup_file: Optional[Path] = None,
        skip_backup_import: bool = False,
    ) -> bool:
        private_key = self.get_key_for_fingerprint(fingerprint)
        if private_key is None:
            self.logged_in = False
            return False

        if self.config.get("enable_profiler", False):
            asyncio.create_task(profile_task(self.root_path, "wallet", self.log))

        db_path_key_suffix = str(private_key.get_g1().get_fingerprint())
        db_path_replaced: str = (
            self.config["database_path"]
            .replace("CHALLENGE", self.config["selected_network"])
            .replace("KEY", db_path_key_suffix)
        )
        path = path_from_root(self.root_path, db_path_replaced)
        mkdir(path.parent)
        self.new_peak_lock = asyncio.Lock()
        assert self.server is not None
        self.wallet_state_manager = await SimpleWalletStateManager.create(
            private_key, self.config, path, self.constants, self.server, self.root_path, self.new_puzzle_hash_created, self.get_coin_state,
            self.subscribe_to_coin_updates
        )

        self.wsm_close_task = None

        assert self.wallet_state_manager is not None

        backup_settings: BackupInitialized = self.wallet_state_manager.user_settings.get_backup_settings()
        if backup_settings.user_initialized is False:
            if new_wallet is True:
                await self.wallet_state_manager.user_settings.user_created_new_wallet()
                self.wallet_state_manager.new_wallet = True
            elif skip_backup_import is True:
                await self.wallet_state_manager.user_settings.user_skipped_backup_import()
            elif backup_file is not None:
                await self.wallet_state_manager.import_backup_info(backup_file)
            else:
                self.backup_initialized = False
                await self.wallet_state_manager.close_all_stores()
                self.wallet_state_manager = None
                self.logged_in = False
                return False

        self.backup_initialized = True

        # Start peers here after the backup initialization has finished
        # We only want to do this once per instantiation
        # However, doing it earlier before backup initialization causes
        # the wallet to spam the introducer
        if self.wallet_peers_initialized is False:
            asyncio.create_task(self.wallet_peers.start())
            self.wallet_peers_initialized = True

        if backup_file is not None:
            json_dict = open_backup_file(backup_file, self.wallet_state_manager.private_key)
            if "start_height" in json_dict["data"]:
                start_height = json_dict["data"]["start_height"]
                self.config["starting_height"] = max(0, start_height - self.config["start_height_buffer"])
            else:
                self.config["starting_height"] = 0
        else:
            self.config["starting_height"] = 0

        if self.state_changed_callback is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)

        self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)
        self._shut_down = False

        self.peer_task = asyncio.create_task(self._periodically_check_full_node())
        self.sync_event = asyncio.Event()
        self.logged_in_fingerprint = fingerprint
        self.logged_in = True
        return True

    async def new_puzzle_hash_created(self, puzzle_hashes):
        full_nodes = self.server.connection_by_type[NodeType.FULL_NODE]
        if len(full_nodes) > 0:
            full_node = list(full_nodes.values())[0]
            await self.subscribe_to_phs(puzzle_hashes, full_node)

    def _close(self):
        self.log.info("self._close")
        self.logged_in_fingerprint = None
        self._shut_down = True

    async def _await_closed(self):
        self.log.info("self._await_closed")
        await self.server.close_all_connections()
        asyncio.create_task(self.wallet_peers.ensure_is_closed())
        if self.wallet_state_manager is not None:
            await self.wallet_state_manager.close_all_stores()
            self.wallet_state_manager = None
        if self.sync_task is not None:
            self.sync_task.cancel()
            self.sync_task = None
        if self.peer_task is not None:
            self.peer_task.cancel()
            self.peer_task = None
        self.logged_in = False

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

        if self.wallet_state_manager is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)
            self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)

    def _pending_tx_handler(self):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return None
        asyncio.create_task(self._resend_queue())

    async def _action_messages(self) -> List[Message]:
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return []
        actions: List[WalletAction] = await self.wallet_state_manager.action_store.get_all_pending_actions()
        result: List[Message] = []
        for action in actions:
            data = json.loads(action.data)
            action_data = data["data"]["action_data"]
            if action.name == "request_puzzle_solution":
                coin_name = bytes32(hexstr_to_bytes(action_data["coin_name"]))
                height = uint32(action_data["height"])
                msg = make_msg(
                    ProtocolMessageTypes.request_puzzle_solution,
                    wallet_protocol.RequestPuzzleSolution(coin_name, height),
                )
                result.append(msg)

        return result

    async def _resend_queue(self):
        if (
            self._shut_down
            or self.server is None
            or self.wallet_state_manager is None
            or self.backup_initialized is None
        ):
            return None

        for msg, sent_peers in await self._messages_to_resend():
            if (
                self._shut_down
                or self.server is None
                or self.wallet_state_manager is None
                or self.backup_initialized is None
            ):
                return None
            full_nodes = self.server.get_full_node_connections()
            for peer in full_nodes:
                if peer.peer_node_id in sent_peers:
                    continue
                await peer.send_message(msg)

        for msg in await self._action_messages():
            if (
                self._shut_down
                or self.server is None
                or self.wallet_state_manager is None
                or self.backup_initialized is None
            ):
                return None
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

    async def _messages_to_resend(self) -> List[Tuple[Message, Set[bytes32]]]:
        if self.wallet_state_manager is None or self.backup_initialized is False or self._shut_down:
            return []
        messages: List[Tuple[Message, Set[bytes32]]] = []

        records: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_not_sent()

        for record in records:
            if record.spend_bundle is None:
                continue
            msg = make_msg(
                ProtocolMessageTypes.send_transaction,
                wallet_protocol.SendTransaction(record.spend_bundle),
            )
            already_sent = set()
            for peer, status, _ in record.sent_to:
                if status == MempoolInclusionStatus.SUCCESS.value:
                    already_sent.add(hexstr_to_bytes(peer))
            messages.append((msg, already_sent))

        return messages

    def set_server(self, server: ChiaServer):
        self.server = server
        DNS_SERVERS_EMPTY: list = []
        # TODO: Perhaps use a different set of DNS seeders for wallets, to split the traffic.
        self.wallet_peers = WalletPeers(
            self.server,
            self.root_path,
            self.config["target_peer_count"],
            self.config["wallet_peers_path"],
            self.config["introducer_peer"],
            DNS_SERVERS_EMPTY,
            self.config["peer_connect_interval"],
            self.config["selected_network"],
            None,
            self.log,
        )
        server.on_connect = self.on_connect

    async def on_connect(self, peer: WSChiaConnection):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return None
        messages_peer_ids = await self._messages_to_resend()
        self.wallet_state_manager.state_changed("add_connection")
        for msg, peer_ids in messages_peer_ids:
            if peer.peer_node_id in peer_ids:
                continue
            await peer.send_message(msg)
        if not self.has_full_node() and self.wallet_peers is not None:
            asyncio.create_task(self.wallet_peers.on_connect(peer))

        await self.update_coin_state(peer)

    async def update_coin_state(self, full_node: WSChiaConnection):
        all_puzzle_hashes = list(await self.wallet_state_manager.puzzle_store.get_all_puzzle_hashes())
        await self.subscribe_to_phs(all_puzzle_hashes, full_node)

        all_coins = await self.wallet_state_manager.coin_store.get_all_coins()
        all_coin_names = [coin_record.name() for coin_record in all_coins]
        await self.subscribe_to_coin_updates(all_coin_names, full_node)

    async def subscribe_to_phs(self, puzzle_hashes, full_node):
        msg = wallet_protocol.RegisterForPhUpdates(puzzle_hashes, 0)
        all_state: Union[Optional, RespondToPhUpdates] = await full_node.register_interest_in_puzzle_hash(msg)
        if all_state is not None:
            await self.handle_coin_state_change(all_state.coin_states)

    async def subscribe_to_coin_updates(self, coin_names, full_node):
        msg = wallet_protocol.RegisterForCoinUpdates(coin_names, uint32(0))
        all_coins_state: Union[Optional, RespondToCoinUpdates] = await full_node.register_interest_in_coin(msg)
        if all_coins_state is not None:
            await self.handle_coin_state_change(all_coins_state.coin_states)

    async def get_coin_state(self, coin_names) -> Optional[List[CoinState]]:
        all_nodes = self.server.connection_by_type[NodeType.FULL_NODE]
        if len(all_nodes.keys()) == 0:
            return None
        first_node = list(all_nodes.values())[0]
        msg = wallet_protocol.RegisterForCoinUpdates(coin_names, uint32(0))
        coin_state: Union[Optional, RespondToCoinUpdates] = await first_node.register_interest_in_coin(msg)
        assert coin_state is not None
        return coin_state.coin_states

    async def state_update_received(self, request: wallet_protocol.CoinStateUpdate):
        await self.wallet_state_manager.new_coin_state(request.items, request.fork_height, request.height)

    async def handle_coin_state_change(self, state_updates: List[CoinState]):
        added, removed = await self.wallet_state_manager.new_coin_state(state_updates)

    async def get_additional_coin_spends(
        self, peer, block, added_coins: List[Coin], removed_coins: List[Coin]
    ) -> List[CoinSpend]:
        assert self.wallet_state_manager is not None
        additional_coin_spends: List[CoinSpend] = []
        if len(removed_coins) > 0:
            removed_coin_ids = set([coin.name() for coin in removed_coins])
            all_added_coins = await self.get_additions(peer, block, [], get_all_additions=True)
            assert all_added_coins is not None
            if all_added_coins is not None:

                for coin in all_added_coins:
                    # This searches specifically for a launcher being created, and adds the solution of the launcher
                    if coin.puzzle_hash == SINGLETON_LAUNCHER_HASH and coin.parent_coin_info in removed_coin_ids:
                        cs: CoinSpend = await self.fetch_puzzle_solution(peer, block.height, coin.name())
                        additional_coin_spends.append(cs)
                        # Apply this coin solution, which might add things to interested list
                        await self.wallet_state_manager.get_next_interesting_coin_ids(cs, False)

                all_removed_coins: Optional[List[Coin]] = await self.get_removals(
                    peer, block, added_coins, removed_coins, request_all_removals=True
                )
                assert all_removed_coins is not None
                all_removed_coins_dict: Dict[bytes32, Coin] = {coin.name(): coin for coin in all_removed_coins}
                keep_searching = True
                while keep_searching:
                    # This keeps fetching solutions for coins we are interested list, in this block, until
                    # there are no more interested things to fetch
                    keep_searching = False
                    interested_ids: List[
                        bytes32
                    ] = await self.wallet_state_manager.interested_store.get_interested_coin_ids()
                    for coin_id in interested_ids:
                        if coin_id in all_removed_coins_dict:
                            coin = all_removed_coins_dict[coin_id]
                            cs = await self.fetch_puzzle_solution(peer, block.height, coin.name())

                            # Apply this coin solution, which might add things to interested list
                            await self.wallet_state_manager.get_next_interesting_coin_ids(cs, False)
                            additional_coin_spends.append(cs)
                            keep_searching = True
                            all_removed_coins_dict.pop(coin_id)
                            break
        return additional_coin_spends


    async def _periodically_check_full_node(self) -> None:
        tries = 0
        while not self._shut_down and tries < 5:
            if self.has_full_node():
                await self.wallet_peers.ensure_is_closed()
                if self.wallet_state_manager is not None:
                    self.wallet_state_manager.state_changed("add_connection")
                break
            tries += 1
            await asyncio.sleep(self.config["peer_connect_interval"])

    def has_full_node(self) -> bool:
        if self.server is None:
            return False
        if "full_node_peer" in self.config:
            full_node_peer = PeerInfo(
                self.config["full_node_peer"]["host"],
                self.config["full_node_peer"]["port"],
            )
            peers = [c.get_peer_info() for c in self.server.get_full_node_connections()]
            full_node_resolved = PeerInfo(socket.gethostbyname(full_node_peer.host), full_node_peer.port)
            if full_node_peer in peers or full_node_resolved in peers:
                self.log.info(f"Will not attempt to connect to other nodes, already connected to {full_node_peer}")
                for connection in self.server.get_full_node_connections():
                    if (
                        connection.get_peer_info() != full_node_peer
                        and connection.get_peer_info() != full_node_resolved
                    ):
                        self.log.info(f"Closing unnecessary connection to {connection.get_peer_info()}.")
                        asyncio.create_task(connection.close())
                return True
        return False


    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection):
        await self.wallet_state_manager.new_peak(peak)

    async def fetch_puzzle_solution(self, peer, height: uint32, coin_name: bytes32) -> CoinSpend:
        solution_response = await peer.request_puzzle_solution(
            wallet_protocol.RequestPuzzleSolution(coin_name, height)
        )
        if solution_response is None or not isinstance(solution_response, wallet_protocol.RespondPuzzleSolution):
            raise ValueError(f"Was not able to obtain solution {solution_response}")
        return CoinSpend(coin, solution_response.response.puzzle, solution_response.response.solution)
