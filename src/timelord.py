import asyncio
import io
import logging
import os
import time
from asyncio import Lock, StreamReader, StreamWriter
from typing import Dict, List, Optional, Tuple

from yaml import safe_load

from definitions import ROOT_DIR
from lib.chiavdf.inkfish.classgroup import ClassGroup
from lib.chiavdf.inkfish.create_discriminant import create_discriminant
from lib.chiavdf.inkfish.proof_of_time import check_proof_of_time_nwesolowski
from src.consensus.constants import constants
from src.protocols import timelord_protocol
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.classgroup import ClassgroupElement
from src.types.proof_of_time import ProofOfTime
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request
from src.util.ints import uint8, uint64

log = logging.getLogger(__name__)


class Timelord:
    def __init__(self):
        config_filename = os.path.join(ROOT_DIR, "config", "config.yaml")
        self.config = safe_load(open(config_filename, "r"))["timelord"]
        self.free_servers: List[Tuple[str, str]] = list(
            zip(self.config["vdf_server_ips"], self.config["vdf_server_ports"])
        )
        self.lock: Lock = Lock()
        self.server_count: int = len(self.free_servers)
        self.active_discriminants: Dict[bytes32, Tuple[StreamWriter, uint64, str]] = {}
        self.best_weight_three_proofs: int = -1
        self.active_discriminants_start_time: Dict = {}
        self.pending_iters: Dict = {}
        self.submitted_iters: Dict = {}
        self.done_discriminants: List[bytes32] = []
        self.proofs_to_write: List[OutboundMessage] = []
        self.seen_discriminants: List[bytes32] = []
        self.proof_count: Dict = {}
        self.avg_ips: Dict = {}
        self.discriminant_queue: List[Tuple[bytes32, uint64]] = []
        self.is_shutdown = False

    async def _shutdown(self):
        async with self.lock:
            for (
                stop_discriminant,
                (stop_writer, _, _),
            ) in self.active_discriminants.items():
                stop_writer.write(b"10")
                await stop_writer.drain()
                self.done_discriminants.append(stop_discriminant)
            self.active_discriminants.clear()
            self.active_discriminants_start_time.clear()
        self.is_shutdown = True

    async def _stop_worst_process(self, worst_weight_active):
        # This is already inside a lock, no need to lock again.
        log.info(f"Stopping one process at weight {worst_weight_active}")
        stop_writer: Optional[StreamWriter] = None
        stop_discriminant: Optional[bytes32] = None

        low_weights = {
            k: v
            for k, v in self.active_discriminants.items()
            if v[1] == worst_weight_active
        }
        no_iters = {
            k: v
            for k, v in low_weights.items()
            if k not in self.pending_iters or len(self.pending_iters[k]) == 0
        }

        # If we have process(es) with no iters, stop the one that started the latest
        if len(no_iters) > 0:
            latest_start_time = max(
                [self.active_discriminants_start_time[k] for k, _ in no_iters.items()]
            )
            stop_discriminant, stop_writer = next(
                (k, v[0])
                for k, v in no_iters.items()
                if self.active_discriminants_start_time[k] == latest_start_time
            )
        else:
            # Otherwise, pick the one that finishes one proof the latest.
            best_iter = {k: min(self.pending_iters[k]) for k, _ in low_weights.items()}
            time_taken = {
                k: time.time() - self.active_discriminants_start_time[k]
                for k, _ in low_weights.items()
            }
            expected_finish = {
                k: max(
                    0,
                    (best_iter[k] - time_taken[k] * self.avg_ips[v[2]][0])
                    / self.avg_ips[v[2]][0],
                )
                for k, v in low_weights.items()
            }
            worst_finish = max([v for v in expected_finish.values()])
            log.info(f"Worst finish time: {worst_finish}s")
            stop_discriminant, stop_writer = next(
                (k, v[0])
                for k, v in low_weights.items()
                if expected_finish[k] == worst_finish
            )
        assert stop_writer is not None
        stop_writer.write(b"10")
        await stop_writer.drain()
        del self.active_discriminants[stop_discriminant]
        del self.active_discriminants_start_time[stop_discriminant]
        self.done_discriminants.append(stop_discriminant)

    async def _update_avg_ips(self, challenge_hash, iterations_needed, ip):
        async with self.lock:
            if challenge_hash in self.active_discriminants:
                time_taken = (
                    time.time() - self.active_discriminants_start_time[challenge_hash]
                )
                ips = int(iterations_needed / time_taken * 10) / 10
                log.info(
                    f"Finished PoT, chall:{challenge_hash[:10].hex()}.."
                    f" {iterations_needed} iters. {int(time_taken*1000)/1000}s, {ips} ips"
                )
                if ip not in self.avg_ips:
                    self.avg_ips[ip] = (ips, 1)
                else:
                    prev_avg_ips, trials = self.avg_ips[ip]
                    new_avg_ips = int((prev_avg_ips * trials + ips) / (trials + 1))
                    self.avg_ips[ip] = (new_avg_ips, trials + 1)
                    log.info(f"New estimate: {new_avg_ips}")
                    #self.pending_iters[challenge_hash].remove(iterations_needed)
            else:
                log.info(
                    f"Finished PoT chall:{challenge_hash[:10].hex()}.. {iterations_needed}"
                    f" iters. But challenge not active anymore"
                )

    async def _update_proofs_count(self, challenge_weight):
        async with self.lock:
            if challenge_weight not in self.proof_count:
                self.proof_count[challenge_weight] = 1
            else:
                self.proof_count[challenge_weight] += 1
            if self.proof_count[challenge_weight] >= 3:
                log.info("Cleaning up servers")
                self.best_weight_three_proofs = max(
                    self.best_weight_three_proofs, challenge_weight
                )
                for active_disc in list(self.active_discriminants):
                    current_writer, current_weight, _ = self.active_discriminants[
                        active_disc
                    ]
                    if current_weight <= challenge_weight:
                        log.info(f"Active weight cleanup: {current_weight}")
                        log.info(f"Cleanup weight: {challenge_weight}")
                        current_writer.write(b"10")
                        await current_writer.drain()
                        del self.active_discriminants[active_disc]
                        del self.active_discriminants_start_time[active_disc]
                        self.done_discriminants.append(active_disc)

    async def _do_process_communication(
        self, challenge_hash, challenge_weight, ip, port
    ):
        disc: int = create_discriminant(
            challenge_hash, constants["DISCRIMINANT_SIZE_BITS"]
        )

        log.info("Attempting SSH connection")
        proc = await asyncio.create_subprocess_shell(
            f"./lib/chiavdf/fast_vdf/vdf_server {port}"
        )

        # TODO(Florin): Handle connection failure (attempt another server)
        writer: Optional[StreamWriter] = None
        reader: Optional[StreamReader] = None
        for _ in range(10):
            try:
                reader, writer = await asyncio.open_connection(ip, port)
                break
            except Exception as e:
                e_to_str = str(e)
            await asyncio.sleep(1)
        if not writer or not reader:
            raise Exception("Unable to connect to VDF server")

        writer.write((str(len(str(disc))) + str(disc)).encode())
        await writer.drain()

        ok = await reader.readexactly(2)
        assert ok.decode() == "OK"

        log.info("Got handshake with VDF server.")

        async with self.lock:
            self.active_discriminants[challenge_hash] = (writer, challenge_weight, ip)
            self.active_discriminants_start_time[challenge_hash] = time.time()

        # Listen to the server until "STOP" is received.
        while True:
            async with self.lock:
                if (challenge_hash in self.active_discriminants) and (challenge_hash in self.pending_iters):
                    if challenge_hash not in self.submitted_iters:
                        self.submitted_iters[challenge_hash] = []
                    log.info(f"Pending: {self.pending_iters[challenge_hash]} Submitted: {self.submitted_iters[challenge_hash]} Hash: {challenge_hash}")
                    for iter in sorted(self.pending_iters[challenge_hash]):
                        if iter in self.submitted_iters[challenge_hash]:
                            continue
                        self.submitted_iters[challenge_hash].append(iter)
                        writer.write((str(len(str(iter))) + str(iter)).encode())
                        await writer.drain()

            try:
                data = await reader.readexactly(4)
            except (asyncio.IncompleteReadError, ConnectionResetError) as e:
                log.warn(f"{type(e)} {e}")
                break

            if data.decode() == "STOP":
                log.info("Stopped server")
                writer.write(b"ACK")
                await writer.drain()
                await proc.wait()
                # Server is now available.
                async with self.lock:
                    self.free_servers.append((ip, port))
                    len_server = len(self.free_servers)
                    log.info(f"Process ended... Server length {len_server}")
                break
            elif data.decode() == "POLL":
                async with self.lock:
                    # If I have a newer discriminant... Free up the VDF server
                    if (
                        len(self.discriminant_queue) > 0
                        and challenge_weight
                        < max([h for _, h in self.discriminant_queue])
                        and challenge_hash in self.active_discriminants
                    ):
                        log.info("Got poll, stopping the challenge!")
                        writer.write(b"10")
                        await writer.drain()
                        del self.active_discriminants[challenge_hash]
                        del self.active_discriminants_start_time[challenge_hash]
                        self.done_discriminants.append(challenge_hash)
            else:
                try:
                    # This must be a proof, read the continuation.
                    proof = await reader.readexactly(1860)
                    stdout_bytes_io: io.BytesIO = io.BytesIO(
                        bytes.fromhex(data.decode() + proof.decode())
                    )
                except Exception as e:
                    e_to_str = str(e)
                    log.error(f"Socket error: {e_to_str}")

                iterations_needed = uint64(
                    int.from_bytes(stdout_bytes_io.read(8), "big", signed=True)
                )
                y = ClassgroupElement.parse(stdout_bytes_io)
                proof_bytes: bytes = stdout_bytes_io.read()

                # Verifies our own proof just in case
                proof_blob = (
                    ClassGroup.from_ab_discriminant(y.a, y.b, disc).serialize()
                    + proof_bytes
                )
                x = ClassGroup.from_ab_discriminant(2, 1, disc)
                if not check_proof_of_time_nwesolowski(
                    disc,
                    x,
                    proof_blob,
                    iterations_needed,
                    constants["DISCRIMINANT_SIZE_BITS"],
                    self.config["n_wesolowski"],
                ):
                    log.error("My proof is incorrect!")

                output = ClassgroupElement(y.a, y.b)
                proof_of_time = ProofOfTime(
                    challenge_hash,
                    iterations_needed,
                    output,
                    self.config["n_wesolowski"],
                    [uint8(b) for b in proof_bytes],
                )
                response = timelord_protocol.ProofOfTimeFinished(proof_of_time)

                await self._update_avg_ips(challenge_hash, iterations_needed, ip)

                async with self.lock:
                    self.proofs_to_write.append(
                        OutboundMessage(
                            NodeType.FULL_NODE,
                            Message("proof_of_time_finished", response),
                            Delivery.BROADCAST,
                        )
                    )

                await self._update_proofs_count(challenge_weight)

    async def _manage_discriminant_queue(self):
        while not self.is_shutdown:
            async with self.lock:
                if len(self.discriminant_queue) > 0:
                    max_weight = max([h for _, h in self.discriminant_queue])
                    if max_weight <= self.best_weight_three_proofs:
                        self.done_discriminants.extend(
                            [d for d, _ in self.discriminant_queue]
                        )
                        self.discriminant_queue.clear()
                    else:
                        disc = next(
                            d for d, h in self.discriminant_queue if h == max_weight
                        )
                        if len(self.free_servers) != 0:
                            ip, port = self.free_servers[0]
                            self.free_servers = self.free_servers[1:]
                            self.discriminant_queue.remove((disc, max_weight))
                            asyncio.create_task(
                                self._do_process_communication(
                                    disc, max_weight, ip, port
                                )
                            )
                        else:
                            if len(self.active_discriminants) == self.server_count:
                                worst_weight_active = min(
                                    [
                                        h
                                        for (
                                            _,
                                            h,
                                            _,
                                        ) in self.active_discriminants.values()
                                    ]
                                )
                                if max_weight > worst_weight_active:
                                    await self._stop_worst_process(worst_weight_active)
                if len(self.proofs_to_write) > 0:
                    for msg in self.proofs_to_write:
                        yield msg
                    self.proofs_to_write.clear()
            await asyncio.sleep(0.5)

    @api_request
    async def challenge_start(self, challenge_start: timelord_protocol.ChallengeStart):
        """
        The full node notifies the timelord node that a new challenge is active, and work
        should be started on it. We add the challenge into the queue if it's worth it to have.
        """
        async with self.lock:
            if challenge_start.challenge_hash in self.seen_discriminants:
                log.info(
                    f"Have already seen this challenge hash {challenge_start.challenge_hash}. Ignoring."
                )
                return
            if challenge_start.weight <= self.best_weight_three_proofs:
                log.info("Not starting challenge, already three proofs at that weight")
                return
            self.seen_discriminants.append(challenge_start.challenge_hash)
            self.discriminant_queue.append(
                (challenge_start.challenge_hash, challenge_start.weight)
            )
            log.info("Appended to discriminant queue.")

    @api_request
    async def proof_of_space_info(
        self, proof_of_space_info: timelord_protocol.ProofOfSpaceInfo
    ):
        """
        Notification from full node about a new proof of space for a challenge. If we already
        have a process for this challenge, we should communicate to the process to tell it how
        many iterations to run for.
        """
        async with self.lock:
            if proof_of_space_info.challenge_hash in self.active_discriminants:
                writer, _, _ = self.active_discriminants[
                    proof_of_space_info.challenge_hash
                ]
                writer.write(
                    (
                        (
                            str(len(str(proof_of_space_info.iterations_needed)))
                            + str(proof_of_space_info.iterations_needed)
                        ).encode()
                    )
                )
                await writer.drain()
            elif proof_of_space_info.challenge_hash in self.done_discriminants:
                return
            if proof_of_space_info.challenge_hash not in self.pending_iters:
                self.pending_iters[proof_of_space_info.challenge_hash] = []
            self.pending_iters[proof_of_space_info.challenge_hash].append(
                proof_of_space_info.iterations_needed
            )
