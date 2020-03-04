from pathlib import Path
from typing import Dict, Optional, List
from blspy import ExtendedPrivateKey
import logging
import src.protocols.wallet_protocol
from src.consensus.constants import constants as consensus_constants
from src.server.server import ChiaServer
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request
from src.wallet.wallet import Wallet
from src.wallet.wallet_state_manager import WalletStateManager


class WalletNode:
    private_key: ExtendedPrivateKey
    key_config: Dict
    config: Dict
    server: Optional[ChiaServer]
    wallet_state_manager: WalletStateManager
    header_hash: List[bytes32]
    start_index: int
    log: logging.Logger
    wallet: Wallet
    constants: Dict

    @staticmethod
    async def create(
        config: Dict, key_config: Dict, name: str = None, override_constants: Dict = {}
    ):
        self = WalletNode()
        self.config = config
        self.key_config = key_config
        sk_hex = self.key_config["wallet_sk"]
        self.private_key = ExtendedPrivateKey.from_bytes(bytes.fromhex(sk_hex))
        self.constants = consensus_constants.copy()
        for key, value in override_constants.items():
            self.constants[key] = value
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        pub_hex = self.private_key.get_public_key().serialize().hex()
        path = Path(f"wallet_db_{pub_hex}.db")

        self.wallet_state_manager = await WalletStateManager.create(
            config, path, override_constants=override_constants,
        )
        self.wallet = await Wallet.create(config, key_config, self.wallet_state_manager)

        self.server = None

        return self

    def set_server(self, server: ChiaServer):
        self.server = server
        self.wallet.set_server(server)

    async def _sync(self):
        """
        Wallet has fallen far behind (or is starting up for the first time), and must be synced
        up to the tip of the blockchain
        """
        # TODO(mariano): implement
        pass

    @api_request
    async def transaction_ack(self, ack: src.protocols.wallet_protocol.TransactionAck):
        if ack.status:
            await self.wallet_state_manager.remove_from_queue(ack.txid)
            self.log.info(f"SpendBundle has been received by the FullNode. id: {id}")
        else:
            self.log.info(f"SpendBundle has been rejected by the FullNode. id: {id}")

    @api_request
    async def respond_all_proof_hashes(
        self, response: src.protocols.wallet_protocol.RespondAllProofHashes
    ):
        # TODO(mariano): save proof hashes
        pass

    @api_request
    async def respond_all_header_hashes_after(
        self, response: src.protocols.wallet_protocol.RespondAllHeaderHashesAfter
    ):
        # TODO(mariano): save header_hashes
        pass

    @api_request
    async def reject_all_header_hashes_after_request(
        self, response: src.protocols.wallet_protocol.RejectAllHeaderHashesAfterRequest
    ):
        # TODO(mariano): retry
        pass

    @api_request
    async def new_lca(self, response: src.protocols.wallet_protocol.NewLCA):
        # TODO(mariano): implement
        # 1. If already have, ignore.
        # 2. If extends chain:
        # - Get header
        # 3. If disconnected:
        # - If far:
        #     - Perform full sync
        # - If close:
        #     - Get header
        pass

    @api_request
    async def respond_header(
        self, response: src.protocols.wallet_protocol.RespondHeader
    ):
        # TODO(mariano): implement
        # 1. If disconnected and close, get parent header and return
        # 2. If we have transactions, fetch adds/deletes
        # adds_deletes = await self.wallet_state_manager.filter_additions_removals()
        # 3. If we don't have, don't fetch
        # 4. If we have the next header cached, process it
        pass

    @api_request
    async def reject_header_request(
        self, response: src.protocols.wallet_protocol.RejectHeaderRequest
    ):
        # TODO(mariano): implement
        pass

    @api_request
    async def respond_removals(
        self, response: src.protocols.wallet_protocol.RespondRemovals
    ):
        # TODO(mariano): implement
        pass

    @api_request
    async def reject_removals_request(
        self, response: src.protocols.wallet_protocol.RejectRemovalsRequest
    ):
        # TODO(mariano): implement
        pass

    # @api_request
    # async def received_body(self, response: src.protocols.wallet_protocol.RespondBody):
    #     """
    #     Called when body is received from the FullNode
    #     """

    #     # Retry sending queued up transactions
    #     await self.retry_send_queue()

    #     additions: List[Coin] = []

    #     if await self.wallet.can_generate_puzzle_hash(
    #         response.header.data.coinbase.puzzle_hash
    #     ):
    #         await self.wallet_state_manager.coin_added(
    #             response.header.data.coinbase, response.height, True
    #         )
    #     if await self.wallet.can_generate_puzzle_hash(
    #         response.header.data.fees_coin.puzzle_hash
    #     ):
    #         await self.wallet_state_manager.coin_added(
    #             response.header.data.fees_coin, response.height, True
    #         )

    #     npc_list: List[NPC]
    #     if response.transactions_generator:
    #         error, npc_list, cost = get_name_puzzle_conditions(
    #             response.transactions_generator
    #         )

    #         additions.extend(additions_for_npc(npc_list))

    #         for added_coin in additions:
    #             if await self.wallet.can_generate_puzzle_hash(added_coin.puzzle_hash):
    #                 await self.wallet_state_manager.coin_added(
    #                     added_coin, response.height, False
    #                 )

    #         for npc in npc_list:
    #             if await self.wallet.can_generate_puzzle_hash(npc.puzzle_hash):
    #                 await self.wallet_state_manager.coin_removed(
    #                     npc.coin_name, response.height
    #                 )

    # async def retry_send_queue(self):
    #     records = await self.wallet_state_manager.get_send_queue()
    #     for record in records:
    #         if record.spend_bundle:
    #             await self._send_transaction(record.spend_bundle)

    # async def _send_transaction(self, spend_bundle: SpendBundle):
    #     """ Sends spendbundle to connected full Nodes."""
    #     await self.wallet_state_manager.add_pending_transaction(spend_bundle)

    #     msg = OutboundMessage(
    #         NodeType.FULL_NODE,
    #         Message("wallet_transaction", spend_bundle),
    #         Delivery.BROADCAST,
    #     )
    #     if self.server:
    #         async for reply in self.server.push_message(msg):
    #             self.log.info(reply)
