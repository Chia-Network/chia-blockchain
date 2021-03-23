import asyncio
import dataclasses
import time
from typing import Callable, Dict, List, Optional, Tuple

from blspy import AugSchemeMPL, G2Element
from chiabip158 import PyBIP158

import src.server.ws_connection as ws
from src.consensus.block_creation import create_unfinished_block
from src.consensus.block_record import BlockRecord
from src.consensus.pot_iterations import calculate_ip_iters, calculate_iterations_quality, calculate_sp_iters
from src.crawler.crawler import Crawler
from src.full_node.full_node import FullNode
from src.full_node.mempool_check_conditions import get_puzzle_and_solution_for_coin
from src.full_node.signage_point import SignagePoint
from src.protocols import farmer_protocol, full_node_protocol, introducer_protocol, timelord_protocol, wallet_protocol
from src.protocols.full_node_protocol import RejectBlock, RejectBlocks
from src.protocols.protocol_message_types import ProtocolMessageTypes
from src.protocols.wallet_protocol import PuzzleSolutionResponse, RejectHeaderBlocks, RejectHeaderRequest
from src.server.outbound_message import Message, NodeType, make_msg
from src.types.blockchain_format.coin import Coin, hash_coin_list
from src.types.blockchain_format.pool_target import PoolTarget
from src.types.blockchain_format.program import Program
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.types.mempool_item import MempoolItem
from src.types.peer_info import PeerInfo
from src.types.spend_bundle import SpendBundle
from src.types.unfinished_block import UnfinishedBlock
from src.util.api_decorators import api_request, peer_required
from src.util.ints import uint8, uint32, uint64, uint128
from src.util.merkle_set import MerkleSet


class CrawlerAPI:
    crawler: Crawler

    def __init__(self, crawler):
        self.crawler = crawler

    def _set_state_changed_callback(self, callback: Callable):
        pass

    def __getattr__(self, attr_name: str):
        async def invoke(*args, **kwargs):
            pass

        return invoke

    @property
    def server(self):
        return self.crawler.server

    @property
    def log(self):
        return self.crawler.log

    @peer_required
    @api_request
    async def request_peers(self, _request: full_node_protocol.RequestPeers, peer: ws.WSChiaConnection):
        pass

    @api_request
    async def request_peers(self, _request):
        pass

    @peer_required
    @api_request
    async def respond_peers(
        self, request: full_node_protocol.RespondPeers, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        pass

    @peer_required
    @api_request
    async def new_peak(
        self, request: full_node_protocol.NewPeak, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        pass

    @peer_required
    @api_request
    async def respond_peers_introducer(
        self, request: introducer_protocol.RespondPeersIntroducer, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        self.log.debug(f"Received {len(request.peer_list)} peers from introducer")

        await peer.close()
        return None


    @api_request
    async def new_transaction(self, transaction: full_node_protocol.NewTransaction) -> Optional[Message]:
        pass

    @api_request
    @peer_required
    async def new_signage_point_or_end_of_sub_slot(
        self, new_sp: full_node_protocol.NewSignagePointOrEndOfSubSlot, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        pass

    @api_request
    async def new_unfinished_block(
        self, new_unfinished_block: full_node_protocol.NewUnfinishedBlock
    ) -> Optional[Message]:
        pass

    @peer_required
    @api_request
    async def new_compact_vdf(self, request: full_node_protocol.NewCompactVDF, peer: ws.WSChiaConnection):
        pass
