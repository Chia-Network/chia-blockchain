from typing import Dict

from blspy import ExtendedPrivateKey
import logging

import src.protocols.wallet_protocol
from src.full_node import OutboundMessageGenerator
from src.protocols.wallet_protocol import ProofHash
from src.server.outbound_message import OutboundMessage, NodeType, Message, Delivery
from src.util.Hash import std_hash
from src.util.api_decorators import api_request


class Wallet:
    private_key: ExtendedPrivateKey
    key_config: Dict
    config: Dict

    def __init__(self, config: Dict, key_config: Dict, name: str = None):
        print("init wallet")
        self.config = config
        self.key_config = key_config
        sk_hex = self.key_config["wallet_sk"]
        self.private_key = ExtendedPrivateKey.from_bytes(bytes.fromhex(sk_hex))
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

    async def _on_connect(self) -> OutboundMessageGenerator:
        """
        Whenever we connect to a FullNode we request new proof_hashes by sending last proof hash we have
        """
        self.log.info(f"Requesting proof hashes")
        request = ProofHash(std_hash(b"deadbeef"))
        yield OutboundMessage(
            NodeType.FULL_NODE, Message("request_proof_hashes", request), Delivery.BROADCAST
        )

    @api_request
    async def proof_hash(self, request: src.protocols.wallet_protocol.ProofHash) -> OutboundMessageGenerator:
        """
        Received a proof hash from the FullNode
        """
        self.log.info(f"Received new proof hash: {request}")
        reply_request = ProofHash(std_hash(b"a"))
        # TODO Store and decide if we want full proof for this proof hash
        yield OutboundMessage(
            NodeType.FULL_NODE, Message("request_full_proof_for_hash", reply_request), Delivery.RESPOND
        )

    @api_request
    async def full_proof_for_hash(self, request: src.protocols.wallet_protocol.FullProofForHash):
        """
        We've received a full proof for hash we requested
        """
        # TODO Validate full proof
        self.log.info(f"Received new proof: {request}")