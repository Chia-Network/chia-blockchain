import asyncio
import concurrent
import logging
import time
from typing import Optional, List, Set

from src.full_node.blockchain import Blockchain, ReceiveBlockResult
from src.full_node.header_blockchain import HeaderBlockchain
from src.types.header_block import HeaderBlock
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
        tip_height: uint32,
        validated_headers: Set,
        blockchain: Blockchain,
    ):
        self.sync_store = sync_store
        self.blockchain = blockchain
        self.fork_height = fork_height
        self.tip_height = tip_height
        self.validated_headers = validated_headers
        self._shut_down = False
        self.BATCH_SIZE = 10
        self.SLEEP_INTERVAL = 10
        self.TOTAL_TIMEOUT = 200

    def shut_down(self):
        self._shut_down = True

    async def process(self) -> None:
        header_hashes = self.sync_store.get_potential_hashes()

        # TODO: run this in a new process so it doesn't have to share CPU time with other things
        for batch_start_height in range(
            self.fork_height + 1, self.tip_height + 1, self.BATCH_SIZE
        ):
            total_time_slept = 0
            batch_end_height = min(
                batch_start_height + self.BATCH_SIZE - 1, self.tip_height
            )
            for height in range(batch_start_height, batch_end_height + 1):
                # If we have already added this block to the chain, skip it
                if header_hashes[height] in self.blockchain.headers:
                    batch_start_height = height + 1

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
                except concurrent.futures.TimeoutError:
                    try:
                        await future
                    except asyncio.CancelledError:
                        pass
                    total_time_slept += self.SLEEP_INTERVAL
                    log.info(
                        f"Did not receive desired blocks ({batch_start_height}, {batch_end_height})"
                    )

            # Verifies this batch, which we are guaranteed to have (since we broke from the above loop)
            blocks = []
            for height in range(batch_start_height, batch_end_height + 1):
                b: Optional[FullBlock] = self.sync_store.potential_blocks[
                    uint32(height)
                ]
                assert b is not None
                blocks.append(b)

            validation_start_time = time.time()
            for index, block in enumerate(blocks):
                assert block is not None

                # The block gets permanantly added to the blockchain
                header_validated = block.header_hash in self.validated_headers

                async with self.blockchain.lock:
                    (
                        result,
                        header_block,
                        error_code,
                    ) = await self.blockchain.receive_block(
                        block, header_validated, sync_mode=True
                    )
                    if (
                        result == ReceiveBlockResult.INVALID_BLOCK
                        or result == ReceiveBlockResult.DISCONNECTED_BLOCK
                    ):
                        if error_code is not None:
                            raise ConsensusError(error_code, block.header_hash)
                        raise RuntimeError(f"Invalid block {block.header_hash}")
                assert (
                    max([h.height for h in self.blockchain.get_current_tips()])
                    >= block.height
                )
                del self.sync_store.potential_blocks[block.height]

            log.info(
                f"Took {time.time() - validation_start_time} seconds to validate and add blocks "
                f"{batch_start_height} to {batch_end_height + 1}."
            )


class SyncHeaderBlocksProcessor:
    def __init__(
        self,
        sync_store: SyncStore,
        fork_height: uint32,
        tip_height: uint32,
        header_blockchain: HeaderBlockchain,
    ):
        self.sync_store = sync_store
        self.header_blockchain = header_blockchain
        self.fork_height = fork_height
        self.tip_height = tip_height
        self._shut_down = False
        self.BATCH_SIZE = 10
        self.SLEEP_INTERVAL = 10
        self.TOTAL_TIMEOUT = 200

    def shut_down(self):
        self._shut_down = True

    async def process(self) -> None:
        header_hashes = self.sync_store.get_potential_hashes()

        # TODO: run this in a new process so it doesn't have to share CPU time with other things
        for batch_start_height in range(
            self.fork_height + 1, self.tip_height + 1, self.BATCH_SIZE
        ):
            total_time_slept = 0
            batch_end_height = min(
                batch_start_height + self.BATCH_SIZE - 1, self.tip_height
            )
            for height in range(batch_start_height, batch_end_height + 1):
                # If we have already added this block to the chain, skip it
                if header_hashes[height] in self.header_blockchain.headers:
                    batch_start_height = height + 1

            while True:
                if self._shut_down:
                    return
                if total_time_slept > self.TOTAL_TIMEOUT:
                    raise TimeoutError("Took too long to fetch header blocks")
                awaitables = [
                    (self.sync_store.potential_headers_received[uint32(height)]).wait()
                    for height in range(batch_start_height, batch_end_height + 1)
                ]
                future = asyncio.gather(*awaitables, return_exceptions=True)
                try:
                    await asyncio.wait_for(future, timeout=self.SLEEP_INTERVAL)
                    break
                except concurrent.futures.TimeoutError:
                    try:
                        await future
                    except asyncio.CancelledError:
                        pass
                    total_time_slept += self.SLEEP_INTERVAL
                    log.info(
                        f"Did not receive desired header blocks ({batch_start_height}, {batch_end_height})"
                    )

            # Verifies this batch, which we are guaranteed to have (since we broke from the above loop)
            blocks: List[HeaderBlock] = []
            for height in range(batch_start_height, batch_end_height + 1):
                b: Optional[HeaderBlock] = self.sync_store.potential_headers[
                    uint32(height)
                ]
                assert b is not None
                blocks.append(b)

            validation_start_time = time.time()

            prevalidate_results = await self.header_blockchain.pre_validate_blocks_multiprocessing(
                blocks
            )
            for index, block in enumerate(blocks):
                assert block is not None

                validated, pos = prevalidate_results[index]
                result, error_code = await self.header_blockchain.receive_block(
                    block, validated, pos
                )
                if (
                    result == ReceiveBlockResult.INVALID_BLOCK
                    or result == ReceiveBlockResult.DISCONNECTED_BLOCK
                ):
                    if error_code is not None:
                        raise ConsensusError(error_code, block.header_hash)
                    raise RuntimeError(
                        f"Invalid header block {block.header_hash} {result} {error_code}"
                    )

                assert self.header_blockchain.tip_header_block.height >= block.height
                del self.sync_store.potential_headers[block.height]

            log.info(
                f"Took {time.time() - validation_start_time} seconds to validate and add header blocks "
                f"{batch_start_height} to {batch_end_height + 1}."
            )
