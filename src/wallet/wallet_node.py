from pathlib import Path
from typing import Dict, Optional, List
from blspy import ExtendedPrivateKey
import logging
import src.protocols.wallet_protocol
from src.full_node import OutboundMessageGenerator
from src.protocols.wallet_protocol import ProofHash
from src.server.outbound_message import OutboundMessage, NodeType, Message, Delivery
from src.server.server import ChiaServer
from src.types.full_block import additions_for_npc
from src.types.hashable.Coin import Coin
from src.types.hashable.SpendBundle import SpendBundle
from src.types.name_puzzle_condition import NPC
from src.types.sized_bytes import bytes32
from src.util.hash import std_hash
from src.util.api_decorators import api_request
from src.util.ints import uint32
from src.util.mempool_check_conditions import get_name_puzzle_conditions
from src.wallet.wallet import Wallet
from src.wallet.wallet_state_manager import WalletStateManager
from src.wallet.wallet_store import WalletStore
from src.wallet.wallet_transaction_store import WalletTransactionStore


class WalletNode:
    private_key: ExtendedPrivateKey
    key_config: Dict
    config: Dict
    server: Optional[ChiaServer]
    wallet_store: WalletStore
    wallet_state_manager: WalletStateManager
    header_hash: List[bytes32]
    start_index: int
    log: logging.Logger
    wallet: Wallet
    tx_store: WalletTransactionStore

    @staticmethod
    async def create(config: Dict, key_config: Dict, name: str = None):
        self = WalletNode()
        print("init wallet node")
        self.config = config
        self.key_config = key_config
        sk_hex = self.key_config["wallet_sk"]
        self.private_key = ExtendedPrivateKey.from_bytes(bytes.fromhex(sk_hex))
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        pub_hex = self.private_key.get_public_key().serialize().hex()
        path = Path(f"wallet_db_{pub_hex}.db")
        self.wallet_store = await WalletStore.create(path)
        self.tx_store = await WalletTransactionStore.create(path)

        self.wallet_state_manager = await WalletStateManager.create(
            config, key_config, self.wallet_store, self.tx_store
        )
        self.wallet = await Wallet.create(config, key_config, self.wallet_state_manager)

        self.server = None

        return self

    def set_server(self, server: ChiaServer):
        self.server = server
        self.wallet.set_server(server)

    async def _on_connect(self) -> OutboundMessageGenerator:
        """
        Whenever we connect to a FullNode we request new proof_hashes by sending last proof hash we have
        """
        self.log.info(f"Requesting proof hashes")
        request = ProofHash(std_hash(b"deadbeef"))
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("request_proof_hashes", request),
            Delivery.BROADCAST,
        )

    @api_request
    async def proof_hash(
        self, request: src.protocols.wallet_protocol.ProofHash
    ) -> OutboundMessageGenerator:
        """
        Received a proof hash from the FullNode
        """
        self.log.info(f"Received a new proof hash: {request}")
        reply_request = ProofHash(std_hash(b"a"))
        # TODO Store and decide if we want full proof for this proof hash
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("request_full_proof_for_hash", reply_request),
            Delivery.RESPOND,
        )

    @api_request
    async def full_proof_for_hash(
        self, request: src.protocols.wallet_protocol.FullProofForHash
    ):
        """
        We've received a full proof for hash we requested
        """
        # TODO Validate full proof
        self.log.info(f"Received new proof: {request}")

    @api_request
    async def received_body(self, response: src.protocols.wallet_protocol.RespondBody):
        """
        Called when body is received from the FullNode
        """

        # Retry sending queued up transactions
        await self.retry_send_queue()

        additions: List[Coin] = []

        if self.wallet.can_generate_puzzle_hash(response.body.coinbase.puzzle_hash):
            await self.wallet_state_manager.coin_added(
                response.body.coinbase, response.height, True
            )
        if self.wallet.can_generate_puzzle_hash(response.body.fees_coin.puzzle_hash):
            await self.wallet_state_manager.coin_added(
                response.body.fees_coin, response.height, True
            )

        npc_list: List[NPC]
        if response.body.transactions:
            error, npc_list, cost = get_name_puzzle_conditions(
                response.body.transactions
            )

            additions.extend(additions_for_npc(npc_list))

            for added_coin in additions:
                if self.wallet.can_generate_puzzle_hash(added_coin.puzzle_hash):
                    await self.wallet_state_manager.coin_added(
                        added_coin, response.height, False
                    )

            for npc in npc_list:
                if self.wallet.can_generate_puzzle_hash(npc.puzzle_hash):
                    await self.wallet_state_manager.coin_removed(
                        npc.coin_name, response.height
                    )

    @api_request
    async def new_lca(self, header: src.protocols.wallet_protocol.Header):
        self.log.info("new tip received")

    async def retry_send_queue(self):
        records = await self.wallet_state_manager.get_send_queue()
        for record in records:
            if record.spend_bundle:
                await self._send_transaction(record.spend_bundle)

    async def _send_transaction(self, spend_bundle: SpendBundle):
        """ Sends spendbundle to connected full Nodes."""
        await self.wallet_state_manager.add_pending_transaction(spend_bundle)

        msg = OutboundMessage(
            NodeType.FULL_NODE,
            Message("wallet_transaction", spend_bundle),
            Delivery.BROADCAST,
        )
        if self.server:
            async for reply in self.server.push_message(msg):
                self.log.info(reply)

    async def _request_add_list(self, height: uint32, header_hash: bytes32):
        obj = src.protocols.wallet_protocol.RequestAdditions(height, header_hash)
        msg = OutboundMessage(
            NodeType.FULL_NODE, Message("request_additions", obj), Delivery.BROADCAST,
        )
        if self.server:
            async for reply in self.server.push_message(msg):
                self.log.info(reply)

    @api_request
    async def response_additions(
        self, response: src.protocols.wallet_protocol.Additions
    ):
        print(response)

    @api_request
    async def response_additions_rejected(
        self, response: src.protocols.wallet_protocol.RequestAdditions
    ):
        print(f"request rejected {response}")

    @api_request
    async def transaction_ack(self, ack: src.protocols.wallet_protocol.TransactionAck):
        if ack.status:
            await self.wallet_state_manager.remove_from_queue(ack.txid)
            self.log.info(f"SpendBundle has been received by the FullNode. id: {id}")
        else:
            self.log.info(f"SpendBundle has been rejected by the FullNode. id: {id}")

    async def requestLCA(self):
        msg = OutboundMessage(
            NodeType.FULL_NODE, Message("request_lca", None), Delivery.BROADCAST,
        )
        async for reply in self.server.push_message(msg):
            self.log.info(reply)
