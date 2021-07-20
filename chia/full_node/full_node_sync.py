import asyncio
import time
from typing import Dict, Any, Tuple, Set, List

from sortedcontainers import SortedDict

from chia.protocols.full_node_protocol import RequestBlocks, RejectBlocks, RespondBlocks
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32


class FullNodeSync:
    full_node: Any

    def __init__(self, full_node):
        self.full_node = full_node
        self.start_height = 0
        self.current_height = 0
        self.target_height = 0
        self.batch_size = 32
        self.request_block_task = None
        self.receive_response_task = None
        self.receive_response_events: Dict[int, asyncio.Event] = {}
        # self.peer_speeds: Dict[bytes32, float] = {}
        self.peer_speeds: SortedDict = SortedDict()  # float, Set[bytes32]
        self.speed_for_peer: Dict[bytes32, float] = {}  # bytes32, float

    async def initialize(self, fork_point_height, target_height, batch_size, summaries, peak_hash):
        self.peak_hash = peak_hash
        self.fork_point_height = fork_point_height
        self.start_height = fork_point_height
        self.current_height = fork_point_height
        self.target_height = target_height
        self.batch_size = batch_size
        self.receive_response_events = {}
        self.received_responses: Dict[int, Tuple[Any, Any, Any]] = {}

        self.advanced_peak = False
        self.summaries = summaries
        self.request_queue: asyncio.Queue = asyncio.Queue()
        self.pending_height = set()

    async def start_sync(self):
        self.sync_end = asyncio.Event()
        self.receive_response_task = asyncio.create_task(self.receive_response())
        self.request_block_task = asyncio.create_task(self.request_block())

        await self.sync_end.wait()
        self.request_block_task.cancel()
        self.receive_response_task.cancel()

    async def receive_response(self):
        max_requests = 5
        counter = 0

        for i in range(self.start_height, self.target_height, self.batch_size):
            if counter > max_requests:
                break

            next_req = min(self.target_height, i + self.batch_size)
            self.pending_height.add((i, next_req))
            await self.request_queue.put((i, next_req))
            self.receive_response_events[i] = asyncio.Event()
            counter += 1

        while True:
            try:
                wait_start = time.time()
                self.full_node.log.debug(f"Waiting for receive_response_event at height: {self.current_height}")
                await self.receive_response_events[self.current_height].wait()
                wait_end = time.time()
                wait_duration = wait_end - wait_start
                self.receive_response_events[self.current_height].clear()
                response, peer, response_time = self.received_responses[self.current_height]
                if response is None:
                    asyncio.create_task(await peer.close())
                    continue
                if isinstance(response, RejectBlocks):
                    asyncio.create_task(await peer.close())
                    continue
                elif isinstance(response, RespondBlocks):
                    try:
                        success, advanced_peak, _ = await self.full_node.receive_block_batch(
                                    response.blocks, peer, None if self.advanced_peak else uint32(self.fork_point_height), self.summaries
                                )
                    except ValueError as e:
                        self.full_node.log.error(f"Error in receiving a block batch: {e}")

                    self.advanced_peak = advanced_peak
                    if not success:
                        # Add this request to queue again
                        next_req = min(self.target_height, self.current_height + self.batch_size)
                        await self.request_queue.put((self.current_height, next_req))
                    else:
                        # Update response time only if successfully added the blocks
                        self.add_to_speed(peer.peer_node_id, response_time)

                        self.current_height = min(self.target_height, self.current_height + self.batch_size)
                        if self.current_height == self.target_height:
                            self.sync_end.set()
                            return
                        counter = 0
                        max_requests = 0
                        for i in range(self.current_height, self.target_height, self.batch_size):
                            if counter > max_requests:
                                break
                            next_req = min(self.target_height, i + self.batch_size)
                            if (i, next_req) not in self.pending_height:
                                self.receive_response_events[i] = asyncio.Event()
                                self.pending_height.add((i, next_req))
                                await self.request_queue.put((i, next_req))
                            counter += 1
            except BaseException as e:
                self.full_node.log.error(f"Error during receive block {e}")

    def add_to_speed(self, peer_id: bytes32, speed: float):
        if speed not in self.peer_speeds:
            self.peer_speeds[speed] = set()

        if peer_id in self.speed_for_peer:
            current_speed = self.speed_for_peer[peer_id]
            self.peer_speeds[current_speed].remove(peer_id)

        self.peer_speeds[speed].add(peer_id)
        self.speed_for_peer[peer_id] = speed

    def remove_from_tracking(self, peer_id, speed):
        self.peer_speeds[speed].remove(peer_id)
        self.speed_for_peer.pop(peer_id)

    def get_fastest_peer(self, request_counter):
        peer_ids: Set[bytes32] = self.full_node.sync_store.get_peers_that_have_peak([self.peak_hash])
        peers_with_peak: List[WSChiaConnection] = [c for c in self.full_node.server.all_connections.values() if c.peer_node_id in peer_ids]
        if len(peers_with_peak) == 0:
           return None

        if request_counter % 10:
            # check peers
            for peer in peers_with_peak:
                if peer.peer_node_id not in self.speed_for_peer:
                    self.add_to_speed(peer.peer_node_id, 0)

        # Get lowest response time peer that is still connected
        for speed, peer_set in self.peer_speeds.copy().items():
            for peer_id in peer_set:
                if peer_id in self.full_node.server.all_connections:
                    if speed == 0:
                        # If response time is not measured yet, set response time to high value so that we don't send multiple request in parallel
                        self.add_to_speed(peer_id, 999)
                    self.full_node.log.info(f"Selected peer {peer_id}, response time was: {speed}")
                    return self.full_node.server.all_connections[peer_id]
                else:
                    self.remove_from_tracking(speed, peer_id)
            if len(peer_set) == 0:
                self.peer_speeds.pop(speed)

        return peers_with_peak[0]

    async def request_block(self):
        request_counter = 0
        while True:
            start_height, end_height = await self.request_queue.get()
            peer = self.get_fastest_peer(request_counter)
            request_counter += 1
            if peer is None:
                self.sync_end.set()
                return
            request = RequestBlocks(uint32(start_height), uint32(end_height), True)
            response = None
            try:
                start_time = time.time()
                response = await peer.request_blocks(request, timeout=60)
                end_time = time.time()
                response_time = end_time - start_time
                self.full_node.log.info(f"Response received for {request}")
            except BaseException as e:
                self.full_node.log.error(f"Exception while trying to get {e}")
                pass
            self.received_responses[start_height] = response, peer, response_time
            self.receive_response_events[start_height].set()
