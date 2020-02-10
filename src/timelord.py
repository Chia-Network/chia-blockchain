import asyncio
import logging
import time
from asyncio import Lock, StreamReader, StreamWriter
from typing import Dict, List, Optional, Tuple


from lib.chiavdf.inkfish.create_discriminant import create_discriminant
from src.consensus.constants import constants
from src.protocols import timelord_protocol
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.classgroup import ClassgroupElement
from src.types.proof_of_time import ProofOfTime
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request
from src.util.ints import uint64

log = logging.getLogger(__name__)


class Timelord:
    def __init__(self, config: Dict):
        self.config: Dict = config
        self.free_servers: List[Tuple[str, str]] = list(
            zip(self.config["vdf_server_ips"], self.config["vdf_server_ports"])
        )
        self.ips_estimate = {
            k: v
            for k, v in list(
                zip(
                    self.config["servers_ips_estimate"]["ip"],
                    self.config["servers_ips_estimate"]["ips"],
                )
            )
        }
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
        self._is_shutdown = False
        self.tasks: List[asyncio.Task] = []

    async def _shutdown(self):
        async with self.lock:
            for (
                stop_discriminant,
                (stop_writer, _, _),
            ) in self.active_discriminants.items():
                stop_writer.write(b"010")
                await stop_writer.drain()
                self.done_discriminants.append(stop_discriminant)
            self.active_discriminants.clear()
            self.active_discriminants_start_time.clear()
        self._is_shutdown = True

        for task in self.tasks:
            await task

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

            server_ip = [v[2] for _, v in low_weights.items()]
            # ips maps an IP to the expected iterations per second of it.
            ips = {}
            for ip in server_ip:
                if ip in self.avg_ips:
                    current_ips, _ = self.avg_ips[ip]
                    ips[ip] = current_ips
                else:
                    ips[ip] = self.ips_estimate[ip]

            expected_finish = {
                k: max(0, (best_iter[k] - time_taken[k] * ips[v[2]]) / ips[v[2]])
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
        stop_writer.write(b"010")
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
                self.pending_iters[challenge_hash].remove(iterations_needed)
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
                        current_writer.write(b"010")
                        await current_writer.drain()
                        del self.active_discriminants[active_disc]
                        del self.active_discriminants_start_time[active_disc]
                        self.done_discriminants.append(active_disc)

    async def _send_iterations(self, challenge_hash, writer):
        alive_discriminant = True
        while alive_discriminant:
            async with self.lock:
                if (challenge_hash in self.active_discriminants) and (
                    challenge_hash in self.pending_iters
                ):
                    if challenge_hash not in self.submitted_iters:
                        self.submitted_iters[challenge_hash] = []
                    for iter in sorted(self.pending_iters[challenge_hash]):
                        if iter in self.submitted_iters[challenge_hash]:
                            continue
                        self.submitted_iters[challenge_hash].append(iter)
                        if len(str(iter)) < 10:
                            iter_size = "0" + str(len(str(iter)))
                        else:
                            iter_size = str(len(str(iter)))
                        writer.write((iter_size + str(iter)).encode())
                        await writer.drain()
                        log.info(f"New iteration submitted: {iter}")
            await asyncio.sleep(3)
            async with self.lock:
                if challenge_hash in self.done_discriminants:
                    alive_discriminant = False

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
                # socket = writer.get_extra_info("socket")
                # socket.settimeout(None)
                break
            except Exception as e:
                e_to_str = str(e)
            await asyncio.sleep(1)
        if not writer or not reader:
            raise Exception("Unable to connect to VDF server")

        len_3_chars = str(len(str(disc)))
        len_3_chars = ("0" * (3 - len(len_3_chars))) + len_3_chars

        writer.write(len_3_chars.encode() + str(disc).encode())
        await writer.drain()

        ok = await reader.readexactly(2)
        assert ok.decode() == "OK"

        log.info("Got handshake with VDF server.")

        async with self.lock:
            self.active_discriminants[challenge_hash] = (writer, challenge_weight, ip)
            self.active_discriminants_start_time[challenge_hash] = time.time()

        self.tasks.append(
            asyncio.create_task(self._send_iterations(challenge_hash, writer))
        )

        # Listen to the server until "STOP" is received.
        while True:
            try:
                data = await reader.readexactly(4)
            except (asyncio.IncompleteReadError, ConnectionResetError) as e:
                log.warning(f"{type(e)} {e}")
                break

            if data.decode() == "STOP":
                log.info("Stopped server")
                async with self.lock:
                    writer.write(b"ACK")
                    await writer.drain()
                    await proc.wait()
                    # Server is now available.
                    self.free_servers.append((ip, port))
                    len_server = len(self.free_servers)
                    log.info(f"Process ended... Server length {len_server}")
                break
            elif data.decode() == "WESO":
                # n-wesolowski
                try:
                    # TODO: change protocol to use bytes and same ProofOfTime format (instead of hex)
                    # Reads 16 bytes of hex, for the 8 byte iterations
                    bytes_read = await reader.readexactly(16)
                    iterations_needed = uint64(
                        int.from_bytes(
                            bytes.fromhex(bytes_read.decode()), "big", signed=True
                        )
                    )
                    bytes_read = await reader.readexactly(16)
                    # Reads 16 bytes of hex, for the 8 byte y_size
                    y_size = uint64(
                        int.from_bytes(
                            bytes.fromhex(bytes_read.decode()), "big", signed=True
                        )
                    )
                    # reads 2 * y_size of hex bytes
                    y_bytes = bytes.fromhex(
                        (await reader.readexactly(2 * y_size)).decode()
                    )
                    # Reads 16 bytes of hex, for the 8 byte proof size
                    proof_size_bytes = await reader.readexactly(16)
                    proof_size = int.from_bytes(
                        bytes.fromhex(proof_size_bytes.decode()), "big", signed=True
                    )

                    # reads 2 * proof_size of hex bytes
                    proof_bytes = bytes.fromhex(
                        (await reader.readexactly(2 * proof_size)).decode()
                    )
                except Exception as e:
                    e_to_str = str(e)
                    log.error(f"Socket error: {e_to_str}")

                output = ClassgroupElement.from_bytes(y_bytes)

                # Verifies our own proof just in case
                proof_of_time = ProofOfTime(
                    challenge_hash,
                    iterations_needed,
                    output,
                    self.config["n_wesolowski"],
                    proof_bytes,
                )
                if not proof_of_time.is_valid(constants["DISCRIMINANT_SIZE_BITS"]):
                    log.error("Invalid proof of time")

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
        while not self._is_shutdown:
            async with self.lock:
                log.warning(f"Done tasks {len([t for t in self.tasks if t.done()])}")
                log.warning(
                    f"Not done tasks {len([t for t in self.tasks if not t.done()])}"
                )
                # Clear done tasks
                self.tasks = [t for t in self.tasks if not t.done()]
                if len(self.discriminant_queue) > 0:
                    max_weight = max([h for _, h in self.discriminant_queue])
                    if max_weight <= self.best_weight_three_proofs:
                        self.done_discriminants.extend(
                            [d for d, _ in self.discriminant_queue]
                        )
                        self.discriminant_queue.clear()
                    else:
                        max_weight_disc = [
                            d for d, h in self.discriminant_queue if h == max_weight
                        ]
                        with_iters = [
                            d
                            for d in max_weight_disc
                            if d in self.pending_iters
                            and len(self.pending_iters[d]) != 0
                        ]
                        if len(with_iters) == 0:
                            disc = max_weight_disc[0]
                        else:
                            min_iter = min(
                                [min(self.pending_iters[d]) for d in with_iters]
                            )
                            disc = next(
                                d
                                for d in with_iters
                                if min(self.pending_iters[d]) == min_iter
                            )
                        if len(self.free_servers) != 0:
                            ip, port = self.free_servers[0]
                            self.free_servers = self.free_servers[1:]
                            self.discriminant_queue.remove((disc, max_weight))
                            self.tasks.append(
                                asyncio.create_task(
                                    self._do_process_communication(
                                        disc, max_weight, ip, port
                                    )
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
                                elif max_weight == worst_weight_active:
                                    if (
                                        disc in self.pending_iters
                                        and len(self.pending_iters[disc]) != 0
                                    ):
                                        if any(
                                            (
                                                k not in self.pending_iters
                                                or len(self.pending_iters[k]) == 0
                                            )
                                            for k, v in self.active_discriminants.items()
                                            if v[1] == worst_weight_active
                                        ):
                                            log.info(
                                                "Stopped process without iters for one with iters."
                                            )
                                            await self._stop_worst_process(
                                                worst_weight_active
                                            )

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
            log.info(
                f"proof_of_space_info {proof_of_space_info.challenge_hash} {proof_of_space_info.iterations_needed}"
            )
            if proof_of_space_info.challenge_hash in self.done_discriminants:
                log.info(
                    f"proof_of_space_info {proof_of_space_info.challenge_hash} already done, returning"
                )
                return

            if proof_of_space_info.challenge_hash not in self.pending_iters:
                self.pending_iters[proof_of_space_info.challenge_hash] = []
            if proof_of_space_info.challenge_hash not in self.submitted_iters:
                self.submitted_iters[proof_of_space_info.challenge_hash] = []

            if (
                proof_of_space_info.iterations_needed
                not in self.pending_iters[proof_of_space_info.challenge_hash]
                and proof_of_space_info.iterations_needed
                not in self.submitted_iters[proof_of_space_info.challenge_hash]
            ):
                log.info(
                    f"proof_of_space_info {proof_of_space_info.challenge_hash} adding "
                    f"{proof_of_space_info.iterations_needed} to "
                    f"{self.pending_iters[proof_of_space_info.challenge_hash]}"
                )
                self.pending_iters[proof_of_space_info.challenge_hash].append(
                    proof_of_space_info.iterations_needed
                )
