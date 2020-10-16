import asyncio
import time
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional, Tuple
from chiabip158 import PyBIP158
from chiapos import Verifier
from blspy import G2Element, AugSchemeMPL

from src.consensus.block_rewards import calculate_base_fee, calculate_block_reward
from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import calculate_iterations
from src.consensus.coinbase import create_coinbase_coin, create_fees_coin

from src.full_node.full_node import FullNode

from src.protocols import (
    introducer_protocol,
    farmer_protocol,
    full_node_protocol,
    timelord_protocol,
    wallet_protocol,
)
from src.protocols.wallet_protocol import GeneratorResponse
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.server.ws_connection import WSChiaConnection
from src.types.challenge import Challenge
from src.types.coin import Coin, hash_coin_list
from src.types.full_block import FullBlock
from src.types.header import Header, HeaderData
from src.types.header_block import HeaderBlock
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.types.mempool_item import MempoolItem
from src.types.program import Program
from src.types.proof_of_space import ProofOfSpace
from src.types.proof_of_time import ProofOfTime
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.util.api_decorators import api_request
from src.full_node.bundle_tools import best_solution_program
from src.full_node.cost_calculator import calculate_cost_of_program
from src.util.errors import ConsensusError, Err
from src.util.hash import std_hash
from src.util.ints import uint32, uint64, uint128
from src.util.merkle_set import MerkleSet
from src.types.peer_info import PeerInfo

OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]


class FullNodeAPI:
    full_node: FullNode

    def __init__(self, full_node):
        self.full_node = full_node

    @api_request
    async def request_peers(
        self, request: full_node_protocol.RequestPeers, peer: WSChiaConnection
    ):
        msgs = await self.full_node.full_node_peers.request_peers(peer)
        await peer.send_messages(msgs)

    @api_request
    async def respond_peers_with_peer_info(
        self,
        request: introducer_protocol.RespondPeers,
        peer_info: PeerInfo,
        peer: WSChiaConnection,
    ):
        await self.full_node.full_node_peers.respond_peers(request, peer_info, False)
        # Pseudo-message to close the connection
        await peer.close()

    @api_request
    async def respond_peers_full_node_with_peer_info(
        self,
        request: full_node_protocol.RespondPeers,
        peer_info: PeerInfo,
        peer: WSChiaConnection,
    ):
        await self.full_node.full_node_peers.respond_peers(request, peer_info, True)

    @api_request
    async def new_tip(self, request: full_node_protocol.NewTip, peer: WSChiaConnection):
        """
        A peer notifies us that they have added a new tip to their blockchain. If we don't have it,
        we can ask for it.
        """
        # Check if we have this block in the blockchain
        if self.full_node.blockchain.contains_block(request.header_hash):
            return

        # TODO: potential optimization, don't request blocks that we have already sent out
        # a "request_block" message for.
        message = Message(
            "request_block",
            full_node_protocol.RequestBlock(request.height, request.header_hash),
        )
        await peer.send_message(message)

    @api_request
    async def removing_tip(
        self, request: full_node_protocol.RemovingTip, peer: WSChiaConnection
    ):
        """
        A peer notifies us that they have removed a tip from their blockchain.
        """
        self.full_node.log.info("removing tip not implemented")

    @api_request
    async def request_transaction(
        self, request: full_node_protocol.RequestTransaction, peer: WSChiaConnection
    ) -> Optional[Message]:
        """ Peer has requested a full transaction from us. """
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None

        spend_bundle = self.full_node.mempool_manager.get_spendbundle(
            request.transaction_id
        )
        if spend_bundle is None:
            reject = full_node_protocol.RejectTransactionRequest(request.transaction_id)
            msg = Message("reject_transaction_request", reject)
            return msg

        transaction = full_node_protocol.RespondTransaction(spend_bundle)
        msg = Message("respond_transaction", transaction)
        self.full_node.log.info(
            f"sending transaction (tx_id: {spend_bundle.name()}) to peer"
        )
        return msg

    @api_request
    async def respond_transaction(
        self, tx: full_node_protocol.RespondTransaction, peer: WSChiaConnection
    ) -> Optional[Message]:
        """
        Receives a full transaction from peer.
        If tx is added to mempool, send tx_id to others. (new_transaction)
        """
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None

        async with self.full_node.blockchain.lock:
            # Ignore if we have already added this transaction
            if (
                self.full_node.mempool_manager.get_spendbundle(tx.transaction.name())
                is not None
            ):
                return None
            cost, status, error = await self.full_node.mempool_manager.add_spendbundle(
                tx.transaction
            )
            if status == MempoolInclusionStatus.SUCCESS:
                self.full_node.log.info(
                    f"Added transaction to mempool: {tx.transaction.name()}"
                )
                fees = tx.transaction.fees()
                assert fees >= 0
                assert cost is not None
                new_tx = full_node_protocol.NewTransaction(
                    tx.transaction.name(),
                    cost,
                    uint64(tx.transaction.fees()),
                )
                message = Message("new_transaction", new_tx)
                if self.full_node.server is not None:
                    await self.full_node.server.send_to_all(
                        [message], NodeType.FULL_NODE
                    )
            else:
                self.full_node.log.warning(
                    f"Wasn't able to add transaction with id {tx.transaction.name()}, {status} error: {error}"
                )
                return None
        return None

    @api_request
    async def reject_transaction_request(
        self,
        reject: full_node_protocol.RejectTransactionRequest,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        """
        The peer rejects the request for a transaction.
        """
        self.full_node.log.warning(f"Rejected request for transaction {reject}")
        return None

    @api_request
    async def new_proof_of_time(
        self,
        new_proof_of_time: full_node_protocol.NewProofOfTime,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        if new_proof_of_time.witness_type == 0:
            # A honest sanitizer will always sanitize until the LCA block.
            if new_proof_of_time.height >= self.full_node.blockchain.lca_block.height:
                return None
            # If we already have the compact PoT in a connected to header block, return
            blocks: List[FullBlock] = await self.full_node.block_store.get_blocks_at(
                [new_proof_of_time.height]
            )
            if new_proof_of_time.height not in self.full_node.blockchain.height_to_hash:
                self.full_node.log.error(
                    f"Height {new_proof_of_time.height} not found in height_to_hash."
                )
                return None
            header_hash = self.full_node.blockchain.height_to_hash[
                new_proof_of_time.height
            ]
            for block in blocks:
                assert block.proof_of_time is not None
                if (
                    block.proof_of_time.witness_type == 0
                    and block.header_hash == header_hash
                ):
                    return None
        else:
            # If we don't have an unfinished block for this PoT, we don't care about it
            if (
                await self.full_node.full_node_store.get_unfinished_block(
                    (
                        new_proof_of_time.challenge_hash,
                        new_proof_of_time.number_of_iterations,
                    )
                )
            ) is None:
                return None

            # If we already have the PoT in a finished block, return
            blocks = await self.full_node.block_store.get_blocks_at(
                [new_proof_of_time.height]
            )
            for block in blocks:
                if (
                    block.proof_of_time is not None
                    and block.proof_of_time.challenge_hash
                    == new_proof_of_time.challenge_hash
                    and block.proof_of_time.number_of_iterations
                    == new_proof_of_time.number_of_iterations
                ):
                    return None

            self.full_node.full_node_store.add_proof_of_time_heights(
                (
                    new_proof_of_time.challenge_hash,
                    new_proof_of_time.number_of_iterations,
                ),
                new_proof_of_time.height,
            )
        message = Message(
            "request_proof_of_time",
            full_node_protocol.RequestProofOfTime(
                new_proof_of_time.height,
                new_proof_of_time.challenge_hash,
                new_proof_of_time.number_of_iterations,
                new_proof_of_time.witness_type,
            ),
        )
        return message

    @api_request
    async def request_proof_of_time(
        self,
        request_proof_of_time: full_node_protocol.RequestProofOfTime,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        blocks: List[FullBlock] = await self.full_node.block_store.get_blocks_at(
            [request_proof_of_time.height]
        )
        for block in blocks:
            if (
                block.proof_of_time is not None
                and block.proof_of_time.challenge_hash
                == request_proof_of_time.challenge_hash
                and block.proof_of_time.number_of_iterations
                == request_proof_of_time.number_of_iterations
                and block.proof_of_time.witness_type
                == request_proof_of_time.witness_type
            ):
                msg = Message(
                    "respond_proof_of_time",
                    full_node_protocol.RespondProofOfTime(block.proof_of_time),
                )
                return msg
        reject = Message(
            "reject_proof_of_time_request",
            full_node_protocol.RejectProofOfTimeRequest(
                request_proof_of_time.challenge_hash,
                request_proof_of_time.number_of_iterations,
            ),
        )
        return reject

    @api_request
    async def respond_proof_of_time(
        self,
        respond_proof_of_time: full_node_protocol.RespondProofOfTime,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        """
        A proof of time, received by a peer full node. If we have the rest of the block,
        we can complete it. Otherwise, we just verify and propagate the proof.
        """
        processed = False
        if respond_proof_of_time.proof.witness_type == 0:
            request = timelord_protocol.ProofOfTimeFinished(respond_proof_of_time.proof)

            await self.proof_of_time_finished(request, peer)
            processed = True

        if (
            await self.full_node.full_node_store.get_unfinished_block(
                (
                    respond_proof_of_time.proof.challenge_hash,
                    respond_proof_of_time.proof.number_of_iterations,
                )
            )
        ) is not None:
            height: Optional[
                uint32
            ] = self.full_node.full_node_store.get_proof_of_time_heights(
                (
                    respond_proof_of_time.proof.challenge_hash,
                    respond_proof_of_time.proof.number_of_iterations,
                )
            )
            if height is not None:
                message = Message(
                    "new_proof_of_time",
                    full_node_protocol.NewProofOfTime(
                        height,
                        respond_proof_of_time.proof.challenge_hash,
                        respond_proof_of_time.proof.number_of_iterations,
                        respond_proof_of_time.proof.witness_type,
                    ),
                )
                if self.full_node.server is not None:
                    await self.full_node.server.send_to_all(
                        [message], NodeType.FULL_NODE
                    )
            if not processed:
                request = timelord_protocol.ProofOfTimeFinished(
                    respond_proof_of_time.proof
                )
                await self.proof_of_time_finished(request, peer)
        return None

    @api_request
    async def reject_proof_of_time_request(
        self,
        reject: full_node_protocol.RejectProofOfTimeRequest,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        self.full_node.log.warning(f"Rejected PoT Request {reject}")
        return None

    async def _respond_compact_proof_of_time(
        self, proof: ProofOfTime, peer: WSChiaConnection
    ):
        """
        A proof of time, received by a peer full node. If we have the rest of the block,
        we can complete it. Otherwise, we just verify and propagate the proof.
        """
        height: Optional[uint32] = self.full_node.block_store.get_height_proof_of_time(
            proof.challenge_hash,
            proof.number_of_iterations,
        )
        if height is None:
            self.full_node.log.info("No block for compact proof of time.")
            return
        if not proof.is_valid(self.full_node.constants.DISCRIMINANT_SIZE_BITS):
            self.full_node.log.error("Invalid compact proof of time.")
            return None

        blocks: List[FullBlock] = await self.full_node.block_store.get_blocks_at(
            [height]
        )
        for block in blocks:
            assert block.proof_of_time is not None
            if (
                block.proof_of_time.witness_type != 0
                and block.proof_of_time.challenge_hash == proof.challenge_hash
                and block.proof_of_time.number_of_iterations
                == proof.number_of_iterations
            ):
                block_new = FullBlock(
                    block.proof_of_space,
                    proof,
                    block.header,
                    block.transactions_generator,
                    block.transactions_filter,
                )
                if self.full_node.block_store.seen_compact_proof(
                    proof.challenge_hash,
                    proof.number_of_iterations,
                ):
                    return None
                await self.full_node.block_store.add_block(block_new)
                self.full_node.log.info(
                    f"Stored compact block at height {block.height}."
                )
                message = Message(
                    "new_proof_of_time",
                    full_node_protocol.NewProofOfTime(
                        height,
                        proof.challenge_hash,
                        proof.number_of_iterations,
                        proof.witness_type,
                    ),
                )
                if self.full_node.server is not None:
                    await self.full_node.server.send_to_all(
                        [message], NodeType.FULL_NODE
                    )
        return None

    @api_request
    async def new_unfinished_block(
        self,
        new_unfinished_block: full_node_protocol.NewUnfinishedBlock,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        if self.full_node.blockchain.contains_block(
            new_unfinished_block.new_header_hash
        ):
            return None
        if not self.full_node.blockchain.contains_block(
            new_unfinished_block.previous_header_hash
        ):
            return None
        prev_block: Optional[FullBlock] = await self.full_node.block_store.get_block(
            new_unfinished_block.previous_header_hash
        )
        if prev_block is not None:
            challenge = self.full_node.blockchain.get_challenge(prev_block)
            if challenge is not None:
                if (
                    await (
                        self.full_node.full_node_store.get_unfinished_block(
                            (
                                challenge.get_hash(),
                                new_unfinished_block.number_of_iterations,
                            )
                        )
                    )
                    is not None
                ):
                    return None
            assert challenge is not None

            message = Message(
                "request_unfinished_block",
                full_node_protocol.RequestUnfinishedBlock(
                    new_unfinished_block.new_header_hash
                ),
            )
            return message
        return None

    @api_request
    async def request_unfinished_block(
        self,
        request_unfinished_block: full_node_protocol.RequestUnfinishedBlock,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        for _, block in (
            await self.full_node.full_node_store.get_unfinished_blocks()
        ).items():
            if block.header_hash == request_unfinished_block.header_hash:
                message = Message(
                    "respond_unfinished_block",
                    full_node_protocol.RespondUnfinishedBlock(block),
                )
                return message
        fetched: Optional[FullBlock] = await self.full_node.block_store.get_block(
            request_unfinished_block.header_hash
        )
        if fetched is not None:
            message = Message(
                "respond_unfinished_block",
                full_node_protocol.RespondUnfinishedBlock(fetched),
            )
            return message

        reject = Message(
            "reject_unfinished_block_request",
            full_node_protocol.RejectUnfinishedBlockRequest(
                request_unfinished_block.header_hash
            ),
        )
        return reject

    # WALLET PROTOCOL
    @api_request
    async def send_transaction(
        self, tx: wallet_protocol.SendTransaction, peer: WSChiaConnection
    ) -> Optional[Message]:
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            status = MempoolInclusionStatus.FAILED
            error: Optional[Err] = Err.UNKNOWN
        else:
            async with self.full_node.blockchain.lock:
                (
                    cost,
                    status,
                    error,
                ) = await self.full_node.mempool_manager.add_spendbundle(tx.transaction)
                if status == MempoolInclusionStatus.SUCCESS:
                    self.full_node.log.info(
                        f"Added transaction to mempool: {tx.transaction.name()}"
                    )
                    # Only broadcast successful transactions, not pending ones. Otherwise it's a DOS
                    # vector.
                    fees = tx.transaction.fees()
                    assert fees >= 0
                    assert cost is not None
                    new_tx = full_node_protocol.NewTransaction(
                        tx.transaction.name(),
                        cost,
                        uint64(tx.transaction.fees()),
                    )
                    message = Message("new_transaction", new_tx)
                    if self.full_node.server is not None:
                        await self.full_node.server.send_to_all(
                            [message], NodeType.FULL_NODE
                        )
                else:
                    self.full_node.log.warning(
                        f"Wasn't able to add transaction with id {tx.transaction.name()}, "
                        f"status {status} error: {error}"
                    )

        error_name = error.name if error is not None else None
        if status == MempoolInclusionStatus.SUCCESS:
            response = wallet_protocol.TransactionAck(
                tx.transaction.name(), status, error_name
            )
        else:
            # If if failed/pending, but it previously succeeded (in mempool), this is idempotence, return SUCCESS
            if (
                self.full_node.mempool_manager.get_spendbundle(tx.transaction.name())
                is not None
            ):
                response = wallet_protocol.TransactionAck(
                    tx.transaction.name(), MempoolInclusionStatus.SUCCESS, None
                )
            else:
                response = wallet_protocol.TransactionAck(
                    tx.transaction.name(), status, error_name
                )
        message = Message("transaction_ack", response)
        return message

    @api_request
    async def request_all_proof_hashes(
        self, request: wallet_protocol.RequestAllProofHashes, peer: WSChiaConnection
    ) -> Optional[Message]:
        proof_hashes_map = await self.full_node.block_store.get_proof_hashes()
        curr = self.full_node.blockchain.lca_block

        hashes: List[Tuple[bytes32, Optional[uint64], Optional[uint64]]] = []
        while curr.height > 0:
            difficulty_update: Optional[uint64] = None
            iters_update: Optional[uint64] = None
            if (
                curr.height % self.full_node.constants.DIFFICULTY_EPOCH
                == self.full_node.constants.DIFFICULTY_DELAY
            ):
                difficulty_update = self.full_node.blockchain.get_next_difficulty(
                    self.full_node.blockchain.headers[curr.prev_header_hash]
                )
            if (curr.height + 1) % self.full_node.constants.DIFFICULTY_EPOCH == 0:
                iters_update = curr.data.total_iters
            hashes.append(
                (proof_hashes_map[curr.header_hash], difficulty_update, iters_update)
            )
            curr = self.full_node.blockchain.headers[curr.prev_header_hash]

        hashes.append(
            (
                proof_hashes_map[self.full_node.blockchain.genesis.header_hash],
                uint64(self.full_node.blockchain.genesis.weight),
                None,
            )
        )
        response = wallet_protocol.RespondAllProofHashes(list(reversed(hashes)))

        message = Message("respond_all_proof_hashes", response)
        return message

    @api_request
    async def request_all_header_hashes_after(
        self,
        request: wallet_protocol.RequestAllHeaderHashesAfter,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        header_hash: Optional[bytes32] = self.full_node.blockchain.height_to_hash.get(
            request.starting_height, None
        )
        if header_hash is None:
            reject = wallet_protocol.RejectAllHeaderHashesAfterRequest(
                request.starting_height, request.previous_challenge_hash
            )
            message = Message("reject_all_header_hashes_after_request", reject)
            return message
        block: Optional[FullBlock] = await self.full_node.block_store.get_block(
            header_hash
        )
        header_hash_again: Optional[
            bytes32
        ] = self.full_node.blockchain.height_to_hash.get(request.starting_height, None)

        if (
            block is None
            or block.proof_of_space.challenge_hash != request.previous_challenge_hash
            or header_hash_again != header_hash
        ):
            reject = wallet_protocol.RejectAllHeaderHashesAfterRequest(
                request.starting_height, request.previous_challenge_hash
            )
            message = Message("reject_all_header_hashes_after_request", reject)
            return message
        header_hashes: List[bytes32] = []
        for height in range(
            request.starting_height, self.full_node.blockchain.lca_block.height + 1
        ):
            header_hashes.append(
                self.full_node.blockchain.height_to_hash[uint32(height)]
            )
        response = wallet_protocol.RespondAllHeaderHashesAfter(
            request.starting_height, request.previous_challenge_hash, header_hashes
        )

        message = Message("respond_all_header_hashes_after", response)
        return message

    @api_request
    async def request_header(
        self, request: wallet_protocol.RequestHeader, peer: WSChiaConnection
    ) -> Optional[Message]:
        full_block: Optional[FullBlock] = await self.full_node.block_store.get_block(
            request.header_hash
        )
        if full_block is not None:
            header_block: Optional[
                HeaderBlock
            ] = self.full_node.blockchain.get_header_block(full_block)
            if header_block is not None and header_block.height == request.height:
                response = wallet_protocol.RespondHeader(
                    header_block, full_block.transactions_filter
                )
                message = Message("respond_header", response)
                return message
        reject = wallet_protocol.RejectHeaderRequest(
            request.height, request.header_hash
        )

        message = Message("reject_header_request", reject)
        return message

    @api_request
    async def request_removals(
        self, request: wallet_protocol.RequestRemovals, peer: WSChiaConnection
    ) -> Optional[Message]:
        block: Optional[FullBlock] = await self.full_node.block_store.get_block(
            request.header_hash
        )
        if (
            block is None
            or block.height != request.height
            or block.height not in self.full_node.blockchain.height_to_hash
            or self.full_node.blockchain.height_to_hash[block.height]
            != block.header_hash
        ):
            reject = wallet_protocol.RejectRemovalsRequest(
                request.height, request.header_hash
            )
            message = Message("reject_removals_request", reject)
            return message

        assert block is not None
        all_removals, _ = await block.tx_removals_and_additions()

        coins_map: List[Tuple[bytes32, Optional[Coin]]] = []
        proofs_map: List[Tuple[bytes32, bytes]] = []

        # If there are no transactions, respond with empty lists
        if block.transactions_generator is None:
            proofs: Optional[List]
            if request.coin_names is None:
                proofs = None
            else:
                proofs = []
            response = wallet_protocol.RespondRemovals(
                block.height, block.header_hash, [], proofs
            )
        elif request.coin_names is None or len(request.coin_names) == 0:
            for removal in all_removals:
                cr = await self.full_node.coin_store.get_coin_record(removal)
                assert cr is not None
                coins_map.append((cr.coin.name(), cr.coin))
            response = wallet_protocol.RespondRemovals(
                block.height, block.header_hash, coins_map, None
            )
        else:
            assert block.transactions_generator
            removal_merkle_set = MerkleSet()
            for coin_name in all_removals:
                removal_merkle_set.add_already_hashed(coin_name)
            assert removal_merkle_set.get_root() == block.header.data.removals_root
            for coin_name in request.coin_names:
                result, proof = removal_merkle_set.is_included_already_hashed(coin_name)
                proofs_map.append((coin_name, proof))
                if coin_name in all_removals:
                    cr = await self.full_node.coin_store.get_coin_record(coin_name)
                    assert cr is not None
                    coins_map.append((coin_name, cr.coin))
                    assert result
                else:
                    coins_map.append((coin_name, None))
                    assert not result
            response = wallet_protocol.RespondRemovals(
                block.height, block.header_hash, coins_map, proofs_map
            )

        message = Message("respond_removals", response)
        return message

    @api_request
    async def request_additions(
        self, request: wallet_protocol.RequestAdditions, peer: WSChiaConnection
    ) -> Optional[Message]:
        block: Optional[FullBlock] = await self.full_node.block_store.get_block(
            request.header_hash
        )
        if (
            block is None
            or block.height != request.height
            or block.height not in self.full_node.blockchain.height_to_hash
            or self.full_node.blockchain.height_to_hash[block.height]
            != block.header_hash
        ):
            reject = wallet_protocol.RejectAdditionsRequest(
                request.height, request.header_hash
            )
            message = Message("reject_additions_request", reject)
            return message

        assert block is not None
        _, additions = await block.tx_removals_and_additions()
        puzzlehash_coins_map: Dict[bytes32, List[Coin]] = {}
        for coin in additions + [block.get_coinbase(), block.get_fees_coin()]:
            if coin.puzzle_hash in puzzlehash_coins_map:
                puzzlehash_coins_map[coin.puzzle_hash].append(coin)
            else:
                puzzlehash_coins_map[coin.puzzle_hash] = [coin]

        coins_map: List[Tuple[bytes32, List[Coin]]] = []
        proofs_map: List[Tuple[bytes32, bytes, Optional[bytes]]] = []

        if request.puzzle_hashes is None:
            for puzzle_hash, coins in puzzlehash_coins_map.items():
                coins_map.append((puzzle_hash, coins))
            response = wallet_protocol.RespondAdditions(
                block.height, block.header_hash, coins_map, None
            )
        else:
            # Create addition Merkle set
            addition_merkle_set = MerkleSet()
            # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
            for puzzle, coins in puzzlehash_coins_map.items():
                addition_merkle_set.add_already_hashed(puzzle)
                addition_merkle_set.add_already_hashed(hash_coin_list(coins))

            assert addition_merkle_set.get_root() == block.header.data.additions_root
            for puzzle_hash in request.puzzle_hashes:
                result, proof = addition_merkle_set.is_included_already_hashed(
                    puzzle_hash
                )
                if puzzle_hash in puzzlehash_coins_map:
                    coins_map.append((puzzle_hash, puzzlehash_coins_map[puzzle_hash]))
                    hash_coin_str = hash_coin_list(puzzlehash_coins_map[puzzle_hash])
                    result_2, proof_2 = addition_merkle_set.is_included_already_hashed(
                        hash_coin_str
                    )
                    assert result
                    assert result_2
                    proofs_map.append((puzzle_hash, proof, proof_2))
                else:
                    coins_map.append((puzzle_hash, []))
                    assert not result
                    proofs_map.append((puzzle_hash, proof, None))
            response = wallet_protocol.RespondAdditions(
                block.height, block.header_hash, coins_map, proofs_map
            )

        message = Message("respond_additions", response)
        return message

    @api_request
    async def request_generator(
        self, request: wallet_protocol.RequestGenerator, peer: WSChiaConnection
    ) -> Optional[Message]:
        full_block: Optional[FullBlock] = await self.full_node.block_store.get_block(
            request.header_hash
        )
        if full_block is not None:
            if full_block.transactions_generator is not None:
                wrapper = GeneratorResponse(
                    full_block.height,
                    full_block.header_hash,
                    full_block.transactions_generator,
                )
                response = wallet_protocol.RespondGenerator(wrapper)
                message = Message("respond_generator", response)
                return message

        reject = wallet_protocol.RejectGeneratorRequest(
            request.height, request.header_hash
        )

        message = Message("reject_generator_request", reject)
        return message

    @api_request
    async def respond_header_block(
        self, request: full_node_protocol.RespondHeaderBlock, peer: WSChiaConnection
    ) -> Optional[Message]:
        """
        Receive header blocks from a peer.
        """
        self.full_node.log.info(f"Received header block {request.header_block.height}.")
        if self.full_node.sync_peers_handler is not None:
            requests = await self.full_node.sync_peers_handler.new_block(
                request.header_block
            )
            if self.full_node.server is None:
                return None
            for req in requests:
                msg = req.message
                node_id = req.specific_peer_node_id
                if node_id is not None:
                    await self.full_node.server.send_to_specific([msg], node_id)
                else:
                    await self.full_node.server.send_to_all([msg], NodeType.FULL_NODE)
        return None

    @api_request
    async def reject_header_block_request(
        self,
        request: full_node_protocol.RejectHeaderBlockRequest,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        self.full_node.log.warning(f"Reject header block request, {request}")
        if self.full_node.sync_store.get_sync_mode():
            await peer.close()
        return None

    @api_request
    async def request_header_hash(
        self, request: farmer_protocol.RequestHeaderHash, peer: WSChiaConnection
    ) -> Optional[Message]:
        """
        Creates a block body and header, with the proof of space, coinbase, and fee targets provided
        by the farmer, and sends the hash of the header data back to the farmer.
        """
        plot_id: bytes32 = request.proof_of_space.get_plot_id()

        # Checks that the proof of space is valid
        quality_string: bytes = Verifier().validate_proof(
            plot_id,
            request.proof_of_space.size,
            request.challenge_hash,
            bytes(request.proof_of_space.proof),
        )
        assert len(quality_string) == 32

        # Retrieves the correct tip for the challenge
        tips: List[Header] = self.full_node.blockchain.get_current_tips()
        tips_blocks: List[Optional[FullBlock]] = [
            await self.full_node.block_store.get_block(tip.header_hash) for tip in tips
        ]
        target_tip_block: Optional[FullBlock] = None
        target_tip: Optional[Header] = None
        for tip in tips_blocks:
            assert tip is not None
            tip_challenge: Optional[
                Challenge
            ] = self.full_node.blockchain.get_challenge(tip)
            assert tip_challenge is not None
            if tip_challenge.get_hash() == request.challenge_hash:
                target_tip_block = tip
                target_tip = tip.header
        if target_tip is None:
            self.full_node.log.warning(
                f"Challenge hash: {request.challenge_hash} not in one of three tips"
            )
            return None

        assert target_tip is not None
        # Grab best transactions from Mempool for given tip target
        async with self.full_node.blockchain.lock:
            spend_bundle: Optional[
                SpendBundle
            ] = await self.full_node.mempool_manager.create_bundle_for_tip(target_tip)
        spend_bundle_fees = 0
        aggregate_sig: G2Element = request.pool_target_signature
        solution_program: Optional[Program] = None

        if spend_bundle:
            solution_program = best_solution_program(spend_bundle)
            spend_bundle_fees = spend_bundle.fees()
            aggregate_sig = AugSchemeMPL.aggregate(
                [spend_bundle.aggregated_signature, aggregate_sig]
            )

        base_fee_reward = calculate_base_fee(target_tip.height + 1)
        full_fee_reward = uint64(int(base_fee_reward + spend_bundle_fees))

        # Calculate the cost of transactions
        cost = uint64(0)
        if solution_program:
            _, _, cost = calculate_cost_of_program(
                solution_program, self.full_node.constants.CLVM_COST_RATIO_CONSTANT
            )

        extension_data: bytes32 = bytes32([0] * 32)

        # Creates a block with transactions, coinbase, and fees
        # Creates the block header
        prev_header_hash: bytes32 = target_tip.get_hash()
        timestamp: uint64 = uint64(int(time.time()))

        # Create filter
        byte_array_tx: List[bytes32] = []
        if spend_bundle:
            additions: List[Coin] = spend_bundle.additions()
            removals: List[Coin] = spend_bundle.removals()
            for coin in additions:
                byte_array_tx.append(bytearray(coin.puzzle_hash))
            for coin in removals:
                byte_array_tx.append(bytearray(coin.name()))

        byte_array_tx.append(bytearray(request.farmer_rewards_puzzle_hash))
        byte_array_tx.append(bytearray(request.pool_target.puzzle_hash))

        bip158: PyBIP158 = PyBIP158(byte_array_tx)
        encoded_filter: bytes = bytes(bip158.GetEncoded())

        proof_of_space_hash: bytes32 = request.proof_of_space.get_hash()
        difficulty = self.full_node.blockchain.get_next_difficulty(target_tip)

        assert target_tip_block is not None
        vdf_min_iters: uint64 = self.full_node.blockchain.get_next_min_iters(
            target_tip_block
        )

        iterations_needed: uint64 = calculate_iterations(
            request.proof_of_space,
            difficulty,
            vdf_min_iters,
            self.full_node.constants.NUMBER_ZERO_BITS_CHALLENGE_SIG,
        )

        removal_merkle_set = MerkleSet()
        addition_merkle_set = MerkleSet()

        additions = []
        removals = []

        if spend_bundle:
            additions = spend_bundle.additions()
            removals = spend_bundle.removals()

        # Create removal Merkle set
        for coin in removals:
            removal_merkle_set.add_already_hashed(coin.name())
        cb_reward = calculate_block_reward(target_tip.height + 1)
        cb_coin = create_coinbase_coin(
            target_tip.height + 1, request.pool_target.puzzle_hash, cb_reward
        )
        fees_coin = create_fees_coin(
            target_tip.height + 1,
            request.farmer_rewards_puzzle_hash,
            full_fee_reward,
        )

        # Create addition Merkle set
        puzzlehash_coins_map: Dict[bytes32, List[Coin]] = {}
        for coin in additions + [cb_coin, fees_coin]:
            if coin.puzzle_hash in puzzlehash_coins_map:
                puzzlehash_coins_map[coin.puzzle_hash].append(coin)
            else:
                puzzlehash_coins_map[coin.puzzle_hash] = [coin]

        # Addition Merkle set contains puzzlehash and hash of all coins with that puzzlehash
        for puzzle, coins in puzzlehash_coins_map.items():
            addition_merkle_set.add_already_hashed(puzzle)
            addition_merkle_set.add_already_hashed(hash_coin_list(coins))

        additions_root = addition_merkle_set.get_root()
        removal_root = removal_merkle_set.get_root()

        generator_hash = (
            solution_program.get_tree_hash()
            if solution_program is not None
            else bytes32([0] * 32)
        )
        filter_hash = std_hash(encoded_filter)

        block_header_data: HeaderData = HeaderData(
            uint32(target_tip.height + 1),
            prev_header_hash,
            timestamp,
            filter_hash,
            proof_of_space_hash,
            uint128(target_tip.weight + difficulty),
            uint64(target_tip.data.total_iters + iterations_needed),
            additions_root,
            removal_root,
            request.farmer_rewards_puzzle_hash,
            full_fee_reward,
            request.pool_target,
            aggregate_sig,
            cost,
            extension_data,
            generator_hash,
        )

        block_header_data_hash: bytes32 = block_header_data.get_hash()

        # Stores this block so we can submit it to the blockchain after it's signed by harvester
        self.full_node.full_node_store.add_candidate_block(
            proof_of_space_hash,
            solution_program,
            encoded_filter,
            block_header_data,
            request.proof_of_space,
            target_tip.height + 1,
        )

        message = farmer_protocol.HeaderHash(
            proof_of_space_hash, block_header_data_hash
        )

        return Message("header_hash", message)

    @api_request
    async def header_signature(
        self, header_signature: farmer_protocol.HeaderSignature, peer: WSChiaConnection
    ) -> Optional[Message]:
        """
        Signature of header hash, by the harvester. This is enough to create an unfinished
        block, which only needs a Proof of Time to be finished. If the signature is valid,
        we call the unfinished_block routine.
        """
        candidate: Optional[
            Tuple[Optional[Program], bytes, HeaderData, ProofOfSpace]
        ] = self.full_node.full_node_store.get_candidate_block(
            header_signature.pos_hash
        )
        if candidate is None:
            self.full_node.log.warning(
                f"PoS hash {header_signature.pos_hash} not found in database"
            )
            return None
        # Verifies that we have the correct header and body stored
        generator, filt, block_header_data, pos = candidate

        assert block_header_data.get_hash() == header_signature.header_hash

        block_header: Header = Header(
            block_header_data, header_signature.header_signature
        )
        unfinished_block_obj: FullBlock = FullBlock(
            pos, None, block_header, generator, filt
        )

        # Propagate to ourselves (which validates and does further propagations)
        request = full_node_protocol.RespondUnfinishedBlock(unfinished_block_obj)
        await self.respond_unfinished_block(request, peer)
        return None

    @api_request
    async def new_transaction(
        self, transaction: full_node_protocol.NewTransaction, peer: WSChiaConnection
    ) -> Optional[Message]:
        """
        A peer notifies us of a new transaction.
        Requests a full transaction if we haven't seen it previously, and if the fees are enough.
        """
        # Ignore if syncing
        if self.full_node.sync_store.get_sync_mode():
            return None
        # Ignore if already seen
        if self.full_node.mempool_manager.seen(transaction.transaction_id):
            return None

        if self.full_node.mempool_manager.is_fee_enough(
            transaction.fees, transaction.cost
        ):
            requestTX = full_node_protocol.RequestTransaction(
                transaction.transaction_id
            )
            return Message("request_transaction", requestTX)

        return None

    # TIMELORD PROTOCOL
    @api_request
    async def proof_of_time_finished(
        self, request: timelord_protocol.ProofOfTimeFinished, peer: WSChiaConnection
    ) -> Optional[Message]:
        """
        A proof of time, received by a peer timelord. We can use this to complete a block,
        and call the block routine (which handles propagation and verification of blocks).
        """
        if request.proof.witness_type == 0:
            await self._respond_compact_proof_of_time(request.proof, peer)

        dict_key = (
            request.proof.challenge_hash,
            request.proof.number_of_iterations,
        )

        unfinished_block_obj: Optional[
            FullBlock
        ] = await self.full_node.full_node_store.get_unfinished_block(dict_key)
        if not unfinished_block_obj:
            if request.proof.witness_type > 0:
                self.full_node.log.warning(
                    f"Received a proof of time that we cannot use to complete a block {dict_key}"
                )
            return None

        new_full_block: FullBlock = FullBlock(
            unfinished_block_obj.proof_of_space,
            request.proof,
            unfinished_block_obj.header,
            unfinished_block_obj.transactions_generator,
            unfinished_block_obj.transactions_filter,
        )

        if self.full_node.sync_store.get_sync_mode():
            self.full_node.sync_store.add_potential_future_block(new_full_block)
        else:
            await self.respond_block(
                full_node_protocol.RespondBlock(new_full_block), peer
            )
        return None

    @api_request
    async def request_block(
        self, request_block: full_node_protocol.RequestBlock, peer: WSChiaConnection
    ) -> Optional[Message]:
        block: Optional[FullBlock] = await self.full_node.block_store.get_block(
            request_block.header_hash
        )
        if block is not None:
            return Message("respond_block", full_node_protocol.RespondBlock(block))

        reject = Message(
            "reject_block_request",
            full_node_protocol.RejectBlockRequest(
                request_block.height, request_block.header_hash
            ),
        )
        return reject

    @api_request
    async def respond_block(
        self, respond_block: full_node_protocol.RespondBlock, peer: WSChiaConnection
    ) -> Optional[Message]:
        await self.full_node._respond_block(respond_block)
        return None

    @api_request
    async def reject_block_request(
        self, reject: full_node_protocol.RejectBlockRequest, peer: WSChiaConnection
    ) -> Optional[Message]:
        self.full_node.log.warning(f"Rejected block request {reject}")
        if self.full_node.sync_store.get_sync_mode():
            await peer.close()
        return None

    @api_request
    async def request_mempool_transactions(
        self,
        request: full_node_protocol.RequestMempoolTransactions,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        received_filter = PyBIP158(bytearray(request.filter))

        items: List[
            MempoolItem
        ] = await self.full_node.mempool_manager.get_items_not_in_filter(
            received_filter
        )

        for item in items:
            transaction = full_node_protocol.RespondTransaction(item.spend_bundle)
            await peer.send_message(Message("respond_transaction", transaction))

        return None

    @api_request
    async def respond_unfinished_block(
        self,
        respond_unfinished_block: full_node_protocol.RespondUnfinishedBlock,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        """
        We have received an unfinished block, either created by us, or from another peer.
        We can validate it and if it's a good block, propagate it to other peers and
        timelords.
        """
        block = respond_unfinished_block.block
        # Adds the unfinished block to seen, and check if it's seen before, to prevent
        # processing it twice
        if self.full_node.full_node_store.seen_unfinished_block(block.header_hash):
            return None

        if not self.full_node.blockchain.is_child_of_head(block):
            return None

        prev_full_block: Optional[
            FullBlock
        ] = await self.full_node.block_store.get_block(block.prev_header_hash)

        assert prev_full_block is not None
        async with self.full_node.blockchain.lock:
            (
                error_code,
                iterations_needed,
            ) = await self.full_node.blockchain.validate_unfinished_block(
                block, prev_full_block
            )

        if error_code is not None:
            raise ConsensusError(error_code)
        assert iterations_needed is not None

        challenge = self.full_node.blockchain.get_challenge(prev_full_block)
        assert challenge is not None
        challenge_hash = challenge.get_hash()

        if (
            await (
                self.full_node.full_node_store.get_unfinished_block(
                    (challenge_hash, iterations_needed)
                )
            )
            is not None
        ):
            return None

        expected_time: uint64 = uint64(
            int(
                iterations_needed
                / (self.full_node.full_node_store.get_proof_of_time_estimate_ips())
            )
        )

        if expected_time > self.full_node.constants.PROPAGATION_DELAY_THRESHOLD:
            self.full_node.log.info(
                f"Block is slow, expected {expected_time} seconds, waiting"
            )
            # If this block is slow, sleep to allow faster blocks to come out first
            await asyncio.sleep(5)

        leader: Tuple[
            uint32, uint64
        ] = self.full_node.full_node_store.get_unfinished_block_leader()
        if leader is None or block.height > leader[0]:
            self.full_node.log.info(
                f"This is the first unfinished block at height {block.height}, so propagate."
            )
            # If this is the first block we see at this height, propagate
            self.full_node.full_node_store.set_unfinished_block_leader(
                (block.height, expected_time)
            )
        elif block.height == leader[0]:
            if (
                expected_time
                > leader[1] + self.full_node.constants.PROPAGATION_THRESHOLD
            ):
                # If VDF is expected to finish X seconds later than the best, don't propagate
                self.full_node.log.info(
                    f"VDF will finish too late {expected_time} seconds, so don't propagate"
                )
                return None
            elif expected_time < leader[1]:
                self.full_node.log.info(
                    f"New best unfinished block at height {block.height}"
                )
                # If this will be the first block to finalize, update our leader
                self.full_node.full_node_store.set_unfinished_block_leader(
                    (leader[0], expected_time)
                )
        else:
            # If we have seen an unfinished block at a greater or equal height, don't propagate
            self.full_node.log.info(
                "Unfinished block at old height, so don't propagate"
            )
            return None

        await self.full_node.full_node_store.add_unfinished_block(
            (challenge_hash, iterations_needed), block
        )

        timelord_request = timelord_protocol.ProofOfSpaceInfo(
            challenge_hash, iterations_needed
        )

        message = Message("proof_of_space_info", timelord_request)
        if self.full_node.server is not None:
            await self.full_node.server.send_to_all([message], NodeType.TIMELORD)
        new_unfinished_block = full_node_protocol.NewUnfinishedBlock(
            block.prev_header_hash, iterations_needed, block.header_hash
        )

        f_message = Message("new_unfinished_block", new_unfinished_block)
        if self.full_node.server is not None:
            await self.full_node.server.send_to_all([f_message], NodeType.FULL_NODE)
        self.full_node._state_changed("block")
        return None

    @api_request
    async def reject_unfinished_block_request(
        self,
        reject: full_node_protocol.RejectUnfinishedBlockRequest,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        self.full_node.log.warning(f"Rejected unfinished block request {reject}")
        return None

    @api_request
    async def request_all_header_hashes(
        self, request: full_node_protocol.RequestAllHeaderHashes, peer: WSChiaConnection
    ) -> Optional[Message]:
        try:
            header_hashes = self.full_node.blockchain.get_header_hashes(
                request.tip_header_hash
            )
            message = Message(
                "all_header_hashes", full_node_protocol.AllHeaderHashes(header_hashes)
            )
            return message
        except ValueError:
            self.full_node.log.info("Do not have requested header hashes.")
            return None

    @api_request
    async def all_header_hashes(
        self,
        all_header_hashes: full_node_protocol.AllHeaderHashes,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        assert len(all_header_hashes.header_hashes) > 0
        self.full_node.sync_store.set_potential_hashes(all_header_hashes.header_hashes)
        phr = self.full_node.sync_store.get_potential_hashes_received()
        assert phr is not None
        phr.set()
        return None

    @api_request
    async def request_header_block(
        self, request: full_node_protocol.RequestHeaderBlock, peer: WSChiaConnection
    ) -> Optional[Message]:
        """
        A peer requests a list of header blocks, by height. Used for syncing or light clients.
        """
        full_block: Optional[FullBlock] = await self.full_node.block_store.get_block(
            request.header_hash
        )
        if full_block is not None:
            header_block: Optional[
                HeaderBlock
            ] = self.full_node.blockchain.get_header_block(full_block)
            if header_block is not None and header_block.height == request.height:
                response = full_node_protocol.RespondHeaderBlock(header_block)

                message = Message("respond_header_block", response)
                return message
        reject = full_node_protocol.RejectHeaderBlockRequest(
            request.height, request.header_hash
        )

        message = Message("reject_header_block_request", reject)
        return message
