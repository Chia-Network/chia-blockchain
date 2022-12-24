from __future__ import annotations

import asyncio
import logging
import tempfile
from concurrent.futures.process import ProcessPoolExecutor
from multiprocessing.context import BaseContext
from typing import IO, List, Optional, Tuple

from chia.consensus.block_record import BlockRecord
from chia.consensus.constants import ConsensusConstants
from chia.full_node.weight_proof import _validate_sub_epoch_summaries, validate_weight_proof_inner
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.weight_proof import WeightProof
from chia.util.ints import uint32
from chia.util.setproctitle import getproctitle, setproctitle

log = logging.getLogger(__name__)


def _create_shutdown_file() -> IO:
    return tempfile.NamedTemporaryFile(prefix="chia_wallet_weight_proof_handler_executor_shutdown_trigger")


class WalletWeightProofHandler:
    def __init__(
        self,
        constants: ConsensusConstants,
        multiprocessing_context: BaseContext,
    ):
        self._constants = constants
        self._num_processes = 4
        self._executor_shutdown_tempfile: IO = _create_shutdown_file()
        self._executor: ProcessPoolExecutor = ProcessPoolExecutor(
            self._num_processes,
            mp_context=multiprocessing_context,
            initializer=setproctitle,
            initargs=(f"{getproctitle()}_worker",),
        )
        self._weight_proof_tasks: List[asyncio.Task] = []

    def cancel_weight_proof_tasks(self):
        for task in self._weight_proof_tasks:
            if not task.done():
                task.cancel()
        self._weight_proof_tasks = []
        self._executor_shutdown_tempfile.close()
        self._executor.shutdown(wait=True)

    async def validate_weight_proof(
        self, weight_proof: WeightProof, skip_segment_validation: bool = False, old_proof: Optional[WeightProof] = None
    ) -> Tuple[bool, List[SubEpochSummary], List[BlockRecord]]:
        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self._constants, weight_proof)
        await asyncio.sleep(0)  # break up otherwise multi-second sync code
        if summaries is None or sub_epoch_weight_list is None:
            log.error("weight proof failed sub epoch data validation")
            return False, [], []
        validate_from = get_fork_ses_idx(old_proof, weight_proof)
        task: asyncio.Task = asyncio.create_task(
            validate_weight_proof_inner(
                self._constants,
                self._executor,
                self._executor_shutdown_tempfile.name,
                self._num_processes,
                weight_proof,
                summaries,
                sub_epoch_weight_list,
                skip_segment_validation,
                validate_from,
            )
        )
        self._weight_proof_tasks.append(task)
        valid, block_records = await task
        self._weight_proof_tasks.remove(task)
        return valid, summaries, block_records


def get_wp_fork_point(constants: ConsensusConstants, old_wp: Optional[WeightProof], new_wp: WeightProof) -> uint32:
    """
    iterate through sub epoch summaries to find fork point. This method is conservative, it does not return the
    actual fork point, it can return a height that is before the actual fork point.
    """

    if old_wp is None:
        return uint32(0)

    overflow = 0
    count = 0
    for idx, new_ses in enumerate(new_wp.sub_epochs):
        if idx == len(new_wp.sub_epochs) - 1 or idx == len(old_wp.sub_epochs):
            break
        if new_ses.reward_chain_hash != old_wp.sub_epochs[idx].reward_chain_hash:
            break

        count = idx + 1
        overflow = new_wp.sub_epochs[idx + 1].num_blocks_overflow

    if new_wp.recent_chain_data[0].height < old_wp.recent_chain_data[-1].height:
        # Try to find an exact fork point
        new_wp_index = 0
        old_wp_index = 0
        while new_wp_index < len(new_wp.recent_chain_data) and old_wp_index < len(old_wp.recent_chain_data):
            if new_wp.recent_chain_data[new_wp_index].header_hash == old_wp.recent_chain_data[old_wp_index].header_hash:
                new_wp_index += 1
                continue
            # Keep incrementing left pointer until we find a match
            old_wp_index += 1
        if new_wp_index != 0:
            # We found a matching block, this is the last matching block
            return new_wp.recent_chain_data[new_wp_index - 1].height

    # Just return the matching sub epoch height
    return uint32((constants.SUB_EPOCH_BLOCKS * count) + overflow)


def get_fork_ses_idx(old_wp: Optional[WeightProof], new_wp: WeightProof) -> int:
    """
    iterate through sub epoch summaries to find fork point. This method is conservative, it does not return the
    actual fork point, it can return a height that is before the actual fork point.
    """

    if old_wp is None:
        return uint32(0)
    ses_index = 0
    for idx, new_ses in enumerate(new_wp.sub_epochs):
        if new_ses.reward_chain_hash != old_wp.sub_epochs[idx].reward_chain_hash:
            ses_index = idx
            break

        if idx == len(old_wp.sub_epochs) - 1:
            ses_index = idx
            break
    return ses_index
