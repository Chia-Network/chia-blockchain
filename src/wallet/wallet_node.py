import asyncio
import json
import time
from typing import Dict, Optional, Tuple, List, AsyncGenerator, Callable
from pathlib import Path
import socket
import logging
from blspy import PrivateKey

from src.protocols.wallet_protocol import (
    RequestSubBlockHeader,
    RespondSubBlockHeader,
    RequestAdditions,
    RequestRemovals,
    RespondAdditions,
    RespondRemovals,
)
from src.server.connection_utils import send_all_first_reply
from src.server.ws_connection import WSChiaConnection
from src.types.peer_info import PeerInfo
from src.util.byte_types import hexstr_to_bytes
from src.protocols import wallet_protocol
from src.consensus.constants import ConsensusConstants
from src.server.server import ChiaServer
from src.server.outbound_message import OutboundMessage, NodeType, Message
from src.server.node_discovery import WalletPeers
from src.util.ints import uint32, uint128
from src.types.sized_bytes import bytes32
from src.wallet.block_record import HeaderBlockRecord
from src.wallet.settings.settings_objects import BackupInitialized
from src.wallet.transaction_record import TransactionRecord
from src.wallet.util.backup_utils import open_backup_file
from src.wallet.wallet_action import WalletAction
from src.wallet.wallet_blockchain import ReceiveBlockResult
from src.wallet.wallet_state_manager import WalletStateManager
from src.types.header_block import HeaderBlock
from src.util.path import path_from_root, mkdir
from src.util.keychain import Keychain

OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]


class WalletNode:
    key_config: Dict
    config: Dict
    constants: ConsensusConstants
    server: Optional[ChiaServer]
    log: logging.Logger
    wallet_peers: WalletPeers
    # Maintains the state of the wallet (blockchain and transactions), handles DB connections
    wallet_state_manager: Optional[WalletStateManager]

    # How far away from LCA we must be to perform a full sync. Before then, do a short sync,
    # which is consecutive requests for the previous block
    short_sync_threshold: int
    _shut_down: bool
    root_path: Path
    state_changed_callback: Optional[Callable]

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
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        # Normal operation data
        self.cached_blocks = {}
        self.future_block_hashes = {}
        self.keychain = keychain

        # Sync data
        self._shut_down = False
        self.proof_hashes = []
        self.header_hashes = []
        self.header_hashes_error = False
        self.short_sync_threshold = 15  # Change the test when changing this
        self.potential_blocks_received = {}
        self.potential_header_hashes = {}
        self.state_changed_callback = None
        self.wallet_state_manager = None
        self.backup_initialized = False  # Delay first launch sync after user imports backup info or decides to skip
        self.server = None
        self.wsm_close_task = None

    def get_key_for_fingerprint(self, fingerprint):
        private_keys = self.keychain.get_all_private_keys()
        if len(private_keys) == 0:
            self.log.warning(
                "No keys present. Create keys with the UI, or with the 'chia keys' program."
            )
            return None

        private_key: Optional[PrivateKey] = None
        if fingerprint is not None:
            for sk, _ in private_keys:
                if sk.get_g1().get_fingerprint() == fingerprint:
                    private_key = sk
                    break
        else:
            private_key = private_keys[0][0]
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
            return False

        db_path_key_suffix = str(private_key.get_g1().get_fingerprint())
        path = path_from_root(
            self.root_path, f"{self.config['database_path']}-{db_path_key_suffix}"
        )
        mkdir(path.parent)

        self.wallet_state_manager = await WalletStateManager.create(
            private_key, self.config, path, self.constants
        )

        self.wsm_close_task = None

        assert self.wallet_state_manager is not None

        backup_settings: BackupInitialized = (
            self.wallet_state_manager.user_settings.get_backup_settings()
        )
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
                return False

        self.backup_initialized = True
        if backup_file is not None:
            json_dict = open_backup_file(
                backup_file, self.wallet_state_manager.private_key
            )
            if "start_height" in json_dict["data"]:
                start_height = json_dict["data"]["start_height"]
                self.config["starting_height"] = max(
                    0, start_height - self.config["start_height_buffer"]
                )
            else:
                self.config["starting_height"] = 0
        else:
            self.config["starting_height"] = 0

        if self.state_changed_callback is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)

        self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)
        self._shut_down = False

        asyncio.create_task(self._periodically_check_full_node())
        return True

    def _close(self):
        self._shut_down = True
        if self.wallet_state_manager is None:
            return
        self.wsm_close_task = asyncio.create_task(
            self.wallet_state_manager.close_all_stores()
        )
        self.wallet_peers_task = asyncio.create_task(
            self.wallet_peers.ensure_is_closed()
        )

    async def _await_closed(self):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        if self.wsm_close_task is not None:
            await self.wsm_close_task
            self.wsm_close_task = None
        self.wallet_state_manager = None

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

        if self.wallet_state_manager is not None:
            self.wallet_state_manager.set_callback(self.state_changed_callback)
            self.wallet_state_manager.set_pending_callback(self._pending_tx_handler)

    def _pending_tx_handler(self):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        asyncio.create_task(self._resend_queue())

    async def _action_messages(self) -> List[Message]:
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return []
        actions: List[
            WalletAction
        ] = await self.wallet_state_manager.action_store.get_all_pending_actions()
        result: List[Message] = []
        for action in actions:
            data = json.loads(action.data)
            action_data = data["data"]["action_data"]
            if action.name == "request_generator":
                header_hash = bytes32(hexstr_to_bytes(action_data["header_hash"]))
                height = uint32(action_data["height"])
                msg = Message(
                    "request_generator",
                    wallet_protocol.RequestGenerator(height, header_hash),
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
            return

        for msg in await self._messages_to_resend():
            if (
                self._shut_down
                or self.server is None
                or self.wallet_state_manager is None
                or self.backup_initialized is None
            ):
                return
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

        for msg in await self._action_messages():
            if (
                self._shut_down
                or self.server is None
                or self.wallet_state_manager is None
                or self.backup_initialized is None
            ):
                return
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

    async def _messages_to_resend(self) -> List[Message]:
        if (
            self.wallet_state_manager is None
            or self.backup_initialized is False
            or self._shut_down
        ):
            return []
        messages: List[Message] = []

        records: List[
            TransactionRecord
        ] = await self.wallet_state_manager.tx_store.get_not_sent()

        for record in records:
            if record.spend_bundle is None:
                continue
            msg = Message(
                "send_transaction",
                wallet_protocol.SendTransaction(record.spend_bundle),
            )
            messages.append(msg)

        return messages

    def set_server(self, server: ChiaServer):
        self.server = server
        self.wallet_peers = WalletPeers(
            self.server,
            self.root_path,
            self.config["target_peer_count"],
            self.config["wallet_peers_path"],
            self.config["introducer_peer"],
            self.config["peer_connect_interval"],
            self.log,
        )
        asyncio.create_task(self.wallet_peers.start())

    async def on_connect(self, peer: WSChiaConnection):
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return
        messages = await self._messages_to_resend()
        for msg in messages:
            await peer.send_message(msg)

    async def _periodically_check_full_node(self):
        tries = 0
        while not self._shut_down and tries < 5:
            if self.has_full_node():
                await self.wallet_peers.ensure_is_closed()
                break
            tries += 1
            await asyncio.sleep(180)

    def has_full_node(self) -> bool:
        assert self.server is not None
        if "full_node_peer" in self.config:
            full_node_peer = PeerInfo(
                self.config["full_node_peer"]["host"],
                self.config["full_node_peer"]["port"],
            )
            peers = [c.get_peer_info() for c in self.server.get_full_node_connections()]
            full_node_resolved = PeerInfo(
                socket.gethostbyname(full_node_peer.host), full_node_peer.port
            )
            if full_node_peer in peers or full_node_resolved in peers:
                self.log.info(
                    f"Will not attempt to connect to other nodes, already connected to {full_node_peer}"
                )
                for connection in self.server.get_full_node_connections():
                    if (
                        connection.get_peer_info() != full_node_peer
                        and connection.get_peer_info() != full_node_resolved
                    ):
                        self.log.info(
                            f"Closing unnecessary connection to {connection.get_peer_info()}."
                        )
                        asyncio.create_task(connection.close())
                return True
        return False

    # @api_request
    # async def respond_peers_with_peer_info(
    #     self,
    #     request: introducer_protocol.RespondPeers,
    #     peer_info: PeerInfo,
    # ) -> OutboundMessageGenerator:
    #     if not self._has_full_node():
    #         await self.wallet_peers.respond_peers(request, peer_info, False)
    #     else:
    #         await self.wallet_peers.ensure_is_closed()
    #     yield OutboundMessage(NodeType.INTRODUCER, Message("", None), Delivery.CLOSE)
    #
    # @api_request
    # async def respond_peers_full_node_with_peer_info(
    #     self,
    #     request: full_node_protocol.RespondPeers,
    #     peer_info: PeerInfo,
    # ):
    #     if not self._has_full_node():
    #         await self.wallet_peers.respond_peers(request, peer_info, True)
    #     else:
    #         await self.wallet_peers.ensure_is_closed()
    #
    # @api_request
    # async def respond_peers_full_node(self, request: full_node_protocol.RespondPeers):
    #     pass
    #

    async def new_peak(self, peak: wallet_protocol.NewPeak, peer: WSChiaConnection):
        if self.wallet_state_manager.blockchain.get_peak().weight > peak.weight:
            return

        request = wallet_protocol.RequestSubBlockHeader(peak.sub_block_height)
        header_block: HeaderBlock = await peer.request_sub_block_header(request)

        if header_block is not None:
            # TODO validate weight
            # TODO Fetch additions /removals
            self.wallet_state_manager.sync_store.add_potential_peak(header_block)
            # TODO sync
            await self._sync()

    async def _sync(self):
        """
        Wallet has fallen far behind (or is starting up for the first time), and must be synced
        up to the LCA of the blockchain.
        """
        if self.wallet_state_manager is None or self.backup_initialized is False:
            return

        await asyncio.sleep(2)
        highest_weight: uint128 = uint128(0)
        peak_height: uint32 = uint32(0)
        sync_start_time = time.time()

        potential_peaks: List[
            Tuple[bytes32, HeaderBlock]
        ] = self.wallet_state_manager.sync_store.get_potential_peaks_tuples()

        self.log.info(f"Have collected {len(potential_peaks)} potential peaks")

        for header_hash, potential_peak_block in potential_peaks:
            if potential_peak_block.weight > highest_weight:
                highest_weight = potential_peak_block.weight
                peak_height = potential_peak_block.height

        if highest_weight <= self.wallet_state_manager.peak.weight:
            self.log.info("Not performing sync, already caught up.")
            return

        peers: List[WSChiaConnection] = self.server.get_full_node_connections()

        if len(peers) == 0:
            self.log.info("No peers to sync to")
            return

        fetched_blocks: Dict[int, HeaderBlockRecord] = {}

        for i in range(0, peak_height):
            # TODO get a block at height i
            request = RequestSubBlockHeader(i)
            response, peer = await send_all_first_reply(
                "request_sub_block_header", request, peers
            )
            res: RespondSubBlockHeader = response
            block_i: HeaderBlock = res.header_block
            if block_i is None:
                continue

            if block_i.is_block:
                # Find additions and removals
                (
                    additions,
                    removals,
                ) = await self.wallet_state_manager.get_filter_additions_removals(
                    block_i, block_i.transactions_filter
                )

                additions_request = RequestAdditions(i, block_i.header_hash, additions)
                removals_request = RequestRemovals(i, block_i.header_hash, removals)
                additions_res: RespondAdditions = await peer.request_additions(
                    additions_request
                )
                removals_res: RespondRemovals = await peer.request_additions(
                    removals_request
                )
                added_coins = [coin for _, coin in additions_res.coins]
                removed_coins = [coin for _, coin in removals_res.coins]

                header_block_record = HeaderBlockRecord(
                    block_i, added_coins, removed_coins
                )
            else:
                header_block_record = HeaderBlockRecord(block_i, [], [])

            fetched_blocks[i] = header_block_record

        for i in range(0, peak_height):
            hbr = fetched_blocks[i]
            (
                result,
                error,
                fork_h,
            ) = await self.wallet_state_manager.blockchain.receive_block(hbr)
            if result == ReceiveBlockResult.NEW_PEAK:
                self.wallet_state_manager.state_changed("new_block")

    def validate_additions(self, coins, proofs, root):
        pass

    def validate_removals(self, coins, proofs, root):
        pass

    #
    # @api_request
    # async def respond_additions(self, response: wallet_protocol.RespondAdditions):
    #     """
    #     The full node has responded with the additions for a block. We will use this
    #     to try to finish the block, and add it to the state.
    #     """
    #     if self.wallet_state_manager is None or self.backup_initialized is False:
    #         return
    #     if self._shut_down:
    #         return
    #     if response.header_hash not in self.cached_blocks:
    #         self.log.warning("Do not have header for additions")
    #         return
    #     block_record, header_block, transaction_filter = self.cached_blocks[
    #         response.header_hash
    #     ]
    #     assert response.height == block_record.height
    #
    #     additions: List[Coin]
    #     if response.proofs is None:
    #         # If there are no proofs, it means all additions were returned in the response.
    #         # we must find the ones relevant to our wallets.
    #         all_coins: List[Coin] = []
    #         for puzzle_hash, coin_list_0 in response.coins:
    #             all_coins += coin_list_0
    #         additions = await self.wallet_state_manager.get_relevant_additions(
    #             all_coins
    #         )
    #         # Verify root
    #         additions_merkle_set = MerkleSet()
    #
    #         # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
    #         for puzzle_hash, coins in response.coins:
    #             additions_merkle_set.add_already_hashed(puzzle_hash)
    #             additions_merkle_set.add_already_hashed(hash_coin_list(coins))
    #
    #         additions_root = additions_merkle_set.get_root()
    #         if header_block.header.data.additions_root != additions_root:
    #             return
    #     else:
    #         # This means the full node has responded only with the relevant additions
    #         # for our wallet. Each merkle proof must be verified.
    #         additions = []
    #         assert len(response.coins) == len(response.proofs)
    #         for i in range(len(response.coins)):
    #             assert response.coins[i][0] == response.proofs[i][0]
    #             coin_list_1: List[Coin] = response.coins[i][1]
    #             puzzle_hash_proof: bytes32 = response.proofs[i][1]
    #             coin_list_proof: Optional[bytes32] = response.proofs[i][2]
    #             if len(coin_list_1) == 0:
    #                 # Verify exclusion proof for puzzle hash
    #                 assert confirm_not_included_already_hashed(
    #                     header_block.header.data.additions_root,
    #                     response.coins[i][0],
    #                     puzzle_hash_proof,
    #                 )
    #             else:
    #                 # Verify inclusion proof for puzzle hash
    #                 assert confirm_included_already_hashed(
    #                     header_block.header.data.additions_root,
    #                     response.coins[i][0],
    #                     puzzle_hash_proof,
    #                 )
    #                 # Verify inclusion proof for coin list
    #                 assert confirm_included_already_hashed(
    #                     header_block.header.data.additions_root,
    #                     hash_coin_list(coin_list_1),
    #                     coin_list_proof,
    #                 )
    #                 for coin in coin_list_1:
    #                     assert coin.puzzle_hash == response.coins[i][0]
    #                 additions += coin_list_1
    #     new_br = BlockRecord(
    #         block_record.header_hash,
    #         block_record.prev_header_hash,
    #         block_record.height,
    #         block_record.weight,
    #         additions,
    #         None,
    #         block_record.total_iters,
    #         header_block.challenge.get_hash(),
    #         header_block.header.data.timestamp,
    #     )
    #     self.cached_blocks[response.header_hash] = (
    #         new_br,
    #         header_block,
    #         transaction_filter,
    #     )
    #
    #     if transaction_filter is None:
    #         raise RuntimeError("Got additions for block with no transactions.")
    #
    #     (_, removals,) = await self.wallet_state_manager.get_filter_additions_removals(
    #         new_br, transaction_filter
    #     )
    #     request_all_removals = False
    #     for coin in additions:
    #         puzzle_store = self.wallet_state_manager.puzzle_store
    #         record_info: Optional[
    #             DerivationRecord
    #         ] = await puzzle_store.get_derivation_record_for_puzzle_hash(
    #             coin.puzzle_hash.hex()
    #         )
    #         if (
    #             record_info is not None
    #             and record_info.wallet_type == WalletType.COLOURED_COIN
    #         ):
    #             request_all_removals = True
    #             break
    #
    #     if len(removals) > 0 or request_all_removals:
    #         if request_all_removals:
    #             request_r = wallet_protocol.RequestRemovals(
    #                 header_block.height, header_block.header_hash, None
    #             )
    #         else:
    #             request_r = wallet_protocol.RequestRemovals(
    #                 header_block.height, header_block.header_hash, removals
    #             )
    #         yield OutboundMessage(
    #             NodeType.FULL_NODE,
    #             Message("request_removals", request_r),
    #             Delivery.RESPOND,
    #         )
    #     else:
    #         # We have collected all three things: header, additions, and removals (since there are no
    #         # relevant removals for us). Can proceed. Otherwise, we wait for the removals to arrive.
    #         new_br = BlockRecord(
    #             new_br.header_hash,
    #             new_br.prev_header_hash,
    #             new_br.height,
    #             new_br.weight,
    #             new_br.additions,
    #             [],
    #             new_br.total_iters,
    #             new_br.new_challenge_hash,
    #             new_br.timestamp,
    #         )
    #         respond_header_msg: Optional[
    #             wallet_protocol.RespondHeader
    #         ] = await self._block_finished(new_br, header_block, transaction_filter)
    #         if respond_header_msg is not None:
    #             async for msg in self.respond_header(respond_header_msg):
    #                 yield msg
    #
    # @api_request
    # async def respond_removals(self, response: wallet_protocol.RespondRemovals):
    #     """
    #     The full node has responded with the removals for a block. We will use this
    #     to try to finish the block, and add it to the state.
    #     """
    #     if self.wallet_state_manager is None or self.backup_initialized is False:
    #         return
    #     if self._shut_down:
    #         return
    #     if (
    #         response.header_hash not in self.cached_blocks
    #         or self.cached_blocks[response.header_hash][0].additions is None
    #     ):
    #         self.log.warning(
    #             "Do not have header for removals, or do not have additions"
    #         )
    #         return
    #
    #     block_record, header_block, transaction_filter = self.cached_blocks[
    #         response.header_hash
    #     ]
    #     assert response.height == block_record.height
    #
    #     all_coins: List[Coin] = []
    #     for coin_name, coin in response.coins:
    #         if coin is not None:
    #             all_coins.append(coin)
    #
    #     if response.proofs is None:
    #         # If there are no proofs, it means all removals were returned in the response.
    #         # we must find the ones relevant to our wallets.
    #
    #         # Verify removals root
    #         removals_merkle_set = MerkleSet()
    #         for coin in all_coins:
    #             if coin is not None:
    #                 removals_merkle_set.add_already_hashed(coin.name())
    #         removals_root = removals_merkle_set.get_root()
    #         assert header_block.header.data.removals_root == removals_root
    #
    #     else:
    #         # This means the full node has responded only with the relevant removals
    #         # for our wallet. Each merkle proof must be verified.
    #         assert len(response.coins) == len(response.proofs)
    #         for i in range(len(response.coins)):
    #             # Coins are in the same order as proofs
    #             assert response.coins[i][0] == response.proofs[i][0]
    #             coin = response.coins[i][1]
    #             if coin is None:
    #                 # Verifies merkle proof of exclusion
    #                 assert confirm_not_included_already_hashed(
    #                     header_block.header.data.removals_root,
    #                     response.coins[i][0],
    #                     response.proofs[i][1],
    #                 )
    #             else:
    #                 # Verifies merkle proof of inclusion of coin name
    #                 assert response.coins[i][0] == coin.name()
    #                 assert confirm_included_already_hashed(
    #                     header_block.header.data.removals_root,
    #                     coin.name(),
    #                     response.proofs[i][1],
    #                 )
    #
    #     new_br = BlockRecord(
    #         block_record.header_hash,
    #         block_record.prev_header_hash,
    #         block_record.height,
    #         block_record.weight,
    #         block_record.additions,
    #         all_coins,
    #         block_record.total_iters,
    #         header_block.challenge.get_hash(),
    #         header_block.header.data.timestamp,
    #     )
    #
    #     self.cached_blocks[response.header_hash] = (
    #         new_br,
    #         header_block,
    #         transaction_filter,
    #     )
    #
    #     # We have collected all three things: header, additions, and removals. Can proceed.
    #     respond_header_msg: Optional[
    #         wallet_protocol.RespondHeader
    #     ] = await self._block_finished(new_br, header_block, transaction_filter)
    #     if respond_header_msg is not None:
    #         async for msg in self.respond_header(respond_header_msg):
    #             yield msg
    #
    # @api_request
    # async def reject_removals_request(
    #     self, response: wallet_protocol.RejectRemovalsRequest
    # ):
    #     """
    #     The full node has rejected our request for removals.
    #     """
    #     # TODO(mariano): implement
    #     if self.wallet_state_manager is None or self.backup_initialized is False:
    #         return
    #     self.log.error("Removals request rejected")
    #
    # @api_request
    # async def reject_additions_request(
    #     self, response: wallet_protocol.RejectAdditionsRequest
    # ):
    #     """
    #     The full node has rejected our request for additions.
    #     """
    #     # TODO(mariano): implement
    #     if self.wallet_state_manager is None or self.backup_initialized is False:
    #         return
    #     self.log.error("Additions request rejected")
    #
    # @api_request
    # async def respond_generator(self, response: wallet_protocol.RespondGenerator):
    #     """
    #     The full node respond with transaction generator
    #     """
    #     if self.wallet_state_manager is None or self.backup_initialized is False:
    #         return
    #     wrapper = response.generatorResponse
    #     if wrapper.generator is not None:
    #         self.log.info(
    #             f"generator received {wrapper.header_hash} {wrapper.generator.get_tree_hash()} {wrapper.height}"
    #         )
    #         await self.wallet_state_manager.generator_received(
    #             wrapper.height, wrapper.header_hash, wrapper.generator
    #         )
    #
    # @api_request
    # async def reject_generator(self, response: wallet_protocol.RejectGeneratorRequest):
    #     """
    #     The full node rejected our request for generator
    #     """
    #     # TODO (Straya): implement
    #     if self.wallet_state_manager is None or self.backup_initialized is False:
    #         return
    #     self.log.info("generator rejected")
