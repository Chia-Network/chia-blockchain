from __future__ import annotations

import asyncio
import dataclasses
import io
import logging
import multiprocessing
import os
import random
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, cast

from chiavdf import create_discriminant, prove

from chia.consensus.constants import ConsensusConstants
from chia.consensus.pot_iterations import calculate_sp_iters, is_overflow_block
from chia.protocols import timelord_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.rpc.rpc_server import StateChangedProtocol, default_get_connections
from chia.server.outbound_message import NodeType, make_msg
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.timelord.iters_from_block import iters_from_block
from chia.timelord.timelord_state import LastState
from chia.timelord.types import Chain, IterationType, StateType
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.reward_chain_block import RewardChainBlock
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import (
    ChallengeChainSubSlot,
    InfusedChallengeChainSubSlot,
    RewardChainSubSlot,
    SubSlotProofs,
)
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo, VDFProof
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.util.config import process_config_start_method
from chia.util.ints import uint8, uint16, uint32, uint64, uint128
from chia.util.setproctitle import getproctitle, setproctitle
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclasses.dataclass(frozen=True)
class BlueboxProcessData(Streamable):
    challenge: bytes32
    size_bits: uint16
    iters: uint64


def prove_bluebox_slow(payload: bytes) -> bytes:
    bluebox_process_data = BlueboxProcessData.from_bytes(payload)
    initial_el = b"\x08" + (b"\x00" * 99)
    return cast(
        bytes,
        prove(
            bluebox_process_data.challenge,
            initial_el,
            bluebox_process_data.size_bits,
            bluebox_process_data.iters,
        ),
    )


class Timelord:
    @property
    def server(self) -> ChiaServer:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._server is None:
            raise RuntimeError("server not assigned")

        return self._server

    def __init__(self, root_path: Path, config: Dict[str, Any], constants: ConsensusConstants) -> None:
        self.config = config
        self.root_path = root_path
        self.constants = constants
        self._shut_down = False
        self.free_clients: List[Tuple[str, asyncio.StreamReader, asyncio.StreamWriter]] = []
        self.ip_whitelist = self.config["vdf_clients"]["ip"]
        self._server: Optional[ChiaServer] = None
        self.chain_type_to_stream: Dict[Chain, Tuple[str, asyncio.StreamReader, asyncio.StreamWriter]] = {}
        self.chain_start_time: Dict[Chain, float] = {}
        # Chains that currently don't have a vdf_client.
        self.unspawned_chains: List[Chain] = [
            Chain.CHALLENGE_CHAIN,
            Chain.REWARD_CHAIN,
            Chain.INFUSED_CHALLENGE_CHAIN,
        ]
        # Chains that currently accept iterations.
        self.allows_iters: List[Chain] = []
        # Last peak received, None if it's already processed.
        self.new_peak: Optional[timelord_protocol.NewPeakTimelord] = None
        # Last state received. Can either be a new peak or a new EndOfSubslotBundle.
        # Unfinished block info, iters adjusted to the last peak.
        self.unfinished_blocks: List[timelord_protocol.NewUnfinishedBlockTimelord] = []
        # Signage points iters, adjusted to the last peak.
        self.signage_point_iters: List[Tuple[uint64, uint8]] = []
        # For each chain, send those info when the process spawns.
        self.iters_to_submit: Dict[Chain, List[uint64]] = {}
        self.iters_submitted: Dict[Chain, List[uint64]] = {}
        self.iters_finished: Set[uint64] = set()
        # For each iteration submitted, know if it's a signage point, an infusion point or an end of slot.
        self.iteration_to_proof_type: Dict[uint64, IterationType] = {}
        # List of proofs finished.
        self.proofs_finished: List[Tuple[Chain, VDFInfo, VDFProof, int]] = []
        # Data to send at vdf_client initialization.
        self.overflow_blocks: List[timelord_protocol.NewUnfinishedBlockTimelord] = []
        # Incremented each time `reset_chains` has been called.
        # Used to label proofs in `finished_proofs` and to only filter proofs corresponding to the most recent state.
        self.num_resets: int = 0

        multiprocessing_start_method = process_config_start_method(config=self.config, log=log)
        self.multiprocessing_context = multiprocessing.get_context(method=multiprocessing_start_method)

        self.process_communication_tasks: List[asyncio.Task[None]] = []
        self.main_loop: Optional[asyncio.Task[None]] = None
        self.vdf_server: Optional[asyncio.base_events.Server] = None
        self._shut_down = False
        self.vdf_failures: List[Tuple[Chain, Optional[int]]] = []
        self.vdf_failures_count: int = 0
        self.vdf_failure_time: float = 0
        self.total_unfinished: int = 0
        self.total_infused: int = 0
        self.state_changed_callback: Optional[StateChangedProtocol] = None
        self.bluebox_mode = self.config.get("bluebox_mode", False)
        # Support backwards compatibility for the old `config.yaml` that has field `sanitizer_mode`.
        if not self.bluebox_mode:
            self.bluebox_mode = self.config.get("sanitizer_mode", False)
        self.pending_bluebox_info: List[Tuple[float, timelord_protocol.RequestCompactProofOfTime]] = []
        self.last_active_time = time.time()
        self.max_allowed_inactivity_time = 60
        self.bluebox_pool: Optional[ProcessPoolExecutor] = None

    async def _start(self) -> None:
        self.lock: asyncio.Lock = asyncio.Lock()
        self.vdf_server = await asyncio.start_server(
            self._handle_client,
            self.config["vdf_server"]["host"],
            int(self.config["vdf_server"]["port"]),
        )
        self.last_state: LastState = LastState(self.constants)
        slow_bluebox = self.config.get("slow_bluebox", False)
        if not self.bluebox_mode:
            self.main_loop = asyncio.create_task(self._manage_chains())
        else:
            if os.name == "nt" or slow_bluebox:
                # `vdf_client` doesn't build on windows, use `prove()` from chiavdf.
                workers = self.config.get("slow_bluebox_process_count", 1)
                self.bluebox_pool = ProcessPoolExecutor(
                    max_workers=workers,
                    mp_context=self.multiprocessing_context,
                    initializer=setproctitle,
                    initargs=(f"{getproctitle()}_worker",),
                )
                self.main_loop = asyncio.create_task(
                    self._start_manage_discriminant_queue_sanitizer_slow(self.bluebox_pool, workers)
                )
            else:
                self.main_loop = asyncio.create_task(self._manage_discriminant_queue_sanitizer())
        log.info(f"Started timelord, listening on port {self.get_vdf_server_port()}")

    def get_connections(self, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

    async def on_connect(self, connection: WSChiaConnection) -> None:
        pass

    def get_vdf_server_port(self) -> Optional[uint16]:
        if self.vdf_server is not None:
            return uint16(self.vdf_server.sockets[0].getsockname()[1])
        return None

    def _close(self) -> None:
        self._shut_down = True
        for task in self.process_communication_tasks:
            task.cancel()
        if self.main_loop is not None:
            self.main_loop.cancel()
        if self.bluebox_pool is not None:
            self.bluebox_pool.shutdown()

    async def _await_closed(self) -> None:
        pass

    def _set_state_changed_callback(self, callback: StateChangedProtocol) -> None:
        self.state_changed_callback = callback

    def state_changed(self, change: str, change_data: Optional[Dict[str, Any]] = None) -> None:
        if self.state_changed_callback is not None:
            self.state_changed_callback(change, change_data)

    def set_server(self, server: ChiaServer) -> None:
        self._server = server

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async with self.lock:
            client_ip = writer.get_extra_info("peername")[0]
            log.debug(f"New timelord connection from client: {client_ip}.")
            if client_ip in self.ip_whitelist:
                self.free_clients.append((client_ip, reader, writer))
                log.debug(f"Added new VDF client {client_ip}.")

    async def _stop_chain(self, chain: Chain) -> None:
        try:
            _, _, stop_writer = self.chain_type_to_stream[chain]
            if chain in self.allows_iters:
                stop_writer.write(b"010")
                await stop_writer.drain()
                self.allows_iters.remove(chain)
            else:
                log.error(f"Trying to stop {chain} before its initialization.")
                stop_writer.close()
                await stop_writer.wait_closed()
            if chain not in self.unspawned_chains:
                self.unspawned_chains.append(chain)
            del self.chain_type_to_stream[chain]
        except ConnectionResetError as e:
            log.error(f"{e}")
        except Exception as e:
            log.error(f"Exception in stop chain: {type(e)} {e}")

    def get_height(self) -> uint32:
        if self.last_state.state_type == StateType.FIRST_SUB_SLOT:
            return uint32(0)
        else:
            return uint32(self.last_state.get_height() + 1)

    def _can_infuse_unfinished_block(self, block: timelord_protocol.NewUnfinishedBlockTimelord) -> Optional[uint64]:
        assert self.last_state is not None
        sub_slot_iters = self.last_state.get_sub_slot_iters()
        difficulty = self.last_state.get_difficulty()
        ip_iters = self.last_state.get_last_ip()
        rc_block = block.reward_chain_block
        try:
            block_sp_iters, block_ip_iters = iters_from_block(
                self.constants,
                rc_block,
                sub_slot_iters,
                difficulty,
                self.get_height(),
            )
        except Exception as e:
            log.warning(f"Received invalid unfinished block: {e}.")
            return None
        block_sp_total_iters = self.last_state.total_iters - ip_iters + block_sp_iters
        if is_overflow_block(self.constants, block.reward_chain_block.signage_point_index):
            block_sp_total_iters -= self.last_state.get_sub_slot_iters()
        found_index = -1
        for index, (rc, total_iters) in enumerate(self.last_state.reward_challenge_cache):
            if rc == block.rc_prev:
                found_index = index
                break
        if found_index == -1:
            log.warning(f"Will not infuse {block.rc_prev} because its reward chain challenge is not in the chain")
            return None
        if ip_iters > block_ip_iters:
            log.warning("Too late to infuse block")
            return None

        new_block_iters = uint64(block_ip_iters - ip_iters)
        if len(self.last_state.reward_challenge_cache) > found_index + 1:
            if self.last_state.reward_challenge_cache[found_index + 1][1] < block_sp_total_iters:
                log.warning(
                    f"Will not infuse unfinished block {block.rc_prev} sp total iters {block_sp_total_iters}, "
                    f"because there is another infusion before its SP"
                )
                return None
            if self.last_state.reward_challenge_cache[found_index][1] > block_sp_total_iters:
                if not is_overflow_block(self.constants, block.reward_chain_block.signage_point_index):
                    log.error(
                        f"Will not infuse unfinished block {block.rc_prev}, sp total iters: {block_sp_total_iters}, "
                        f"because its iters are too low"
                    )
                return None

        if new_block_iters > 0:
            return new_block_iters
        return None

    async def _reset_chains(self, *, first_run: bool = False, only_eos: bool = False) -> None:
        # First, stop all chains.
        self.last_active_time = time.time()
        log.debug("Resetting chains")
        ip_iters = self.last_state.get_last_ip()
        sub_slot_iters = self.last_state.get_sub_slot_iters()

        if not first_run:
            for chain in list(self.chain_type_to_stream.keys()):
                await self._stop_chain(chain)

        # Adjust all signage points iterations to the peak.
        iters_per_signage = uint64(sub_slot_iters // self.constants.NUM_SPS_SUB_SLOT)
        self.signage_point_iters = [
            (uint64(k * iters_per_signage - ip_iters), uint8(k))
            for k in range(1, self.constants.NUM_SPS_SUB_SLOT)
            if k * iters_per_signage - ip_iters > 0
        ]
        for sp, k in self.signage_point_iters:
            assert k * iters_per_signage > 0
            assert k * iters_per_signage < sub_slot_iters
        # Adjust all unfinished blocks iterations to the peak.
        new_unfinished_blocks = []
        self.iters_finished = set()
        self.proofs_finished = []
        self.num_resets += 1
        for chain in [Chain.CHALLENGE_CHAIN, Chain.REWARD_CHAIN, Chain.INFUSED_CHALLENGE_CHAIN]:
            self.iters_to_submit[chain] = []
            self.iters_submitted[chain] = []
        self.iteration_to_proof_type = {}
        if not only_eos:
            for block in self.unfinished_blocks + self.overflow_blocks:
                new_block_iters: Optional[uint64] = self._can_infuse_unfinished_block(block)
                # Does not add duplicates, or blocks that we cannot infuse
                if new_block_iters and new_block_iters not in self.iters_to_submit[Chain.CHALLENGE_CHAIN]:
                    if block not in self.unfinished_blocks:
                        self.total_unfinished += 1
                    new_unfinished_blocks.append(block)
                    for chain in [Chain.REWARD_CHAIN, Chain.CHALLENGE_CHAIN]:
                        self.iters_to_submit[chain].append(new_block_iters)
                    if self.last_state.get_deficit() < self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                        self.iters_to_submit[Chain.INFUSED_CHALLENGE_CHAIN].append(new_block_iters)
                    self.iteration_to_proof_type[new_block_iters] = IterationType.INFUSION_POINT
        # Remove all unfinished blocks that have already passed.
        self.unfinished_blocks = new_unfinished_blocks
        # Signage points.
        if not only_eos and len(self.signage_point_iters) > 0:
            count_signage = 0
            for signage, k in self.signage_point_iters:
                for chain in [Chain.CHALLENGE_CHAIN, Chain.REWARD_CHAIN]:
                    self.iters_to_submit[chain].append(signage)
                self.iteration_to_proof_type[signage] = IterationType.SIGNAGE_POINT
                count_signage += 1
                if count_signage == 3:
                    break
        left_subslot_iters = uint64(sub_slot_iters - ip_iters)
        assert left_subslot_iters > 0

        if self.last_state.get_deficit() < self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
            self.iters_to_submit[Chain.INFUSED_CHALLENGE_CHAIN].append(left_subslot_iters)
        self.iters_to_submit[Chain.CHALLENGE_CHAIN].append(left_subslot_iters)
        self.iters_to_submit[Chain.REWARD_CHAIN].append(left_subslot_iters)
        self.iteration_to_proof_type[left_subslot_iters] = IterationType.END_OF_SUBSLOT

        for chain, iters in self.iters_to_submit.items():
            for iteration in iters:
                assert iteration > 0

    async def _handle_new_peak(self) -> None:
        assert self.new_peak is not None
        self.last_state.set_state(self.new_peak)

        if self.total_unfinished > 0:
            remove_unfinished = []
            for unf_block_timelord in self.unfinished_blocks + self.overflow_blocks:
                if (
                    unf_block_timelord.reward_chain_block.get_hash()
                    == self.new_peak.reward_chain_block.get_unfinished().get_hash()
                ):
                    if unf_block_timelord not in self.unfinished_blocks:
                        # We never got the EOS for this, but we have the block in overflow list
                        self.total_unfinished += 1

                    remove_unfinished.append(unf_block_timelord)
            if len(remove_unfinished) > 0:
                self.total_infused += 1
            for block in remove_unfinished:
                if block in self.unfinished_blocks:
                    self.unfinished_blocks.remove(block)
                if block in self.overflow_blocks:
                    self.overflow_blocks.remove(block)
            infusion_rate = round(self.total_infused / self.total_unfinished * 100.0, 2)
            log.info(
                f"Total unfinished blocks: {self.total_unfinished}. "
                f"Total infused blocks: {self.total_infused}. "
                f"Infusion rate: {infusion_rate}%."
            )

        self.new_peak = None
        await self._reset_chains()

    async def _map_chains_with_vdf_clients(self) -> None:
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

            log.debug(f"Mapping free vdf_client with chain: {picked_chain}.")
            assert challenge is not None
            assert initial_form is not None
            self.process_communication_tasks.append(
                asyncio.create_task(
                    self._do_process_communication(
                        picked_chain, challenge, initial_form, ip, reader, writer, proof_label=self.num_resets
                    )
                )
            )

    async def _submit_iterations(self) -> None:
        for chain in [Chain.CHALLENGE_CHAIN, Chain.REWARD_CHAIN, Chain.INFUSED_CHALLENGE_CHAIN]:
            if chain in self.allows_iters:
                _, _, writer = self.chain_type_to_stream[chain]
                for iteration in self.iters_to_submit[chain]:
                    if iteration in self.iters_submitted[chain]:
                        continue
                    log.debug(f"Submitting iterations to {chain}: {iteration}")
                    assert iteration > 0
                    prefix = str(len(str(iteration)))
                    if len(str(iteration)) < 10:
                        prefix = "0" + prefix
                    iter_str = prefix + str(iteration)
                    writer.write(iter_str.encode())
                    await writer.drain()
                    self.iters_submitted[chain].append(iteration)

    def _clear_proof_list(self, iters: uint64) -> List[Tuple[Chain, VDFInfo, VDFProof, int]]:
        return [
            (chain, info, proof, label)
            for chain, info, proof, label in self.proofs_finished
            if info.number_of_iterations != iters
        ]

    async def _check_for_new_sp(self, iter_to_look_for: uint64) -> None:
        signage_iters = [
            iteration for iteration, t in self.iteration_to_proof_type.items() if t == IterationType.SIGNAGE_POINT
        ]
        if len(signage_iters) == 0:
            return
        to_remove = []
        for potential_sp_iters, signage_point_index in self.signage_point_iters:
            if potential_sp_iters not in signage_iters or potential_sp_iters != iter_to_look_for:
                continue
            signage_iter = potential_sp_iters
            proofs_with_iter = [
                (chain, info, proof)
                for chain, info, proof, label in self.proofs_finished
                if info.number_of_iterations == signage_iter and label == self.num_resets
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
                self.iters_finished.add(iter_to_look_for)
                self.last_active_time = time.time()

                rc_challenge = self.last_state.get_challenge(Chain.REWARD_CHAIN)
                if rc_info.challenge != rc_challenge:
                    assert rc_challenge is not None
                    log.warning(f"SP: Do not have correct challenge {rc_challenge.hex()} has {rc_info.challenge}")
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
                if self._server is not None:
                    msg = make_msg(ProtocolMessageTypes.new_signage_point_vdf, response)
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
                    if next_iters_count == 10:
                        break

                # Break so we alternate between checking SP and IP
                break
        for r in to_remove:
            self.signage_point_iters.remove(r)

    async def _check_for_new_ip(self, iter_to_look_for: uint64) -> None:
        if len(self.unfinished_blocks) == 0:
            return
        infusion_iters = [
            iteration for iteration, t in self.iteration_to_proof_type.items() if t == IterationType.INFUSION_POINT
        ]
        for iteration in infusion_iters:
            if iteration != iter_to_look_for:
                continue
            proofs_with_iter = [
                (chain, info, proof)
                for chain, info, proof, label in self.proofs_finished
                if info.number_of_iterations == iteration and label == self.num_resets
            ]
            if self.last_state.get_challenge(Chain.INFUSED_CHALLENGE_CHAIN) is not None:
                chain_count = 3
            else:
                chain_count = 2
            if len(proofs_with_iter) == chain_count:
                block = None
                ip_iters = None
                for unfinished_block in self.unfinished_blocks:
                    try:
                        _, ip_iters = iters_from_block(
                            self.constants,
                            unfinished_block.reward_chain_block,
                            self.last_state.get_sub_slot_iters(),
                            self.last_state.get_difficulty(),
                            self.get_height(),
                        )
                    except Exception as e:
                        log.error(f"Error {e}")
                        continue
                    if ip_iters - self.last_state.get_last_ip() == iteration:
                        block = unfinished_block
                        break
                assert ip_iters is not None
                if block is not None:
                    ip_total_iters = self.last_state.get_total_iters() + iteration
                    challenge = block.reward_chain_block.get_hash()
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

                    rc_challenge = self.last_state.get_challenge(Chain.REWARD_CHAIN)
                    if rc_info.challenge != rc_challenge:
                        assert rc_challenge is not None
                        log.warning(
                            f"Do not have correct challenge {rc_challenge.hex()} "
                            f"has {rc_info.challenge}, partial hash {block.reward_chain_block.get_hash()}"
                        )
                        # This proof is on an outdated challenge, so don't use it
                        continue

                    self.iters_finished.add(iter_to_look_for)
                    self.last_active_time = time.time()
                    log.debug(f"Generated infusion point for challenge: {challenge} iterations: {iteration}.")

                    overflow = is_overflow_block(self.constants, block.reward_chain_block.signage_point_index)

                    if not self.last_state.can_infuse_block(overflow):
                        log.warning("Too many blocks, or overflow in new epoch, cannot infuse, discarding")
                        return

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
                    msg = make_msg(ProtocolMessageTypes.new_infusion_point_vdf, response)
                    if self._server is not None:
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
                            self.constants,
                            block.sub_slot_iters,
                            block.reward_chain_block.signage_point_index,
                        )
                        - (block.sub_slot_iters if overflow else 0)
                    )
                    if self.last_state.state_type == StateType.FIRST_SUB_SLOT:
                        is_transaction_block = True
                        height: uint32 = uint32(0)
                    else:
                        last_block_ti = self.last_state.get_last_block_total_iters()
                        assert last_block_ti is not None
                        is_transaction_block = last_block_ti < sp_total_iters
                        height = uint32(self.last_state.get_height() + 1)

                    if height < 5:
                        # Don't directly update our state for the first few blocks, because we cannot validate
                        # whether the pre-farm is correct
                        return

                    new_reward_chain_block = RewardChainBlock(
                        uint128(self.last_state.get_weight() + block.difficulty),
                        height,
                        uint128(ip_total_iters),
                        block.reward_chain_block.signage_point_index,
                        block.reward_chain_block.pos_ss_cc_challenge_hash,
                        block.reward_chain_block.proof_of_space,
                        block.reward_chain_block.challenge_chain_sp_vdf,
                        block.reward_chain_block.challenge_chain_sp_signature,
                        cc_info,
                        block.reward_chain_block.reward_chain_sp_vdf,
                        block.reward_chain_block.reward_chain_sp_signature,
                        rc_info,
                        icc_info,
                        is_transaction_block,
                    )
                    if self.last_state.state_type == StateType.FIRST_SUB_SLOT:
                        # Genesis
                        new_deficit = self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1
                    elif overflow and self.last_state.deficit == self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                        if self.last_state.peak is not None:
                            assert self.last_state.subslot_end is None
                            # This means the previous block is also an overflow block, and did not manage
                            # to lower the deficit, therefore we cannot lower it either. (new slot)
                            new_deficit = self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK
                        else:
                            # This means we are the first infusion in this sub-slot. This may be a new slot or not.
                            assert self.last_state.subslot_end is not None
                            if self.last_state.subslot_end.infused_challenge_chain is None:
                                # There is no ICC, which means we are not finishing a slot. We can reduce the deficit.
                                new_deficit = self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1
                            else:
                                # There is an ICC, which means we are finishing a slot. Different slot, so can't change
                                # the deficit
                                new_deficit = self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK
                    else:
                        new_deficit = max(self.last_state.deficit - 1, 0)

                    if new_deficit == self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                        last_csb_or_eos = ip_total_iters
                    else:
                        last_csb_or_eos = self.last_state.last_challenge_sb_or_eos_total_iters

                    if self.last_state.just_infused_sub_epoch_summary():
                        new_sub_epoch_summary = None
                        passed_ses_height_but_not_yet_included = False
                    else:
                        new_sub_epoch_summary = block.sub_epoch_summary
                        if new_reward_chain_block.height % self.constants.SUB_EPOCH_BLOCKS == 0:
                            passed_ses_height_but_not_yet_included = True
                        else:
                            passed_ses_height_but_not_yet_included = (
                                self.last_state.get_passed_ses_height_but_not_yet_included()
                            )

                    self.new_peak = timelord_protocol.NewPeakTimelord(
                        new_reward_chain_block,
                        block.difficulty,
                        uint8(new_deficit),
                        block.sub_slot_iters,
                        new_sub_epoch_summary,
                        self.last_state.reward_challenge_cache,
                        uint128(last_csb_or_eos),
                        passed_ses_height_but_not_yet_included,
                    )

                    await self._handle_new_peak()
                    # Break so we alternate between checking SP and IP
                    break

    async def _check_for_end_of_subslot(self, iter_to_look_for: uint64) -> None:
        left_subslot_iters = [
            iteration for iteration, t in self.iteration_to_proof_type.items() if t == IterationType.END_OF_SUBSLOT
        ]
        if len(left_subslot_iters) == 0:
            return
        if left_subslot_iters[0] != iter_to_look_for:
            return
        chains_finished = [
            (chain, info, proof)
            for chain, info, proof, label in self.proofs_finished
            if info.number_of_iterations == left_subslot_iters[0] and label == self.num_resets
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

            rc_challenge = self.last_state.get_challenge(Chain.REWARD_CHAIN)
            if rc_vdf.challenge != rc_challenge:
                assert rc_challenge is not None
                log.warning(f"Do not have correct challenge {rc_challenge.hex()} has {rc_vdf.challenge}")
                # This proof is on an outdated challenge, so don't use it
                return
            log.debug("Collected end of subslot vdfs.")
            self.iters_finished.add(iter_to_look_for)
            self.last_active_time = time.time()
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
            icc_sub_slot_hash: Optional[bytes32]
            if self.last_state.get_deficit() == 0:
                assert icc_sub_slot is not None
                icc_sub_slot_hash = icc_sub_slot.get_hash()
            else:
                icc_sub_slot_hash = None
            next_ses: Optional[SubEpochSummary] = self.last_state.get_next_sub_epoch_summary()
            ses_hash: Optional[bytes32]
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
                if self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK > self.last_state.get_deficit() > 0
                else self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK
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
            if self._server is not None:
                msg = make_msg(
                    ProtocolMessageTypes.new_end_of_sub_slot_vdf,
                    timelord_protocol.NewEndOfSubSlotVDF(eos_bundle),
                )
                await self.server.send_to_all([msg], NodeType.FULL_NODE)

            log.info(
                f"Built end of subslot bundle. cc hash: {eos_bundle.challenge_chain.get_hash()}. New_difficulty: "
                f"{eos_bundle.challenge_chain.new_difficulty} New ssi: {eos_bundle.challenge_chain.new_sub_slot_iters}"
            )

            if next_ses is None or next_ses.new_difficulty is None:
                self.unfinished_blocks = self.overflow_blocks.copy()
            else:
                # No overflow blocks in a new epoch
                self.unfinished_blocks = []
            self.overflow_blocks = []

            self.last_state.set_state(eos_bundle)
            for block in self.unfinished_blocks:
                if self._can_infuse_unfinished_block(block) is not None:
                    self.total_unfinished += 1
            await self._reset_chains()

    async def _handle_failures(self) -> None:
        if len(self.vdf_failures) > 0:
            # This can happen if one of the VDF processes has an issue. In this case, we abort all other
            # infusion points and signage points, and go straight to the end of slot, so we avoid potential
            # issues with the number of iterations that failed.

            failed_chain, proof_label = self.vdf_failures[0]
            log.error(
                f"Vdf clients failed {self.vdf_failures_count} times. Last failure: {failed_chain}, "
                f"label {proof_label}, current: {self.num_resets}"
            )
            if proof_label == self.num_resets:
                await self._reset_chains(only_eos=True)
            self.vdf_failure_time = time.time()
            self.vdf_failures = []

        # If something goes wrong in the VDF client due to a failed thread, we might get stuck in a situation where we
        # are waiting for that client to finish. Usually other peers will finish the VDFs and reset us. In the case that
        # there are no other timelords, this reset should bring the timelord back to a running state.
        if time.time() - self.vdf_failure_time < self.constants.SUB_SLOT_TIME_TARGET * 3:
            # If we have recently had a failure, allow some more time to finish the slot (we can be up to 3x slower)
            active_time_threshold = self.constants.SUB_SLOT_TIME_TARGET * 3
        else:
            # If there were no failures recently trigger a reset after 60 seconds of no activity.
            # Signage points should be every 9 seconds
            active_time_threshold = self.max_allowed_inactivity_time
        if time.time() - self.last_active_time > active_time_threshold:
            log.error(f"Not active for {active_time_threshold} seconds, restarting all chains")
            self.max_allowed_inactivity_time = min(self.max_allowed_inactivity_time * 2, 1800)
            await self._reset_chains()

    async def _manage_chains(self) -> None:
        async with self.lock:
            await asyncio.sleep(5)
            await self._reset_chains(first_run=True)
        while not self._shut_down:
            try:
                await asyncio.sleep(0.1)
                async with self.lock:
                    await self._handle_failures()
                    # We've got a new peak, process it.
                    if self.new_peak is not None:
                        await self._handle_new_peak()
                # Map free vdf_clients to unspawned chains.
                await self._map_chains_with_vdf_clients()
                async with self.lock:
                    # Submit pending iterations.
                    await self._submit_iterations()

                    not_finished_iters = [
                        it for it in self.iters_submitted[Chain.REWARD_CHAIN] if it not in self.iters_finished
                    ]
                    if len(not_finished_iters) == 0:
                        await asyncio.sleep(0.1)
                        continue
                    selected_iter = min(not_finished_iters)

                    # Check for new infusion point and broadcast it if present.
                    await self._check_for_new_ip(selected_iter)
                    # Check for new signage point and broadcast it if present.
                    await self._check_for_new_sp(selected_iter)
                    # Check for end of subslot, respawn chains and build EndOfSubslotBundle.
                    await self._check_for_end_of_subslot(selected_iter)

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
        # Data specific only when running in bluebox mode.
        bluebox_iteration: Optional[uint64] = None,
        header_hash: Optional[bytes32] = None,
        height: Optional[uint32] = None,
        field_vdf: Optional[uint8] = None,
        # Labels a proof to the current state only
        proof_label: Optional[int] = None,
    ) -> None:
        disc: int = create_discriminant(challenge, self.constants.DISCRIMINANT_SIZE_BITS)

        try:
            # Depending on the flags 'fast_algorithm' and 'bluebox_mode',
            # the timelord tells the vdf_client what to execute.
            async with self.lock:
                if self.bluebox_mode:
                    writer.write(b"S")
                else:
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
            async with self.lock:
                writer.write((prefix + str(disc)).encode())
                await writer.drain()

            # Send initial_form prefixed with its length.
            async with self.lock:
                writer.write(bytes([len(initial_form.data)]) + initial_form.data)
                await writer.drain()
            try:
                ok = await reader.readexactly(2)
            except (asyncio.IncompleteReadError, ConnectionResetError, Exception) as e:
                log.warning(f"{type(e)} {e}")
                async with self.lock:
                    self.vdf_failures.append((chain, proof_label))
                    self.vdf_failures_count += 1
                return

            if ok.decode() != "OK":
                return

            log.debug("Got handshake with VDF client.")
            if not self.bluebox_mode:
                async with self.lock:
                    self.allows_iters.append(chain)
            else:
                async with self.lock:
                    assert chain is Chain.BLUEBOX
                    assert bluebox_iteration is not None
                    prefix = str(len(str(bluebox_iteration)))
                    if len(str(bluebox_iteration)) < 10:
                        prefix = "0" + prefix
                    iter_str = prefix + str(bluebox_iteration)
                    writer.write(iter_str.encode())
                    await writer.drain()

            # Listen to the client until "STOP" is received.
            while True:
                try:
                    data = await reader.readexactly(4)
                except (
                    asyncio.IncompleteReadError,
                    ConnectionResetError,
                    Exception,
                ) as e:
                    log.warning(f"{type(e)} {e}")
                    async with self.lock:
                        self.vdf_failures.append((chain, proof_label))
                        self.vdf_failures_count += 1
                    break

                if data == b"STOP":
                    log.debug(f"Stopped client running on ip {ip}.")
                    async with self.lock:
                        writer.write(b"ACK")
                        await writer.drain()
                    break
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
                    async with self.lock:
                        self.vdf_failures.append((chain, proof_label))
                        self.vdf_failures_count += 1
                    break

                iterations_needed = uint64(int.from_bytes(stdout_bytes_io.read(8), "big", signed=True))

                y_size_bytes = stdout_bytes_io.read(8)
                y_size = uint64(int.from_bytes(y_size_bytes, "big", signed=True))

                y_bytes = stdout_bytes_io.read(y_size)
                witness_type = uint8(int.from_bytes(stdout_bytes_io.read(1), "big", signed=True))
                proof_bytes: bytes = stdout_bytes_io.read()

                # Verifies our own proof just in case
                form_size = ClassgroupElement.get_size(self.constants)
                output = ClassgroupElement.from_bytes(y_bytes[:form_size])
                # default value so that it's always set for state_changed later
                ips: float = 0
                if not self.bluebox_mode:
                    time_taken = time.time() - self.chain_start_time[chain]
                    ips = int(iterations_needed / time_taken * 10) / 10
                    log.info(
                        f"Finished PoT chall:{challenge[:10].hex()}.. {iterations_needed}"
                        f" iters, "
                        f"Estimated IPS: {ips}, Chain: {chain}"
                    )

                vdf_info: VDFInfo = VDFInfo(
                    challenge,
                    iterations_needed,
                    output,
                )
                vdf_proof: VDFProof = VDFProof(
                    witness_type,
                    proof_bytes,
                    self.bluebox_mode,
                )

                if not vdf_proof.is_valid(self.constants, initial_form, vdf_info):
                    log.error("Invalid proof of time!")
                if not self.bluebox_mode:
                    async with self.lock:
                        assert proof_label is not None
                        self.proofs_finished.append((chain, vdf_info, vdf_proof, proof_label))
                    self.state_changed(
                        "finished_pot",
                        {
                            "estimated_ips": ips,
                            "iterations_needed": iterations_needed,
                            "chain": chain.value,
                            "vdf_info": vdf_info,
                            "vdf_proof": vdf_proof,
                        },
                    )
                else:
                    async with self.lock:
                        writer.write(b"010")
                        await writer.drain()
                    assert header_hash is not None
                    assert field_vdf is not None
                    assert height is not None
                    response = timelord_protocol.RespondCompactProofOfTime(
                        vdf_info, vdf_proof, header_hash, height, field_vdf
                    )
                    if self._server is not None:
                        message = make_msg(ProtocolMessageTypes.respond_compact_proof_of_time, response)
                        await self.server.send_to_all([message], NodeType.FULL_NODE)
                    self.state_changed(
                        "new_compact_proof", {"header_hash": header_hash, "height": height, "field_vdf": field_vdf}
                    )

        except ConnectionResetError as e:
            log.debug(f"Connection reset with VDF client {e}")

    async def _manage_discriminant_queue_sanitizer(self) -> None:
        while not self._shut_down:
            async with self.lock:
                try:
                    while len(self.pending_bluebox_info) > 0 and len(self.free_clients) > 0:
                        # Select randomly the field_vdf we're creating a compact vdf for.
                        # This is done because CC_SP and CC_IP are more frequent than
                        # CC_EOS and ICC_EOS. This guarantees everything is picked uniformly.
                        target_field_vdf = random.randint(1, 4)
                        info = next(
                            (info for info in self.pending_bluebox_info if info[1].field_vdf == target_field_vdf),
                            None,
                        )
                        if info is None:
                            # Nothing found with target_field_vdf, just pick the first VDFInfo.
                            info = self.pending_bluebox_info[0]
                        ip, reader, writer = self.free_clients[0]
                        self.process_communication_tasks.append(
                            asyncio.create_task(
                                self._do_process_communication(
                                    Chain.BLUEBOX,
                                    info[1].new_proof_of_time.challenge,
                                    ClassgroupElement.get_default_element(),
                                    ip,
                                    reader,
                                    writer,
                                    info[1].new_proof_of_time.number_of_iterations,
                                    info[1].header_hash,
                                    info[1].height,
                                    info[1].field_vdf,
                                )
                            )
                        )
                        self.pending_bluebox_info.remove(info)
                        self.free_clients = self.free_clients[1:]
                except Exception as e:
                    log.error(f"Exception manage discriminant queue: {e}")
            await asyncio.sleep(0.1)

    async def _start_manage_discriminant_queue_sanitizer_slow(self, pool: ProcessPoolExecutor, counter: int) -> None:
        tasks = []
        for _ in range(counter):
            tasks.append(asyncio.create_task(self._manage_discriminant_queue_sanitizer_slow(pool)))
        for task in tasks:
            await task

    async def _manage_discriminant_queue_sanitizer_slow(self, pool: ProcessPoolExecutor) -> None:
        log.info("Started task for managing bluebox queue.")
        while not self._shut_down:
            picked_info = None
            async with self.lock:
                try:
                    if len(self.pending_bluebox_info) > 0:
                        # Select randomly the field_vdf we're creating a compact vdf for.
                        # This is done because CC_SP and CC_IP are more frequent than
                        # CC_EOS and ICC_EOS. This guarantees everything is picked uniformly.
                        target_field_vdf = random.randint(1, 4)
                        info = next(
                            (info for info in self.pending_bluebox_info if info[1].field_vdf == target_field_vdf),
                            None,
                        )
                        if info is None:
                            # Nothing found with target_field_vdf, just pick the first VDFInfo.
                            info = self.pending_bluebox_info[0]
                        self.pending_bluebox_info.remove(info)
                        picked_info = info[1]
                except Exception as e:
                    log.error(f"Exception manage discriminant queue: {e}")
            if picked_info is not None:
                try:
                    t1 = time.time()
                    log.info(
                        f"Working on compact proof for height: {picked_info.height}. "
                        f"Iters: {picked_info.new_proof_of_time.number_of_iterations}."
                    )
                    bluebox_process_data = BlueboxProcessData(
                        picked_info.new_proof_of_time.challenge,
                        uint16(self.constants.DISCRIMINANT_SIZE_BITS),
                        picked_info.new_proof_of_time.number_of_iterations,
                    )
                    proof = await asyncio.get_running_loop().run_in_executor(
                        pool,
                        prove_bluebox_slow,
                        bytes(bluebox_process_data),
                    )
                    t2 = time.time()
                    delta = t2 - t1
                    if delta > 0:
                        ips = picked_info.new_proof_of_time.number_of_iterations / delta
                    else:
                        ips = 0
                    log.info(f"Finished compact proof: {picked_info.height}. Time: {delta}s. IPS: {ips}.")
                    output = proof[:100]
                    proof_part = proof[100:200]
                    if ClassgroupElement.from_bytes(output) != picked_info.new_proof_of_time.output:
                        log.error("Expected vdf output different than produced one. Stopping.")
                        return
                    vdf_proof = VDFProof(uint8(0), proof_part, True)
                    initial_form = ClassgroupElement.get_default_element()
                    if not vdf_proof.is_valid(self.constants, initial_form, picked_info.new_proof_of_time):
                        log.error("Invalid compact proof of time!")
                        return
                    response = timelord_protocol.RespondCompactProofOfTime(
                        picked_info.new_proof_of_time,
                        vdf_proof,
                        picked_info.header_hash,
                        picked_info.height,
                        picked_info.field_vdf,
                    )
                    if self._server is not None:
                        message = make_msg(ProtocolMessageTypes.respond_compact_proof_of_time, response)
                        await self.server.send_to_all([message], NodeType.FULL_NODE)
                except Exception as e:
                    log.error(f"Exception manage discriminant queue: {e}")
                    tb = traceback.format_exc()
                    log.error(f"Error while handling message: {tb}")
            await asyncio.sleep(0.1)
