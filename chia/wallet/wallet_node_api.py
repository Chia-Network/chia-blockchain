from __future__ import annotations

from chia.protocols import full_node_protocol, introducer_protocol, wallet_protocol
from chia.server.outbound_message import NodeType
from chia.server.ws_connection import WSChiaConnection
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.api_decorators import api_request
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

    @api_request(peer_required=True)
    async def respond_removals(self, response: wallet_protocol.RespondRemovals, peer: WSChiaConnection):
        pass

    async def reject_removals_request(self, response: wallet_protocol.RejectRemovalsRequest, peer: WSChiaConnection):
        """
        The full node has rejected our request for removals.
        """
        pass

    @api_request()
    async def reject_additions_request(self, response: wallet_protocol.RejectAdditionsRequest):
        """
        The full node has rejected our request for additions.
        """
        pass

    @api_request(peer_required=True, execute_task=True)
    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection):
        """
        The full node sent as a new peak
        """
        self.wallet_node.node_peaks[peer.peer_node_id] = (peak.height, peak.header_hash)
        # For trusted peers check if there are untrusted peers, if so make sure to disconnect them if the trusted node
        # is synced.
        if self.wallet_node.is_trusted(peer):
            full_node_connections = self.wallet_node.server.get_connections(NodeType.FULL_NODE)
            untrusted_peers = [
                peer for peer in full_node_connections if not self.wallet_node.is_trusted(peer) and not peer.closed
            ]

            # Check for untrusted peers first to avoid calling is_peer_synced if not required
            if len(untrusted_peers) > 0 and await self.wallet_node.is_peer_synced(peer, peak.height):
                self.log.info("Connected to a a synced trusted peer, disconnecting from all untrusted nodes.")
                # Stop peer discovery/connect tasks first
                if self.wallet_node.wallet_peers is not None:
                    await self.wallet_node.wallet_peers.ensure_is_closed()
                    self.wallet_node.wallet_peers = None
                # Then disconnect from all untrusted nodes
                for untrusted_peer in untrusted_peers:
                    await untrusted_peer.close()

        await self.wallet_node.new_peak_queue.new_peak_wallet(peak, peer)

    @api_request()
    async def reject_header_request(self, response: wallet_protocol.RejectHeaderRequest):
        """
        The full node has rejected our request for a header.
        """
        pass

    @api_request()
    async def respond_block_header(self, response: wallet_protocol.RespondBlockHeader):
        pass

    @api_request(peer_required=True)
    async def respond_additions(self, response: wallet_protocol.RespondAdditions, peer: WSChiaConnection):
        pass

    @api_request()
    async def respond_proof_of_weight(self, response: full_node_protocol.RespondProofOfWeight):
        pass

    @api_request(peer_required=True)
    async def transaction_ack(self, ack: wallet_protocol.TransactionAck, peer: WSChiaConnection):
        """
        This is an ack for our previous SendTransaction call. This removes the transaction from
        the send queue if we have sent it to enough nodes.
        """
        async with self.wallet_node.wallet_state_manager.lock:
            assert peer.peer_node_id is not None
            name = peer.peer_node_id.hex()
            status = MempoolInclusionStatus(ack.status)
            try:
                wallet_state_manager = self.wallet_node.wallet_state_manager
            except RuntimeError as e:
                if "not assigned" in str(e):
                    return None
                raise

            if status == MempoolInclusionStatus.SUCCESS:
                self.wallet_node.log.info(
                    f"SpendBundle has been received and accepted to mempool by the FullNode. {ack}"
                )
            elif status == MempoolInclusionStatus.PENDING:
                self.wallet_node.log.info(f"SpendBundle has been received (and is pending) by the FullNode. {ack}")
            else:
                if not self.wallet_node.is_trusted(peer) and ack.error == Err.NO_TRANSACTIONS_WHILE_SYNCING.name:
                    self.wallet_node.log.info(f"Peer {peer.get_peer_info()} is not synced, closing connection")
                    await peer.close()
                    return
                self.wallet_node.log.warning(f"SpendBundle has been rejected by the FullNode. {ack}")
            if ack.error is not None:
                await wallet_state_manager.remove_from_queue(ack.txid, name, status, Err[ack.error])
            else:
                await wallet_state_manager.remove_from_queue(ack.txid, name, status, None)

    @api_request(peer_required=True)
    async def respond_peers_introducer(
        self, request: introducer_protocol.RespondPeersIntroducer, peer: WSChiaConnection
    ):
        if self.wallet_node.wallet_peers is not None:
            await self.wallet_node.wallet_peers.add_peers(request.peer_list, peer.get_peer_info(), False)

        if peer is not None and peer.connection_type is NodeType.INTRODUCER:
            await peer.close()

    @api_request(peer_required=True)
    async def respond_peers(self, request: full_node_protocol.RespondPeers, peer: WSChiaConnection):
        if self.wallet_node.wallet_peers is None:
            return None

        self.log.info(f"Wallet received {len(request.peer_list)} peers.")
        await self.wallet_node.wallet_peers.add_peers(request.peer_list, peer.get_peer_info(), True)

        return None

    @api_request()
    async def respond_puzzle_solution(self, request: wallet_protocol.RespondPuzzleSolution):
        self.log.error("Unexpected message `respond_puzzle_solution`. Peer might be slow to respond")
        return None

    @api_request()
    async def reject_puzzle_solution(self, request: wallet_protocol.RejectPuzzleSolution):
        self.log.warning(f"Reject puzzle solution: {request}")

    @api_request()
    async def respond_header_blocks(self, request: wallet_protocol.RespondHeaderBlocks):
        pass

    @api_request()
    async def respond_block_headers(self, request: wallet_protocol.RespondBlockHeaders):
        pass

    @api_request()
    async def reject_header_blocks(self, request: wallet_protocol.RejectHeaderBlocks):
        self.log.warning(f"Reject header blocks: {request}")

    @api_request()
    async def reject_block_headers(self, request: wallet_protocol.RejectBlockHeaders):
        pass

    @api_request(peer_required=True, execute_task=True)
    async def coin_state_update(self, request: wallet_protocol.CoinStateUpdate, peer: WSChiaConnection):
        await self.wallet_node.new_peak_queue.full_node_state_updated(request, peer)

    # TODO: Review this hinting issue around this rust type not being a Streamable
    #       subclass, as you might expect it wouldn't be.  Maybe we can get the
    #       protocol working right back at the api_request definition.
    @api_request()  # type: ignore[type-var]
    async def respond_to_ph_update(self, request: wallet_protocol.RespondToPhUpdates):
        pass

    @api_request()
    async def respond_to_coin_update(self, request: wallet_protocol.RespondToCoinUpdates):
        pass

    @api_request()
    async def respond_children(self, request: wallet_protocol.RespondChildren):
        pass

    @api_request()
    async def respond_ses_hashes(self, request: wallet_protocol.RespondSESInfo):
        pass

    @api_request()
    async def respond_blocks(self, request: full_node_protocol.RespondBlocks) -> None:
        pass
