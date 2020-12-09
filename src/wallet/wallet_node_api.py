import traceback
from typing import List, Optional

from src.protocols import wallet_protocol
from src.server.outbound_message import Message
from src.server.ws_connection import WSChiaConnection
from src.types.coin import Coin, hash_coin_list
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request, peer_required
from src.util.errors import Err
from src.util.merkle_set import (
    MerkleSet,
    confirm_not_included_already_hashed,
    confirm_included_already_hashed,
)
from src.wallet.derivation_record import DerivationRecord
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet_node import WalletNode


class WalletNodeAPI:
    wallet_node: WalletNode

    def __init__(self, wallet_node):
        self.wallet_node = wallet_node

    @peer_required
    @api_request
    async def respond_removals(
        self, response: wallet_protocol.RespondRemovals, peer: WSChiaConnection
    ):
        """
        The full node has responded with the removals for a block. We will use this
        to try to finish the block, and add it to the state.
        """
        if (
            self.wallet_node.wallet_state_manager is None
            or self.wallet_node.backup_initialized is False
        ):
            return
        if self.wallet_node._shut_down:
            return
        if (
            response.header_hash not in self.wallet_node.cached_blocks
            or self.wallet_node.cached_blocks[response.header_hash][0].additions is None
        ):
            self.wallet_node.log.warning(
                "Do not have header for removals, or do not have additions"
            )
            return

        block_record, header_block, transaction_filter = self.wallet_node.cached_blocks[
            response.header_hash
        ]
        assert response.height == block_record.height

        all_coins: List[Coin] = []
        for coin_name, coin in response.coins:
            if coin is not None:
                all_coins.append(coin)

        if response.proofs is None:
            # If there are no proofs, it means all removals were returned in the response.
            # we must find the ones relevant to our wallets.

            # Verify removals root
            removals_merkle_set = MerkleSet()
            for coin in all_coins:
                if coin is not None:
                    removals_merkle_set.add_already_hashed(coin.name())
            removals_root = removals_merkle_set.get_root()
            assert header_block.header.data.removals_root == removals_root

        else:
            # This means the full node has responded only with the relevant removals
            # for our wallet. Each merkle proof must be verified.
            assert len(response.coins) == len(response.proofs)
            for i in range(len(response.coins)):
                # Coins are in the same order as proofs
                assert response.coins[i][0] == response.proofs[i][0]
                coin = response.coins[i][1]
                if coin is None:
                    # Verifies merkle proof of exclusion
                    assert confirm_not_included_already_hashed(
                        header_block.header.data.removals_root,
                        response.coins[i][0],
                        response.proofs[i][1],
                    )
                else:
                    # Verifies merkle proof of inclusion of coin name
                    assert response.coins[i][0] == coin.name()
                    assert confirm_included_already_hashed(
                        header_block.header.data.removals_root,
                        coin.name(),
                        response.proofs[i][1],
                    )

        # new_br = BlockRecord(
        #     block_record.header_hash,
        #     block_record.prev_header_hash,
        #     block_record.height,
        #     block_record.weight,
        #     block_record.additions,
        #     all_coins,
        #     block_record.total_iters,
        #     header_block.challenge.get_hash(),
        #     header_block.header.data.timestamp,
        # )
        #
        # self.wallet_node.cached_blocks[response.header_hash] = (
        #     new_br,
        #     header_block,
        #     transaction_filter,
        # )
        #
        # # We have collected all three things: header, additions, and removals. Can proceed.
        # respond_header_msg: Optional[
        #     wallet_protocol.RespondHeader
        # ] = await self.wallet_node._block_finished(
        #     new_br, header_block, transaction_filter
        # )
        # if respond_header_msg is not None:
        #     await self.respond_header(respond_header_msg, peer)

    @api_request
    async def reject_removals_request(
        self, response: wallet_protocol.RejectRemovalsRequest, peer: WSChiaConnection
    ):
        """
        The full node has rejected our request for removals.
        """
        # TODO(mariano): implement
        if (
            self.wallet_node.wallet_state_manager is None
            or self.wallet_node.backup_initialized is False
        ):
            return
        self.wallet_node.log.error("Removals request rejected")

    @api_request
    async def reject_additions_request(
        self, response: wallet_protocol.RejectAdditionsRequest
    ):
        """
        The full node has rejected our request for additions.
        """
        # TODO(mariano): implement
        if (
            self.wallet_node.wallet_state_manager is None
            or self.wallet_node.backup_initialized is False
        ):
            return
        self.wallet_node.log.error("Additions request rejected")

    @peer_required
    @api_request
    async def new_peak(self, peak: wallet_protocol.NewPeak, peer: WSChiaConnection):
        """
        The full node sent as a new peak
        """
        await self.wallet_node.new_peak(peak, peer)

    @api_request
    async def reject_header_request(
        self, response: wallet_protocol.RejectHeaderRequest
    ):
        """
        The full node has rejected our request for a header.
        """
        # TODO(mariano): implement
        if (
            self.wallet_node.wallet_state_manager is None
            or self.wallet_node.backup_initialized is False
        ):
            return
        self.wallet_node.log.error("Header request rejected")

    @api_request
    async def respond_sub_block_header(
        self, response: wallet_protocol.RespondSubBlockHeader
    ):
        pass

    @peer_required
    @api_request
    async def respond_additions(
        self, response: wallet_protocol.RespondAdditions, peer: WSChiaConnection
    ):
        pass

    @peer_required
    @api_request
    async def reject_additions_request(
        self, response: wallet_protocol.RejectAdditionsRequest, peer: WSChiaConnection
    ):
        pass

    @peer_required
    @api_request
    async def respond_removals(
        self, response: wallet_protocol.RespondRemovals, peer: WSChiaConnection
    ):
        pass

    @peer_required
    @api_request
    async def reject_removals_request(
        self, response: wallet_protocol.RejectRemovalsRequest, peer: WSChiaConnection
    ):
        pass

    #     if (
    #         self.wallet_node.wallet_state_manager is None
    #         or self.wallet_node.backup_initialized is False
    #     ):
    #         return
    #     if self.wallet_node._shut_down:
    #         return
    #     if response.header_hash not in self.wallet_node.cached_blocks:
    #         self.wallet_node.log.warning("Do not have header for additions")
    #         return
    #     block_record, header_block, transaction_filter = self.wallet_node.cached_blocks[
    #         response.header_hash
    #     ]
    #     assert response.height == block_record.height
    #
    #     additions: List[Coin]
    #     if response.proofs is None:
    #         # If there are no proofs, it means all additions were returned in the response.
    #         # we must find the ones relevant to our wallets.
    #         all_coins: List[Coin] = []
    #         for puzzle_hash, coin_list_0 in response.coins:
    #             all_coins += coin_list_0
    #         additions = (
    #             await self.wallet_node.wallet_state_manager.get_relevant_additions(
    #                 all_coins
    #             )
    #         )
    #         # Verify root
    #         additions_merkle_set = MerkleSet()
    #
    #         # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
    #         for puzzle_hash, coins in response.coins:
    #             additions_merkle_set.add_already_hashed(puzzle_hash)
    #             additions_merkle_set.add_already_hashed(hash_coin_list(coins))
    #
    #         additions_root = additions_merkle_set.get_root()
    #         if header_block.header.data.additions_root != additions_root:
    #             return
    #     else:
    #         # This means the full node has responded only with the relevant additions
    #         # for our wallet. Each merkle proof must be verified.
    #         additions = []
    #         assert len(response.coins) == len(response.proofs)
    #         for i in range(len(response.coins)):
    #             assert response.coins[i][0] == response.proofs[i][0]
    #             coin_list_1: List[Coin] = response.coins[i][1]
    #             puzzle_hash_proof: bytes32 = response.proofs[i][1]
    #             coin_list_proof: Optional[bytes32] = response.proofs[i][2]
    #             if len(coin_list_1) == 0:
    #                 # Verify exclusion proof for puzzle hash
    #                 assert confirm_not_included_already_hashed(
    #                     header_block.header.data.additions_root,
    #                     response.coins[i][0],
    #                     puzzle_hash_proof,
    #                 )
    #             else:
    #                 # Verify inclusion proof for puzzle hash
    #                 assert confirm_included_already_hashed(
    #                     header_block.header.data.additions_root,
    #                     response.coins[i][0],
    #                     puzzle_hash_proof,
    #                 )
    #                 # Verify inclusion proof for coin list
    #                 assert confirm_included_already_hashed(
    #                     header_block.header.data.additions_root,
    #                     hash_coin_list(coin_list_1),
    #                     coin_list_proof,
    #                 )
    #                 for coin in coin_list_1:
    #                     assert coin.puzzle_hash == response.coins[i][0]
    #                 additions += coin_list_1
    #     new_br = BlockRecord(
    #         block_record.header_hash,
    #         block_record.prev_header_hash,
    #         block_record.height,
    #         block_record.weight,
    #         additions,
    #         None,
    #         block_record.total_iters,
    #         header_block.challenge.get_hash(),
    #         header_block.header.data.timestamp,
    #     )
    #     self.wallet_node.cached_blocks[response.header_hash] = (
    #         new_br,
    #         header_block,
    #         transaction_filter,
    #     )
    #
    #     if transaction_filter is None:
    #         raise RuntimeError("Got additions for block with no transactions.")
    #
    #     (
    #         _,
    #         removals,
    #     ) = await self.wallet_node.wallet_state_manager.get_filter_additions_removals(
    #         new_br, transaction_filter
    #     )
    #     request_all_removals = False
    #     for coin in additions:
    #         puzzle_store = self.wallet_node.wallet_state_manager.puzzle_store
    #         record_info: Optional[
    #             DerivationRecord
    #         ] = await puzzle_store.get_derivation_record_for_puzzle_hash(
    #             coin.puzzle_hash.hex()
    #         )
    #         if (
    #             record_info is not None
    #             and record_info.wallet_type == WalletType.COLOURED_COIN
    #         ):
    #             request_all_removals = True
    #             break
    #
    #     if len(removals) > 0 or request_all_removals:
    #         if request_all_removals:
    #             request_r = wallet_protocol.RequestRemovals(
    #                 header_block.height, header_block.header_hash, None
    #             )
    #         else:
    #             request_r = wallet_protocol.RequestRemovals(
    #                 header_block.height, header_block.header_hash, removals
    #             )
    #         msg = Message("request_removals", request_r)
    #         await peer.send_message(msg)
    #     else:
    #         # We have collected all three things: header, additions, and removals (since there are no
    #         # relevant removals for us). Can proceed. Otherwise, we wait for the removals to arrive.
    #         new_br = BlockRecord(
    #             new_br.header_hash,
    #             new_br.prev_header_hash,
    #             new_br.height,
    #             new_br.weight,
    #             new_br.additions,
    #             [],
    #             new_br.total_iters,
    #             new_br.new_challenge_hash,
    #             new_br.timestamp,
    #         )
    #         respond_header_msg: Optional[
    #             wallet_protocol.RespondHeader
    #         ] = await self.wallet_node._block_finished(
    #             new_br, header_block, transaction_filter
    #         )
    #         if respond_header_msg is not None:
    #             await self.wallet_node._respond_header(respond_header_msg, peer)

    @peer_required
    @api_request
    async def transaction_ack(
        self, ack: wallet_protocol.TransactionAck, peer: WSChiaConnection
    ):
        """
        This is an ack for our previous SendTransaction call. This removes the transaction from
        the send queue if we have sent it to enough nodes.
        """
        assert peer.peer_node_id is not None
        name = peer.peer_node_id.hex()
        if (
            self.wallet_node.wallet_state_manager is None
            or self.wallet_node.backup_initialized is False
        ):
            return
        if ack.status == MempoolInclusionStatus.SUCCESS:
            self.wallet_node.log.info(
                f"SpendBundle has been received and accepted to mempool by the FullNode. {ack}"
            )
        elif ack.status == MempoolInclusionStatus.PENDING:
            self.wallet_node.log.info(
                f"SpendBundle has been received (and is pending) by the FullNode. {ack}"
            )
        else:
            self.wallet_node.log.warning(
                f"SpendBundle has been rejected by the FullNode. {ack}"
            )
        if ack.error is not None:
            await self.wallet_node.wallet_state_manager.remove_from_queue(
                ack.txid, name, ack.status, Err[ack.error]
            )
        else:
            await self.wallet_node.wallet_state_manager.remove_from_queue(
                ack.txid, name, ack.status, None
            )

    # @api_request
    # async def respond_all_proof_hashes(
    #     self, response: wallet_protocol.RespondAllProofHashes
    # ):
    #     """
    #     Receipt of proof hashes, used during sync for interactive weight verification protocol.
    #     """
    #     if (
    #         self.wallet_node.wallet_state_manager is None
    #         or self.wallet_node.backup_initialized is False
    #     ):
    #         return
    #     if not self.wallet_node.wallet_state_manager.sync_mode:
    #         self.wallet_node.log.warning("Receiving proof hashes while not syncing.")
    #         return
    #     self.wallet_node.proof_hashes = response.hashes
    #
    # @api_request
    # async def respond_all_header_hashes_after(
    #     self,
    #     response: wallet_protocol.RespondAllHeaderHashesAfter,
    # ):
    #     """
    #     Response containing all header hashes after a point. This is used to find the fork
    #     point between our current blockchain, and the current heaviest tip.
    #     """
    #     if (
    #         self.wallet_node.wallet_state_manager is None
    #         or self.wallet_node.backup_initialized is False
    #     ):
    #         return
    #     if not self.wallet_node.wallet_state_manager.sync_mode:
    #         self.wallet_node.log.warning("Receiving header hashes while not syncing.")
    #         return
    #     self.wallet_node.header_hashes = response.hashes
    #
    # @api_request
    # async def reject_all_header_hashes_after_request(
    #     self,
    #     response: wallet_protocol.RejectAllHeaderHashesAfterRequest,
    # ):
    #     """
    #     Error in requesting all header hashes.
    #     """
    #     self.wallet_node.log.error("All header hashes after request rejected")
    #     if (
    #         self.wallet_node.wallet_state_manager is None
    #         or self.wallet_node.backup_initialized is False
    #     ):
    #         return
    #     self.wallet_node.header_hashes_error = True
    #
    # @peer_required
    # @api_request
    # async def new_lca(self, request: wallet_protocol.NewLCA, peer: WSChiaConnection):
    #     """
    #     Notification from full node that a new LCA (Least common ancestor of the three blockchain
    #     tips) has been added to the full node.
    #     """
    #     if (
    #         self.wallet_node.wallet_state_manager is None
    #         or self.wallet_node.backup_initialized is False
    #     ):
    #         return
    #     if self.wallet_node._shut_down:
    #         return
    #     if self.wallet_node.wallet_state_manager.sync_mode:
    #         return
    #     # If already seen LCA, ignore.
    #     if request.lca_hash in self.wallet_node.wallet_state_manager.block_records:
    #         return
    #
    #     lca = self.wallet_node.wallet_state_manager.block_records[
    #         self.wallet_node.wallet_state_manager.lca
    #     ]
    #     # If it's not the heaviest chain, ignore.
    #     if request.weight < lca.weight:
    #         return
    #
    #     if (
    #         int(request.height) - int(lca.height)
    #         > self.wallet_node.short_sync_threshold
    #     ):
    #         try:
    #             # Performs sync, and catch exceptions so we don't close the connection
    #             self.wallet_node.wallet_state_manager.set_sync_mode(True)
    #             await self.wallet_node._sync(peer)
    #         except Exception as e:
    #             tb = traceback.format_exc()
    #             self.wallet_node.log.error(f"Error with syncing. {type(e)} {tb}")
    #         self.wallet_node.wallet_state_manager.set_sync_mode(False)
    #     else:
    #         header_request = wallet_protocol.RequestHeader(
    #             uint32(request.height), request.lca_hash
    #         )
    #         Message("request_header", header_request),
    #         msg = Message("request_header", header_request)
    #         await peer.send_message(msg)
    #
    #     # Try sending queued up transaction when new LCA arrives
    #     await self.wallet_node._resend_queue()
    #
    # @peer_required
    # @api_request
    # async def respond_header(
    #     self, response: wallet_protocol.RespondHeader, peer: WSChiaConnection
    # ):
    #     await self.wallet_node._respond_header(response, peer)
    #
    # @peer_required
    # @api_request
    # async def respond_peers(
    #     self, request: introducer_protocol.RespondPeers, peer: WSChiaConnection
    # ):
    #     if not self.wallet_node.has_full_node():
    #         await self.wallet_node.wallet_peers.respond_peers(
    #             request, peer.get_peer_info(), False
    #         )
    #     else:
    #         await self.wallet_node.wallet_peers.ensure_is_closed()
    #
    #     if peer is not None and peer.connection_type is NodeType.INTRODUCER:
    #         await peer.close()
