import logging
import random
from typing import Dict, Optional, List, Union

from blspy import AugSchemeMPL

from src.consensus.blockchain import Blockchain
from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import is_overflow_sub_block, calculate_iterations_quality, calculate_ip_iters
from src.consensus.sub_block_record import SubBlockRecord
from src.types.classgroup import ClassgroupElement
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.slots import ChallengeChainSubSlot, RewardChainSubSlot, InfusedChallengeChainSubSlot
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.vdf import VDFProof, VDFInfo
from src.types.weight_proof import (
    WeightProof,
    SubEpochData,
    SubEpochChallengeSegment,
    SubSlotData,
    ProofBlockHeader,
)
from src.util.hash import std_hash
from src.util.ints import uint32, uint64, uint8, uint128


class BlockCache:
    def __init__(self, blockchain: Blockchain):
        # todo make these read only copies from here
        self._sub_blocks = blockchain.sub_blocks
        self._block_store = blockchain.block_store
        self._sub_height_to_hash = blockchain.sub_height_to_hash

    async def header_block(self, header_hash: bytes32) -> HeaderBlock:
        block = await self._block_store.get_full_block(header_hash)
        return await block.get_block_header()

    async def height_to_header_block(self, height: uint32) -> HeaderBlock:
        block = await self._block_store.get_full_blocks_at([height])
        return await block[0].get_block_header()

    def sub_block_record(self, header_hash: bytes32) -> SubBlockRecord:
        return self._sub_blocks[header_hash]

    def height_to_sub_block_record(self, height: uint32) -> SubBlockRecord:
        return self._sub_blocks[self._height_to_hash(height)]

    def max_height(self) -> uint32:
        return uint32(len(self._sub_blocks) - 1)

    def _height_to_hash(self, height: uint32) -> bytes32:
        return self._sub_height_to_hash[height]


class BlockCacheMock:
    def __init__(
        self,
        sub_blocks: Dict[bytes32, SubBlockRecord],
        sub_height_to_hash: Dict[uint32, bytes32],
        header_blocks: Dict[uint32, HeaderBlock],
    ):
        self._sub_blocks = sub_blocks
        self._header_cache = header_blocks
        self._sub_height_to_hash = sub_height_to_hash

    def header_block(self, header_hash: bytes32) -> HeaderBlock:
        return self._header_cache[header_hash]

    def height_to_header_block(self, height: uint32) -> HeaderBlock:
        return self._header_cache[self._height_to_hash(height)]

    def sub_block_record(self, header_hash: bytes32) -> SubBlockRecord:
        return self._sub_blocks[header_hash]

    def height_to_sub_block_record(self, height: uint32) -> SubBlockRecord:
        return self._sub_blocks[self._height_to_hash(height)]

    def max_height(self) -> uint32:
        return uint32(len(self._sub_blocks) - 1)

    def _height_to_hash(self, height: uint32) -> bytes32:
        return self._sub_height_to_hash[height]


async def init_block_block_cache_mock(blockchain: Blockchain, start: uint32, stop: uint32) -> BlockCacheMock:
    batch_size = 200
    full_blocks: List[FullBlock] = []
    batch_blocks: List[uint32] = []
    for x in range(start, stop):
        batch_blocks.append(uint32(x))

        if len(batch_blocks) == batch_size:
            blocks = await blockchain.block_store.get_full_blocks_at(batch_blocks)
            full_blocks.extend(blocks)
            batch_blocks: List[uint32] = []

    # fetch remaining blocks
    blocks = await blockchain.block_store.get_full_blocks_at(batch_blocks)
    full_blocks.extend(blocks)

    # convert to FullBlocks HeaderBlocks
    header_blocks: Dict[bytes32, HeaderBlock] = {}
    for block in full_blocks:
        header_blocks[block.header_hash] = await block.get_block_header()

    return BlockCacheMock(blockchain.sub_blocks, blockchain.sub_height_to_hash, header_blocks)


class WeightProofHandler:
    def __init__(
        self,
        constants: ConsensusConstants,
        block_cache: Union[BlockCache, BlockCacheMock] = None,
        name: str = None,
    ):
        self.constants = constants
        self.block_cache = block_cache

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

    def set_block_cache(self, block_cache):
        self.block_cache = block_cache

    def create_proof_of_weight(
        self, recent_blocks_n: uint32, total_number_of_blocks: uint32, tip: bytes32
    ) -> WeightProof:
        """
        Creates a weight proof object
        """

        # todo assert recent blocks number
        # todo clean some of the logs after tests pass
        sub_epoch_data: List[SubEpochData] = []
        sub_epoch_segments: List[SubEpochChallengeSegment] = []
        proof_blocks: List[ProofBlockHeader] = []
        rng: random.Random = random.Random(tip)
        # ses_hash from the latest sub epoch summary before this part of the chain
        sub_block_height = self.block_cache.sub_block_record(tip).sub_block_height

        assert sub_block_height >= total_number_of_blocks - 1

        blocks_left = total_number_of_blocks
        curr_height = sub_block_height - (total_number_of_blocks - 1)

        self.log.info(
            f"build weight proofs, peak : {sub_block_height} num of blocks: {total_number_of_blocks}, "
            f"start from {curr_height}"
        )

        total_overflow_blocks = 0
        sub_epoch_n = uint32(0)
        while curr_height < sub_block_height:
            # next sub block
            sub_block = self.block_cache.height_to_sub_block_record(curr_height)
            header_block = self.block_cache.height_to_header_block(curr_height)
            if is_overflow_sub_block(self.constants, header_block.reward_chain_sub_block.signage_point_index):
                total_overflow_blocks += 1
                self.log.debug(f"overflow block at height {curr_height}  ")
            # for each sub-epoch
            if sub_block.sub_epoch_summary_included is not None:
                self.log.debug(
                    f"sub epoch end, block height {sub_block.sub_block_height} {sub_block.sub_epoch_summary_included}"
                )
                sub_epoch_data.append(make_sub_epoch_data(sub_block.sub_epoch_summary_included))
                # get sub_epoch_blocks_n in sub_epoch
                sub_epoch_blocks_n = get_sub_epoch_block_num(sub_block, self.block_cache)
                #   sample sub epoch
                if choose_sub_epoch(sub_epoch_blocks_n, rng, total_number_of_blocks):
                    segments = self.__create_sub_epoch_segments(sub_block, sub_epoch_blocks_n, sub_epoch_n)
                    self.log.debug(
                        f"sub epoch {sub_epoch_n}  chosen, has {len(segments)} challenge segments {sub_epoch_blocks_n} "
                        f"blocks probability of {sub_epoch_blocks_n / total_number_of_blocks}"
                    )
                    sub_epoch_n += 1
                    sub_epoch_segments.extend(segments)

            if sub_block_height - curr_height <= recent_blocks_n:
                # add to needed reward chain recent blocks
                proof_blocks.append(
                    ProofBlockHeader(header_block.finished_sub_slots, header_block.reward_chain_sub_block)
                )

            blocks_left -= 1
            curr_height += 1
        self.log.debug(f"total overflow blocks in proof {total_overflow_blocks}")
        return WeightProof(sub_epoch_data, sub_epoch_segments, proof_blocks)

    def validate_weight_proof(self, weight_proof: WeightProof, fork_point: Optional[SubBlockRecord] = None) -> bool:
        # sub epoch summaries validate hashes
        self.log.info("validate summaries")
        prev_ses_hash = self.constants.GENESIS_SES_HASH

        # last find latest ses
        if fork_point is not None:
            self.log.info(f"fork point {fork_point.sub_block_height}")
            curr = fork_point
            while not curr.sub_epoch_summary_included and curr.sub_block_height > 0:
                curr = self.block_cache.sub_block_record(curr.prev_hash)
            self.log.info(f"last sub_epoch summary before proof at {curr.sub_block_height}")

            if curr.sub_block_height != 0:
                prev_ses_hash = curr.sub_epoch_summary_included.get_hash()

        if len(weight_proof.sub_epochs) > 0:
            summaries = self.validate_sub_epoch_summaries(weight_proof, fork_point, prev_ses_hash)
            if summaries is None:
                return False

            # self.log.info(f"validate sub epoch challenge segments")
            # if not self._validate_segments(weight_proof, summaries, curr):
            #     return False

        self.log.info("validate weight proof recent blocks")
        if not self._validate_recent_blocks(weight_proof):
            return False

        return True

    def _validate_recent_blocks(self, weight_proof: WeightProof):
        return True

    def validate_sub_epoch_summaries(
        self, weight_proof: WeightProof, fork_point: Optional[SubBlockRecord], prev_ses_hash: bytes32
    ):

        if fork_point is None or fork_point.sub_block_height == 0:
            fork_point_difficulty = self.constants.DIFFICULTY_STARTING
        else:
            fork_point_difficulty = uint64(
                fork_point.weight - self.block_cache.sub_block_record(fork_point.prev_hash).weight
            )

        summaries, sub_epoch_data_weight = map_summaries(
            self.constants.SUB_EPOCH_SUB_BLOCKS, prev_ses_hash, weight_proof.sub_epochs, fork_point_difficulty
        )

        self.log.debug(f"validating {len(summaries)} summaries")

        last_ses = summaries[uint32(len(summaries) - 1)]
        last_ses_block = get_last_ses_block_idx(self.constants, weight_proof.recent_chain_data)
        if last_ses_block is None:
            self.log.error("could not find first block after last sub epoch end")
            return None
        # validate weight

        # validate last ses_hash
        if last_ses.get_hash() != last_ses_block.finished_sub_slots[-1].challenge_chain.subepoch_summary_hash:
            self.log.error(
                f"failed to validate ses hashes block height {last_ses_block.reward_chain_sub_block.sub_block_height}"
                f"{last_ses.get_hash()}  {last_ses_block.finished_sub_slots[-1].challenge_chain.subepoch_summary_hash}"
            )
            return None
        return summaries

    def validate_segments(
        self,
        weight_proof: WeightProof,
        summaries: Dict[uint32, SubEpochSummary],
        curr_ssi: uint64,
        rc_sub_slot_hash: bytes32,
    ):
        # total_challenge_blocks, total_ip_iters = uint64(0), uint64(0)
        total_slot_iters, total_slots = uint64(0), uint64(0)
        total_ip_iters = uint64(0)
        # validate sub epoch samples

        curr_sub_epoch_n = -1

        for idx, segment in enumerate(weight_proof.sub_epoch_segments):
            if curr_sub_epoch_n < segment.sub_epoch_n:
                self.log.info(f"handle new sub epoch {segment.sub_epoch_n}")

                # todo  validate vdfs
                ses = summaries[segment.sub_epoch_n]
                if not ses.reward_chain_hash == rc_sub_slot_hash:
                    self.log.error(f"failed reward_chain_hash validation sub_epoch {segment.sub_epoch_n}")
                    self.log.error(f"rc slot hash  {rc_sub_slot_hash}")
                    return False

                # recreate RewardChainSubSlot for next ses rc_hash
                rc_sub_slot_hash = self.get_rc_sub_slot(
                    segment, ses.get_hash(), ses.new_sub_slot_iters, ses.new_difficulty, summaries
                ).get_hash()

            if not self.__validate_segment_slots(
                summaries, segment, curr_ssi, total_slot_iters, total_slots, total_ip_iters, rc_sub_slot_hash
            ):
                self.log.error(f"failed to validate segment {idx} of sub_epoch {segment.sub_epoch_n} slots")
                return False

            curr_sub_epoch_n = segment.sub_epoch_n
        # todo floats
        # avg_ip_iters = total_ip_iters / total_challenge_blocks
        # avg_slot_iters = total_slot_iters / total_slots
        # if avg_slot_iters / avg_ip_iters < float(self.constants.WEIGHT_PROOF_THRESHOLD):
        #     self.log.error(f"bad avg challenge block positioning ration: {avg_slot_iters / avg_ip_iters}")
        #     return False

        return True

    def get_rc_sub_slot(
        self,
        segment: SubEpochChallengeSegment,
        ses_hash: bytes32,
        new_sub_slot_iters: Optional[uint64],
        new_difficulty: Optional[uint64],
        summaries: Dict[uint32, SubEpochSummary],
    ) -> RewardChainSubSlot:

        first_slot = segment.sub_slots[0]
        icc_sub_slot = InfusedChallengeChainSubSlot(first_slot.icc_slot_end_info)

        cc_sub_slot = ChallengeChainSubSlot(
            first_slot.cc_slot_end_info,
            icc_sub_slot.get_hash(),
            ses_hash,
            new_sub_slot_iters,
            new_difficulty,
        )
        deficit = self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
        if summaries[segment.sub_epoch_n + 1].num_sub_blocks_overflow == 0:
            deficit -= 1  # no overflow in start of sub epoch

        rc_sub_slot = RewardChainSubSlot(
            segment.last_reward_chain_vdf_info,
            cc_sub_slot.get_hash(),
            icc_sub_slot.get_hash(),
            uint8(deficit),  # -1 if no overflows in start of sub_epoch
        )
        self.log.info(f"recreated rc sub slot \n {rc_sub_slot}")
        self.log.info("------------------------------------------------------------")
        self.log.info(f"recreated  cc sub slot \n {cc_sub_slot}")
        self.log.info("------------------------------------------------------------")
        self.log.info(f"recreated  icc sub slot  \n {icc_sub_slot}")

        return rc_sub_slot

    def __create_sub_epoch_segments(
        self, block: SubBlockRecord, sub_epoch_blocks_n: uint32, sub_epoch_n: uint32
    ) -> List[SubEpochChallengeSegment]:
        """
        receives the last block in sub epoch and creates List[SubEpochChallengeSegment] for that sub_epoch
        """

        segments: List[SubEpochChallengeSegment] = []
        curr = block

        last_slot = self.block_cache.header_block(block.header_hash).finished_sub_slots[-1]
        self.log.info(f"rc sub slot  \n {last_slot.reward_chain}")
        self.log.info("------------------------------------------------------------")
        self.log.info(f"cc sub slot \n {last_slot.challenge_chain}")
        self.log.info("------------------------------------------------------------")
        self.log.info(f"icc sub slot \n {last_slot.infused_challenge_chain}")

        count = sub_epoch_blocks_n
        while not count == 0:
            # not challenge block skip
            if curr.is_challenge_sub_block(self.constants):
                self.log.debug(f"sub epoch {sub_epoch_n} challenge segment, starts at {curr.sub_block_height} ")
                challenge_sub_block = self.block_cache.header_block(curr.header_hash)
                # prepend as we are stepping backwards in the chain
                seg = self._handle_challenge_segment(challenge_sub_block, sub_epoch_n)
                segments.insert(0, seg)

            curr = self.block_cache.sub_block_record(curr.prev_hash)
            count -= 1

        return segments

    def _handle_challenge_segment(self, block: HeaderBlock, sub_epoch_n: uint32) -> SubEpochChallengeSegment:
        sub_slots: List[SubSlotData] = []
        self.log.debug(
            f"create challenge segment for block {block.header_hash} sub_block_height {block.sub_block_height} "
        )

        # VDFs from sub slots before challenge block
        self.log.debug(f"create ip vdf for block {block.header_hash} height {block.sub_block_height} ")
        first_sub_slots, end_height = self.__first_sub_slots_data(block)
        sub_slots.extend(first_sub_slots)

        # VDFs from slot after challenge block to end of slot
        self.log.debug(f"create slot end vdf for block {block.header_hash} height {block.sub_block_height} ")

        challenge_slot_end_sub_slots = self.__get_slot_end_vdf(self.block_cache.height_to_header_block(end_height))

        sub_slots.extend(challenge_slot_end_sub_slots)
        self.log.debug(f"segment number of sub slots {len(sub_slots)}")
        return SubEpochChallengeSegment(sub_epoch_n, block.reward_chain_sub_block.reward_chain_ip_vdf, sub_slots)

    def __get_slot_end_vdf(self, block: HeaderBlock) -> List[SubSlotData]:
        # gets all vdfs first sub slot after challenge block to last sub slot
        curr = block
        cc_proofs: List[VDFProof] = []
        icc_proofs: List[VDFProof] = []
        sub_slots_data: List[SubSlotData] = []
        max_height = self.block_cache.max_height()
        while curr.sub_block_height + 1 < max_height:
            curr = self.block_cache.height_to_header_block(curr.sub_block_height + 1)
            if len(curr.finished_sub_slots) > 0:
                # slot finished combine proofs and add slot data to list
                sub_slots_data.append(
                    SubSlotData(
                        None, None, None, None, None, combine_proofs(cc_proofs), combine_proofs(icc_proofs), None, None
                    )
                )

                # handle finished empty sub slots
                for sub_slot in curr.finished_sub_slots:
                    sub_slots_data.append(empty_sub_slot_data(sub_slot))
                    if sub_slot.reward_chain.deficit == self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                        # end of challenge slot
                        break

                # new sub slot
                cc_proofs = []

            # append sub slot proofs
            icc_proofs.append(curr.infused_challenge_chain_ip_proof)
            cc_proofs.extend([curr.challenge_chain_sp_proof, curr.challenge_chain_ip_proof])

        return sub_slots_data

    # returns a challenge chain vdf from slot start to signage point
    def __first_sub_slots_data(self, block: HeaderBlock) -> (List[SubSlotData], uint64):
        # combine cc vdfs of all reward blocks from the start of the sub slot to end
        sub_slots: List[SubSlotData] = []

        # todo vdf of the overflow blocks before the challenge block ?

        sub_slots: List[SubSlotData]
        # get all finished sub slots
        if len(block.finished_sub_slots) > 0:
            for sub_slot in block.finished_sub_slots:
                sub_slots.append(empty_sub_slot_data(sub_slot))

        # find sub slot end
        curr = block
        next_slot_height = 0
        cc_slot_end_vdf: List[VDFProof] = []
        icc_slot_end_vdf: List[VDFProof] = []
        while True:
            curr = self.block_cache.height_to_sub_block_record(curr.sub_block_height + 1)
            curr_header = self.block_cache.header_block(curr.header_hash)
            if len(curr_header.finished_sub_slots) > 0:
                # sub slot ended
                next_slot_height = curr.sub_block_height + 1
                sub_slots.append(
                    SubSlotData(
                        None,
                        None,
                        None,
                        None,
                        None,
                        combine_proofs(cc_slot_end_vdf),
                        combine_proofs(icc_slot_end_vdf),
                        curr_header.finished_sub_slots[-1].challenge_chain.challenge_chain_end_of_slot_vdf,
                        curr_header.finished_sub_slots[
                            -1
                        ].infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf,
                    )
                )

            if curr.is_challenge_sub_block(self.constants):
                break

            cc_slot_end_vdf.extend([curr_header.challenge_chain_sp_proof, curr_header.challenge_chain_ip_proof])
            icc_slot_end_vdf.append(curr_header.infused_challenge_chain_ip_proof)

        sub_slots.append(
            SubSlotData(
                block.reward_chain_sub_block.proof_of_space,
                block.reward_chain_sub_block.challenge_chain_sp_signature,
                block.challenge_chain_sp_proof,
                block.challenge_chain_ip_proof,
                block.reward_chain_sub_block.signage_point_index,
                combine_proofs(cc_slot_end_vdf),
                combine_proofs(icc_slot_end_vdf),
                None,
                None,
            )
        )

        return sub_slots, next_slot_height

    def __get_quality_string(
        self, segment: SubEpochChallengeSegment, ses: SubEpochSummary, slot_iters: uint64
    ) -> Optional[bytes32]:

        # find challenge block sub slot
        challenge_sub_slot: Optional[SubSlotData] = None
        idx = 0
        for idx, slot in enumerate(segment.sub_slots):
            if slot.proof_of_space is not None:
                challenge_sub_slot = slot
                break

        cc_vdf = segment.sub_slots[idx - 1].cc_slot_end_info
        icc_vdf = segment.sub_slots[idx - 1].icc_slot_end_info
        cc_sub_slot = ChallengeChainSubSlot(cc_vdf, icc_vdf.get_hash(), None, None, None)
        # get challenge
        self.log.debug(f"cc_end_of_slot {cc_sub_slot}")

        # check filter
        if challenge_sub_slot.cc_signage_point is None:
            cc_sp_hash: bytes32 = cc_sub_slot.get_hash()
        else:
            cc_sp_hash = challenge_sub_slot.challenge_chain_sp_vdf.output.get_hash()

        if not AugSchemeMPL.verify(
            challenge_sub_slot.proof_of_space.plot_public_key,
            cc_sp_hash,
            challenge_sub_slot.cc_sp_sig,
        ):
            self.log.error("did not pass filter")
            return None

        # validate proof of space
        return challenge_sub_slot.proof_of_space.verify_and_get_quality_string(
            self.constants,
            cc_sub_slot.get_hash(),
            cc_sp_hash,
        )

    def __validate_segment_slots(
        self,
        summaries: Dict[uint32, SubEpochSummary],
        segment: SubEpochChallengeSegment,
        curr_ssi: uint64,
        total_slot_iters: uint64,
        total_slots: uint64,
        total_ip_iters: uint64,
        challenge: bytes32,
    ) -> (bool, uint64, uint64, int):
        ses = summaries[segment.sub_epoch_n]
        challenge_blocks = 0
        if ses.new_sub_slot_iters is not None:
            curr_ssi: uint64 = ses.new_sub_slot_iters
        for sub_slot in segment.sub_slots:
            total_slot_iters += curr_ssi
            total_slots += 1

            # todo uncomment after vdf merging is done
            # if not validate_sub_slot_vdfs(self.constants, sub_slot, vdf_info, sub_slot.is_challenge()):
            #     self.log.info(f"failed to validate {idx} sub slot vdfs")
            #     return False

            if sub_slot.is_challenge():
                q_str = self.__get_quality_string(segment, summaries[segment.sub_epoch_n], curr_ssi)
                if q_str is None:
                    self.log.info(f"failed to validate {segment} segment space proof")
                    return False
                required_iters: uint64 = calculate_iterations_quality(
                    q_str,
                    sub_slot.proof_of_space.size,
                    challenge,
                    sub_slot.cc_signage_point.get_hash(),
                )
                total_ip_iters += calculate_ip_iters(
                    self.constants, curr_ssi, sub_slot.cc_signage_point_index, required_iters
                )
                challenge_blocks += 1

            if sub_slot.cc_slot_end_info is not None:
                challenge = sub_slot.cc_slot_end_info.get_hash()
            else:
                self.log.error("implement")

        return True, total_slot_iters, total_slots, challenge_blocks


def combine_proofs(proofs: List[VDFProof]) -> VDFProof:
    # todo

    return VDFProof(witness_type=uint8(0), witness=b"")


def make_sub_epoch_data(
    sub_epoch_summary: SubEpochSummary,
) -> SubEpochData:
    reward_chain_hash: bytes32 = sub_epoch_summary.reward_chain_hash
    #  Number of subblocks overflow in previous slot
    previous_sub_epoch_overflows: uint8 = sub_epoch_summary.num_sub_blocks_overflow  # total in sub epoch - expected
    #  New work difficulty and iterations per sub-slot
    sub_slot_iters: Optional[uint64] = sub_epoch_summary.new_sub_slot_iters
    new_difficulty: Optional[uint64] = sub_epoch_summary.new_difficulty
    return SubEpochData(reward_chain_hash, previous_sub_epoch_overflows, sub_slot_iters, new_difficulty)


def get_sub_epoch_block_num(last_block: SubBlockRecord, cache: Union[BlockCache, BlockCacheMock]) -> uint32:
    """
    returns the number of blocks in a sub epoch ending with
    """
    # count from end of sub_epoch
    if last_block.sub_epoch_summary_included is None:
        raise Exception("block does not finish a sub_epoch")

    curr = cache.sub_block_record(last_block.prev_hash)
    count: uint32 = uint32(0)
    while not curr.sub_epoch_summary_included:
        # todo skip overflows from last sub epoch
        if curr.sub_block_height == 0:
            return count

        curr = cache.sub_block_record(curr.prev_hash)
        count += 1
    count += 1

    return count


def choose_sub_epoch(sub_epoch_blocks_n: uint32, rng: random.Random, total_number_of_blocks: uint32) -> bool:
    prob = sub_epoch_blocks_n / total_number_of_blocks
    i = 0
    while i < sub_epoch_blocks_n:
        if rng.random() < prob:
            return True
        i += 1
    return False


# returns a challenge chain vdf from infusion point to end of slot
def count_sub_epochs_in_range(
    curr: SubBlockRecord, sub_blocks: Dict[bytes32, SubBlockRecord], total_number_of_blocks: int
):
    sub_epochs_n = 0
    while not total_number_of_blocks == 0:
        assert curr.sub_block_height != 0
        curr = sub_blocks[curr.prev_hash]
        if curr.sub_epoch_summary_included is not None:
            sub_epochs_n += 1
        total_number_of_blocks -= 1
    return sub_epochs_n


# todo fix to correct vdf inputs
def validate_sub_slot_vdfs(
    constants: ConsensusConstants, sub_slot: SubSlotData, vdf_info: VDFInfo, infused: bool
) -> bool:
    default = ClassgroupElement.get_default_element()
    if infused:
        if not sub_slot.cc_signage_point.is_valid(constants, default, vdf_info):
            return False
        if not sub_slot.cc_infusion_point.is_valid(constants, default, vdf_info):
            return False
        if not sub_slot.cc_infusion_to_slot_end_vdf.is_valid(constants, default, vdf_info):
            return False
        if not sub_slot.icc_infusion_to_slot_end_vdf.is_valid(constants, default, vdf_info):
            return False

        return True

    return sub_slot.cc_slot_end.is_valid(constants, ClassgroupElement.get_default_element(), vdf_info)


def map_summaries(
    sub_blocks_for_se: uint32,
    ses_hash: bytes32,
    sub_epoch_data: List[SubEpochData],
    curr_difficulty: uint64,
) -> (Dict[uint32, SubEpochSummary], uint128):
    sub_epoch_data_weight: uint128 = uint128(0)
    summaries: Dict[uint32, SubEpochSummary] = {}

    for idx, data in enumerate(sub_epoch_data):
        ses = SubEpochSummary(
            ses_hash,
            data.reward_chain_hash,
            data.num_sub_blocks_overflow,
            data.new_difficulty,
            data.new_sub_slot_iters,
        )

        # if new epoch update diff and iters
        if data.new_sub_slot_iters is not None:
            curr_difficulty = data.new_difficulty

        sub_epoch_data_weight += curr_difficulty * (sub_blocks_for_se + data.num_sub_blocks_overflow)

        # add to dict
        summaries[idx] = ses
        ses_hash = std_hash(ses)
    return summaries, sub_epoch_data_weight


def get_last_ses_block_idx(
    constants: ConsensusConstants, recent_reward_chain: List[ProofBlockHeader]
) -> Optional[ProofBlockHeader]:
    for idx, block in enumerate(reversed(recent_reward_chain)):
        print(f"check block {block.reward_chain_sub_block.sub_block_height} for ses")
        if uint8(block.reward_chain_sub_block.sub_block_height % constants.SUB_EPOCH_SUB_BLOCKS) == 0:
            idx = len(recent_reward_chain) - 1 - idx  # reverse
            # find first block after sub slot end
            curr = recent_reward_chain[idx]
            while True:
                if len(curr.finished_sub_slots) > 0:
                    for slot in curr.finished_sub_slots:
                        if slot.challenge_chain.subepoch_summary_hash is not None:
                            print(f"last ses at {curr.reward_chain_sub_block.sub_block_height}")
                            return curr
                idx += 1
                curr = recent_reward_chain[idx]

    return None


def empty_sub_slot_data(end_of_slot: EndOfSubSlotBundle):
    icc_end_of_slot_info: Optional = None
    if end_of_slot.infused_challenge_chain is not None:
        icc_end_of_slot_info = end_of_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf
    return SubSlotData(
        None,
        None,
        None,
        None,
        None,
        end_of_slot.proofs.challenge_chain_slot_proof,
        end_of_slot.proofs.infused_challenge_chain_slot_proof,
        end_of_slot.challenge_chain.challenge_chain_end_of_slot_vdf,
        icc_end_of_slot_info,
    )
