import asyncio
import io
import logging
import time
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from chiavdf import create_discriminant

from src.consensus.constants import ConsensusConstants
from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.consensus.pot_iterations import (
    calculate_iterations_quality,
    calculate_sp_iters,
    calculate_ip_iters,
)
from blspy import G2Element
from src.protocols import timelord_protocol
from src.server.outbound_message import OutboundMessage, NodeType, Message, Delivery
from src.server.server import ChiaServer
from src.types.classgroup import ClassgroupElement
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.reward_chain_sub_block import (
    RewardChainSubBlock,
    RewardChainSubBlockUnfinished,
)
from src.types.sized_bytes import bytes32
from src.types.slots import ChallengeChainSubSlot, InfusedChallengeChainSubSlot, RewardChainSubSlot, SubSlotProofs
from src.types.vdf import VDFInfo, VDFProof
from src.util.api_decorators import api_request
from src.util.ints import uint64, uint8, uint128, int512
from src.types.sub_epoch_summary import SubEpochSummary
from src.util.block_tools import BlockTools
from chiapos import Verifier
from src.types.slots import ChallengeBlockInfo

log = logging.getLogger(__name__)


def iters_from_sub_block(
    constants,
    reward_chain_sub_block: Union[RewardChainSubBlock, RewardChainSubBlockUnfinished],
    sub_slot_iters: uint64,
    difficulty: uint64,
) -> Tuple[uint64, uint64]:
    v = Verifier()
    pos = reward_chain_sub_block.proof_of_space
    plot_id: bytes32 = pos.get_plot_id()
    quality = v.validate_proof(plot_id, pos.size, pos.challenge_hash, bytes(pos.proof))

    if reward_chain_sub_block.challenge_chain_sp_vdf is None:
        assert reward_chain_sub_block.signage_point_index == 0
        cc_sp: bytes32 = reward_chain_sub_block.proof_of_space.challenge_hash
    else:
        cc_sp: bytes32 = reward_chain_sub_block.challenge_chain_sp_vdf.get_hash()
    required_iters = calculate_iterations_quality(
        quality,
        reward_chain_sub_block.proof_of_space.size,
        difficulty,
        cc_sp,
    )
    return (
        calculate_sp_iters(constants, sub_slot_iters, reward_chain_sub_block.signage_point_index),
        calculate_ip_iters(constants, sub_slot_iters, reward_chain_sub_block.signage_point_index, required_iters),
    )

class EndOfSubSlotData:
    eos_bundle: EndOfSubSlotBundle
    sub_slot_iters: uint64
    new_difficulty: uint64
    deficit: uint8

    def __init__(self, eos_bundle, sub_slot_iters, new_difficulty, deficit):
        self.eos_bundle = eos_bundle
        self.sub_slot_iters = sub_slot_iters
        self.new_difficulty = new_difficulty
        self.deficit = deficit

class Chain(Enum):
    CHALLENGE_CHAIN = 1
    REWARD_CHAIN = 2
    INFUSED_CHALLENGE_CHAIN = 3

class IterationType(Enum):
    SIGNAGE_POINT = 1
    INFUSION_POINT = 2
    END_OF_SUBSLOT = 3

class LastState:
    def __init__(self, constants):
        self.peak: Optional[timelord_protocol.NewPeak] = None
        self.subslot_end: Optional[EndOfSubSlotData] = None
        self.last_ip: uint64 = 0
        self.deficit: uint8 = 0
        self.sub_epoch_summary: Optional[SubEpochSummary] = None
        self.constants = constants
        self.last_weight = 0
        self.total_iters = 0
        self.last_peak_challenge: Optional[bytes32] = None

    def set_state(self, state):
        if isinstance(state, timelord_protocol.NewPeak):
            self.peak = state
            self.subslot_end = None
            _, self.last_ip = iters_from_sub_block(
                self.constants,
                state.reward_chain_sub_block,
                state.sub_slot_iters,
                state.difficulty,
            )
            self.deficit = state.deficit
            self.sub_epoch_summary = state.sub_epoch_summary
            self.last_weight = state.reward_chain_sub_block.weight
            self.total_iters = state.reward_chain_sub_block.total_iters
            self.last_peak_challenge = state.reward_chain_sub_block.get_hash()
        if isinstance(state, EndOfSubSlotData):
            self.peak = None
            self.subslot_end = state
            self.last_ip = 0
            self.deficit = state.deficit
    
    def is_empty(self) -> bool:
        return self.peak is None and self.subslot_end is None

    def get_sub_slot_iters(self) -> uint64:
        if self.peak is not None:
            return self.peak.sub_slot_iters
        return self.subslot_end.sub_slot_iters
    
    def get_weight(self) -> uint64:
        return self.last_weight

    def get_total_iters(self) -> uint128:
        return self.total_iters

    def get_last_peak_challenge(self) -> Optional[bytes32]:
        return self.last_peak_challenge

    def get_difficulty(self) -> uint64:
        if self.peak is not None:
            return self.peak.difficulty
        return self.subslot_end.new_difficulty
    
    def get_last_ip(self) -> uint64:
        return self.last_ip
    
    def get_deficit(self) -> uint8:
        if self.peak is not None:
            return self.peak.deficit
        return self.subslot_end.deficit
    
    def get_sub_epoch_summary(self) -> Optional[SubEpochSummary]:
        return self.sub_epoch_summary

    def get_challenge(self, chain: Chain) -> Optional[bytes32]:
        if self.peak is not None:
            sub_block = self.peak.reward_chain_sub_block
            if chain == Chain.CHALLENGE_CHAIN:
                return sub_block.challenge_chain_ip_vdf.challenge_hash
            if chain == Chain.REWARD_CHAIN:
                return sub_block.get_hash()
            if chain == Chain.INFUSED_CHALLENGE_CHAIN:
                if sub_block.infused_challenge_chain_ip_vdf is not None:
                    return sub_block.infused_challenge_chain_ip_vdf.challenge_hash
                if self.peak.deficit == 4:
                    return ChallengeBlockInfo(
                        sub_block.proof_of_space,
                        sub_block.challenge_chain_sp_vdf,
                        sub_block.challenge_chain_sp_signature,
                        sub_block.challenge_chain_ip_vdf,
                    ).get_hash()
                return None
        if self.subslot_end is not None:
            if chain == Chain.CHALLENGE_CHAIN:
                return self.subslot_end.eos_bundle.challenge_chain.get_hash()
            if chain == Chain.REWARD_CHAIN:
                return self.subslot_end.eos_bundle.reward_chain.get_hash()
            if chain == Chain.INFUSED_CHALLENGE_CHAIN:
                if self.subslot_end.deficit < self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                    return self.subslot_end.eos_bundle.infused_challenge_chain.get_hash()
                else:
                    return None
        return None

    def get_initial_form(self, chain: Chain) -> Optional[ClassgroupElement]:
        if self.peak is not None:
            sub_block = self.peak.reward_chain_sub_block
            if chain == Chain.CHALLENGE_CHAIN:
                return sub_block.challenge_chain_ip_vdf.output
            if chain == Chain.REWARD_CHAIN:
                return ClassgroupElement.get_default_element()
            if chain == Chain.INFUSED_CHALLENGE_CHAIN:
                if sub_block.infused_challenge_chain_ip_vdf is not None:
                    return sub_block.infused_challenge_chain_ip_vdf.output
                elif self.peak.deficit == 4:
                    return ClassgroupElement.get_default_element()
                else:
                    return None
        if self.subslot_end is not None:
            if chain == Chain.CHALLENGE_CHAIN or chain == Chain.REWARD_CHAIN:
                return ClassgroupElement.get_default_element()
            if chain == Chain.INFUSED_CHALLENGE_CHAIN:
                if self.subslot_end.deficit < self.constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK:
                    return ClassgroupElement.get_default_element()
                else:
                    return None
        return None

class Timelord:
    def __init__(self, config: Dict, constants: ConsensusConstants):
        self.config = config
        self.constants = constants
        self._is_stopped = False
        self.free_clients: List[Tuple[str, asyncio.StreamReader, asyncio.StreamWriter]] = []
        self.lock: asyncio.Lock = asyncio.Lock()
        self.potential_free_clients: List = []
        self.ip_whitelist = self.config["vdf_clients"]["ip"]
        self.server: Optional[ChiaServer] = None
        self.chain_type_to_stream: Dict[Chain, Tuple[ip, asyncio.StreamReader, asyncio.StreamWriter]] = {}
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
        self.new_subslot_end: Optional[EndOfSubSlotData] = None
        # Last state received. Can either be a new peak or a new EndOfSubslotBundle.
        self.last_state: LastState = LastState(self.constants)
        # Unfinished block info, iters adjusted to the last peak.
        self.unfinished_blocks: List[timelord_protocol.NewUnfinishedSubBlock] = []
        # Signage points iters, adjusted to the last peak.
        self.signage_point_iters: List[uint64] = []
        # For each chain, send those info when the process spawns.
        self.iters_to_submit: Dict[str, List[uint64]] = {}
        self.iters_submitted: Dict[str, List[uint64]] = {}
        # For each iteration submitted, know if it's a signage point, an infusion point or an end of slot.
        self.iteration_to_proof_type: Dict[uint64, IterationType] = {}
        # List of proofs finished.
        self.proofs_finished: List[Tuple[Chain, VDFInfo, VDFProof]] = []
        # Data to send at vdf_client initialization.
        self.finished_sp = 0
        self.overflow_blocks: List[timelord_protocol.NewUnfinishedSubBlock] = []

    async def start(self):
        log.info("Starting timelord.")
        self.main_loop = asyncio.create_task(self._manage_chains())

        self.vdf_server = await asyncio.start_server(
            self._handle_client,
            self.config["vdf_server"]["host"],
            self.config["vdf_server"]["port"],
        )
        log.info("Started timelord.")

    def set_server(self, server: ChiaServer):
        self.server = server

    @api_request
    async def new_peak(self, new_peak: timelord_protocol.NewPeak):
        async with self.lock:
            if (
                self.last_state is None
                or self.last_state.get_weight() < new_peak.weight
            ):
                self.new_peak = new_peak

    @api_request
    async def new_unfinished_subblock(self, new_unfinished_subblock: timelord_protocol.NewUnfinishedSubBlock):
        async with self.lock:
            if not self._accept_unfinished_block(new_unfinished_subblock):
                return
            sp_iters, ip_iters = iters_from_sub_block(
                new_unfinished_subblock.reward_chain_sub_block,
                self.last_state.get_sub_slot_iters(),
                self.last_state.get_difficulty(),
            )
            last_ip_iters = self.last_state.get_last_ip()
            if sp_iters < ip_iters:
                self.overflow_blocks.append(new_unfinished_subblock)
            elif ip_iters > last_ip_iters:
                self.unfinished_blocks.append(new_unfinished_subblock)
                for chain in Chain:
                    self.iters_to_submit[chain].append(uint64(ip_iters - last_ip_iters))
                self.iteration_to_proof_type[ip_iters - self.last_ip_iters] = IterationType.INFUSION_POINT

    def _accept_unfinished_block(self, block: timelord_protocol.NewUnfinishedSubBlock) -> bool:
        # Total unfinished block iters needs to exceed peak's iters.
        if self.last_state.get_total_iters() >= block.total_iters:
            return False
        # The peak hash of the rc-sub-block must match 
        # the signage point rc VDF challenge hash of the unfinished sub-block.
        if (
            block.reward_chain_sp_vdf is not None
            and self.last_state.get_last_peak_challenge() is not None
            and self.last_state.get_last_peak_challenge()
            != block.reward_chain_sp_vdf.challenge_hash
        ):
            return False
        return True

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
        stop_ip, _, stop_writer = self.chain_type_to_stream[chain]
        self.potential_free_clients.append((stop_ip, time.time()))
        stop_writer.write(b"010")
        await stop_writer.drain()
        if chain in self.allows_iters:
            self.allows_iters.remove(chain)
        self.unspawned_chains.append(chain)

    async def _reset_chains(self):
        # First, stop all chains.
        ip_iters = self.last_state.get_last_ip()
        sub_slot_iters = self.last_state.get_sub_slot_iters()
        difficulty = self.last_state.get_difficulty()
        for chain in self.chain_type_to_stream.keys():
            await self._stop_chain(chain)
        # Adjust all signage points iterations to the peak.
        iters_per_signage = uint64(sub_slot_iters // self.constants.NUM_SPS_SUB_SLOT)
        self.signage_point_iters = [
            k * iters_per_signage - ip_iters
            for k in range(1, self.constants.NUM_SPS_SUB_SLOT + 1)
            if k * iters_per_signage - ip_iters > 0 and k * iters_per_signage < sub_slot_iters
        ]
        # Adjust all unfinished blocks iterations to the peak.
        new_unfinished_blocks = []
        self.proofs_finished = []
        for chain in Chain:
            self.iters_to_submit[chain] = []
            self.iters_submitted[chain] = []
        self.iteration_to_proof_type = {}
        for block in self.unfinished_blocks:
            if not self._accept_unfinished_block(block):
                continue
            block_sp_iters, block_ip_iters = iters_from_sub_block(
                self.constants,
                blocks,
                sub_slot_iters,
                difficulty,
            )
            new_block_iters = block_ip_iters - ip_iters
            if new_block_iters > 0:
                new_unfinished_blocks.append(block)
                for chain in Chain:
                    self.iters_to_submit[chain].append(new_block_iters)
                self.iteration_to_proof_type[new_block_iters] = IterationType.INFUSION_POINT
        # Remove all unfinished blocks that have already passed.
        self.unfinished_blocks = new_unfinished_blocks
        # Signage points.
        if len(self.signage_point_iters) > 0:
            count_signage = 0
            for signage in self.signage_point_iters:
                for chain in [Chain.CHALLENGE_CHAIN, Chain.REWARD_CHAIN]:
                    self.iters_to_submit[chain].append(signage)
                self.iteration_to_proof_type[signage] = IterationType.SIGNAGE_POINT
                count_signage += 1
                if count_signage == 3:
                    break
        # TODO: handle the special case when infusion point is the end of subslot.
        left_subslot_iters = sub_slot_iters - ip_iters
        log.info(f"Left subslot iters: {left_subslot_iters}.")
        for chain in Chain:
            self.iters_to_submit[chain].append(left_subslot_iters)
        self.iteration_to_proof_type[left_subslot_iters] = IterationType.END_OF_SUBSLOT

    async def _handle_new_peak(self):
        self.last_state.set_state(self.new_peak)
        self.new_peak = None
        await self._reset_chains()

    async def _handle_subslot_end(self):
        self.finished_sp = 0
        self.last_state.set_state(self.new_subslot_end)
        self.new_subslot_end = None
        await self._reset_chains()

    async def _map_chains_with_vdf_clients(self):
        while not self._is_stopped:
            picked_chain = None
            async with self.lock:
                if len(self.free_clients) == 0:
                    break
                ip, reader, writer = self.free_clients[0]
                for chain_type in self.unspawned_chains:
                    challenge_hash = self.last_state.get_challenge(chain_type)
                    initial_form = self.last_state.get_initial_form(chain_type)
                    if challenge_hash is not None and initial_form is not None:
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
            asyncio.create_task(
                self._do_process_communication(picked_chain, challenge_hash, initial_form, ip, reader, writer)
            )

    async def _submit_iterations(self):
        for chain in Chain:
            if chain in self.allows_iters:
                _, _, writer = self.chain_type_to_stream[chain]
                for iteration in self.iters_to_submit[chain]:
                    if iteration in self.iters_submitted[chain]:
                        continue
                    prefix = str(len(str(iteration)))
                    if len(str(iteration)) < 10:
                        prefix = "0" + prefix
                    iter_str = prefix + str(iteration)
                    writer.write(iter_str.encode())
                    await writer.drain()
                    self.iters_submitted[chain].append(iteration)

    def _clear_proof_list(self, iter):
        return [
            (chain, info, proof) for chain, info, proof in self.proofs_finished if info.number_of_iterations != iter
        ]

    async def _check_for_new_sp(self):
        signage_iters = [
            iteration for iteration, t in self.iteration_to_proof_type.items()
            if t == IterationType.SIGNAGE_POINT
        ]
        if len(signage_iters) == 0:
            return
        for signage_iter in signage_iters:
            proofs_with_iter = [
                (chain, info, proof)
                for chain, info, proof in self.proofs_finished
                if info.number_of_iterations == signage_iter
            ]
            # Wait for both cc and rc to have the signage point.
            if len(proofs_with_iter) == 2:
                for chain, info, proof in proofs_with_iter:
                    if chain == Chain.CHALLENGE_CHAIN:
                        cc_info = info
                        cc_proof = proof
                    if chain == Chain.REWARD_CHAIN:
                        rc_info = info
                        rc_proof = proof
                response = timelord_protocol.NewSignagePointVDF(
                    self.finished_sp,
                    cc_info,
                    cc_proof,
                    rc_info,
                    rc_proof,
                )
                if self.server is not None:
                    self.server.push_message(
                        OutboundMessage(
                            NodeType.FULL_NODE,
                            Message("new_signage_point_vdf", response),
                            Delivery.BROADCAST,
                        )
                    )
                # Cleanup the signage point from memory.
                self.signage_point_iters.remove(signage_iter)
                self.finished_sp += 1
                self.proofs_finished = self._clear_proof_list(signage_iter)
                # Send the next 3 signage point to the chains.
                next_iters_count = 0
                for next_sp in self.signage_point_iters:                
                    for chain in [Chain.CHALLENGE_CHAIN, Chain.REWARD_CHAIN]:
                        if (
                            next_sp not in self.iters_submitted[chain]
                            and next_sp not in self.iters_to_submit[chain]
                        ):
                            self.iters_to_submit[chain].append(next_sp)
                    self.iteration_to_proof_type[next_sp] = IterationType.SIGNAGE_POINT
                    next_iters_count += 1
                    if next_iters_count == 3:
                        break

    async def _check_for_new_ip(self):
        infusion_iters = [
            iteration for iteration, t in self.iteration_to_proof_type.items()
            if t == IterationType.INFUSION_POINT
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
                for unfinished_block in self.unfinished_blocks:
                    _, ip_iters = iters_from_sub_block(
                        self.constants,
                        unfinished_block,
                        self.last_state.get_sub_slot_iters(),
                        self.last_state.get_difficulty(),
                    )
                    if ip_iters - self.last_state.get_last_ip() == iteration:
                        block = unfinished_block
                        break
                if block is not None:
                    self.unfinished_blocks.remove(block)
                    challenge_hash = block.reward_chain_sub_block.get_hash()
                    icc_info = None
                    icc_proof = None
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
                    response = timelord_protocol.NewInfusionPointVDF(
                        challenge_hash,
                        cc_info,
                        cc_proof,
                        rc_info,
                        rc_proof,
                        icc_info,
                        icc_proof,
                    )
                    self.server.push_message(
                        OutboundMessage(
                            NodeType.FULL_NODE,
                            Message("new_infusion_point_vdf", response),
                            Delivery.BROADCAST,
                        )
                    )
        for iteration in infusion_iters:
            self.proofs_finished = self._clear_proof_list(iteration)

    async def _check_for_end_of_subslot(self):
        left_subslot_iters = [
            iteration for iteration, t in self.iteration_to_proof_type.items()
            if t == IterationType.END_OF_SUBSLOT
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
            log.info("Collected end of subslot vdfs.")

            icc_sub_slot: Optional[InfusedChallengeChainSubSlot] = (
                None if icc_ip_vdf is None
                else InfusedChallengeChainSubSlot(icc_ip_vdf)
            )
            icc_sub_slot_hash = icc_sub_slot.get_hash() if self.last_state.get_deficit() == 0 else None
            if self.last_state.get_sub_epoch_summary() is not None:
                ses_hash = self.last_state.get_sub_epoch_summary().get_hash()
                new_sub_slot_iters = self.last_state.get_sub_epoch_summary().new_sub_slot_iters
                new_difficulty = self.last_state.get_sub_epoch_summary().new_difficulty
            else:
                ses_hash = None
                new_sub_slot_iters = self.last_state.get_sub_slot_iters()
                new_difficulty = self.last_state.get_difficulty()
            cc_sub_slot = ChallengeChainSubSlot(cc_vdf, icc_sub_slot_hash, ses_hash, new_sub_slot_iters, new_difficulty)
            eos_deficit: uint8 = (
                self.last_state.get_deficit()
                if self.last_state.get_deficit() > 0
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
                self.server.push_message(
                    OutboundMessage(
                        NodeType.FULL_NODE,
                        Message("end_of_sub_slot_bundle", timelord_protocol.NewEndOfSubSlotVDF(eos_bundle)),
                        Delivery.BROADCAST,
                    )
                )
            log.info("Built end of subslot bundle.")
            self.unfinished_blocks = self.overflow_blocks
            self.overflow_blocks = []
            self.new_subslot_end = EndOfSubSlotData(
                eos_bundle,
                new_sub_slot_iters,
                new_difficulty,
                eos_deficit,
            )

    async def _manage_chains(self):
        while not self._is_stopped:
            await asyncio.sleep(0.1)
            # Didn't get any useful data, continue.
            async with self.lock:
                if self.last_state.is_empty() and self.new_peak is None:
                    continue
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

    async def _do_process_communication(self, chain, challenge_hash, initial_form, ip, reader, writer):
        disc: int = create_discriminant(challenge_hash, self.constants.DISCRIMINANT_SIZE_BITS)
        # Depending on the flags 'fast_algorithm' and 'sanitizer_mode',
        # the timelord tells the vdf_client what to execute.
        if self.config["fast_algorithm"]:
            # Run n-wesolowski (fast) algorithm.
            writer.write(b"N")
        else:
            # Run two-wesolowski (slow) algorithm.
            writer.write(b"N")
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
            prefix = len(str(num))
            prefix_len = len(str(prefix))
            writer.write((str(prefix_len) + str(prefix) + str(num)).encode())
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
            except Exception as e:
                # log.error(f"Exception while decoding data {e}")
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
                    f"Finished PoT chall:{challenge_hash[:10].hex()}.. {iterations_needed}" f" iters."
                    f"Estimated IPS: {ips}. Chain: {chain}"
                )

                vdf_info: VDFInfo = VDFInfo(
                    challenge_hash,
                    initial_form,
                    iterations_needed,
                    output,
                )
                vdf_proof: VDFProof = VDFProof(
                    witness_type,
                    proof_bytes,
                )

                if not vdf_proof.is_valid(self.constants, vdf_info):
                    log.error("Invalid proof of time!")
                    # continue
                async with self.lock:
                    self.proofs_finished.append(
                        (chain, vdf_info, vdf_proof)
                    )
