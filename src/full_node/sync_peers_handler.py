from typing import List, Dict, AsyncGenerator
import logging
import time

from src.full_node.sync_store import SyncStore
from src.types.sized_bytes import bytes32
from src.types.full_block import FullBlock
from src.protocols import full_node_protocol
from src.full_node.blockchain import Blockchain
from src.util.ints import uint64, uint32
from src.server.outbound_message import OutboundMessage, Message, Delivery, NodeType


log = logging.getLogger(__name__)
OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]


class SyncPeersHandler:
    # Node id -> (block_hash -> time). For each node, the blocks that have been requested,
    # and the time the request was sent.
    current_outbound_sets: Dict[bytes32, Dict[bytes32, uint64]]
    sync_store: SyncStore
    fully_validated_up_to: uint32

    def __init__(
        self,
        sync_store: SyncStore,
        peers: List[bytes32],
        fork_height: uint32,
        blockchain: Blockchain,
    ):
        self.sync_store = sync_store
        # Set of outbound requests for every full_node peer, and time sent
        self.current_outbound_sets = {}
        self.blockchain = blockchain
        self.header_hashes = self.sync_store.get_potential_hashes()
        self.fully_validated_up_to = fork_height
        # Only request this height greater than our current validation
        self.MAX_GAP = 200
        # Only request this many simultaneous blocks per peer
        self.MAX_REQUESTS_PER_PEER = 5
        # If a response for a block request is not received by this timeout, the connection
        # is closed.
        self.BLOCK_RESPONSE_TIMEOUT = 60
        for node_id in peers:
            self.current_outbound_sets[node_id] = {}

    def done(self) -> bool:
        for height in range(self.fully_validated_up_to + 1, len(self.header_hashes)):
            if not self.sync_store.potential_blocks_received[uint32(height)].is_set():
                # Some blocks have not been received yet
                return False
        # We have received all blocks
        return True

    async def monitor_timeouts(self) -> OutboundMessageGenerator:
        current_time = time.time()
        remove_node_ids = []
        for node_id, outbound_set in self.current_outbound_sets.items():
            for _, time_requested in outbound_set.items():
                if current_time - time_requested > self.BLOCK_RESPONSE_TIMEOUT:
                    remove_node_ids.append(node_id)
        for rnid in remove_node_ids:
            self.current_outbound_sets.pop(node_id, None)
            yield OutboundMessage(
                NodeType.FULL_NODE, Message("", None), Delivery.CLOSE, rnid
            )

    async def _add_to_request_sets(self) -> OutboundMessageGenerator:
        """
        Refreshes the pointers of how far we validated and how far we downloaded. Then goes through
        all peers and sends requests to peers for the blocks we have not requested yet.
        """
        if not self.sync_store.get_sync_mode():
            return

        #     fork       fully validated                           MAX_GAP   target
        # $$$$$X$$$$$$$$$$$$$$$X================----==---=--====---=--X------->
        #      $
        #      $
        #      $$$$$$$$$$$$$$$$$$$$$$$$>
        #                         prev tip

        # Refresh the fully_validated_up_to pointer
        target_height = len(self.header_hashes) - 1
        for height in range(self.fully_validated_up_to + 1, target_height + 1):
            if self.header_hashes[height] in self.blockchain.headers:
                self.fully_validated_up_to = uint32(height)
            else:
                break

        # Number of request slots
        free_slots = 0
        for node_id, request_set in self.current_outbound_sets.items():
            free_slots += self.MAX_REQUESTS_PER_PEER - len(request_set)

        to_send: List[uint32] = []
        # Finds a block height
        for height in range(
            self.fully_validated_up_to + 1,
            min(self.fully_validated_up_to + self.MAX_GAP + 1, target_height + 1),
        ):
            if len(to_send) == free_slots:
                # No more slots to send to any peers
                break
            if self.sync_store.potential_blocks_received[uint32(height)].is_set():
                continue
            already_requested = False
            # If we have asked for this block to some peer, we don't want to ask for it again yet.
            for node_id_2, request_set_2 in self.current_outbound_sets.items():
                if self.header_hashes[height] in request_set_2:
                    already_requested = True
                    break
            if already_requested:
                continue

            to_send.append(uint32(height))

        # Sort by the peers that have the least outgoing messages
        outbound_sets_list = list(self.current_outbound_sets.items())
        outbound_sets_list.sort(key=lambda x: len(x[1]))
        index = 0
        for height in to_send:
            # Find a the next peer with an empty slot
            while (
                len(outbound_sets_list[index % len(outbound_sets_list)][1])
                == self.MAX_REQUESTS_PER_PEER
            ):
                index += 1

            # Add to peer request
            node_id, request_set = outbound_sets_list[index % len(outbound_sets_list)]
            request_set[self.header_hashes[height]] = uint64(int(time.time()))

            # yields the request
            request_sync = full_node_protocol.RequestBlock(
                height, self.header_hashes[height]
            )
            log.info(f"Yielding request for {height}")
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("request_block", request_sync),
                Delivery.SPECIFIC,
                node_id,
            )

    async def new_block(self, block: FullBlock) -> OutboundMessageGenerator:
        header_hash: bytes32 = block.get_hash()
        # This block is wrong, so ignore
        if (
            block.height >= len(self.header_hashes)
            or self.header_hashes[block.height] != header_hash
        ):
            log.info(
                f"Received header hash that is not in sync path {header_hash} at height {block.height}"
            )
            return

        # save block to DB
        await self.sync_store.add_potential_block(block)
        if not self.sync_store.get_sync_mode():
            return

        assert block.height in self.sync_store.potential_blocks_received

        self.sync_store.get_potential_blocks_received(block.height).set()

        # remove block from request set
        for node_id, request_set in self.current_outbound_sets.items():
            request_set.pop(header_hash, None)

        # add to request sets
        async for msg in self._add_to_request_sets():
            yield msg

    async def reject_block(
        self, header_hash: bytes32, node_id: bytes32
    ) -> OutboundMessageGenerator:
        # Remove all blocks from request set
        self.current_outbound_sets.pop(node_id, None)
        yield OutboundMessage(NodeType.FULL_NODE, Message("", None), Delivery.CLOSE)

    async def new_node_connected(self, node_id: bytes32) -> OutboundMessageGenerator:
        self.current_outbound_sets[node_id] = {}
        # add to request sets
        async for msg in self._add_to_request_sets():
            yield msg

    def node_disconnected(self, node_id: bytes32):
        self.current_outbound_sets.pop(node_id, None)
