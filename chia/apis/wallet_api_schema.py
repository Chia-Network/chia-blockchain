from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from chia_rs import RespondToPhUpdates

from chia.protocols import full_node_protocol, introducer_protocol, wallet_protocol
from chia.server.api_protocol import ApiMetadata, ApiProtocolSchema
from chia.server.ws_connection import WSChiaConnection


class WalletNodeApiSchema:
    if TYPE_CHECKING:
        _protocol_check: ApiProtocolSchema = cast("WalletNodeApiSchema", None)

    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    @metadata.request(peer_required=True)
    async def respond_removals(self, response: wallet_protocol.RespondRemovals, peer: WSChiaConnection) -> None: ...

    @metadata.request()
    async def reject_additions_request(self, response: wallet_protocol.RejectAdditionsRequest) -> None: ...

    @metadata.request(peer_required=True, execute_task=True)
    async def new_peak_wallet(self, peak: wallet_protocol.NewPeakWallet, peer: WSChiaConnection) -> None: ...

    @metadata.request()
    async def reject_header_request(self, response: wallet_protocol.RejectHeaderRequest) -> None: ...

    @metadata.request()
    async def respond_block_header(self, response: wallet_protocol.RespondBlockHeader) -> None: ...

    @metadata.request(peer_required=True)
    async def respond_additions(self, response: wallet_protocol.RespondAdditions, peer: WSChiaConnection) -> None: ...

    @metadata.request()
    async def respond_proof_of_weight(self, response: full_node_protocol.RespondProofOfWeight) -> None: ...

    @metadata.request(peer_required=True)
    async def transaction_ack(self, ack: wallet_protocol.TransactionAck, peer: WSChiaConnection) -> None: ...

    @metadata.request(peer_required=True)
    async def respond_peers_introducer(
        self, request: introducer_protocol.RespondPeersIntroducer, peer: WSChiaConnection
    ) -> None: ...

    @metadata.request(peer_required=True)
    async def respond_peers(self, request: full_node_protocol.RespondPeers, peer: WSChiaConnection) -> None: ...

    @metadata.request()
    async def respond_puzzle_solution(self, request: wallet_protocol.RespondPuzzleSolution) -> None: ...

    @metadata.request()
    async def reject_puzzle_solution(self, request: wallet_protocol.RejectPuzzleSolution) -> None: ...

    @metadata.request()
    async def respond_header_blocks(self, request: wallet_protocol.RespondHeaderBlocks) -> None: ...

    @metadata.request()
    async def respond_block_headers(self, request: wallet_protocol.RespondBlockHeaders) -> None: ...

    @metadata.request()
    async def reject_header_blocks(self, request: wallet_protocol.RejectHeaderBlocks) -> None: ...

    @metadata.request()
    async def reject_block_headers(self, request: wallet_protocol.RejectBlockHeaders) -> None: ...

    @metadata.request(peer_required=True, execute_task=True)
    async def coin_state_update(self, request: wallet_protocol.CoinStateUpdate, peer: WSChiaConnection) -> None: ...

    @metadata.request()  # type: ignore[type-var]
    async def respond_to_ph_updates(self, request: RespondToPhUpdates) -> None: ...

    @metadata.request()
    async def respond_to_coin_updates(self, request: wallet_protocol.RespondToCoinUpdates) -> None: ...

    @metadata.request()
    async def respond_children(self, request: wallet_protocol.RespondChildren) -> None: ...

    @metadata.request()
    async def respond_ses_hashes(self, request: wallet_protocol.RespondSESInfo) -> None: ...

    @metadata.request()
    async def respond_blocks(self, request: full_node_protocol.RespondBlocks) -> None: ...
