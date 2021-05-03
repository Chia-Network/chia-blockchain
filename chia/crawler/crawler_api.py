from typing import Callable, Optional
import chia.server.ws_connection as ws
from chia.crawler.crawler import Crawler
from chia.server.outbound_message import Message
from chia.util.api_decorators import api_request, peer_required
from chia.full_node.full_node import full_node_protocol


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

    @peer_required
    @api_request
    async def respond_peers(
        self, request: full_node_protocol.RespondPeers, peer: ws.WSChiaConnection
    ) -> Optional[Message]:
        pass

    @peer_required
    @api_request
    async def new_peak(self, request: full_node_protocol.NewPeak, peer: ws.WSChiaConnection) -> Optional[Message]:
        await self.crawler.new_peak(request, peer)
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
