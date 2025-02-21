from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, cast

from chia.protocols import full_node_protocol, introducer_protocol, wallet_protocol
from chia.server.api_protocol import ApiMetadata
from chia.server.outbound_message import NodeType
from chia.server.ws_connection import WSChiaConnection
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.wallet.wallet_node import WalletNode


class WalletNodeAPI:
    if TYPE_CHECKING:
        from chia.server.api_protocol import ApiProtocol

        _protocol_check: ClassVar[ApiProtocol] = cast("WalletNodeAPI", None)

    log: logging.Logger
    wallet_node: WalletNode
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def __init__(self, wallet_node) -> None:
        self.log = logging.getLogger(__name__)
        self.wallet_node = wallet_node

    def ready(self) -> bool:
        return self.wallet_node.logged_in

    @metadata.request(peer_required=True)
    async def respond_removals(self, response: wallet_protocol.RespondRemovals, peer: WSChiaConnection):
        pass

    async def reject_removals_request(self, response: wallet_protocol.RejectRemovalsRequest, peer: WSChiaConnection):
        """
        The full node has rejected our request for removals.
        """
        pass

    @metadata.request()
    async def reject_additions_request(self, response: wallet_protocol.RejectAdditionsRequest):
        """
        The full node has rejected our request for additions.
        """
        pass

    @metadata.request(peer_required=True, execute_task=True)
    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection):
        """
        The full node sent as a new peak
        """
        # For trusted peers check if there are untrusted peers, if so make sure to disconnect them if the trusted node
        # is synced.
        if self.wallet_node.is_trusted(peer):
            full_node_connections = self.wallet_node.server.get_connections(NodeType.FULL_NODE)
            untrusted_peers = [
                peer for peer in full_node_connections if not self.wallet_node.is_trusted(peer) and not peer.closed
            ]

            # Check for untrusted peers to avoid fetching the timestamp if not required
            if len(untrusted_peers) > 0:
                timestamp = await self.wallet_node.get_timestamp_for_height_from_peer(peak.height, peer)
            else:
                timestamp = None
            if timestamp is not None and self.wallet_node.is_timestamp_in_sync(timestamp):
                self.log.info("Connected to a synced trusted peer, disconnecting from all untrusted nodes.")
                # Stop peer discovery/connect tasks first
                if self.wallet_node.wallet_peers is not None:
                    await self.wallet_node.wallet_peers.ensure_is_closed()
                    self.wallet_node.wallet_peers = None
                # Then disconnect from all untrusted nodes
                for untrusted_peer in untrusted_peers:
                    await untrusted_peer.close()

        await self.wallet_node.new_peak_queue.new_peak_wallet(peak, peer)

    @metadata.request()
    async def reject_header_request(self, response: wallet_protocol.RejectHeaderRequest):
        """
        The full node has rejected our request for a header.
        """
        pass

    @metadata.request()
    async def respond_block_header(self, response: wallet_protocol.RespondBlockHeader):
        pass

    @metadata.request(peer_required=True)
    async def respond_additions(self, response: wallet_protocol.RespondAdditions, peer: WSChiaConnection):
        pass

    @metadata.request()
    async def respond_proof_of_weight(self, response: full_node_protocol.RespondProofOfWeight):
        pass

    @metadata.request(peer_required=True)
    async def transaction_ack(self, ack: wallet_protocol.TransactionAck, peer: WSChiaConnection):
        """
        This is an ack for our previous SendTransaction call. This removes the transaction from
        the send queue if we have sent it to enough nodes.
        """
        async with self.wallet_node.wallet_state_manager.lock:
            assert peer.peer_node_id is not None
            name = peer.peer_node_id.hex()
            if peer.peer_node_id in self.wallet_node._tx_messages_in_progress:
                self.wallet_node._tx_messages_in_progress[peer.peer_node_id] = [
                    txid for txid in self.wallet_node._tx_messages_in_progress[peer.peer_node_id] if txid != ack.txid
                ]
                if self.wallet_node._tx_messages_in_progress[peer.peer_node_id] == []:
                    del self.wallet_node._tx_messages_in_progress[peer.peer_node_id]
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

    @metadata.request(peer_required=True)
    async def respond_peers_introducer(
        self, request: introducer_protocol.RespondPeersIntroducer, peer: WSChiaConnection
    ):
        if self.wallet_node.wallet_peers is not None:
            await self.wallet_node.wallet_peers.add_peers(request.peer_list, peer.get_peer_info(), False)

        if peer is not None and peer.connection_type is NodeType.INTRODUCER:
            await peer.close()

    @metadata.request(peer_required=True)
    async def respond_peers(self, request: full_node_protocol.RespondPeers, peer: WSChiaConnection):
        if self.wallet_node.wallet_peers is None:
            return None

        self.log.info(f"Wallet received {len(request.peer_list)} peers.")
        await self.wallet_node.wallet_peers.add_peers(request.peer_list, peer.get_peer_info(), True)

        return None

    @metadata.request()
    async def respond_puzzle_solution(self, request: wallet_protocol.RespondPuzzleSolution):
        self.log.error("Unexpected message `respond_puzzle_solution`. Peer might be slow to respond")

    @metadata.request()
    async def reject_puzzle_solution(self, request: wallet_protocol.RejectPuzzleSolution):
        self.log.warning(f"Reject puzzle solution: {request}")

    @metadata.request()
    async def respond_header_blocks(self, request: wallet_protocol.RespondHeaderBlocks):
        pass

    @metadata.request()
    async def respond_block_headers(self, request: wallet_protocol.RespondBlockHeaders):
        pass

    @metadata.request()
    async def reject_header_blocks(self, request: wallet_protocol.RejectHeaderBlocks):
        self.log.warning(f"Reject header blocks: {request}")

    @metadata.request()
    async def reject_block_headers(self, request: wallet_protocol.RejectBlockHeaders):
        pass

    @metadata.request(peer_required=True, execute_task=True)
    async def coin_state_update(self, request: wallet_protocol.CoinStateUpdate, peer: WSChiaConnection):
        await self.wallet_node.new_peak_queue.full_node_state_updated(request, peer)

    # TODO: Review this hinting issue around this rust type not being a Streamable
    #       subclass, as you might expect it wouldn't be.  Maybe we can get the
    #       protocol working right back at the api.request definition.
    @metadata.request()  # type: ignore[type-var]
    async def respond_to_ph_updates(self, request: wallet_protocol.RespondToPhUpdates):
        pass

    @metadata.request()
    async def respond_to_coin_updates(self, request: wallet_protocol.RespondToCoinUpdates):
        pass

    @metadata.request()
    async def respond_children(self, request: wallet_protocol.RespondChildren):
        pass

    @metadata.request()
    async def respond_ses_hashes(self, request: wallet_protocol.RespondSESInfo):
        pass

    @metadata.request()
    async def respond_blocks(self, request: full_node_protocol.RespondBlocks) -> None:
        pass
