import asyncio
import logging
import pathlib
import random
import tempfile
from concurrent.futures.process import ProcessPoolExecutor
from multiprocessing.context import BaseContext
from typing import IO, List, Tuple, Optional

from chia.consensus.block_record import BlockRecord
from chia.consensus.constants import ConsensusConstants
from chia.full_node.weight_proof import (
    _validate_sub_epoch_summaries,
    vars_to_bytes,
    validate_sub_epoch_sampling,
    _validate_sub_epoch_segments,
    _validate_recent_blocks_and_get_records,
    chunks,
    _validate_vdf_batch,
)
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary

from chia.types.weight_proof import (
    WeightProof,
)

from chia.util.ints import uint32
from chia.util.setproctitle import getproctitle, setproctitle

log = logging.getLogger(__name__)


def _create_shutdown_file() -> IO:
    return tempfile.NamedTemporaryFile(prefix="chia_wallet_weight_proof_handler_executor_shutdown_trigger")


class WalletWeightProofHandler:

    LAMBDA_L = 100
    C = 0.5
    MAX_SAMPLES = 20

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
        validate_from = get_fork_ses_idx(old_proof, weight_proof)
        task: asyncio.Task = asyncio.create_task(
            self._validate_weight_proof_inner(weight_proof, skip_segment_validation, validate_from)
        )
        self._weight_proof_tasks.append(task)
        valid, summaries, block_records = await task
        self._weight_proof_tasks.remove(task)
        return valid, summaries, block_records

    async def _validate_weight_proof_inner(
        self, weight_proof: WeightProof, skip_segment_validation: bool, validate_from: int
    ) -> Tuple[bool, List[SubEpochSummary], List[BlockRecord]]:
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, [], []

        peak_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
        log.info(f"validate weight proof peak height {peak_height}")

        # TODO: Consider if this can be spun off to a thread as an alternative to
        #       sprinkling async sleeps around.  Also see the corresponding comment
        #       in the full node code.
        #       all instances tagged as: 098faior2ru08d08ufa

        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self._constants, weight_proof)
        await asyncio.sleep(0)  # break up otherwise multi-second sync code
        if summaries is None:
            log.error("weight proof failed sub epoch data validation")
            return False, [], []

        seed = summaries[-2].get_hash()
        rng = random.Random(seed)
        if not validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
            log.error("failed weight proof sub epoch sample validation")
            return False, [], []

        summary_bytes, wp_segment_bytes, wp_recent_chain_bytes = vars_to_bytes(summaries, weight_proof)
        await asyncio.sleep(0)  # break up otherwise multi-second sync code

        vdf_tasks: List[asyncio.Future] = []
        recent_blocks_validation_task: asyncio.Future = asyncio.get_running_loop().run_in_executor(
            self._executor,
            _validate_recent_blocks_and_get_records,
            self._constants,
            wp_recent_chain_bytes,
            summary_bytes,
            pathlib.Path(self._executor_shutdown_tempfile.name),
        )
        try:
            if not skip_segment_validation:
                segments_validated, vdfs_to_validate = _validate_sub_epoch_segments(
                    self._constants, rng, wp_segment_bytes, summary_bytes, validate_from
                )
                await asyncio.sleep(0)  # break up otherwise multi-second sync code

                if not segments_validated:
                    return False, [], []

                vdf_chunks = chunks(vdfs_to_validate, self._num_processes)
                for chunk in vdf_chunks:
                    byte_chunks = []
                    for vdf_proof, classgroup, vdf_info in chunk:
                        byte_chunks.append((bytes(vdf_proof), bytes(classgroup), bytes(vdf_info)))

                    vdf_task: asyncio.Future = asyncio.get_running_loop().run_in_executor(
                        self._executor,
                        _validate_vdf_batch,
                        self._constants,
                        byte_chunks,
                        pathlib.Path(self._executor_shutdown_tempfile.name),
                    )
                    vdf_tasks.append(vdf_task)
                    # give other stuff a turn
                    await asyncio.sleep(0)

                for vdf_task in vdf_tasks:
                    validated = await vdf_task
                    if not validated:
                        return False, [], []

            valid_recent_blocks, records_bytes = await recent_blocks_validation_task
        finally:
            recent_blocks_validation_task.cancel()
            for vdf_task in vdf_tasks:
                vdf_task.cancel()

        if not valid_recent_blocks:
            log.error("failed validating weight proof recent blocks")
            # Verify the data
            return False, [], []

        records = [BlockRecord.from_bytes(b) for b in records_bytes]
        return True, summaries, records


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
