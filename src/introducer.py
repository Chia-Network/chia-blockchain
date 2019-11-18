import os
from typing import AsyncGenerator

import yaml

from definitions import ROOT_DIR
from src.protocols.peer_protocol import Peers, RequestPeers
from src.server.outbound_message import (Delivery, Message, NodeType,
                                         OutboundMessage)
from src.server.server import ChiaServer
from src.util.api_decorators import api_request


class Introducer:
    def __init__(self):
        config_filename = os.path.join(ROOT_DIR, "src", "config", "config.yaml")
        self.config = yaml.safe_load(open(config_filename, "r"))["introducer"]

    def set_server(self, server: ChiaServer):
        self.server = server

    @api_request
    async def request_peers(self, request: RequestPeers) \
            -> AsyncGenerator[OutboundMessage, None]:
        max_peers = self.config['max_peers_to_send']
        peers = self.server.global_connections.peers.get_peers(max_peers, True)
        msg = Message("peers", Peers(peers))
        yield OutboundMessage(NodeType.FULL_NODE, msg, Delivery.RESPOND)
