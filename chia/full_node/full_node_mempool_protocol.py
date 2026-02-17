from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8

from chia.consensus.blockchain import BlockchainMutexPriority
from chia.full_node.mempool import MempoolRemoveInfo
from chia.full_node.subscriptions import peers_for_spend_bundle
from chia.full_node.tx_processing_queue import PeerWithTx
from chia.protocols import full_node_protocol, wallet_protocol
from chia.protocols.outbound_message import NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.protocol_timing import CONSENSUS_ERROR_BAN_SECONDS
from chia.protocols.shared_protocol import Capability
from chia.types.clvm_cost import QUOTE_BYTES, QUOTE_EXECUTION_COST
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.util.path import path_from_root

if TYPE_CHECKING:
    from chia_rs import SpendBundle

    from chia.full_node.full_node import FullNode
    from chia.server.ws_connection import WSChiaConnection
    from chia.types.mempool_item import MempoolItem


async def add_transaction(
    self: FullNode,
    transaction: SpendBundle,
    spend_name: bytes32,
    peer: WSChiaConnection | None = None,
    test: bool = False,
    # Map of peer ID to its hostname, the fee and the cost it advertised
    # for this transaction.
    peers_with_tx: dict[bytes32, PeerWithTx] = {},
) -> tuple[MempoolInclusionStatus, Err | None]:
    if self.sync_store.get_sync_mode():
        return MempoolInclusionStatus.FAILED, Err.NO_TRANSACTIONS_WHILE_SYNCING
    if not test and not (await self.synced()):
        return MempoolInclusionStatus.FAILED, Err.NO_TRANSACTIONS_WHILE_SYNCING

    if self.mempool_manager.get_spendbundle(spend_name) is not None:
        self.mempool_manager.remove_seen(spend_name)
        return MempoolInclusionStatus.SUCCESS, None
    if self.mempool_manager.seen(spend_name):
        return MempoolInclusionStatus.FAILED, Err.ALREADY_INCLUDING_TRANSACTION
    self.log.debug(f"Processing transaction: {spend_name}")
    # Ignore if syncing or if we have not yet received a block
    # the mempool must have a peak to validate transactions
    if self.sync_store.get_sync_mode() or self.mempool_manager.peak is None:
        return MempoolInclusionStatus.FAILED, Err.NO_TRANSACTIONS_WHILE_SYNCING

    cost_result = await self.mempool_manager.pre_validate_spendbundle(transaction, spend_name, self._bls_cache)

    self.mempool_manager.add_and_maybe_pop_seen(spend_name)

    if self.config.get("log_mempool", False):  # pragma: no cover
        try:
            mempool_dir = path_from_root(self.root_path, "mempool-log") / f"{self.blockchain.get_peak_height()}"
            mempool_dir.mkdir(parents=True, exist_ok=True)
            with open(mempool_dir / f"{spend_name}.bundle", "wb+") as f:
                f.write(bytes(transaction))
        except Exception:
            self.log.exception(f"Failed to log mempool item: {spend_name}")

    async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.low):
        if self.mempool_manager.get_spendbundle(spend_name) is not None:
            self.mempool_manager.remove_seen(spend_name)
            return MempoolInclusionStatus.SUCCESS, None
        if self.mempool_manager.peak is None:
            return MempoolInclusionStatus.FAILED, Err.MEMPOOL_NOT_INITIALIZED
        info = await self.mempool_manager.add_spend_bundle(
            transaction, cost_result, spend_name, self.mempool_manager.peak.height
        )
        status = info.status
        error = info.error
    if status == MempoolInclusionStatus.SUCCESS:
        self.log.debug(
            f"Added transaction to mempool: {spend_name} mempool size: "
            f"{self.mempool_manager.mempool.total_mempool_cost()} normalized "
            f"{self.mempool_manager.mempool.total_mempool_cost() / 5000000}"
        )

        mempool_item = self.mempool_manager.get_mempool_item(spend_name)
        assert mempool_item is not None
        # Now that we validated this transaction, check what fees and
        # costs the peers have advertised for it.
        for peer_id, entry in peers_with_tx.items():
            # Older nodes (2.4.3 and earlier) compute the cost slightly
            # differently. They include the byte cost and execution cost of
            # the quote for the puzzle.
            tolerated_diff = QUOTE_BYTES * self.constants.COST_PER_BYTE + QUOTE_EXECUTION_COST
            if entry.advertised_fee == mempool_item.fee and (
                entry.advertised_cost == mempool_item.cost
                or entry.advertised_cost == mempool_item.cost + tolerated_diff
            ):
                continue
            self.log.warning(
                f"Banning peer {peer_id}. Sent us a new tx {spend_name} with mismatch "
                f"on cost {entry.advertised_cost} vs validation cost {mempool_item.cost} and/or "
                f"fee {entry.advertised_fee} vs {mempool_item.fee}."
            )
            peer = self.server.all_connections.get(peer_id)
            if peer is None:
                self.server.ban_peer(entry.peer_host, CONSENSUS_ERROR_BAN_SECONDS)
            else:
                await peer.close(CONSENSUS_ERROR_BAN_SECONDS)
        # Only broadcast successful transactions, not pending ones. Otherwise it's a DOS
        # vector.
        await self.broadcast_removed_tx(info.removals)
        await self.broadcast_added_tx(mempool_item, current_peer=peer)

        if self.simulator_transaction_callback is not None:  # callback
            await self.simulator_transaction_callback(spend_name)

    else:
        self.mempool_manager.remove_seen(spend_name)
        self.log.debug(f"Wasn't able to add transaction with id {spend_name}, status {status} error: {error}")
    return status, error


async def broadcast_added_tx(
    self: FullNode, mempool_item: MempoolItem, current_peer: WSChiaConnection | None = None
) -> None:
    assert mempool_item.fee >= 0
    assert mempool_item.cost is not None

    new_tx = full_node_protocol.NewTransaction(
        mempool_item.name,
        mempool_item.cost,
        mempool_item.fee,
    )
    msg = make_msg(ProtocolMessageTypes.new_transaction, new_tx)
    if current_peer is None:
        await self.server.send_to_all([msg], NodeType.FULL_NODE)
    else:
        await self.server.send_to_all([msg], NodeType.FULL_NODE, current_peer.peer_node_id)

    conds = mempool_item.conds

    all_peers = {
        peer_id
        for peer_id, peer in self.server.all_connections.items()
        if peer.has_capability(Capability.MEMPOOL_UPDATES)
    }

    if len(all_peers) == 0:
        return

    start_time = time.monotonic()

    hints_for_removals = await self.hint_store.get_hints([bytes32(spend.coin_id) for spend in conds.spends])
    peer_ids = all_peers.intersection(peers_for_spend_bundle(self.subscriptions, conds, set(hints_for_removals)))

    for peer_id in peer_ids:
        peer = self.server.all_connections.get(peer_id)

        if peer is None:
            continue

        msg = make_msg(ProtocolMessageTypes.mempool_items_added, wallet_protocol.MempoolItemsAdded([mempool_item.name]))
        await peer.send_message(msg)

    total_time = time.monotonic() - start_time

    if len(peer_ids) == 0:
        self.log.log(
            logging.DEBUG if total_time < 0.5 else logging.WARNING,
            f"Looking up hints for {len(conds.spends)} spends took {total_time:.4f}s",
        )
    else:
        self.log.log(
            logging.DEBUG if total_time < 0.5 else logging.WARNING,
            f"Broadcasting added transaction {mempool_item.name} to {len(peer_ids)} peers took {total_time:.4f}s",
        )


async def broadcast_removed_tx(self: FullNode, mempool_removals: list[MempoolRemoveInfo]) -> None:
    total_removals = sum(len(r.items) for r in mempool_removals)
    if total_removals == 0:
        return

    start_time = time.monotonic()

    self.log.debug(f"Broadcasting {total_removals} removed transactions to peers")

    all_peers = {
        peer_id
        for peer_id, peer in self.server.all_connections.items()
        if peer.has_capability(Capability.MEMPOOL_UPDATES)
    }

    if len(all_peers) == 0:
        return

    removals_to_send: dict[bytes32, list[wallet_protocol.RemovedMempoolItem]] = dict()

    for removal_info in mempool_removals:
        for transaction_id, internal_mempool_item in removal_info.items.items():
            conds = internal_mempool_item.conds
            assert conds is not None

            hints_for_removals = await self.hint_store.get_hints([bytes32(spend.coin_id) for spend in conds.spends])
            peer_ids = all_peers.intersection(
                peers_for_spend_bundle(self.subscriptions, conds, set(hints_for_removals))
            )

            if len(peer_ids) == 0:
                continue

            self.log.debug(f"Broadcasting removed transaction {transaction_id} to wallet peers {peer_ids}")

            for peer_id in peer_ids:
                peer = self.server.all_connections.get(peer_id)

                if peer is None:
                    continue

                removal = wallet_protocol.RemovedMempoolItem(transaction_id, uint8(removal_info.reason.value))
                removals_to_send.setdefault(peer.peer_node_id, []).append(removal)

    for peer_id, removals in removals_to_send.items():
        peer = self.server.all_connections.get(peer_id)

        if peer is None:
            continue

        msg = make_msg(
            ProtocolMessageTypes.mempool_items_removed,
            wallet_protocol.MempoolItemsRemoved(removals),
        )
        await peer.send_message(msg)

    total_time = time.monotonic() - start_time

    self.log.log(
        logging.DEBUG if total_time < 0.5 else logging.WARNING,
        f"Broadcasting {total_removals} removed transactions to {len(removals_to_send)} peers took {total_time:.4f}s",
    )
