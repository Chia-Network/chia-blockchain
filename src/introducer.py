import asyncio
import logging
from typing import AsyncGenerator, Dict

from src.protocols.full_node_protocol import RespondPeers, RequestPeers
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.server.server import ChiaServer
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request

log = logging.getLogger(__name__)


class Introducer:
    def __init__(self, config: Dict):
        self.config: Dict = config
        self.vetted: Dict[bytes32, bool] = {}

    def set_server(self, server: ChiaServer):
        self.server = server

    @api_request
    async def request_peers(
        self, request: RequestPeers
    ) -> AsyncGenerator[OutboundMessage, None]:
        max_peers = self.config["max_peers_to_send"]
        rawpeers = self.server.global_connections.peers.get_peers(
            max_peers * 2, True, self.config["recent_peer_threshold"]
        )

        peers = []

        for peer in rawpeers:
            if peer.get_hash() not in self.vetted:
                try:
                    r, w = await asyncio.open_connection(peer.host, int(peer.port))
                    w.close()
                except (
                    ConnectionRefusedError,
                    TimeoutError,
                    OSError,
                    asyncio.TimeoutError,
                ) as e:
                    log.warning(f"Could not vet {peer}. {type(e)}{str(e)}")
                    self.vetted[peer.get_hash()] = False
                    continue

                log.info(f"Have vetted {peer} successfully!")
                self.vetted[peer.get_hash()] = True

            if self.vetted[peer.get_hash()]:
                peers.append(peer)

            if len(peers) >= max_peers:
                break

        log.info(f"Sending vetted {peers}")

        msg = Message("respond_peers", RespondPeers(peers))
        yield OutboundMessage(NodeType.FULL_NODE, msg, Delivery.RESPOND)
        yield OutboundMessage(NodeType.WALLET, msg, Delivery.RESPOND)
