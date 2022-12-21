from __future__ import annotations

import logging
from typing import List, Optional, Tuple, Union

from chia.consensus.constants import ConsensusConstants
from chia.protocols import timelord_protocol
from chia.timelord.iters_from_block import iters_from_block
from chia.timelord.types import Chain, StateType
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import ChallengeBlockInfo
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.util.ints import uint8, uint32, uint64, uint128

log = logging.getLogger(__name__)


class LastState:
    """
    Represents the state that the timelord is in, and should execute VDFs on top of. A state can be one of three types:
    1. A "peak" or a block
    2. An end of sub-slot
    3. None, if it's the first sub-slot and there are no blocks yet
    Timelords execute VDFs until they reach the next block or sub-slot, at which point the state is changed again.
    The state can also be changed arbitrarily to a sub-slot or peak, for example in the case the timelord receives
    a new block in the future.
    """

    def __init__(self, constants: ConsensusConstants):
        self.state_type: StateType = StateType.FIRST_SUB_SLOT
        self.peak: Optional[timelord_protocol.NewPeakTimelord] = None
        self.subslot_end: Optional[EndOfSubSlotBundle] = None
        self.last_ip: uint64 = uint64(0)
        self.deficit: uint8 = constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK
        self.sub_epoch_summary: Optional[SubEpochSummary] = None
        self.constants: ConsensusConstants = constants
        self.last_weight: uint128 = uint128(0)
        self.last_height: uint32 = uint32(0)
        self.total_iters: uint128 = uint128(0)
        self.last_challenge_sb_or_eos_total_iters = uint128(0)
        self.last_block_total_iters: Optional[uint128] = None
        self.last_peak_challenge: bytes32 = constants.GENESIS_CHALLENGE
        self.difficulty: uint64 = constants.DIFFICULTY_STARTING
        self.sub_slot_iters: uint64 = constants.SUB_SLOT_ITERS_STARTING
        self.reward_challenge_cache: List[Tuple[bytes32, uint128]] = [(constants.GENESIS_CHALLENGE, uint128(0))]
        self.new_epoch = False
        self.passed_ses_height_but_not_yet_included = False
        self.infused_ses = False

    def set_state(self, state: Union[timelord_protocol.NewPeakTimelord, EndOfSubSlotBundle]):
        if isinstance(state, timelord_protocol.NewPeakTimelord):
            self.state_type = StateType.PEAK
            self.peak = state
            self.subslot_end = None
            _, self.last_ip = iters_from_block(
                self.constants,
                state.reward_chain_block,
                state.sub_slot_iters,
                state.difficulty,
            )
            self.deficit = state.deficit
            self.sub_epoch_summary = state.sub_epoch_summary
            self.last_weight = state.reward_chain_block.weight
            self.last_height = state.reward_chain_block.height
            self.total_iters = state.reward_chain_block.total_iters
            self.last_peak_challenge = state.reward_chain_block.get_hash()
            self.difficulty = state.difficulty
            self.sub_slot_iters = state.sub_slot_iters
            if state.reward_chain_block.is_transaction_block:
                self.last_block_total_iters = self.total_iters
            self.reward_challenge_cache = state.previous_reward_challenges
            self.last_challenge_sb_or_eos_total_iters = self.peak.last_challenge_sb_or_eos_total_iters
            self.new_epoch = False
            if (self.peak.reward_chain_block.height + 1) % self.constants.SUB_EPOCH_BLOCKS == 0:
                self.passed_ses_height_but_not_yet_included = True
            else:
                self.passed_ses_height_but_not_yet_included = state.passes_ses_height_but_not_yet_included
        elif isinstance(state, EndOfSubSlotBundle):
            self.state_type = StateType.END_OF_SUB_SLOT
            if self.peak is not None:
                self.total_iters = uint128(self.total_iters - self.get_last_ip() + self.sub_slot_iters)
            else:
                self.total_iters = uint128(self.total_iters + self.sub_slot_iters)
            self.peak = None
            self.subslot_end = state
            self.last_ip = uint64(0)
            self.deficit = state.reward_chain.deficit
            if state.challenge_chain.new_difficulty is not None:
                assert state.challenge_chain.new_sub_slot_iters is not None
                self.difficulty = state.challenge_chain.new_difficulty
                self.sub_slot_iters = state.challenge_chain.new_sub_slot_iters
                self.new_epoch = True
            else:
                self.new_epoch = False
            if state.challenge_chain.subepoch_summary_hash is not None:
                self.infused_ses = True
                self.passed_ses_height_but_not_yet_included = False
            else:
                self.infused_ses = False
                # Since we have a new sub slot which is not an end of subepoch,
                # we will use the last value that we saw for
                # passed_ses_height_but_not_yet_included
            self.last_challenge_sb_or_eos_total_iters = self.total_iters
        else:
            assert False

        reward_challenge: Optional[bytes32] = self.get_challenge(Chain.REWARD_CHAIN)
        assert reward_challenge is not None  # Reward chain always has VDFs
        self.reward_challenge_cache.append((reward_challenge, self.total_iters))
        log.info(f"Updated timelord peak to {reward_challenge}, total iters: {self.total_iters}")
        while len(self.reward_challenge_cache) > 2 * self.constants.MAX_SUB_SLOT_BLOCKS:
            self.reward_challenge_cache.pop(0)

    def get_sub_slot_iters(self) -> uint64:
        return self.sub_slot_iters

    def can_infuse_block(self, overflow: bool) -> bool:
        if overflow and self.new_epoch:
            # No overflows in new epoch
            return False
        if self.state_type == StateType.FIRST_SUB_SLOT or self.state_type == StateType.END_OF_SUB_SLOT:
            return True
        ss_start_iters = self.get_total_iters() - self.get_last_ip()
        already_infused_count: int = 0
        for _, total_iters in self.reward_challenge_cache:
            if total_iters > ss_start_iters:
                already_infused_count += 1
        if already_infused_count >= self.constants.MAX_SUB_SLOT_BLOCKS:
            return False
        return True

    def get_weight(self) -> uint128:
        return self.last_weight

    def get_height(self) -> uint32:
        return self.last_height

    def get_total_iters(self) -> uint128:
        return self.total_iters

    def get_last_peak_challenge(self) -> Optional[bytes32]:
        return self.last_peak_challenge

    def get_difficulty(self) -> uint64:
        return self.difficulty

    def get_last_ip(self) -> uint64:
        return self.last_ip

    def get_deficit(self) -> uint8:
        return self.deficit

    def just_infused_sub_epoch_summary(self) -> bool:
        """
        Returns true if state is an end of sub-slot, and that end of sub-slot infused a sub epoch summary
        """
        return self.state_type == StateType.END_OF_SUB_SLOT and self.infused_ses

    def get_next_sub_epoch_summary(self) -> Optional[SubEpochSummary]:
        if self.state_type == StateType.FIRST_SUB_SLOT or self.state_type == StateType.END_OF_SUB_SLOT:
            # Can only infuse SES after a peak (in an end of sub slot)
            return None
        assert self.peak is not None
        if self.passed_ses_height_but_not_yet_included and self.get_deficit() == 0:
            # This will mean we will include the ses in the next sub-slot
            return self.sub_epoch_summary
        return None

    def get_last_block_total_iters(self) -> Optional[uint128]:
        return self.last_block_total_iters

    def get_passed_ses_height_but_not_yet_included(self) -> bool:
        return self.passed_ses_height_but_not_yet_included

    def get_challenge(self, chain: Chain) -> Optional[bytes32]:
        if self.state_type == StateType.FIRST_SUB_SLOT:
            assert self.peak is None and self.subslot_end is None
            if chain == Chain.CHALLENGE_CHAIN:
                return self.constants.GENESIS_CHALLENGE
            elif chain == Chain.REWARD_CHAIN:
                return self.constants.GENESIS_CHALLENGE
            elif chain == Chain.INFUSED_CHALLENGE_CHAIN:
                return None
        elif self.state_type == StateType.PEAK:
            assert self.peak is not None
            reward_chain_block = self.peak.reward_chain_block
            if chain == Chain.CHALLENGE_CHAIN:
                return reward_chain_block.challenge_chain_ip_vdf.challenge
            elif chain == Chain.REWARD_CHAIN:
                return reward_chain_block.get_hash()
            elif chain == Chain.INFUSED_CHALLENGE_CHAIN:
                if reward_chain_block.infused_challenge_chain_ip_vdf is not None:
                    return reward_chain_block.infused_challenge_chain_ip_vdf.challenge
                elif self.peak.deficit == self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                    return ChallengeBlockInfo(
                        reward_chain_block.proof_of_space,
                        reward_chain_block.challenge_chain_sp_vdf,
                        reward_chain_block.challenge_chain_sp_signature,
                        reward_chain_block.challenge_chain_ip_vdf,
                    ).get_hash()
                return None
        elif self.state_type == StateType.END_OF_SUB_SLOT:
            assert self.subslot_end is not None
            if chain == Chain.CHALLENGE_CHAIN:
                return self.subslot_end.challenge_chain.get_hash()
            elif chain == Chain.REWARD_CHAIN:
                return self.subslot_end.reward_chain.get_hash()
            elif chain == Chain.INFUSED_CHALLENGE_CHAIN:
                if self.subslot_end.reward_chain.deficit < self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                    assert self.subslot_end.infused_challenge_chain is not None
                    return self.subslot_end.infused_challenge_chain.get_hash()
                return None
        return None

    def get_initial_form(self, chain: Chain) -> Optional[ClassgroupElement]:
        if self.state_type == StateType.FIRST_SUB_SLOT:
            return ClassgroupElement.get_default_element()
        elif self.state_type == StateType.PEAK:
            assert self.peak is not None
            reward_chain_block = self.peak.reward_chain_block
            if chain == Chain.CHALLENGE_CHAIN:
                return reward_chain_block.challenge_chain_ip_vdf.output
            if chain == Chain.REWARD_CHAIN:
                return ClassgroupElement.get_default_element()
            if chain == Chain.INFUSED_CHALLENGE_CHAIN:
                if reward_chain_block.infused_challenge_chain_ip_vdf is not None:
                    return reward_chain_block.infused_challenge_chain_ip_vdf.output
                elif self.peak.deficit == self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                    return ClassgroupElement.get_default_element()
                else:
                    return None
        elif self.state_type == StateType.END_OF_SUB_SLOT:
            if chain == Chain.CHALLENGE_CHAIN or chain == Chain.REWARD_CHAIN:
                return ClassgroupElement.get_default_element()
            if chain == Chain.INFUSED_CHALLENGE_CHAIN:
                assert self.subslot_end is not None
                if self.subslot_end.reward_chain.deficit < self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                    return ClassgroupElement.get_default_element()
                else:
                    return None
        return None
