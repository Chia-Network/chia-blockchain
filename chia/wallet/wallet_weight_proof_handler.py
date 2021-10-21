import asyncio
import logging
import random
from concurrent.futures.process import ProcessPoolExecutor
from typing import List, Tuple, Any

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


class WalletWeightProofHandler:

    LAMBDA_L = 100
    C = 0.5
    MAX_SAMPLES = 20
    _blockchain: Any

    def __init__(
        self,
        constants: ConsensusConstants,
        blockchain: Any,
    ):
        self._constants = constants
        self._blockchain = blockchain
        self._num_processes = 4
        self._executor: ProcessPoolExecutor = ProcessPoolExecutor(self._num_processes)
        self._weight_proof_tasks: List[asyncio.Task] = []

    def cancel_weight_proof_tasks(self):
        log.warning("CANCELLING WEIGHT PROOF TASKS")
        old_executor = self._executor
        self._executor = ProcessPoolExecutor(self._num_processes)
        old_executor.shutdown(wait=False)
        for task in self._weight_proof_tasks:
            if not task.done():
                task.cancel()
        self._weight_proof_tasks = []

    async def validate_weight_proof(
        self, weight_proof: WeightProof
    ) -> Tuple[bool, uint32, List[SubEpochSummary], List[BlockRecord]]:
        task: asyncio.Task = asyncio.create_task(self.validate_weight_proof_inner(weight_proof))
        self._weight_proof_tasks.append(task)
        valid, fork_point, summaries, block_records = await task
        self._weight_proof_tasks.remove(task)
        return valid, fork_point, summaries, block_records

    async def validate_weight_proof_inner(
        self, weight_proof: WeightProof
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

        recent_blocks_validation_task = asyncio.get_running_loop().run_in_executor(
            self._executor, _validate_recent_blocks_and_get_records, constants, wp_recent_chain_bytes, summary_bytes
        )

        segments_validated, vdfs_to_validate = _validate_sub_epoch_segments(
            constants, rng, wp_segment_bytes, summary_bytes
        )

        if not segments_validated:
            return False, uint32(0), [], []

        vdf_chunks = chunks(vdfs_to_validate, self._num_processes)
        vdf_tasks = []
        for chunk in vdf_chunks:
            byte_chunks = []
            for vdf_proof, classgroup, vdf_info in chunk:
                byte_chunks.append((bytes(vdf_proof), bytes(classgroup), bytes(vdf_info)))

            vdf_task = asyncio.get_running_loop().run_in_executor(
                self._executor, _validate_vdf_batch, constants, byte_chunks
            )
            vdf_tasks.append(vdf_task)

        for vdf_task in vdf_tasks:
            validated = await vdf_task
            if not validated:
                return False, uint32(0), [], []

        valid_recent_blocks, sub_block_bytes = await recent_blocks_validation_task

        if not valid_recent_blocks:
            log.error("failed validating weight proof recent blocks")
            # Verify the data
            return False, uint32(0), [], []

        sub_blocks = [BlockRecord.from_bytes(b) for b in sub_block_bytes]

        # TODO fix find fork point
        return True, uint32(0), summaries, sub_blocks

    def get_recent_chain_fork(self, new_wp: WeightProof) -> uint32:
        for nblock in reversed(new_wp.recent_chain_data):
            if self._blockchain.contains_block(nblock.prev_header_hash):
                return uint32(nblock.height - 1)

        return uint32(0)

    def get_fork_point(self, old_summaries: List[SubEpochSummary], received_summaries: List[SubEpochSummary]) -> uint32:
        # iterate through sub epoch summaries to find fork point
        if len(old_summaries) == 0:
            return uint32(0)

        old_ses = set()

        for ses in old_summaries:
            old_ses.add(ses.reward_chain_hash)

        overflow = 0
        count = 0
        for idx, new_ses in enumerate(received_summaries):
            if new_ses.reward_chain_hash in old_ses:
                count += 1
                overflow += new_ses.num_blocks_overflow
                continue
            else:
                break

        fork_point = uint32((self._constants.SUB_EPOCH_BLOCKS * count) - overflow)
        return fork_point
