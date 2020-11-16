import asyncio
import concurrent
import logging
import time
from typing import Optional

from src.full_node.blockchain import Blockchain, ReceiveBlockResult
from src.full_node.sync_store import SyncStore
from src.types.full_block import FullBlock
from src.util.errors import ConsensusError
from src.util.ints import uint32

log = logging.getLogger(__name__)


class SyncBlocksProcessor:
    def __init__(
        self,
        sync_store: SyncStore,
        fork_height: uint32,
        peak_height: uint32,
        blockchain: Blockchain,
    ):
        self.sync_store = sync_store
        self.blockchain = blockchain
        self.fork_height = fork_height
        self.peak_height = peak_height
        self._shut_down = False
        self.BATCH_SIZE = 10
        self.SLEEP_INTERVAL = 10
        self.TOTAL_TIMEOUT = 200

    def shut_down(self):
        self._shut_down = True

    async def process(self) -> None:
        # TODO: run this in a new process so it doesn't have to share CPU time with other things
        for batch_start_height in range(self.fork_height + 1, self.peak_height + 1, self.BATCH_SIZE):
            if self._shut_down:
                return
            total_time_slept = 0
            batch_end_height = min(batch_start_height + self.BATCH_SIZE - 1, self.peak_height)

            while True:
                if self._shut_down:
                    return
                if total_time_slept > self.TOTAL_TIMEOUT:
                    raise TimeoutError("Took too long to fetch blocks")
                awaitables = [
                    (self.sync_store.potential_blocks_received[uint32(height)]).wait()
                    for height in range(batch_start_height, batch_end_height + 1)
                ]
                future = asyncio.gather(*awaitables, return_exceptions=True)
                try:
                    await asyncio.wait_for(future, timeout=self.SLEEP_INTERVAL)
                    break
                # https://github.com/python/cpython/pull/13528
                except (concurrent.futures.TimeoutError, asyncio.TimeoutError):
                    try:
                        await future
                    except asyncio.CancelledError:
                        pass
                    total_time_slept += self.SLEEP_INTERVAL
                    log.info(f"Did not receive desired blocks ({batch_start_height}, {batch_end_height})")

            # Verifies this batch, which we are guaranteed to have (since we broke from the above loop)
            blocks = []
            for height in range(batch_start_height, batch_end_height + 1):
                b: Optional[FullBlock] = self.sync_store.potential_blocks[uint32(height)]
                assert b is not None
                blocks.append(b)

            validation_start_time = time.time()

            if self._shut_down:
                return

            for index, block in enumerate(blocks):
                assert block is not None

                async with self.blockchain.lock:
                    (
                        result,
                        error,
                        fork_height,
                    ) = await self.blockchain.receive_block(block)
                    if result == ReceiveBlockResult.INVALID_BLOCK or result == ReceiveBlockResult.DISCONNECTED_BLOCK:
                        if error is not None:
                            raise ConsensusError(error, block.header_hash)
                        raise RuntimeError(f"Invalid block {block.header_hash}")
                assert self.blockchain.get_peak().height >= block.height
                del self.sync_store.potential_blocks[block.height]
                self.sync_store.add_header_hashes_added(block.height, block.header_hash)

            log.info(
                f"Took {time.time() - validation_start_time} seconds to validate and add blocks "
                f"{batch_start_height} to {batch_end_height + 1}."
            )
