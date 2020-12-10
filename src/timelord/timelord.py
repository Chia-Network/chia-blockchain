import asyncio
import dataclasses
import io
import logging
import time
import traceback
from typing import Dict, List, Optional, Tuple

from chiavdf import create_discriminant

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_sp_iters,
    is_overflow_sub_block,
)
from src.protocols import timelord_protocol
from src.server.outbound_message import NodeType, Message
from src.server.server import ChiaServer
from src.timelord.iters_from_sub_block import iters_from_sub_block
from src.timelord.timelord_state import LastState
from src.timelord.types import Chain, IterationType, StateType
from src.types.classgroup import ClassgroupElement
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.reward_chain_sub_block import (
    RewardChainSubBlock,
)
from src.types.sized_bytes import bytes32
from src.types.slots import ChallengeChainSubSlot, InfusedChallengeChainSubSlot, RewardChainSubSlot, SubSlotProofs
from src.types.vdf import VDFInfo, VDFProof
from src.util.ints import uint64, uint8, int512, uint32
from src.types.sub_epoch_summary import SubEpochSummary

log = logging.getLogger(__name__)


class Timelord:
    def __init__(self, config: Dict, constants: ConsensusConstants):
        self.config = config
        self.constants = constants
        self._shut_down = False
        self.free_clients: List[Tuple[str, asyncio.StreamReader, asyncio.StreamWriter]] = []
        self.potential_free_clients: List = []
        self.ip_whitelist = self.config["vdf_clients"]["ip"]
        self.server: Optional[ChiaServer] = None
        self.chain_type_to_stream: Dict[Chain, Tuple[str, asyncio.StreamReader, asyncio.StreamWriter]] = {}
        self.chain_start_time: Dict = {}
        # Chains that currently don't have a vdf_client.
        self.unspawned_chains: List[Chain] = [
            Chain.CHALLENGE_CHAIN,
            Chain.REWARD_CHAIN,
            Chain.INFUSED_CHALLENGE_CHAIN,
        ]
        # Chains that currently accept iterations.
        self.allows_iters: List[Chain] = []
        # Last peak received, None if it's already processed.
        self.new_peak: Optional[timelord_protocol.NewPeak] = None
        # Last end of subslot bundle, None if we built a peak on top of it.
        self.new_subslot_end: Optional[EndOfSubSlotBundle] = None
        # Last state received. Can either be a new peak or a new EndOfSubslotBundle.
        self.last_state: LastState = LastState(self.constants)
        # Unfinished block info, iters adjusted to the last peak.
        self.unfinished_blocks: List[timelord_protocol.NewUnfinishedSubBlock] = []
        # Signage points iters, adjusted to the last peak.
        self.signage_point_iters: List[Tuple[uint64, uint8]] = []
        # For each chain, send those info when the process spawns.
        self.iters_to_submit: Dict[Chain, List[uint64]] = {}
        self.iters_submitted: Dict[Chain, List[uint64]] = {}
        # For each iteration submitted, know if it's a signage point, an infusion point or an end of slot.
        self.iteration_to_proof_type: Dict[uint64, IterationType] = {}
        # List of proofs finished.
        self.proofs_finished: List[Tuple[Chain, VDFInfo, VDFProof]] = []
        # Data to send at vdf_client initialization.
        self.overflow_blocks: List[timelord_protocol.NewUnfinishedSubBlock] = []

        self.process_communication_tasks: List[asyncio.Task] = []
        self.main_loop = None
        self.vdf_server = None
        self._shut_down = False

    async def _start(self):
        self.lock: asyncio.Lock = asyncio.Lock()
        self.main_loop = asyncio.create_task(self._manage_chains())

        self.vdf_server = await asyncio.start_server(
            self._handle_client,
            self.config["vdf_server"]["host"],
            self.config["vdf_server"]["port"],
        )
        log.info("Started timelord.")

    def _close(self):
        self._shut_down = True
        for task in self.process_communication_tasks:
            task.cancel()

    async def _await_closed(self):
        pass

    def set_server(self, server: ChiaServer):
        self.server = server

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        async with self.lock:
            client_ip = writer.get_extra_info("peername")[0]
            log.info(f"New timelord connection from client: {client_ip}.")
            if client_ip in self.ip_whitelist:
                self.free_clients.append((client_ip, reader, writer))
                log.info(f"Added new VDF client {client_ip}.")
                for ip, end_time in list(self.potential_free_clients):
                    if ip == client_ip:
                        self.potential_free_clients.remove((ip, end_time))
                        break

    async def _stop_chain(self, chain: Chain):
        try:
            stop_ip, _, stop_writer = self.chain_type_to_stream[chain]
            self.potential_free_clients.append((stop_ip, time.time()))
            stop_writer.write(b"010")
            await stop_writer.drain()
            if chain in self.allows_iters:
                self.allows_iters.remove(chain)
            self.unspawned_chains.append(chain)
        except ConnectionResetError as e:
            log.error(f"{e}")

    def _can_infuse_unfinished_block(self, block: timelord_protocol.NewUnfinishedSubBlock) -> Optional[uint64]:
        sub_slot_iters = self.last_state.get_sub_slot_iters()
        difficulty = self.last_state.get_difficulty()
        ip_iters = self.last_state.get_last_ip()
        rc_block = block.reward_chain_sub_block
        block_sp_iters, block_ip_iters = iters_from_sub_block(
            self.constants,
            rc_block,
            sub_slot_iters,
            difficulty,
        )
        block_sp_total_iters = self.last_state.total_iters - ip_iters + block_sp_iters
        if is_overflow_sub_block(self.constants, block.reward_chain_sub_block.signage_point_index):
            block_sp_total_iters -= self.last_state.get_sub_slot_iters()
        found_index = -1
        for index, (rc, total_iters) in enumerate(self.last_state.reward_challenge_cache):
            if rc == block.rc_prev:
                found_index = index
                break
        if found_index == -1:
            log.warning(f"Will not infuse {block.rc_prev} because it's reward chain challenge is not in the chain")
            return None

        new_block_iters = uint64(block_ip_iters - ip_iters)
        if len(self.last_state.reward_challenge_cache) > found_index + 1:
            if self.last_state.reward_challenge_cache[found_index + 1][1] < block_sp_total_iters:
                log.warning(
                    f"Will not infuse unfinished block {block.rc_prev} sp total iters {block_sp_total_iters}, "
                    f"because there is another infusion before it's SP"
                )
                return None
            if self.last_state.reward_challenge_cache[found_index][1] > block_sp_total_iters:
                log.error(
                    f"Will not infuse unfinished block {block.rc_prev}, sp total iters: {block_sp_total_iters}, "
                    f"because it's iters are too low"
                )
                return None

        if new_block_iters > 0:
            return new_block_iters
        return None

    async def _reset_chains(self):
        # First, stop all chains.
        ip_iters = self.last_state.get_last_ip()
        sub_slot_iters = self.last_state.get_sub_slot_iters()

        for chain in self.chain_type_to_stream.keys():
            await self._stop_chain(chain)

        # Adjust all signage points iterations to the peak.
        iters_per_signage = uint64(sub_slot_iters // self.constants.NUM_SPS_SUB_SLOT)
        self.signage_point_iters = [
            (k * iters_per_signage - ip_iters, k)
            for k in range(1, self.constants.NUM_SPS_SUB_SLOT)
            if k * iters_per_signage - ip_iters > 0
        ]
        for sp, k in self.signage_point_iters:
            assert k * iters_per_signage > 0
            assert k * iters_per_signage < sub_slot_iters
        # Adjust all unfinished blocks iterations to the peak.
        new_unfinished_blocks = []
        self.proofs_finished = []
        for chain in Chain:
            self.iters_to_submit[chain] = []
            self.iters_submitted[chain] = []
        self.iteration_to_proof_type = {}
        for block in self.unfinished_blocks:
            new_block_iters: Optional[uint64] = self._can_infuse_unfinished_block(block)
            if new_block_iters:
                new_unfinished_blocks.append(block)
                for chain in [Chain.REWARD_CHAIN, Chain.CHALLENGE_CHAIN]:
                    self.iters_to_submit[chain].append(new_block_iters)
                if self.last_state.get_deficit() < self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                    self.iters_to_submit[Chain.INFUSED_CHALLENGE_CHAIN].append(new_block_iters)
                self.iteration_to_proof_type[new_block_iters] = IterationType.INFUSION_POINT
        # Remove all unfinished blocks that have already passed.
        self.unfinished_blocks = new_unfinished_blocks
        # Signage points.
        if len(self.signage_point_iters) > 0:
            count_signage = 0
            for signage, k in self.signage_point_iters:
                for chain in [Chain.CHALLENGE_CHAIN, Chain.REWARD_CHAIN]:
                    self.iters_to_submit[chain].append(signage)
                self.iteration_to_proof_type[signage] = IterationType.SIGNAGE_POINT
                count_signage += 1
                if count_signage == 3:
                    break
        # TODO: handle the special case when infusion point is the end of subslot.
        left_subslot_iters = sub_slot_iters - ip_iters

        if self.last_state.get_deficit() < self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
            self.iters_to_submit[Chain.INFUSED_CHALLENGE_CHAIN].append(left_subslot_iters)
        self.iters_to_submit[Chain.CHALLENGE_CHAIN].append(left_subslot_iters)
        self.iters_to_submit[Chain.REWARD_CHAIN].append(left_subslot_iters)
        self.iteration_to_proof_type[left_subslot_iters] = IterationType.END_OF_SUBSLOT
        log.warning(f"Iters to submit {self.iters_to_submit}")

        for chain, iters in self.iters_to_submit.items():
            for iteration in iters:
                assert iteration > 0

    async def _handle_new_peak(self):
        self.last_state.set_state(self.new_peak)
        self.new_peak = None
        await self._reset_chains()

    async def _handle_subslot_end(self):
        self.last_state.set_state(self.new_subslot_end)
        self.new_subslot_end = None
        await self._reset_chains()

    async def _map_chains_with_vdf_clients(self):
        while not self._shut_down:
            picked_chain = None
            async with self.lock:
                if len(self.free_clients) == 0:
                    break
                ip, reader, writer = self.free_clients[0]
                for chain_type in self.unspawned_chains:
                    challenge = self.last_state.get_challenge(chain_type)
                    initial_form = self.last_state.get_initial_form(chain_type)
                    if challenge is not None and initial_form is not None:
                        picked_chain = chain_type
                        break
                if picked_chain is None:
                    break
                picked_chain = self.unspawned_chains[0]
                self.chain_type_to_stream[picked_chain] = (ip, reader, writer)
                self.free_clients = self.free_clients[1:]
                self.unspawned_chains = self.unspawned_chains[1:]
                self.chain_start_time[picked_chain] = time.time()

            log.info(f"Mapping free vdf_client with chain: {picked_chain}.")
            self.process_communication_tasks.append(
                asyncio.create_task(
                    self._do_process_communication(picked_chain, challenge, initial_form, ip, reader, writer)
                )
            )

    async def _submit_iterations(self):
        for chain in Chain:
            if chain in self.allows_iters:
                _, _, writer = self.chain_type_to_stream[chain]
                for iteration in self.iters_to_submit[chain]:
                    if iteration in self.iters_submitted[chain]:
                        continue
                    assert iteration > 0
                    prefix = str(len(str(iteration)))
                    if len(str(iteration)) < 10:
                        prefix = "0" + prefix
                    iter_str = prefix + str(iteration)
                    writer.write(iter_str.encode())
                    await writer.drain()
                    self.iters_submitted[chain].append(iteration)

    def _clear_proof_list(self, iters: uint64):
        return [
            (chain, info, proof) for chain, info, proof in self.proofs_finished if info.number_of_iterations != iters
        ]

    async def _check_for_new_sp(self):
        signage_iters = [
            iteration for iteration, t in self.iteration_to_proof_type.items() if t == IterationType.SIGNAGE_POINT
        ]
        if len(signage_iters) == 0:
            return
        to_remove = []
        for potential_sp_iters, signage_point_index in self.signage_point_iters:
            if potential_sp_iters not in signage_iters:
                continue
            signage_iter = potential_sp_iters
            proofs_with_iter = [
                (chain, info, proof)
                for chain, info, proof in self.proofs_finished
                if info.number_of_iterations == signage_iter
            ]
            # Wait for both cc and rc to have the signage point.
            if len(proofs_with_iter) == 2:
                cc_info: Optional[VDFInfo] = None
                cc_proof: Optional[VDFProof] = None
                rc_info: Optional[VDFInfo] = None
                rc_proof: Optional[VDFProof] = None
                for chain, info, proof in proofs_with_iter:
                    if chain == Chain.CHALLENGE_CHAIN:
                        cc_info = info
                        cc_proof = proof
                    if chain == Chain.REWARD_CHAIN:
                        rc_info = info
                        rc_proof = proof
                if cc_info is None or cc_proof is None or rc_info is None or rc_proof is None:
                    log.error(f"Insufficient signage point data {signage_iter}")
                    continue

                if rc_info.challenge != self.last_state.get_challenge(Chain.REWARD_CHAIN):
                    log.warning(
                        f"SP: Do not have correct challenge {self.last_state.get_challenge(Chain.REWARD_CHAIN).hex()}"
                        f" has {rc_info.challenge}"
                    )
                    # This proof is on an outdated challenge, so don't use it
                    continue
                iters_from_sub_slot_start = cc_info.number_of_iterations + self.last_state.get_last_ip()
                response = timelord_protocol.NewSignagePointVDF(
                    signage_point_index,
                    dataclasses.replace(cc_info, number_of_iterations=iters_from_sub_slot_start),
                    cc_proof,
                    rc_info,
                    rc_proof,
                )
                if self.server is not None:
                    msg = Message("new_signage_point_vdf", response)
                    await self.server.send_to_all([msg], NodeType.FULL_NODE)
                # Cleanup the signage point from memory.
                to_remove.append((signage_iter, signage_point_index))

                self.proofs_finished = self._clear_proof_list(signage_iter)
                # Send the next 3 signage point to the chains.
                next_iters_count = 0
                for next_sp, k in self.signage_point_iters:
                    for chain in [Chain.CHALLENGE_CHAIN, Chain.REWARD_CHAIN]:
                        if next_sp not in self.iters_submitted[chain] and next_sp not in self.iters_to_submit[chain]:
                            self.iters_to_submit[chain].append(next_sp)
                    self.iteration_to_proof_type[next_sp] = IterationType.SIGNAGE_POINT
                    next_iters_count += 1
                    if next_iters_count == 3:
                        break

                # Break so we alternate between checking SP and IP
                break
        for r in to_remove:
            self.signage_point_iters.remove(r)

    async def _check_for_new_ip(self):
        infusion_iters = [
            iteration for iteration, t in self.iteration_to_proof_type.items() if t == IterationType.INFUSION_POINT
        ]
        for iteration in infusion_iters:
            proofs_with_iter = [
                (chain, info, proof)
                for chain, info, proof in self.proofs_finished
                if info.number_of_iterations == iteration
            ]
            if self.last_state.get_challenge(Chain.INFUSED_CHALLENGE_CHAIN) is not None:
                chain_count = 3
            else:
                chain_count = 2
            if len(proofs_with_iter) == chain_count:
                block = None
                ip_iters = None
                for unfinished_block in self.unfinished_blocks:
                    _, ip_iters = iters_from_sub_block(
                        self.constants,
                        unfinished_block.reward_chain_sub_block,
                        self.last_state.get_sub_slot_iters(),
                        self.last_state.get_difficulty(),
                    )
                    if ip_iters - self.last_state.get_last_ip() == iteration:
                        block = unfinished_block
                        break
                if block is not None:
                    ip_total_iters = self.last_state.get_total_iters() + iteration
                    challenge = block.reward_chain_sub_block.get_hash()
                    icc_info: Optional[VDFInfo] = None
                    icc_proof: Optional[VDFProof] = None
                    cc_info: Optional[VDFInfo] = None
                    cc_proof: Optional[VDFProof] = None
                    rc_info: Optional[VDFInfo] = None
                    rc_proof: Optional[VDFProof] = None
                    for chain, info, proof in proofs_with_iter:
                        if chain == Chain.CHALLENGE_CHAIN:
                            cc_info = info
                            cc_proof = proof
                        if chain == Chain.REWARD_CHAIN:
                            rc_info = info
                            rc_proof = proof
                        if chain == Chain.INFUSED_CHALLENGE_CHAIN:
                            icc_info = info
                            icc_proof = proof
                    if cc_info is None or cc_proof is None or rc_info is None or rc_proof is None:
                        log.error(f"Insufficient VDF proofs for infusion point ch: {challenge} iterations:{iteration}")
                        return

                    if rc_info.challenge != self.last_state.get_challenge(Chain.REWARD_CHAIN):
                        log.warning(
                            f"Do not have correct challenge {self.last_state.get_challenge(Chain.REWARD_CHAIN).hex()} "
                            f"has {rc_info.challenge}, partial hash {block.reward_chain_sub_block.get_hash()}"
                        )
                        # This proof is on an outdated challenge, so don't use it
                        continue

                    self.unfinished_blocks.remove(block)
                    log.info(f"Generated infusion point for challenge: {challenge} iterations: {iteration}.")
                    if not self.last_state.can_infuse_sub_block():
                        log.warning("Too many sub-blocks, cannot infuse, discarding")
                        # Too many sub blocks
                        return
                    overflow = is_overflow_sub_block(self.constants, block.reward_chain_sub_block.signage_point_index)

                    cc_info = dataclasses.replace(cc_info, number_of_iterations=ip_iters)
                    response = timelord_protocol.NewInfusionPointVDF(
                        challenge,
                        cc_info,
                        cc_proof,
                        rc_info,
                        rc_proof,
                        icc_info,
                        icc_proof,
                    )
                    msg = Message("new_infusion_point_vdf", response)
                    if self.server is not None:
                        await self.server.send_to_all([msg], NodeType.FULL_NODE)

                    self.proofs_finished = self._clear_proof_list(iteration)

                    if (
                        self.last_state.get_last_block_total_iters() is None
                        and not self.last_state.state_type == StateType.FIRST_SUB_SLOT
                    ):
                        # We don't know when the last block was, so we can't make peaks
                        return

                    sp_total_iters = (
                        ip_total_iters
                        - ip_iters
                        + calculate_sp_iters(
                            self.constants, block.sub_slot_iters, block.reward_chain_sub_block.signage_point_index
                        )
                        - (block.sub_slot_iters if overflow else 0)
                    )
                    if self.last_state.state_type == StateType.FIRST_SUB_SLOT:
                        is_block = True
                        sub_block_height: uint32 = uint32(0)
                    else:
                        is_block = self.last_state.get_last_block_total_iters() < sp_total_iters
                        sub_block_height: uint32 = self.last_state.get_height() + 1

                    if sub_block_height < 5:
                        # Don't directly update our state for the first few sub-blocks, because we cannot validate
                        # whether the pre-farm is correct
                        return

                    new_reward_chain_sub_block = RewardChainSubBlock(
                        self.last_state.get_weight() + block.difficulty,
                        sub_block_height,
                        ip_total_iters,
                        block.reward_chain_sub_block.signage_point_index,
                        block.reward_chain_sub_block.pos_ss_cc_challenge_hash,
                        block.reward_chain_sub_block.proof_of_space,
                        block.reward_chain_sub_block.challenge_chain_sp_vdf,
                        block.reward_chain_sub_block.challenge_chain_sp_signature,
                        cc_info,
                        block.reward_chain_sub_block.reward_chain_sp_vdf,
                        block.reward_chain_sub_block.reward_chain_sp_signature,
                        rc_info,
                        icc_info,
                        is_block,
                    )
                    if self.last_state.state_type == StateType.FIRST_SUB_SLOT:
                        # Genesis
                        new_deficit = self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1
                    elif overflow and self.last_state.deficit == self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                        if self.last_state.peak is not None:
                            assert self.last_state.subslot_end is None
                            # This means the previous sub-block is also an overflow sub-block, and did not manage
                            # to lower the deficit, therefore we cannot lower it either. (new slot)
                            new_deficit = self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
                        else:
                            # This means we are the first infusion in this sub-slot. This may be a new slot or not.
                            assert self.last_state.subslot_end is not None
                            if self.last_state.subslot_end.infused_challenge_chain is None:
                                # There is no ICC, which means we are not finishing a slot. We can reduce the deficit.
                                new_deficit = self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1
                            else:
                                # There is an ICC, which means we are finishing a slot. Different slot, so can't change
                                # the deficit
                                new_deficit = self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
                    else:
                        new_deficit = max(self.last_state.deficit - 1, 0)

                    if new_deficit == self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                        last_csb_or_eos = ip_total_iters
                    else:
                        last_csb_or_eos = self.last_state.last_challenge_sb_or_eos_total_iters

                    if self.last_state.get_infused_sub_epoch_summary() is not None:
                        new_sub_epoch_summary = None
                    else:
                        new_sub_epoch_summary = block.sub_epoch_summary

                    self.new_peak = timelord_protocol.NewPeak(
                        new_reward_chain_sub_block,
                        block.difficulty,
                        new_deficit,
                        block.sub_slot_iters,
                        new_sub_epoch_summary,
                        self.last_state.reward_challenge_cache,
                        last_csb_or_eos,
                    )
                    await self._handle_new_peak()
                    # Break so we alternate between checking SP and IP
                    break

    async def _check_for_end_of_subslot(self):
        left_subslot_iters = [
            iteration for iteration, t in self.iteration_to_proof_type.items() if t == IterationType.END_OF_SUBSLOT
        ]
        if len(left_subslot_iters) == 0:
            return
        chains_finished = [
            (chain, info, proof)
            for chain, info, proof in self.proofs_finished
            if info.number_of_iterations == left_subslot_iters[0]
        ]
        if self.last_state.get_challenge(Chain.INFUSED_CHALLENGE_CHAIN) is not None:
            chain_count = 3
        else:
            chain_count = 2
        if len(chains_finished) == chain_count:
            icc_ip_vdf: Optional[VDFInfo] = None
            icc_ip_proof: Optional[VDFProof] = None
            cc_vdf: Optional[VDFInfo] = None
            cc_proof: Optional[VDFProof] = None
            rc_vdf: Optional[VDFInfo] = None
            rc_proof: Optional[VDFProof] = None
            for chain, info, proof in chains_finished:
                if chain == Chain.CHALLENGE_CHAIN:
                    cc_vdf = info
                    cc_proof = proof
                if chain == Chain.REWARD_CHAIN:
                    rc_vdf = info
                    rc_proof = proof
                if chain == Chain.INFUSED_CHALLENGE_CHAIN:
                    icc_ip_vdf = info
                    icc_ip_proof = proof
            assert cc_proof is not None and rc_proof is not None and cc_vdf is not None and rc_vdf is not None

            if rc_vdf.challenge != self.last_state.get_challenge(Chain.REWARD_CHAIN):
                log.warning(
                    f"Do not have correct challenge {self.last_state.get_challenge(Chain.REWARD_CHAIN).hex()} has"
                    f" {rc_vdf.challenge}"
                )
                # This proof is on an outdated challenge, so don't use it
                return
            log.info("Collected end of subslot vdfs.")
            iters_from_sub_slot_start = cc_vdf.number_of_iterations + self.last_state.get_last_ip()
            cc_vdf = dataclasses.replace(cc_vdf, number_of_iterations=iters_from_sub_slot_start)
            if icc_ip_vdf is not None:
                if self.last_state.peak is not None:
                    total_iters = (
                        self.last_state.get_total_iters()
                        - self.last_state.get_last_ip()
                        + self.last_state.get_sub_slot_iters()
                    )
                else:
                    total_iters = self.last_state.get_total_iters() + self.last_state.get_sub_slot_iters()
                iters_from_cb = uint64(total_iters - self.last_state.last_challenge_sb_or_eos_total_iters)
                if iters_from_cb > self.last_state.sub_slot_iters:
                    log.error(f"{self.last_state.peak}")
                    log.error(f"{self.last_state.subslot_end}")
                    assert False
                assert iters_from_cb <= self.last_state.sub_slot_iters
                icc_ip_vdf = dataclasses.replace(icc_ip_vdf, number_of_iterations=iters_from_cb)

            icc_sub_slot: Optional[InfusedChallengeChainSubSlot] = (
                None if icc_ip_vdf is None else InfusedChallengeChainSubSlot(icc_ip_vdf)
            )
            icc_sub_slot_hash = icc_sub_slot.get_hash() if self.last_state.get_deficit() == 0 else None
            next_ses: Optional[SubEpochSummary] = self.last_state.get_next_sub_epoch_summary()
            if next_ses is not None:
                log.info(f"Including sub epoch summary{next_ses}")
                ses_hash = next_ses.get_hash()
                new_sub_slot_iters = next_ses.new_sub_slot_iters
                new_difficulty = next_ses.new_difficulty
            else:
                ses_hash = None
                new_sub_slot_iters = None
                new_difficulty = None
            cc_sub_slot = ChallengeChainSubSlot(cc_vdf, icc_sub_slot_hash, ses_hash, new_sub_slot_iters, new_difficulty)
            eos_deficit: uint8 = (
                self.last_state.get_deficit()
                if self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK > self.last_state.get_deficit() > 0
                else self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
            )
            rc_sub_slot = RewardChainSubSlot(
                rc_vdf,
                cc_sub_slot.get_hash(),
                icc_sub_slot.get_hash() if icc_sub_slot is not None else None,
                eos_deficit,
            )
            eos_bundle = EndOfSubSlotBundle(
                cc_sub_slot,
                icc_sub_slot,
                rc_sub_slot,
                SubSlotProofs(cc_proof, icc_ip_proof, rc_proof),
            )
            if self.server is not None:
                msg = Message("new_end_of_sub_slot_vdf", timelord_protocol.NewEndOfSubSlotVDF(eos_bundle))
                await self.server.send_to_all([msg], NodeType.FULL_NODE)

            log.info(
                f"Built end of subslot bundle. cc hash: {eos_bundle.challenge_chain.get_hash()}. New_difficulty: "
                f"{eos_bundle.challenge_chain.new_difficulty} New ssi: {eos_bundle.challenge_chain.new_sub_slot_iters}"
            )

            if next_ses is None or next_ses.new_difficulty is None:
                self.unfinished_blocks = self.overflow_blocks
            else:
                # No overflow blocks in a new epoch
                self.unfinished_blocks = []
            self.overflow_blocks = []
            self.new_subslot_end = eos_bundle

    async def _manage_chains(self):
        async with self.lock:
            await asyncio.sleep(5)
            await self._reset_chains()
        while not self._shut_down:
            try:
                await asyncio.sleep(0.1)
                # Didn't get any useful data, continue.
                # Map free vdf_clients to unspawned chains.
                await self._map_chains_with_vdf_clients()
                async with self.lock:
                    # We've got a new peak, process it.
                    if self.new_peak is not None:
                        await self._handle_new_peak()
                    # A subslot ended, process it.
                    if self.new_subslot_end is not None:
                        await self._handle_subslot_end()
                    # Submit pending iterations.
                    await self._submit_iterations()
                    # Check for new signage point and broadcast it if present.
                    await self._check_for_new_sp()
                    # Check for new infusion point and broadcast it if present.
                    await self._check_for_new_ip()
                    # Check for end of subslot, respawn chains and build EndOfSubslotBundle.
                    await self._check_for_end_of_subslot()
            except Exception:
                tb = traceback.format_exc()
                log.error(f"Error while handling message: {tb}")

    async def _do_process_communication(
        self,
        chain: Chain,
        challenge: bytes32,
        initial_form: ClassgroupElement,
        ip: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        disc: int = create_discriminant(challenge, self.constants.DISCRIMINANT_SIZE_BITS)

        try:
            # Depending on the flags 'fast_algorithm' and 'sanitizer_mode',
            # the timelord tells the vdf_client what to execute.
            if self.config["fast_algorithm"]:
                # Run n-wesolowski (fast) algorithm.
                writer.write(b"N")
            else:
                # Run two-wesolowski (slow) algorithm.
                writer.write(b"T")
            await writer.drain()

            prefix = str(len(str(disc)))
            if len(prefix) == 1:
                prefix = "00" + prefix
            if len(prefix) == 2:
                prefix = "0" + prefix
            writer.write((prefix + str(disc)).encode())
            await writer.drain()

            # Send (a, b) from 'initial_form'.
            for num in [initial_form.a, initial_form.b]:
                prefix_l = len(str(num))
                prefix_len = len(str(prefix_l))
                writer.write((str(prefix_len) + str(prefix_l) + str(num)).encode())
                await writer.drain()
            try:
                ok = await reader.readexactly(2)
            except (asyncio.IncompleteReadError, ConnectionResetError, Exception) as e:
                log.warning(f"{type(e)} {e}")
                return

            if ok.decode() != "OK":
                return

            log.info("Got handshake with VDF client.")
            async with self.lock:
                self.allows_iters.append(chain)
            # Listen to the client until "STOP" is received.
            while True:
                try:
                    data = await reader.readexactly(4)
                except (asyncio.IncompleteReadError, ConnectionResetError, Exception) as e:
                    log.warning(f"{type(e)} {e}")
                    break

                msg = ""
                try:
                    msg = data.decode()
                except Exception:
                    pass
                if msg == "STOP":
                    log.info(f"Stopped client running on ip {ip}.")
                    async with self.lock:
                        writer.write(b"ACK")
                        await writer.drain()
                    break
                else:
                    try:
                        # This must be a proof, 4 bytes is length prefix
                        length = int.from_bytes(data, "big")
                        proof = await reader.readexactly(length)
                        stdout_bytes_io: io.BytesIO = io.BytesIO(bytes.fromhex(proof.decode()))
                    except (
                        asyncio.IncompleteReadError,
                        ConnectionResetError,
                        Exception,
                    ) as e:
                        log.warning(f"{type(e)} {e}")
                        break

                    iterations_needed = uint64(int.from_bytes(stdout_bytes_io.read(8), "big", signed=True))

                    y_size_bytes = stdout_bytes_io.read(8)
                    y_size = uint64(int.from_bytes(y_size_bytes, "big", signed=True))

                    y_bytes = stdout_bytes_io.read(y_size)
                    witness_type = uint8(int.from_bytes(stdout_bytes_io.read(1), "big", signed=True))
                    proof_bytes: bytes = stdout_bytes_io.read()

                    # Verifies our own proof just in case
                    a = int.from_bytes(y_bytes[:129], "big", signed=True)
                    b = int.from_bytes(y_bytes[129:], "big", signed=True)
                    output = ClassgroupElement(int512(a), int512(b))
                    time_taken = time.time() - self.chain_start_time[chain]
                    ips = int(iterations_needed / time_taken * 10) / 10
                    log.info(
                        f"Finished PoT chall:{challenge[:10].hex()}.. {iterations_needed}"
                        f" iters."
                        f"Estimated IPS: {ips}. Chain: {chain}"
                    )

                    vdf_info: VDFInfo = VDFInfo(
                        challenge,
                        iterations_needed,
                        output,
                    )
                    vdf_proof: VDFProof = VDFProof(
                        witness_type,
                        proof_bytes,
                    )

                    if not vdf_proof.is_valid(self.constants, initial_form, vdf_info):
                        log.error("Invalid proof of time!")
                    async with self.lock:
                        self.proofs_finished.append((chain, vdf_info, vdf_proof))
        except ConnectionResetError as e:
            log.info(f"Connection reset with VDF client {e}")
