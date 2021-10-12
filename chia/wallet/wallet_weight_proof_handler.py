import asyncio
import logging
import random
from concurrent.futures.process import ProcessPoolExecutor
from typing import List, Optional, Tuple, Any

from chia.consensus.constants import ConsensusConstants
from chia.full_node.weight_proof import (
    _validate_sub_epoch_summaries,
    vars_to_bytes,
    validate_sub_epoch_sampling,
    _validate_recent_blocks,
    _validate_sub_epoch_segments,
)
from chia.types.blockchain_format.sized_bytes import bytes32
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
    blockchain: Any

    def __init__(
        self,
        constants: ConsensusConstants,
        blockchain: Any,
    ):
        self.tip: Optional[bytes32] = None
        self.proof: Optional[WeightProof] = None
        self.constants = constants
        self.blockchain = blockchain
        self.lock = asyncio.Lock()

    def validate_weight_proof_single_proc(self, weight_proof: WeightProof) -> Tuple[bool, uint32]:
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0)

        peak_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
        log.info(f"validate weight proof peak height {peak_height}")
        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self.constants, weight_proof)
        if summaries is None:
            log.warning("weight proof failed sub epoch data validation")
            return False, uint32(0)
        constants, summary_bytes, wp_segment_bytes, wp_recent_chain_bytes = vars_to_bytes(
            self.constants, summaries, weight_proof
        )
        log.info("validate sub epoch challenge segments")
        seed = summaries[-2].get_hash()
        rng = random.Random(seed)
        if not validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
            log.error("failed weight proof sub epoch sample validation")
            return False, uint32(0)

        if not _validate_sub_epoch_segments(constants, rng, wp_segment_bytes, summary_bytes):
            return False, uint32(0)
        log.info("validate weight proof recent blocks")
        if not _validate_recent_blocks(constants, wp_recent_chain_bytes, summary_bytes):
            return False, uint32(0)
        return True, self.get_fork_point(summaries)

    def get_fork_point_no_validations(self, weight_proof: WeightProof) -> Tuple[bool, uint32]:
        log.debug("get fork point skip validations")
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0)
        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self.constants, weight_proof)
        if summaries is None:
            log.warning("weight proof failed to validate sub epoch summaries")
            return False, uint32(0)
        return True, self.get_fork_point(summaries)

    async def validate_weight_proof(self, weight_proof: WeightProof) -> Tuple[bool, uint32, List[SubEpochSummary]]:
        assert len(weight_proof.sub_epochs) > 0
        if len(weight_proof.sub_epochs) == 0:
            return False, uint32(0), []

        peak_height = weight_proof.recent_chain_data[-1].reward_chain_block.height
        log.info(f"validate weight proof peak height {peak_height}")

        summaries, sub_epoch_weight_list = _validate_sub_epoch_summaries(self.constants, weight_proof)
        if summaries is None:
            log.error("weight proof failed sub epoch data validation")
            return False, uint32(0), []

        seed = summaries[-2].get_hash()
        rng = random.Random(seed)
        if not validate_sub_epoch_sampling(rng, sub_epoch_weight_list, weight_proof):
            log.error("failed weight proof sub epoch sample validation")
            return False, uint32(0), []

        executor = ProcessPoolExecutor(1)
        constants, summary_bytes, wp_segment_bytes, wp_recent_chain_bytes = vars_to_bytes(
            self.constants, summaries, weight_proof
        )
        segment_validation_task = asyncio.get_running_loop().run_in_executor(
            executor, _validate_sub_epoch_segments, constants, rng, wp_segment_bytes, summary_bytes
        )

        recent_blocks_validation_task = asyncio.get_running_loop().run_in_executor(
            executor, _validate_recent_blocks, constants, wp_recent_chain_bytes, summary_bytes
        )

        valid_recent_blocks = await recent_blocks_validation_task
        # valid_recent_blocks, recent_block_records = _validate_recent_blocks(
        #     constants, wp_recent_chain_bytes, summary_bytes, True
        # )
        if not valid_recent_blocks:
            log.error("failed validating weight proof recent blocks")
            # Verify the data
            return False, uint32(0), []

        valid_segments = await segment_validation_task
        if not valid_segments:
            log.error("failed validating weight proof sub epoch segments")
            return False, uint32(0), []

        # TODO fix find fork point
        return True, uint32(0), summaries

    def get_fork_point(self, received_summaries: List[SubEpochSummary]) -> uint32:
        # iterate through sub epoch summaries to find fork point
        fork_point_index = 0
        ses_heights = self.blockchain.get_ses_heights()
        for idx, summary_height in enumerate(ses_heights):
            log.debug(f"check summary {idx} height {summary_height}")
            local_ses = self.blockchain.get_ses(summary_height)
            if idx == len(received_summaries) - 1:
                # end of wp summaries, local chain is longer or equal to wp chain
                break
            if local_ses is None or local_ses.get_hash() != received_summaries[idx].get_hash():
                break
            fork_point_index = idx

        if fork_point_index > 2:
            # Two summeries can have different blocks and still be identical
            # This gets resolved after one full sub epoch
            height = ses_heights[fork_point_index - 2]
        else:
            height = uint32(0)

        return height
