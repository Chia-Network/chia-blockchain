import asyncio
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Union

from src.full_node.blockchain import Blockchain
from src.full_node.sync_store import SyncStore
from src.protocols import full_node_protocol
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64

log = logging.getLogger(__name__)
OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]


class SyncPeersHandler:
    """
    Handles the sync process by downloading blocks from all connected peers. Requests for blocks
    are sent to alternating peers, with a total max outgoing count for each peer, and a total
    download limit beyond what has already been processed into the blockchain.
    This works both for downloading HeaderBlocks, and downloading FullBlocks.
    Successfully downloaded blocks are saved to the SyncStore, which then are collected by the
    BlockProcessor and added to the chain.
    """

    # Node id -> (block_hash -> time). For each node, the blocks that have been requested,
    # and the time the request was sent.
    current_outbound_sets: Dict[bytes32, Dict[bytes32, uint64]]
    sync_store: SyncStore
    fully_validated_up_to: uint32
    potential_blocks_received: Dict[uint32, asyncio.Event]
    potential_blocks: Dict[uint32, Any]

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
        self.MAX_GAP = 100
        # Only request this many simultaneous blocks per peer
        self.MAX_REQUESTS_PER_PEER = 10
        # If a response for a block request is not received by this timeout, the connection
        # is closed.
        self.BLOCK_RESPONSE_TIMEOUT = 60
        for node_id in peers:
            self.current_outbound_sets[node_id] = {}

        self.potential_blocks_received = self.sync_store.potential_blocks_received
        self.potential_blocks = self.sync_store.potential_blocks

        # No blocks received yet
        for height in range(self.fully_validated_up_to + 1, len(self.header_hashes)):
            self.potential_blocks_received[uint32(height)] = asyncio.Event()

    def done(self) -> bool:
        """
        Returns True iff all required blocks have been downloaded.
        """
        for height in range(self.fully_validated_up_to + 1, len(self.header_hashes)):
            if not self.potential_blocks_received[uint32(height)].is_set():
                # Some blocks have not been received yet
                return False
        # We have received all blocks
        return True

    async def monitor_timeouts(self) -> OutboundMessageGenerator:
        """
        If any of our requests have timed out, disconnects from the node that should
        have responded.
        """
        current_time = time.time()
        remove_node_ids = []
        for node_id, outbound_set in self.current_outbound_sets.items():
            for _, time_requested in outbound_set.items():
                if current_time - time_requested > self.BLOCK_RESPONSE_TIMEOUT:
                    remove_node_ids.append(node_id)
        for rnid in remove_node_ids:
            if rnid in self.current_outbound_sets:
                log.warning(
                    f"Timeout receiving block, closing connection with node {rnid}"
                )
                self.current_outbound_sets.pop(rnid, None)
                yield OutboundMessage(
                    NodeType.FULL_NODE, Message("", None), Delivery.CLOSE, rnid
                )

    async def _add_to_request_sets(self) -> OutboundMessageGenerator:
        """
        Refreshes the pointers of how far we validated and how far we downloaded. Then goes through
        all peers and sends requests to peers for the blocks we have not requested yet, or have
        requested to a peer that did not respond in time or disconnected.
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
            header_hash = self.header_hashes[uint32(height)]
            if header_hash in self.blockchain.headers:
                # Avoids downloading blocks and headers that we already have
                continue

            if self.potential_blocks_received[uint32(height)].is_set():
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
        to_yield: List[Any] = []
        for height in to_send:
            # Find a the next peer with an empty slot. There must be an empty slot: to_send
            # includes up to free_slots things, and current_outbound sets cannot change since there is
            # no await from when free_slots is computed (and thus no context switch).
            while (
                len(outbound_sets_list[index % len(outbound_sets_list)][1])
                == self.MAX_REQUESTS_PER_PEER
            ):
                index += 1

            # Add to peer request
            node_id, request_set = outbound_sets_list[index % len(outbound_sets_list)]
            request_set[self.header_hashes[height]] = uint64(int(time.time()))

            to_yield.append(
                full_node_protocol.RequestBlock(height, self.header_hashes[height])
            )

        for request in to_yield:
            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("request_block", request),
                Delivery.SPECIFIC,
                node_id,
            )

    async def new_block(
        self, block: Union[FullBlock, HeaderBlock]
    ) -> OutboundMessageGenerator:
        """
        A new block was received from a peer.
        """
        header_hash: bytes32 = block.header_hash
        if not isinstance(block, FullBlock):
            return
        if (
            block.height >= len(self.header_hashes)
            or self.header_hashes[block.height] != header_hash
        ):
            # This block is wrong, so ignore
            log.info(
                f"Received header hash that is not in sync path {header_hash} at height {block.height}"
            )
            return

        # save block to DB
        self.potential_blocks[block.height] = block
        if not self.sync_store.get_sync_mode():
            return

        assert block.height in self.potential_blocks_received

        self.potential_blocks_received[block.height].set()

        # remove block from request set
        for node_id, request_set in self.current_outbound_sets.items():
            request_set.pop(header_hash, None)

        # add to request sets
        async for msg in self._add_to_request_sets():
            yield msg

    async def reject_block(
        self, header_hash: bytes32, node_id: bytes32
    ) -> OutboundMessageGenerator:
        """
        A rejection was received from a peer, so we remove this peer and close the connection,
        since we assume this peer cannot help us sync up. All blocks are removed from the
        request set.
        """
        self.current_outbound_sets.pop(node_id, None)
        yield OutboundMessage(NodeType.FULL_NODE, Message("", None), Delivery.CLOSE)

    def new_node_connected(self, node_id: bytes32):
        """
        A new node has connected to us.
        """
        self.current_outbound_sets[node_id] = {}

    def node_disconnected(self, node_id: bytes32):
        """
        A connection with a node has been closed.
        """
        self.current_outbound_sets.pop(node_id, None)
