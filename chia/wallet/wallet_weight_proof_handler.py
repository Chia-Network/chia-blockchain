import asyncio
import logging
import pathlib
import random
import tempfile
from concurrent.futures.process import ProcessPoolExecutor
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

log = logging.getLogger(__name__)


def _create_shutdown_file() -> IO:
    return tempfile.NamedTemporaryFile(prefix="chia_executor_shutdown_trigger")


class WalletWeightProofHandler:

    LAMBDA_L = 100
    C = 0.5
    MAX_SAMPLES = 20

    def __init__(
        self,
        constants: ConsensusConstants,
    ):
        self._constants = constants
        self._num_processes = 4
        self._executor_shutdown_tempfile: IO = _create_shutdown_file()
        self._executor: ProcessPoolExecutor = ProcessPoolExecutor(self._num_processes)
        self._weight_proof_tasks: List[asyncio.Task] = []

    def cancel_weight_proof_tasks(self):
        for task in self._weight_proof_tasks:
            if not task.done():
                task.cancel()
        self._weight_proof_tasks = []
        self._executor_shutdown_tempfile.close()
        self._executor.shutdown(wait=True)

    async def validate_weight_proof(
        self, weight_proof: WeightProof, skip_segment_validation=False
    ) -> Tuple[bool, uint32, List[SubEpochSummary], List[BlockRecord]]:
        task: asyncio.Task = asyncio.create_task(
            self._validate_weight_proof_inner(weight_proof, skip_segment_validation)
        )
        self._weight_proof_tasks.append(task)
        valid, fork_point, summaries, block_records = await task
        self._weight_proof_tasks.remove(task)
        return valid, fork_point, summaries, block_records

    async def _validate_weight_proof_inner(
        self, weight_proof: WeightProof, skip_segment_validation: bool
    ) -> Tuple[bool, uint32, List[SubEpochSummary], List[BlockRecord]]:
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0), [], []

        peak_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
        log.info(f"validate weight proof peak height {peak_height}")

        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self._constants, weight_proof)
        if summaries is None:
            log.error("weight proof failed sub epoch data validation")
            return False, uint32(0), [], []

        seed = summaries[-2].get_hash()
        rng = random.Random(seed)
        if not validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
            log.error("failed weight proof sub epoch sample validation")
            return False, uint32(0), [], []

        constants, summary_bytes, wp_segment_bytes, wp_recent_chain_bytes = vars_to_bytes(
            self._constants, summaries, weight_proof
        )

        vdf_tasks: List[asyncio.Future] = []
        recent_blocks_validation_task: asyncio.Future = asyncio.get_running_loop().run_in_executor(
            self._executor,
            _validate_recent_blocks_and_get_records,
            constants,
            wp_recent_chain_bytes,
            summary_bytes,
            pathlib.Path(self._executor_shutdown_tempfile.name),
        )
        try:
            if not skip_segment_validation:
                segments_validated, vdfs_to_validate = _validate_sub_epoch_segments(
                    constants, rng, wp_segment_bytes, summary_bytes
                )

                if not segments_validated:
                    return False, uint32(0), [], []

                vdf_chunks = chunks(vdfs_to_validate, self._num_processes)
                for chunk in vdf_chunks:
                    byte_chunks = []
                    for vdf_proof, classgroup, vdf_info in chunk:
                        byte_chunks.append((bytes(vdf_proof), bytes(classgroup), bytes(vdf_info)))

                    vdf_task: asyncio.Future = asyncio.get_running_loop().run_in_executor(
                        self._executor,
                        _validate_vdf_batch,
                        constants,
                        byte_chunks,
                        pathlib.Path(self._executor_shutdown_tempfile.name),
                    )
                    vdf_tasks.append(vdf_task)

                for vdf_task in vdf_tasks:
                    validated = await vdf_task
                    if not validated:
                        return False, uint32(0), [], []

            valid_recent_blocks, records_bytes = await recent_blocks_validation_task
        finally:
            recent_blocks_validation_task.cancel()
            for vdf_task in vdf_tasks:
                vdf_task.cancel()

        if not valid_recent_blocks:
            log.error("failed validating weight proof recent blocks")
            # Verify the data
            return False, uint32(0), [], []

        records = [BlockRecord.from_bytes(b) for b in records_bytes]

        # TODO fix find fork point
        return True, uint32(0), summaries, records

    def get_fork_point(self, old_wp: Optional[WeightProof], new_wp: WeightProof) -> uint32:
        """
        iterate through sub epoch summaries to find fork point. This method is conservative, it does not return the
        actual fork point, it can return a height that is before the actual fork point.
        """

        if old_wp is None:
            return uint32(0)

        old_ses = set()

        for ses in old_wp.sub_epochs:
            old_ses.add(ses.reward_chain_hash)

        overflow = 0
        count = 0
        for idx, new_ses in enumerate(new_wp.sub_epochs):
            if new_ses.reward_chain_hash in old_ses:
                count += 1
                overflow += new_ses.num_blocks_overflow
                continue
            else:
                break

        # Try to find an exact fork point
        if new_wp.recent_chain_data[0].height >= old_wp.recent_chain_data[0].height:
            left_wp = old_wp
            right_wp = new_wp
        else:
            left_wp = new_wp
            right_wp = old_wp

        r_index = 0
        l_index = 0
        while r_index < len(right_wp.recent_chain_data) and l_index < len(left_wp.recent_chain_data):
            if right_wp.recent_chain_data[r_index].header_hash == left_wp.recent_chain_data[l_index].header_hash:
                r_index += 1
                continue
            # Keep incrementing left pointer until we find a match
            l_index += 1
        if r_index != 0:
            # We found a matching block, this is the last matching block
            return right_wp.recent_chain_data[r_index - 1].height

        # Just return the matching sub epoch height
        return uint32((self._constants.SUB_EPOCH_BLOCKS * count) - overflow)
