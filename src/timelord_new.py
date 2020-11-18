import asyncio
import io
import logging
import time
import socket
from typing import Dict, List, Optional, Tuple
from src.consensus.constants import ConsensusConstants

log = logging.getLogger(__name__)


class Timelord:
    def __init__(self, config: Dict, discriminant_size_bits: int):
        self.free_clients: List[
            Tuple[str, asyncio.StreamReader, asyncio.StreamWriter]
        ] = []
        self.lock: asyncio.Lock = asyncio.Lock()
        self.potential_free_clients: List = []
        self.ip_whitelist = self.config["vdf_clients"]["ip"]
        self.server: Optional[ChiaServer] = None
        self.chain_type_to_stream: Dict[
            str, Tuple[ip, asyncio.StreamReader, asyncio.StreamWriter]
        ] = {}
        # Chains that currently don't have a vdf_client.
        self.unspawned_chains: List[str] = ["cc", "rc", "icc"]
        # Chains that currently accept iterations.
        self.allows_iters: List[str] = []
        # Last peak received, None if it's already processed.
        self.last_peak: Optional[timelord_protocol.NewPeak] = None
        # Unfinished block info, iters adjusted to the last peak.
        self.unfinished_blocks: List[
            Tuple[timelord_protocol.NewUnfinishedSubBlock]
        ] = []
        # Signage points iters, adjusted to the last peak.
        self.signage_points_iters: List[uint64] = []
        # Left subslot iters, adjusted to the last peak.
        self.left_subslot_iters = 0
        # Infusion point of the peak.
        self.last_ip_iters = 0
        # For each chain, send those info when the process spawns.
        self.iters_to_submit: Dict[str, List[uint64]] = {}
        # For each iteration submitted, know if it's a signage point, an infusion point or an end of slot.
        self.iteration_to_proof_type: Dict[uint64, str] = {}
        # List of proofs finished.
        self.proofs_finished: List[Tuple[str, VDFInfo, VDFProof]] = {}
        # Data to send at vdf_client initialization.
        self.discriminant_to_submit: Dict[str, bytes32] = {}
        self.initial_form_to_submit: Dict[str, ClassgroupElement] = {}
        self.has_icc = False
        self.new_subslot = False
        self.finished_sp = 0
        self.cached_peak = None
        self.overflow_bloks: List[
            Tuple[timelord_protocol.NewUnfinishedSubBlock]
        ] = []
    
    def _set_server(self, server: ChiaServer):
        self.server = server

    @api_request
    async def new_peak(self, new_peak: timelord_protocol.NewPeak):
        async with self.lock:
            if self.cached_peak is not new_peak:
                self.last_peak = new_peak

    @api_request
    async def new_unfinished_subblock(self, new_unfinished_subblock: timelord_protocol.NewUnfinishedSubBlock):
        async with self.lock:
            sp_iters, ip_iters = self.iters_from_proof_of_space(
                new_unfinished_subblock.reward_chain_sub_block.proof_of_space,
                self.cached_peak.ips,
                self.cached_peak.difficulty,
            )
            if sp_iters < ip_iters:
                self.unfinished_blocks.append(new_unfinished_subblock)
            elif ip_iters > self.last_ip_iters:
                self.unfinished_blocks.append(new_unfinished_subblock)
                for chain in ["cc", "icc", "rc"]:
                    self.iters_to_submit[chain] = ip_iters - self.last_ip_iters
                self.iteration_to_proof_type[ip_iters - self.last_ip_iters] = "ip"

    def iters_from_proof_of_space(self, constants, pos: ProofOfSpace, ips, difficulty):
        quality = pos.verify_and_get_quality_string()
        required_iters = calculate_iterations_quality(
            quality,
            pos.size,
            difficulty,
        )
        return (
            calculate_sp_iters(constants, ips, required_iters),
            calculate_ip_iters(constants, ips, required_iters),
        )

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
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

    async def _stop_chain(self, chain):
        stop_ip, _, stop_writer = self.chain_type_to_stream[chain]
        self.potential_free_clients.append((stop_ip, time.time()))
        stop_writer.write(b"010")
        await current_writer.drain()
        if chain in self.allows_iters:
            self.allows_iters.remove(chain)
        self.unspawned_chains.append(chain)

    async def _handle_new_peak_or_subslot(self):
        # First, stop all chains.
        for chain in self.chain_type_to_stream.keys():
            await self._stop_chain(chain)
        # Store the new discriminants and initial forms to send.
        if not self.new_subslot:
            sub_block = self.last_peak.reward_chain_sub_block
            self.discriminant_to_submit["cc"] = sub_block.challenge_chain_ip_vdf.challenge_hash
            if sub_block.infused_challenge_chain_ip_vdf is not None:
                self.discriminant_to_submit["icc"] = sub_block.infused_challenge_chain_ip_vdf.challenge_hash
                self.has_icc = True
            elif sub_block.deficit == 4:
                # Is this hash correct?
                self.discriminant_to_submit["icc"] = sub_block.get_hash()
                self.has_icc = True
            self.discriminant_to_submit["rc"] = sub_block.reward_chain_ip_vdf.challenge_hash
            self.initial_form_to_submit["cc"] = sub_block.challenge_chain_ip_vdf.output
            if sub_block.infused_challenge_chain_ip_vdf is not None:
                self.initial_form_to_submit["icc"] = sub_block.infused_challenge_chain_ip_vdf.output
            elif sub_block.deficit == 4:
                self.initial_form_to_submit["icc"] = ClassgroupElement.get_default_element()
            self.initial_form_to_submit["rc"] = ClassgroupElement.get_default_element()
        # Retrieve the iterations of this peak.
        if not self.new_subslot:
            _, ip_iters = self.iters_from_proof_of_space(
                constants, self.sub_block.proof_of_space, self.last_peak.ips, self.last_peak.difficulty
            )
        else:
            ip_iters = 0
            self.new_subslot = False
        
        sub_slot_iters = calculate_sub_slot_iters(constants, self.last_peak.ips)
        # Adjust all signage points iterations to the peak.
        iters_per_signage = uint64(sub_slot_iters // constants.NUM_CHECKPOINTS_PER_SLOT)
        self.signage_point_iters = [
            k * iters_per_signage - ip_iters
            for k in range(1, constants.NUM_CHECKPOINTS_PER_SLOT + 1)
            if k * iters_per_signage - ip_iters > 0
            and k * iters_per_signage <= sub_slot_iters
        ]
        # Adjust all unfinished blocks iterations to the peak.
        new_unfinished_blocks = []
        for block in self.unfinished_blocks:
            block_sp_iters, block_ip_iters = self.iters_from_proof_of_space(
                constants, block.proof_of_space, self.last_peak.ips, self.last_peak.difficulty
            )
            if block_sp_iters < block_ip_iters:
                new_block_iters = block_ip_iters - ip_iters
            else:
                # This will get infused in the next subslot.
                new_block_iters = None
            if new_block_iters > 0:
                new_unfinished_blocks.append(block)
                for chain in ["cc", "rc", "icc"]:
                    self.iters_to_submit[chain].append(new_block_iters)
                self.iteration_to_proof_type[new_block_iters] = "ip"
        new_overflow_blocks = []
        for block in self.overflow_blocks:
            _, block_ip_iters = self.iters_from_proof_of_space(
                constants, block.proof_of_space, self.last_peak.ips, self.last_peak.difficulty
            )
            new_block_iters = block_ip_iters - ip_iters
            if new_block_iters > 0:
                new_overflow_blocks.append(block)
                for chain in ["cc", "rc", "icc"]:
                    self.iters_to_submit[chain].append(new_block_iters)
                self.iteration_to_proof_type[new_block_iters] = "ip"
        # Remove all unfinished blocks that have already passed.
        self.unfinished_blocks = new_unfinished_blocks
        self.overflow_blocks = new_overflow_blocks
        # Adjust subslot iterations to the peak.
        self.left_subslot_iters = sub_slot_iters - ip_iters
        # Finish up iters_to_submit.
        for chain in ["cc", "rc", "icc"]:
            self.iters_to_submit[chain] = []
        self.proofs_finished = []
        self.iters_to_submit = []
        self.iteration_to_proof_type = {}
        if len(self.signage_point_iters) > 0:
            smallest_sp = min(self.signage_point_iters)
            for chain in ["cc", "rc"]:
                self.iters_to_submit[chain].append(smallest_sp)
            self.iteration_to_proof_type[smallest_sp] = "sp"                
        # TODO: handle the special case when infusion point is the end of subslot.
        for chain in ["cc", "rc", "icc"]:
            self.iters_to_submit[chain].append(self.left_subslot_iters)
        self.iteration_to_proof_type[self.left_subslot_iters] = "end"
        self.last_ip_iters = ip_iters
        # Mark the peak as processed.
        self.cached_peak = self.last_peak
        self.last_peak = None

    async def _map_chains_with_vdf_clients(self):
        while not self._is_stopped:
            picked_chain = None
            async with self.lock:
                if len(self.free_clients) == 0:
                    break
                ip, reader, writer = self.free_clients[0]
                for chain_type in self.unspawned_chains:
                    if (
                        chain_type in self.discriminant_to_submit
                        and chain_type in self.initial_form_to_submit
                    ):
                        picked_chain = chain_type
                        break
                if picked_chain is None:
                    break
                picked_chain = self.unspawned_chains[0]
                self.chain_type_to_stream[picked_chain] = (ip, reader, writer)
                self.free_clients = self.free_clients[:1]
                self.unspawned_chains = self.unspawned_chains[:1]
                challenge_hash = self.discriminant_to_submit[picked_chain]
                initial_form = self.initial_form_to_submit[picked_chain]
                del self.discriminant_to_submit[picked_chain]
                del self.initial_form_to_submit[picked_chain]

            asyncio.create_task(
                self._do_process_communication(
                    picked_chain, challenge_hash, initial_form, ip, reader, writer
                )
            )

    async def _submit_iterations(self):
        for chain in ["cc", "rc", "icc"]:
            if chain in self.allows_iters:
                _, _, writer = self.chain_type_to_stream[chain]
                for iter in self.iters_to_submit[chain]:
                    prefix = str(len(str(iter)))
                    prefix_len = str(len(prefix))
                    iter_str = prefix_len + prefix + str(iter)
                    writer.write(iter_str.encode())
                self.iters_to_submit[chain].clear()

    def _clear_proof_list(self, iter):
        return [
            (chain, info, proof)
            for chain, info, proof in self.proofs_finished
            if info.number_of_iterations != iter
        ]

    async def _check_for_new_sp(self):
        signage_iters = [
            iter
            for iter, t in self.iteration_to_proof_type
            if t == "sp"
        ]
        if len(signage_iters) > 1:
            log.error("Warning: more than 1 signage iter sent.")
        if len(signage_iters) == 0:
            return
        proofs_with_iter = [
            (chain, info, proof)
            for chain, info, proof in self.proofs_finished
            if info.number_of_iterations == signage_iters[0]
        ]
        # Wait for both cc and rc to have the signage point.
        if len(proofs_with_iter) == 2:
            for chain, info, proof in proofs_with_iter:
                if chain == "cc":
                    cc_info = info
                    cc_proof = proof
                else:
                    rc_info = info
                    rc_proof = proof
            response = timelord_protocol.NewSignagePointVDF(
                self.finished_sp,
                cc_info,
                cc_proof,
                rc_info,
                rc_proof,
            )
            self.server.push_message(
                OutboundMessage(
                    NodeType.FULL_NODE,
                    Message("new_signage_point_vdf", response),
                    Delivery.BROADCAST,
                )
            )
            # Cleanup the signage point fromm memory.
            self.signage_point_iters.remove(signage_iters[0])
            for chain in ["cc", "rc"]:
                del self.iteration_to_proof_type[chain][signage_iters[0]]
            self.finished_sp += 1
            self.proofs_finished = self._clear_proof_list(signage_iters[0])
            # Send the next signage point to the chains.
            if len(self.signage_point_iters) > 0:
                next_sp = min(self.ignage_point_iters)
            for chain in ["cc", "rc"]:
                self.iters_to_submit[chain] = next_sp
                self.iteration_to_proof_type[next_sp] = "sp"

    async def _check_for_new_ip(self):
        infusion_iters = [
            iter
            for iter, t in self.iteration_to_proof_type
            if t == "ip"
        ]
        for iter in infusion_iters:
            proofs_with_iter = [
                (chain, info, proof)
                for chain, info, proof in self.proofs_finished
                if info.number_of_iterations == iter
            ]
            chain_count = 3 if self.has_icc else 2
            if len(proofs_with_iter) == chain_count:
                block = None
                for unfinished_block in self.unfinished_blocks + self.overflow_blocks:
                    _, ip_iters = self.iters_from_proof_of_space(
                        self.constants, self.cached_peak.ips, self.cached_peak.difficulty
                    )
                    if ip_iters - self.last_ip_iters == iter:
                        block = unfinished_block
                        break
                if block is not None:
                    self.unfinished_blocks.remove(block)
                    for chain in ["cc", "rc"]:
                        del self.iteration_to_proof_type[chain][iter]
                    if self.has_icc:
                        del self.iteration_to_proof_type["icc"][iter]
                    challenge_hash = block.reward_chain_sub_block.get_hash()
                    icc_info = None
                    icc_proof = None
                    for chain, info, proof in proofs_with_iter:
                        if chain == "cc":
                            cc_info = info
                            cc_proof = proof
                        if chain == "rc":
                            rc_info = info
                            rc_proof = proof
                        if chain == "icc":
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
        for iter in infusion_iters:
            self.proofs_finished = self._clear_proof_list(iter)

    async def _check_for_end_of_subslot(self):
        chains_finished = [
            (chain, info, proof)
            for chain, info, proof in self.proofs_finished
            if info.number_of_iterations == self.left_subslot_iters
        ]
        chain_count = 3 if self.has_icc else 2
        if len(chains_finished) == chain_count:
            icc_ip_vdf, icc_ip_proof = None
            for chain, info, proof in chains_finished:
                if chain == "cc":
                    cc_vdf = info
                    cc_proof = proof
                if chain == "rc":
                    rc_vdf = info
                    rc_proof = proof
                if chain == "icc":
                    icc_ip_vdf = info
                    icc_ip_proof = proof
            icc_sub_slot: Optional[InfusedChallengeChainSubSlot] = InfusedChallengeChainSubSlot(icc_ip_vdf)
            icc_sub_slot_hash = icc_sub_slot.get_hash() if self.cached_peak.deficit == 0 else None
            if self.cached_peak.sub_epoch_summary is not None:
                ses_hash = self.cached_peak.sub_epoch_summary.get_hash()
                new_ips = self.cached_peak.sub_epoch_summary.new_ips
                new_difficulty = self.cached_peak.sub_epoch_summary.new_difficulty
            else:
                ses_hash = None
                new_ips = None
                new_difficulty = None
            cc_sub_slot = ChallengeChainSubSlot(cc_vdf, icc_sub_slot_hash, ses_hash, new_ips, new_difficulty)
            eos_deficit: uint8 = (
                self.cached_peak.deficit
                if self.cached_peak.deficit > 0
                else constants.MIN_SUB_BLOCKS_PER_CHALLENGE_BLOCK
            )
            rc_sub_slot = RewardChainSubSlot(
                rc_vdf,
                cc_sub_slot.get_hash(),
                icc_sub_slot.get_hash() if icc_sub_slot is not None else None,
                eos_deficit,
            ),
            eos_bundle = EndOfSubSlotBundle(
                cc_sub_slot,
                icc_sub_slot,
                SubSlotProofs(cc_proof, icc_ip_proof, rc_proof),
            )
            self.server.push_message(
                OutboundMessage(
                    NodeType.FULL_NODE,
                    Message("end_of_sub_slot_bundle", response),
                    Delivery.BROADCAST,
                )
            )
            # Calculate overflow blocks for the next subslot.
            self.overflow_blocks = []
            for unfinished_block in self.unfinished_blocks:
                sp_iters, ip_iters = self.iters_from_proof_of_space(
                    self.constants, self.cached_peak.ips, self.cached_peak.difficulty
                )
                if sp_iters > ip_iters:
                    self.overflow_blocks.append(block)
            self.unfinished_blocks = []
            # Create a "fake" peak, with the end of subslot info, so everything will reset.
            self.last_peak = self.cached_peak
            self.new_subslot = True
            self.finished_sp = 0
            if new_ips is not None:
                self.last_peak.ips = new_ips
            if new_difficulty is not None:
                self.last_peak.difficulty = new_difficulty
            # Create new discriminants and initial forms for the next subslot.
            self.discriminant_to_submit["cc"] = cc_sub_slot.get_hash()
            self.discriminant_to_submit["rc"] = rc_sub_slot.get_hash()
            self.initial_form_to_submit["cc"] = ClassgroupElement.get_default_element()
            self.initial_form_to_submit["rc"] = ClassgroupElement.get_default_element()
            if self.last_peak.deficit > 0:
                self.discriminant_to_submit["icc"] = icc_sub_slot_hash
                self.initial_form_to_submit["icc"] = ClassgroupElement.get_default_element()
                self.has_icc = True
            else:
                self.has_icc = False

    async def _manage_chains(self):
        while not self._is_stopped:
            # Didn't get any useful data, continue.
            async with self.lock:
                if self.left_subslot_iters == 0:
                    await asyncio.sleep(0.1)
                    continue
                if (
                    self.cached_peak is None
                    and self.last_peak is None
                ):
                    await asyncio.sleep(0.1)
                    continue
            # Map free vdf_clients to unspawned chains.
            await self._map_chains_with_vdf_clients()
            async with self.lock:
                # We've got a new peak, process it.
                if self.last_peak is not None:
                    await self._handle_new_peak_or_subslot()
                # Submit pending iterations.
                await self._submit_iterations()
                # Check for new signage point and broadcast it if present.
                await self._check_for_new_sp()
                # Check for new infusion point and broadcast it if present.
                await self._check_for_new_ip()
                # Check for end of subslot, respawn chains and build EndOfSubslotBundle.
                await self._check_for_end_of_subslot()
            await asyncio.sleep(0.1)

    async def _do_process_communication(
        self, chain, challenge_hash, initial_form, ip, reader, writer
    ):
        # TODO: Send initial_form.
        disc: int = create_discriminant(challenge_hash, self.discriminant_size_bits)
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
                log.error(f"Exception while decoding data {e}")

            if msg == "STOP":
                log.info(f"Stopped client running on ip {ip}.")
                async with self.lock:
                    writer.write(b"ACK")
                    await writer.drain()
                break
            else:
                try:
                    # This must be a proof, 4bytes is length prefix
                    length = int.from_bytes(data, "big")
                    proof = await reader.readexactly(length)
                    stdout_bytes_io: io.BytesIO = io.BytesIO(
                        bytes.fromhex(proof.decode())
                    )
                except (
                    asyncio.IncompleteReadError,
                    ConnectionResetError,
                    Exception,
                ) as e:
                    log.warning(f"{type(e)} {e}")
                    break

                iterations_needed = uint64(
                    int.from_bytes(stdout_bytes_io.read(8), "big", signed=True)
                )

                y_size_bytes = stdout_bytes_io.read(8)
                y_size = uint64(int.from_bytes(y_size_bytes, "big", signed=True))

                y_bytes = stdout_bytes_io.read(y_size)
                witness_type = uint8(
                    int.from_bytes(stdout_bytes_io.read(1), "big", signed=True)
                )
                proof_bytes: bytes = stdout_bytes_io.read()

                # Verifies our own proof just in case
                a = int.from_bytes(y_bytes[:129], "big", signed=True)
                b = int.from_bytes(y_bytes[129:], "big", signed=True)
                output = ClassgroupElement(int512(a), int512(b))
                log.info(
                    f"Finished PoT chall:{challenge_hash[:10].hex()}.. {iterations_needed}"
                    f" iters."
                )
                if not proof_of_time.is_valid(self.discriminant_size_bits):
                    log.error("Invalid proof of time")
                # TODO: Append to proofs_finished.
