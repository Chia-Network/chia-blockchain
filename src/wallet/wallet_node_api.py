from src.protocols import wallet_protocol, full_node_protocol, introducer_protocol
from src.server.outbound_message import NodeType
from src.server.ws_connection import WSChiaConnection
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.util.api_decorators import api_request, peer_required
from src.util.errors import Err
from src.wallet.wallet_node import WalletNode


class WalletNodeAPI:
    wallet_node: WalletNode

    def __init__(self, wallet_node):
        self.wallet_node = wallet_node

    @peer_required
    @api_request
    async def respond_removals(self, response: wallet_protocol.RespondRemovals, peer: WSChiaConnection):
        pass

    async def reject_removals_request(self, response: wallet_protocol.RejectRemovalsRequest, peer: WSChiaConnection):
        """
        The full node has rejected our request for removals.
        """
        pass

    @api_request
    async def reject_additions_request(self, response: wallet_protocol.RejectAdditionsRequest):
        """
        The full node has rejected our request for additions.
        """
        pass

    @peer_required
    @api_request
    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection):
        """
        The full node sent as a new peak
        """
        await self.wallet_node.new_peak_wallet(peak, peer)

    @api_request
    async def reject_block_header(self, response: wallet_protocol.RejectHeaderRequest):
        """
        The full node has rejected our request for a header.
        """
        pass

    @api_request
    async def respond_block_header(self, response: wallet_protocol.RespondBlockHeader):
        pass

    @peer_required
    @api_request
    async def respond_additions(self, response: wallet_protocol.RespondAdditions, peer: WSChiaConnection):
        pass

    @api_request
    async def respond_proof_of_weight(self, response: full_node_protocol.RespondProofOfWeight):
        pass

    @peer_required
    @api_request
    async def transaction_ack(self, ack: wallet_protocol.TransactionAck, peer: WSChiaConnection):
        """
        This is an ack for our previous SendTransaction call. This removes the transaction from
        the send queue if we have sent it to enough nodes.
        """
        assert peer.peer_node_id is not None
        name = peer.peer_node_id.hex()
        status = MempoolInclusionStatus(ack.status)
        if self.wallet_node.wallet_state_manager is None or self.wallet_node.backup_initialized is False:
            return
        if status == MempoolInclusionStatus.SUCCESS:
            self.wallet_node.log.info(f"SpendBundle has been received and accepted to mempool by the FullNode. {ack}")
        elif status == MempoolInclusionStatus.PENDING:
            self.wallet_node.log.info(f"SpendBundle has been received (and is pending) by the FullNode. {ack}")
        else:
            self.wallet_node.log.warning(f"SpendBundle has been rejected by the FullNode. {ack}")
        if ack.error is not None:
            await self.wallet_node.wallet_state_manager.remove_from_queue(ack.txid, name, status, Err[ack.error])
        else:
            await self.wallet_node.wallet_state_manager.remove_from_queue(ack.txid, name, status, None)

    @peer_required
    @api_request
    async def respond_peers_introducer(
        self, request: introducer_protocol.RespondPeersIntroducer, peer: WSChiaConnection
    ):
        if not self.wallet_node.has_full_node():
            await self.wallet_node.wallet_peers.respond_peers(request, peer.get_peer_info(), False)
        else:
            await self.wallet_node.wallet_peers.ensure_is_closed()

        if peer is not None and peer.connection_type is NodeType.INTRODUCER:
            await peer.close()

    @api_request
    async def respond_puzzle_solution(self, request: wallet_protocol.RespondPuzzleSolution):
        if self.wallet_node.wallet_state_manager is None or self.wallet_node.backup_initialized is False:
            return
        await self.wallet_node.wallet_state_manager.puzzle_solution_received(request)

    @api_request
    async def reject_puzzle_solution(self, request: wallet_protocol.RespondPuzzleSolution):
        pass

    @api_request
    async def respond_header_blocks(self, request: wallet_protocol.RespondHeaderBlocks):
        pass

    @api_request
    async def reject_header_blocks(self, request: wallet_protocol.RejectHeaderBlocks):
        pass
