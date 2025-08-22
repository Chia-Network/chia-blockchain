from __future__ import annotations

from chia_rs import RespondToPhUpdates

from chia.protocols import full_node_protocol, introducer_protocol, wallet_protocol
from chia.server.api_protocol import ApiMetadata
from chia.server.ws_connection import WSChiaConnection


class WalletNodeApiSchema:
    metadata = ApiMetadata()

    @metadata.request(peer_required=True)
    async def respond_removals(self, response: wallet_protocol.RespondRemovals, peer: WSChiaConnection): ...

    @metadata.request()
    async def reject_additions_request(self, response: wallet_protocol.RejectAdditionsRequest): ...

    @metadata.request(peer_required=True, execute_task=True)
    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection): ...

    @metadata.request()
    async def reject_header_request(self, response: wallet_protocol.RejectHeaderRequest): ...

    @metadata.request()
    async def respond_block_header(self, response: wallet_protocol.RespondBlockHeader): ...

    @metadata.request(peer_required=True)
    async def respond_additions(self, response: wallet_protocol.RespondAdditions, peer: WSChiaConnection): ...

    @metadata.request()
    async def respond_proof_of_weight(self, response: full_node_protocol.RespondProofOfWeight): ...

    @metadata.request(peer_required=True)
    async def transaction_ack(self, ack: wallet_protocol.TransactionAck, peer: WSChiaConnection): ...

    @metadata.request(peer_required=True)
    async def respond_peers_introducer(
        self, request: introducer_protocol.RespondPeersIntroducer, peer: WSChiaConnection
    ): ...

    @metadata.request(peer_required=True)
    async def respond_peers(self, request: full_node_protocol.RespondPeers, peer: WSChiaConnection): ...

    @metadata.request()
    async def respond_puzzle_solution(self, request: wallet_protocol.RespondPuzzleSolution): ...

    @metadata.request()
    async def reject_puzzle_solution(self, request: wallet_protocol.RejectPuzzleSolution): ...

    @metadata.request()
    async def respond_header_blocks(self, request: wallet_protocol.RespondHeaderBlocks): ...

    @metadata.request()
    async def respond_block_headers(self, request: wallet_protocol.RespondBlockHeaders): ...

    @metadata.request()
    async def reject_header_blocks(self, request: wallet_protocol.RejectHeaderBlocks): ...

    @metadata.request()
    async def reject_block_headers(self, request: wallet_protocol.RejectBlockHeaders): ...

    @metadata.request(peer_required=True, execute_task=True)
    async def coin_state_update(self, request: wallet_protocol.CoinStateUpdate, peer: WSChiaConnection): ...

    @metadata.request()  # type: ignore[type-var]
    async def respond_to_ph_updates(self, request: RespondToPhUpdates): ...

    @metadata.request()
    async def respond_to_coin_updates(self, request: wallet_protocol.RespondToCoinUpdates): ...

    @metadata.request()
    async def respond_children(self, request: wallet_protocol.RespondChildren): ...

    @metadata.request()
    async def respond_ses_hashes(self, request: wallet_protocol.RespondSESInfo): ...

    @metadata.request()
    async def respond_blocks(self, request: full_node_protocol.RespondBlocks) -> None: ...
