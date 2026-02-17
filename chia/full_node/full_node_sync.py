from __future__ import annotations

import asyncio
import copy
import random
import time
import traceback
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any

from chia_rs import BlockRecord, FullBlock, SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint128

from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.blockchain import BlockchainMutexPriority, StateChangeSummary
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.hint_management import get_hints_and_subscription_coin_ids
from chia.protocols import full_node_protocol
from chia.protocols.full_node_protocol import RequestBlocks, RespondBlock, RespondBlocks
from chia.protocols.outbound_message import NodeType
from chia.protocols.protocol_timing import CONSENSUS_ERROR_BAN_SECONDS
from chia.server.ws_connection import WSChiaConnection
from chia.types.validation_state import ValidationState
from chia.util.network import is_localhost
from chia.util.safe_cancel_task import cancel_task_safe
from chia.util.task_referencer import create_referenced_task

if TYPE_CHECKING:
    from chia.full_node.full_node import FullNode


async def short_sync_batch(
    self: FullNode, peer: WSChiaConnection, start_height: uint32, target_height: uint32
) -> bool:
    """
    Tries to sync to a chain which is not too far in the future, by downloading batches of blocks. If the first
    block that we download is not connected to our chain, we return False and do an expensive long sync instead.
    Long sync is not preferred because it requires downloading and validating a weight proof.

    Args:
        peer: peer to sync from
        start_height: height that we should start downloading at. (Our peak is higher)
        target_height: target to sync to

    Returns:
        False if the fork point was not found, and we need to do a long sync. True otherwise.

    """
    # Don't trigger multiple batch syncs to the same peer

    if self.sync_store.is_backtrack_syncing(node_id=peer.peer_node_id):
        return True  # Don't batch sync, we are already in progress of a backtrack sync
    if peer.peer_node_id in self.sync_store.batch_syncing:
        return True  # Don't trigger a long sync
    self.sync_store.batch_syncing.add(peer.peer_node_id)

    self.log.info(f"Starting batch short sync from {start_height} to height {target_height}")
    if start_height > 0:
        first = await peer.call_api(
            FullNodeAPI.request_block, full_node_protocol.RequestBlock(uint32(start_height), False)
        )
        if first is None or not isinstance(first, full_node_protocol.RespondBlock):
            self.sync_store.batch_syncing.remove(peer.peer_node_id)
            self.log.error(f"Error short batch syncing, could not fetch block at height {start_height}")
            return False
        hash = self.blockchain.height_to_hash(first.block.height - 1)
        assert hash is not None
        if hash != first.block.prev_header_hash:
            self.log.info("Batch syncing stopped, this is a deep chain")
            self.sync_store.batch_syncing.remove(peer.peer_node_id)
            # First sb not connected to our blockchain, do a long sync instead
            return False

    batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS
    for task in self._segment_task_list[:]:
        if task.done():
            self._segment_task_list.remove(task)
        else:
            cancel_task_safe(task=task, log=self.log)

    try:
        peer_info = peer.get_peer_logging()
        if start_height > 0:
            fork_hash = self.blockchain.height_to_hash(uint32(start_height - 1))
        else:
            fork_hash = self.constants.GENESIS_CHALLENGE
        assert fork_hash
        fork_info = ForkInfo(start_height - 1, start_height - 1, fork_hash)
        blockchain = AugmentedBlockchain(self.blockchain)
        for height in range(start_height, target_height, batch_size):
            end_height = min(target_height, height + batch_size)
            request = RequestBlocks(uint32(height), uint32(end_height), True)
            response = await peer.call_api(FullNodeAPI.request_blocks, request)
            if not response:
                raise ValueError(f"Error short batch syncing, invalid/no response for {height}-{end_height}")
            async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
                state_change_summary: StateChangeSummary | None
                prev_b = None
                if response.blocks[0].height > 0:
                    prev_b = await self.blockchain.get_block_record_from_db(response.blocks[0].prev_header_hash)
                    assert prev_b is not None
                new_slot = len(response.blocks[0].finished_sub_slots) > 0
                ssi, diff = get_next_sub_slot_iters_and_difficulty(
                    self.constants, new_slot, prev_b, self.blockchain
                )
                vs = ValidationState(ssi, diff, None)
                success, state_change_summary = await self.add_block_batch(
                    response.blocks, peer_info, fork_info, vs, blockchain
                )
                if not success:
                    raise ValueError(f"Error short batch syncing, failed to validate blocks {height}-{end_height}")
                if state_change_summary is not None:
                    try:
                        peak_fb: FullBlock | None = await self.blockchain.get_full_peak()
                        assert peak_fb is not None
                        ppp_result = await self.peak_post_processing(
                            peak_fb,
                            state_change_summary,
                            peer,
                        )
                    except Exception:
                        # Still do post processing after cancel (or exception)
                        peak_fb = await self.blockchain.get_full_peak()
                        assert peak_fb is not None
                        await self.peak_post_processing(peak_fb, state_change_summary, peer)
                        raise
                    finally:
                        self.log.info(f"Added blocks {height}-{end_height}")
            if state_change_summary is not None and peak_fb is not None:
                # Call outside of priority_mutex to encourage concurrency
                await self.peak_post_processing_2(peak_fb, peer, state_change_summary, ppp_result)
    finally:
        self.sync_store.batch_syncing.remove(peer.peer_node_id)
    return True


async def short_sync_backtrack(
    self: FullNode,
    peer: WSChiaConnection,
    peak_height: uint32,
    target_height: uint32,
    target_unf_hash: bytes32,
) -> bool:
    """
    Performs a backtrack sync, where blocks are downloaded one at a time from newest to oldest. If we do not
    find the fork point 5 deeper than our peak, we return False and do a long sync instead.

    Args:
        peer: peer to sync from
        peak_height: height of our peak
        target_height: target height
        target_unf_hash: partial hash of the unfinished block of the target

    Returns:
        True iff we found the fork point, and we do not need to long sync.
    """
    try:
        self.sync_store.increment_backtrack_syncing(node_id=peer.peer_node_id)

        unfinished_block = self.full_node_store.get_unfinished_block(target_unf_hash)
        curr_height: int = target_height
        found_fork_point = False
        blocks = []
        while curr_height > peak_height - 5:
            # If we already have the unfinished block, don't fetch the transactions. In the normal case, we will
            # already have the unfinished block, from when it was broadcast, so we just need to download the header,
            # but not the transactions
            fetch_tx: bool = unfinished_block is None or curr_height != target_height
            curr = await peer.call_api(
                FullNodeAPI.request_block, full_node_protocol.RequestBlock(uint32(curr_height), fetch_tx)
            )
            if curr is None:
                raise ValueError(f"Failed to fetch block {curr_height} from {peer.get_peer_logging()}, timed out")
            if curr is None or not isinstance(curr, full_node_protocol.RespondBlock):
                raise ValueError(
                    f"Failed to fetch block {curr_height} from {peer.get_peer_logging()}, wrong type {type(curr)}"
                )
            blocks.append(curr.block)
            if curr_height == 0:
                found_fork_point = True
                break
            hash_at_height = self.blockchain.height_to_hash(curr.block.height - 1)
            if hash_at_height is not None and hash_at_height == curr.block.prev_header_hash:
                found_fork_point = True
                break
            curr_height -= 1
        if found_fork_point:
            first_block = blocks[-1]  # blocks are reveresd this is the lowest block to add
            # we create the fork_info and pass it here so it would be updated on each call to add_block
            fork_info = ForkInfo(first_block.height - 1, first_block.height - 1, first_block.prev_header_hash)
            for block in reversed(blocks):
                # when syncing, we won't share any signatures with the
                # mempool, so there's no need to pass in the BLS cache.
                await self.add_block(block, peer, fork_info=fork_info)
    except (asyncio.CancelledError, Exception):
        self.sync_store.decrement_backtrack_syncing(node_id=peer.peer_node_id)
        raise

    self.sync_store.decrement_backtrack_syncing(node_id=peer.peer_node_id)
    return found_fork_point


async def _refresh_ui_connections(self: FullNode, sleep_before: float = 0) -> None:
    if sleep_before > 0:
        await asyncio.sleep(sleep_before)
    self._state_changed("peer_changed_peak")


async def new_peak(self: FullNode, request: full_node_protocol.NewPeak, peer: WSChiaConnection) -> None:
    """
    We have received a notification of a new peak from a peer. This happens either when we have just connected,
    or when the peer has updated their peak.

    Args:
        request: information about the new peak
        peer: peer that sent the message

    """

    try:
        seen_header_hash = self.sync_store.seen_header_hash(request.header_hash)
        # Updates heights in the UI. Sleeps 1.5s before, so other peers have time to update their peaks as well.
        # Limit to 3 refreshes.
        if not seen_header_hash and len(self._ui_tasks) < 3:
            self._ui_tasks.add(create_referenced_task(self._refresh_ui_connections(1.5)))
        # Prune completed connect tasks
        self._ui_tasks = set(filter(lambda t: not t.done(), self._ui_tasks))
    except Exception as e:
        self.log.warning(f"Exception UI refresh task: {e}")

    # Store this peak/peer combination in case we want to sync to it, and to keep track of peers
    self.sync_store.peer_has_block(request.header_hash, peer.peer_node_id, request.weight, request.height, True)

    if self.blockchain.contains_block(request.header_hash, request.height):
        return None

    # Not interested in less heavy peaks
    peak: BlockRecord | None = self.blockchain.get_peak()
    curr_peak_height = uint32(0) if peak is None else peak.height
    if peak is not None and peak.weight > request.weight:
        return None

    if self.sync_store.get_sync_mode():
        # If peer connects while we are syncing, check if they have the block we are syncing towards
        target_peak = self.sync_store.target_peak
        if target_peak is not None and request.header_hash != target_peak.header_hash:
            peak_peers: set[bytes32] = self.sync_store.get_peers_that_have_peak([target_peak.header_hash])
            # Don't ask if we already know this peer has the peak
            if peer.peer_node_id not in peak_peers:
                target_peak_response: RespondBlock | None = await peer.call_api(
                    FullNodeAPI.request_block,
                    full_node_protocol.RequestBlock(target_peak.height, False),
                    timeout=10,
                )
                if (
                    target_peak_response is not None
                    and isinstance(target_peak_response, RespondBlock)
                    and target_peak_response.block.header_hash == target_peak.header_hash
                ):
                    self.sync_store.peer_has_block(
                        target_peak.header_hash,
                        peer.peer_node_id,
                        target_peak_response.block.weight,
                        target_peak.height,
                        False,
                    )
    else:
        if (
            curr_peak_height <= request.height
            and request.height <= curr_peak_height + self.config["short_sync_blocks_behind_threshold"]
        ):
            # This is the normal case of receiving the next block
            if await self.short_sync_backtrack(
                peer, curr_peak_height, request.height, request.unfinished_reward_block_hash
            ):
                return None

        if request.height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
            # This is the case of syncing up more than a few blocks, at the start of the chain
            self.log.debug("Doing batch sync, no backup")
            await self.short_sync_batch(peer, uint32(0), request.height)
            return None

        if (
            curr_peak_height <= request.height
            and request.height < curr_peak_height + self.config["sync_blocks_behind_threshold"]
        ):
            # This case of being behind but not by so much
            if await self.short_sync_batch(peer, uint32(max(curr_peak_height - 6, 0)), request.height):
                return None

        # Clean up task reference list (used to prevent gc from killing running tasks)
        for oldtask in self._sync_task_list[:]:
            if oldtask.done():
                self._sync_task_list.remove(oldtask)

        # This is the either the case where we were not able to sync successfully (for example, due to the fork
        # point being in the past), or we are very far behind. Performs a long sync.
        # Multiple tasks may be created here. If we don't save all handles, a task could enter a sync object
        # and be cleaned up by the GC, corrupting the sync object and possibly not allowing anything else in.
        self._sync_task_list.append(create_referenced_task(self._sync()))


async def _sync(self: FullNode) -> None:
    """
    Performs a full sync of the blockchain up to the peak.
        - Wait a few seconds for peers to send us their peaks
        - Select the heaviest peak, and request a weight proof from a peer with that peak
        - Validate the weight proof, and disconnect from the peer if invalid
        - Find the fork point to see where to start downloading blocks
        - Download blocks in batch (and in parallel) and verify them one at a time
        - Disconnect peers that provide invalid blocks or don't have the blocks
    """
    from chia.full_node.check_fork_next_block import check_fork_next_block

    # Ensure we are only syncing once and not double calling this method
    fork_point: uint32 | None = None
    if self.sync_store.get_sync_mode():
        return None

    if self.sync_store.get_long_sync():
        self.log.debug("already in long sync")
        return None

    self.sync_store.set_long_sync(True)
    self.log.debug("long sync started")
    try:
        self.log.info("Starting to perform sync.")

        # Wait until we have 3 peaks or up to a max of 30 seconds
        max_iterations = int(self.config.get("max_sync_wait", 30)) * 10

        self.log.info(f"Waiting to receive peaks from peers. (timeout: {max_iterations / 10}s)")
        peaks = []
        for i in range(max_iterations):
            peaks = [peak.header_hash for peak in self.sync_store.get_peak_of_each_peer().values()]
            if len(self.sync_store.get_peers_that_have_peak(peaks)) < 3:
                if self._shut_down:
                    return None
                await asyncio.sleep(0.1)
                continue
            break

        self.log.info(f"Collected a total of {len(peaks)} peaks.")

        # Based on responses from peers about the current peaks, see which peak is the heaviest
        # (similar to longest chain rule).
        target_peak = self.sync_store.get_heaviest_peak()

        if target_peak is None:
            raise RuntimeError("Not performing sync, no peaks collected")

        self.sync_store.target_peak = target_peak

        self.log.info(f"Selected peak {target_peak}")
        # Check which peers are updated to this height

        peers = self.server.get_connections(NodeType.FULL_NODE)
        coroutines = []
        for peer in peers:
            coroutines.append(
                peer.call_api(
                    FullNodeAPI.request_block,
                    full_node_protocol.RequestBlock(target_peak.height, True),
                    timeout=10,
                )
            )
        for i, target_peak_response in enumerate(await asyncio.gather(*coroutines)):
            if (
                target_peak_response is not None
                and isinstance(target_peak_response, RespondBlock)
                and target_peak_response.block.header_hash == target_peak.header_hash
            ):
                self.sync_store.peer_has_block(
                    target_peak.header_hash, peers[i].peer_node_id, target_peak.weight, target_peak.height, False
                )
        # TODO: disconnect from peer which gave us the heaviest_peak, if nobody has the peak
        fork_point, summaries = await self.request_validate_wp(
            target_peak.header_hash, target_peak.height, target_peak.weight
        )
        # Ensures that the fork point does not change
        async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
            await self.blockchain.warmup(fork_point)
            fork_point = await check_fork_next_block(
                self.blockchain,
                fork_point,
                self.get_peers_with_peak(target_peak.header_hash),
                node_next_block_check,
            )
            await self.sync_from_fork_point(fork_point, target_peak.height, target_peak.header_hash, summaries)
    except asyncio.CancelledError:
        self.log.warning("Syncing failed, CancelledError")
    except Exception as e:
        tb = traceback.format_exc()
        self.log.error(f"Error with syncing: {type(e)}{tb}")
    finally:
        if self._shut_down:
            return None
        await self._finish_sync(fork_point)


async def request_validate_wp(
    self: FullNode, peak_header_hash: bytes32, peak_height: uint32, peak_weight: uint128
) -> tuple[uint32, list[SubEpochSummary]]:
    if self.weight_proof_handler is None:
        raise RuntimeError("Weight proof handler is None")
    peers_with_peak = self.get_peers_with_peak(peak_header_hash)
    # Request weight proof from a random peer
    peers_with_peak_len = len(peers_with_peak)
    self.log.info(f"Total of {peers_with_peak_len} peers with peak {peak_height}")
    # We can't choose from an empty sequence
    if peers_with_peak_len == 0:
        raise RuntimeError(f"Not performing sync, no peers with peak {peak_height}")
    weight_proof_peer: WSChiaConnection = random.choice(peers_with_peak)
    self.log.info(
        f"Requesting weight proof from peer {weight_proof_peer.peer_info.host} up to height {peak_height}"
    )
    cur_peak: BlockRecord | None = self.blockchain.get_peak()
    if cur_peak is not None and peak_weight <= cur_peak.weight:
        raise ValueError("Not performing sync, already caught up.")
    wp_timeout = 360
    if "weight_proof_timeout" in self.config:
        wp_timeout = self.config["weight_proof_timeout"]
    self.log.debug(f"weight proof timeout is {wp_timeout} sec")
    request = full_node_protocol.RequestProofOfWeight(peak_height, peak_header_hash)
    response = await weight_proof_peer.call_api(FullNodeAPI.request_proof_of_weight, request, timeout=wp_timeout)
    # Disconnect from this peer, because they have not behaved properly
    if response is None or not isinstance(response, full_node_protocol.RespondProofOfWeight):
        await weight_proof_peer.close(CONSENSUS_ERROR_BAN_SECONDS)
        raise RuntimeError(f"Weight proof did not arrive in time from peer: {weight_proof_peer.peer_info.host}")
    if response.wp.recent_chain_data[-1].reward_chain_block.height != peak_height:
        await weight_proof_peer.close(CONSENSUS_ERROR_BAN_SECONDS)
        raise RuntimeError(f"Weight proof had the wrong height: {weight_proof_peer.peer_info.host}")
    if response.wp.recent_chain_data[-1].reward_chain_block.weight != peak_weight:
        await weight_proof_peer.close(CONSENSUS_ERROR_BAN_SECONDS)
        raise RuntimeError(f"Weight proof had the wrong weight: {weight_proof_peer.peer_info.host}")
    if self.in_bad_peak_cache(response.wp):
        raise ValueError("Weight proof failed bad peak cache validation")
    # dont sync to wp if local peak is heavier,
    # dont ban peer, we asked for this peak
    current_peak = self.blockchain.get_peak()
    if current_peak is not None:
        if response.wp.recent_chain_data[-1].reward_chain_block.weight <= current_peak.weight:
            raise RuntimeError(
                f"current peak is heavier than Weight proof peek: {weight_proof_peer.peer_info.host}"
            )
    try:
        validated, fork_point, summaries = await self.weight_proof_handler.validate_weight_proof(response.wp)
    except Exception as e:
        await weight_proof_peer.close(CONSENSUS_ERROR_BAN_SECONDS)
        raise ValueError(f"Weight proof validation threw an error {e}")
    if not validated:
        await weight_proof_peer.close(CONSENSUS_ERROR_BAN_SECONDS)
        raise ValueError("Weight proof validation failed")
    self.log.info(f"Re-checked peers: total of {len(peers_with_peak)} peers with peak {peak_height}")
    self.sync_store.set_sync_mode(True)
    self._state_changed("sync_mode")
    return fork_point, summaries


async def sync_from_fork_point(
    self: FullNode,
    fork_point_height: uint32,
    target_peak_sb_height: uint32,
    peak_hash: bytes32,
    summaries: list[SubEpochSummary],
) -> None:
    self.log.info(f"Start syncing from fork point at {fork_point_height} up to {target_peak_sb_height}")
    batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS
    counter = 0
    if fork_point_height != 0:
        # warmup the cache
        curr = self.blockchain.height_to_block_record(fork_point_height)
        while (
            curr.sub_epoch_summary_included is None
            or counter < 3 * self.constants.MAX_SUB_SLOT_BLOCKS + self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK + 3
        ):
            res = await self.blockchain.get_block_record_from_db(curr.prev_hash)
            if res is None:
                break
            curr = res
            self.blockchain.add_block_record(curr)
            counter += 1

    # normally "fork_point" or "fork_height" refers to the first common
    # block between the main chain and the fork. Here "fork_point_height"
    # seems to refer to the first diverging block
    # in case we're validating a reorg fork (i.e. not extending the
    # main chain), we need to record the coin set from that fork in
    # fork_info. Otherwise validation is very expensive, especially
    # for deep reorgs
    if fork_point_height > 0:
        fork_hash = self.blockchain.height_to_hash(uint32(fork_point_height - 1))
        assert fork_hash is not None
    else:
        fork_hash = self.constants.GENESIS_CHALLENGE
    fork_info = ForkInfo(fork_point_height - 1, fork_point_height - 1, fork_hash)

    if fork_point_height == 0:
        ssi = self.constants.SUB_SLOT_ITERS_STARTING
        diff = self.constants.DIFFICULTY_STARTING
        prev_ses_block = None
    else:
        prev_b_hash = self.blockchain.height_to_hash(fork_point_height)
        assert prev_b_hash is not None
        prev_b = await self.blockchain.get_full_block(prev_b_hash)
        assert prev_b is not None
        ssi, diff, prev_ses_block = await self.get_sub_slot_iters_difficulty_ses_block(prev_b, None, None)

    # we need an augmented blockchain to validate blocks in batches. The
    # batch must be treated as if it's part of the chain to validate the
    # blocks in it. We also need them to keep appearing as if they're part
    # of the chain when pipelining the validation of blocks. We start
    # validating the next batch while still adding the first batch to the
    # chain.
    blockchain = AugmentedBlockchain(self.blockchain)
    peers_with_peak: list[WSChiaConnection] = self.get_peers_with_peak(peak_hash)

    async def fetch_blocks(output_queue: asyncio.Queue[tuple[WSChiaConnection, list[FullBlock]] | None]) -> None:
        # the rate limit for respond_blocks is 100 messages / 60 seconds.
        # But the limit is scaled to 30% for outbound messages, so that's 30
        # messages per 60 seconds.
        # That's 2 seconds per request.
        seconds_per_request = 2
        start_height, end_height = 0, 0

        # the timestamp of when the next request_block message is allowed to
        # be sent. It's initialized to the current time, and bumped by the
        # seconds_per_request every time we send a request. This ensures we
        # won't exceed the 100 requests / 60 seconds rate limit.
        # Whichever peer has the lowest timestamp is the one we request
        # from. peers that take more than 5 seconds to respond are pushed to
        # the end of the queue, to be less likely to request from.

        # This should be cleaned up to not be a hard coded value, and maybe
        # allow higher request rates (and align the request_blocks and
        # respond_blocks rate limits).
        now = time.monotonic()
        new_peers_with_peak: list[tuple[WSChiaConnection, float]] = [(c, now) for c in peers_with_peak[:]]
        self.log.info(f"peers with peak: {len(new_peers_with_peak)}")
        random.shuffle(new_peers_with_peak)
        try:
            # block request ranges are *inclusive*, this requires some
            # gymnastics of this range (+1 to make it exclusive, like normal
            # ranges) and then -1 when forming the request message
            for start_height in range(fork_point_height, target_peak_sb_height + 1, batch_size):
                end_height = min(target_peak_sb_height, start_height + batch_size - 1)
                request = RequestBlocks(uint32(start_height), uint32(end_height), True)
                new_peers_with_peak.sort(key=lambda pair: pair[1])
                fetched = False
                for idx, (peer, timestamp) in enumerate(new_peers_with_peak):
                    if peer.closed:
                        continue

                    start = time.monotonic()
                    if start < timestamp:
                        # rate limit ourselves, since we sent a message to
                        # this peer too recently
                        await asyncio.sleep(timestamp - start)
                        start = time.monotonic()

                    # update the timestamp, now that we're sending a request
                    # it's OK for the timestamp to fall behind wall-clock
                    # time. It just means we're allowed to send more
                    # requests to catch up
                    if is_localhost(peer.peer_info.host):
                        # we don't apply rate limits to localhost, and our
                        # tests depend on it
                        bump = 0.1
                    else:
                        bump = seconds_per_request

                    new_peers_with_peak[idx] = (
                        new_peers_with_peak[idx][0],
                        new_peers_with_peak[idx][1] + bump,
                    )
                    # the fewer peers we have, the more willing we should be
                    # to wait for them.
                    timeout = int(30 + 30 / len(new_peers_with_peak))
                    response = await peer.call_api(FullNodeAPI.request_blocks, request, timeout=timeout)
                    end = time.monotonic()
                    if response is None:
                        self.log.info(f"peer timed out after {end - start:.1f} s")
                        await peer.close()
                    elif isinstance(response, RespondBlocks):
                        if end - start > 5:
                            self.log.info(f"peer took {end - start:.1f} s to respond to request_blocks")
                            # this isn't a great peer, reduce its priority
                            # to prefer any peers that had to wait for it.
                            # By setting the next allowed timestamp to now,
                            # means that any other peer that has waited for
                            # this will have its next allowed timestamp in
                            # the passed, and be preferred multiple times
                            # over this peer.
                            new_peers_with_peak[idx] = (
                                new_peers_with_peak[idx][0],
                                end,
                            )
                        start = time.monotonic()
                        await output_queue.put((peer, response.blocks))
                        end = time.monotonic()
                        if end - start > 1:
                            self.log.info(
                                f"sync pipeline back-pressure. stalled {end - start:0.2f} "
                                "seconds on prevalidate block"
                            )
                        fetched = True
                        break
                if fetched is False:
                    self.log.error(f"failed fetching {start_height} to {end_height} from peers")
                    return
                if self.sync_store.peers_changed.is_set():
                    existing_peers = {id(c): timestamp for c, timestamp in new_peers_with_peak}
                    peers = self.get_peers_with_peak(peak_hash)
                    new_peers_with_peak = [(c, existing_peers.get(id(c), end)) for c in peers]
                    random.shuffle(new_peers_with_peak)
                    self.sync_store.peers_changed.clear()
                    self.log.info(f"peers with peak: {len(new_peers_with_peak)}")
        except Exception as e:
            self.log.error(f"Exception fetching {start_height} to {end_height} from peer {e}")
        finally:
            # finished signal with None
            await output_queue.put(None)

    async def validate_blocks(
        input_queue: asyncio.Queue[tuple[WSChiaConnection, list[FullBlock]] | None],
        output_queue: asyncio.Queue[
            tuple[WSChiaConnection, ValidationState, list[Awaitable[PreValidationResult]], list[FullBlock]] | None
        ],
    ) -> None:
        nonlocal blockchain
        nonlocal fork_info
        first_batch = True

        vs = ValidationState(ssi, diff, prev_ses_block)

        try:
            while True:
                res: tuple[WSChiaConnection, list[FullBlock]] | None = await input_queue.get()
                if res is None:
                    self.log.debug("done fetching blocks")
                    return None
                peer, blocks = res

                # skip_blocks is only relevant at the start of the sync,
                # to skip blocks we already have in the database (and have
                # been validated). Once we start validating blocks, we
                # shouldn't be skipping any.
                blocks_to_validate = await self.skip_blocks(blockchain, blocks, fork_info, vs)
                assert first_batch or len(blocks_to_validate) == len(blocks)
                next_validation_state = copy.copy(vs)

                if len(blocks_to_validate) == 0:
                    continue

                first_batch = False

                futures: list[Awaitable[PreValidationResult]] = []
                for block in blocks_to_validate:
                    futures.extend(
                        await self.prevalidate_blocks(
                            blockchain,
                            [block],
                            vs,
                            summaries,
                        )
                    )
                start = time.monotonic()
                await output_queue.put((peer, next_validation_state, list(futures), blocks_to_validate))
                end = time.monotonic()
                if end - start > 1:
                    self.log.info(f"sync pipeline back-pressure. stalled {end - start:0.2f} seconds on add_block()")
        except Exception:
            self.log.exception("Exception validating")
        finally:
            # finished signal with None
            await output_queue.put(None)

    async def ingest_blocks(
        input_queue: asyncio.Queue[
            tuple[WSChiaConnection, ValidationState, list[Awaitable[PreValidationResult]], list[FullBlock]] | None
        ],
    ) -> None:
        nonlocal fork_info
        block_rate = 0.0
        block_rate_time = time.monotonic()
        block_rate_height = -1
        while True:
            res = await input_queue.get()
            if res is None:
                self.log.debug("done validating blocks")
                return None
            peer, vs, futures, blocks = res
            start_height = blocks[0].height
            end_height = blocks[-1].height

            if block_rate_height == -1:
                block_rate_height = start_height

            pre_validation_results = list(await asyncio.gather(*futures))
            # The ValidationState object (vs) is an in-out parameter. the add_block_batch()
            # call will update it
            state_change_summary, err = await self.add_prevalidated_blocks(
                blockchain,
                blocks,
                pre_validation_results,
                fork_info,
                peer.peer_info,
                vs,
            )
            if err is not None:
                await peer.close(CONSENSUS_ERROR_BAN_SECONDS)
                raise ValueError(f"Failed to validate block batch {start_height} to {end_height}: {err}")
            if end_height - block_rate_height > 100:
                now = time.monotonic()
                block_rate = (end_height - block_rate_height) / (now - block_rate_time)
                block_rate_time = now
                block_rate_height = end_height

            self.log.info(
                f"Added blocks {start_height} to {end_height} "
                f"({block_rate:.3g} blocks/s) (from: {peer.peer_info.ip})"
            )
            peak: BlockRecord | None = self.blockchain.get_peak()
            if state_change_summary is not None:
                assert peak is not None
                # Hints must be added to the DB. The other post-processing tasks are not required when syncing
                hints_to_add, _ = get_hints_and_subscription_coin_ids(
                    state_change_summary,
                    self.subscriptions.has_coin_subscription,
                    self.subscriptions.has_puzzle_subscription,
                )
                await self.hint_store.add_hints(hints_to_add)
            # Note that end_height is not necessarily the peak at this
            # point. In case of a re-org, it may even be significantly
            # higher than _peak_height, and still not be the peak.
            # clean_block_record() will not necessarily honor this cut-off
            # height, in that case.
            self.blockchain.clean_block_record(end_height - self.constants.BLOCKS_CACHE_SIZE)

    block_queue: asyncio.Queue[tuple[WSChiaConnection, list[FullBlock]] | None] = asyncio.Queue(maxsize=10)
    validation_queue: asyncio.Queue[
        tuple[WSChiaConnection, ValidationState, list[Awaitable[PreValidationResult]], list[FullBlock]] | None
    ] = asyncio.Queue(maxsize=10)

    fetch_task = create_referenced_task(fetch_blocks(block_queue))
    validate_task = create_referenced_task(validate_blocks(block_queue, validation_queue))
    ingest_task = create_referenced_task(ingest_blocks(validation_queue))
    try:
        await asyncio.gather(fetch_task, validate_task, ingest_task)
    except Exception:
        self.log.exception("sync from fork point failed")
    finally:
        cancel_task_safe(validate_task, self.log)
        cancel_task_safe(fetch_task)
        cancel_task_safe(ingest_task)

        # we still need to await all the pending futures of the
        # prevalidation steps posted to the thread pool
        while not validation_queue.empty():
            result = validation_queue.get_nowait()
            if result is None:
                continue

            _, _, futures, _ = result
            await asyncio.gather(*futures)


def get_peers_with_peak(self: FullNode, peak_hash: bytes32) -> list[WSChiaConnection]:
    peer_ids: set[bytes32] = self.sync_store.get_peers_that_have_peak([peak_hash])
    if len(peer_ids) == 0:
        self.log.warning(f"Not syncing, no peers with header_hash {peak_hash} ")
        return []
    return [c for c in self.server.all_connections.values() if c.peer_node_id in peer_ids]


async def _finish_sync(self: FullNode, fork_point: uint32 | None) -> None:
    """
    Finalize sync by setting sync mode to False, clearing all sync information, and adding any final
    blocks that we have finalized recently.
    """
    self.log.info("long sync done")
    self.sync_store.set_long_sync(False)
    self.sync_store.set_sync_mode(False)
    self._state_changed("sync_mode")
    if self._server is None:
        return None

    async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
        peak: BlockRecord | None = self.blockchain.get_peak()
        peak_fb: FullBlock | None = await self.blockchain.get_full_peak()
        if peak_fb is not None:
            if fork_point is None:
                fork_point = uint32(max(peak_fb.height - 1, 0))
            assert peak is not None
            state_change_summary = StateChangeSummary(peak, fork_point, [], [], [], [])
            ppp_result = await self.peak_post_processing(peak_fb, state_change_summary, None)

    if peak_fb is not None:
        # Call outside of priority_mutex to encourage concurrency
        await self.peak_post_processing_2(peak_fb, None, state_change_summary, ppp_result)

    if peak is not None and self.weight_proof_handler is not None:
        await self.weight_proof_handler.get_proof_of_weight(peak.header_hash)
        self._state_changed("block")


async def node_next_block_check(
    peer: WSChiaConnection, potential_peek: uint32, blockchain: BlockchainInterface
) -> bool:
    block_response: Any | None = await peer.call_api(
        FullNodeAPI.request_block, full_node_protocol.RequestBlock(potential_peek, True)
    )
    if block_response is not None and isinstance(block_response, full_node_protocol.RespondBlock):
        peak = blockchain.get_peak()
        if peak is not None and block_response.block.prev_header_hash == peak.header_hash:
            return True
    return False
