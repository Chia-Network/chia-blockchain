from chia.protocols import full_node_protocol, introducer_protocol, wallet_protocol
from chia.server.outbound_message import NodeType
from chia.server.ws_connection import WSChiaConnection
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.api_decorators import api_request, peer_required, execute_task
from chia.util.errors import Err
from chia.wallet.wallet_node import WalletNode


class WalletNodeAPI:
    wallet_node: WalletNode

    def __init__(self, wallet_node) -> None:
        self.wallet_node = wallet_node

    @property
    def log(self):
        return self.wallet_node.log

    @property
    def api_ready(self):
        return self.wallet_node.logged_in

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

    @execute_task
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

    @peer_required
    @api_request
    async def respond_peers(self, request: full_node_protocol.RespondPeers, peer: WSChiaConnection):
        if not self.wallet_node.has_full_node():
            self.log.info(f"Wallet received {len(request.peer_list)} peers.")
            await self.wallet_node.wallet_peers.respond_peers(request, peer.get_peer_info(), True)
        else:
            self.log.info(f"Wallet received {len(request.peer_list)} peers, but ignoring, since we have a full node.")
            await self.wallet_node.wallet_peers.ensure_is_closed()
        return None

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
