import logging
import asyncio
import io
from yaml import safe_load
import time
from asyncio import Lock
from typing import Dict, List

from lib.chiavdf.inkfish.create_discriminant import create_discriminant
from lib.chiavdf.inkfish.proof_of_time import check_proof_of_time_nwesolowski
from lib.chiavdf.inkfish.classgroup import ClassGroup
from src.util.api_decorators import api_request
from src.protocols import timelord_protocol
from src.types.proof_of_time import ProofOfTimeOutput, ProofOfTime
from src.types.classgroup import ClassgroupElement
from src.types.sized_bytes import bytes32
from src.util.ints import uint8, uint32, uint64
from src.consensus.constants import constants
from src.server.outbound_message import OutboundMessage, Delivery, Message, NodeType


log = logging.getLogger(__name__)


class Timelord:
    def __init__(self):
        self.config = safe_load(open("src/config/timelord.yaml", "r"))
        self.lock: Lock = Lock()
        self.free_servers: List[str, str] = list(zip(self.config["vdf_server_ips"], self.config["vdf_server_ports"]))
        self.server_count: int = len(self.free_servers)
        self.active_discriminants: Dict = {}
        self.best_height_three_proofs: int = -1
        self.active_discriminants_start_time: Dict = {}
        self.pending_iters: Dict = {}
        self.discriminant_to_server: Dict = {}
        self.done_discriminants: List[bytes32] = []
        self.seen_discriminants: List[bytes32] = []
        self.proof_count: Dict = {}
        self.avg_ips: Dict = {}
        self.discriminant_queue: List[bytes32, uint32] = []

    async def manage_discriminant_queue(self):
        while(True):                
            async with self.lock:
                if (len(self.discriminant_queue) > 0):
                    max_height = max([h for _, h in self.discriminant_queue])
                    if (max_height <= self.best_height_three_proofs):
                        self.done_discriminants.extend([d for d, _ in self.discriminant_queue])
                        self.discriminant_queue.clear()
                    else:
                        disc = next(d for d, h in self.discriminant_queue if h == max_height)
                        if (len(self.free_servers) != 0):
                            ip, port = self.free_servers[0]
                            self.free_servers = self.free_servers[1:]
                            self.discriminant_to_server[disc] = (ip, port)
                            self.discriminant_queue.remove((disc, max_height))
            await asyncio.sleep(0.5)
            
    @api_request
    async def challenge_start(self, challenge_start: timelord_protocol.ChallengeStart):
        """
        The full node notifies the timelord node that a new challenge is active, and work
        should be started on it. We can generate a classgroup (discriminant), and start
        a new VDF process here. But we don't know how many iterations to run for, so we run
        forever.
        """
        disc: int = create_discriminant(challenge_start.challenge_hash, constants["DISCRIMINANT_SIZE_BITS"])
        async with self.lock:
            if (challenge_start.challenge_hash in self.seen_discriminants):
                log.info(f"Already seen this challenge hash {challenge_start.challenge_hash}. Ignoring.")
                return
            self.seen_discriminants.append(challenge_start.challenge_hash)
            self.discriminant_queue.append((challenge_start.challenge_hash, challenge_start.height))

        async with self.lock:
            if (challenge_start.height <= self.best_height_three_proofs):
                log.info("Not starting challenge, already three proofs at that height")
                return 
            if (len(self.active_discriminants) == self.server_count):
                worst_height_active = min([h for (_, h, _) in self.active_discriminants.values()])
                if (worst_height_active >= challenge_start.height):
                    return
                # We need to stop one process having worst_height_active.
                log.info(f"Worst height running {worst_height_active}")
                log.info(f"Challenge start height {challenge_start.height}")
                stop_writer = None
                stop_discriminant = None
                
                low_heights = {k: v for k, v in self.active_discriminants.items() if v[1] == worst_height_active}
                no_iters = {k: v for k, v in low_heights.items() if k not in self.pending_iters or len(self.pending_iters[k]) == 0}
                
                # If we have process(es) with no iters, stop the one that started the latest
                if len(no_iters) > 0:
                    latest_start_time = max([self.active_discriminants_start_time[k] for k, _ in no_iters.items()])
                    stop_discriminant, stop_writer = next((k, v[0]) for k, v in no_iters.items() if self.active_discriminants_start_time[k] == latest_start_time)                    
                else:
                    #Otherwise, pick the one that finishes one proof the latest.
                    best_iter = {k: min(self.pending_iters[k]) for k, _ in low_heights.items()}
                    time_taken = {k: time.time() - self.active_discriminants_start_time[k] for k, _ in low_heights.items()}
                    expected_finish = {k: max(0, (best_iter[k] - time_taken[k] * self.avg_ips[v[2]][0]) / self.avg_ips[v[2]][0]) for k, v in low_heights.items()}
                    worst_finish = max([v for v in expected_finish.values()])
                    log.info(f"Worst finish time: {worst_finish}s")
                    stop_discriminant, stop_writer = next((k, v[0]) for k, v in low_heights.items() if expected_finish[k] == worst_finish)
                               
                log.info("Stopping one server as new challenge")
                stop_writer.write(b'10')
                await stop_writer.drain()
                del self.active_discriminants[stop_discriminant]
                del self.active_discriminants_start_time[stop_discriminant]
                self.done_discriminants.append(stop_discriminant)

        while (True):
            async with self.lock:
                if (challenge_start.challenge_hash in self.discriminant_to_server):
                    ip, port = self.discriminant_to_server[challenge_start.challenge_hash]
                    log.info(f"New discriminant got attached to port: {port}, ip: {ip}")
                    break
                if (challenge_start.challenge_hash in self.done_discriminants):
                    return
            await asyncio.sleep(0.5)

        log.info("Attempting SSH connection")
        #proc = await asyncio.create_subprocess_shell(f"ssh chia@{ip} '~/fast_vdf2/server {port} 2>&1 | tee -a ~/logs.txt'")
        proc = await asyncio.create_subprocess_shell(f"./lib/chiavdf/fast_vdf/vdf_server {port}")

        # TODO(Florin): Handle connection failure (attempt another server)
        writer, reader = None, None
        for _ in range(10):
            try:
                reader, writer = await asyncio.open_connection(ip, port)
                break
            except Exception as e:
                e_to_str = str(e)
                log.error(f"Connection to VDF server error message: {e_to_str}")
            await asyncio.sleep(1)
        if not writer or not reader:
            raise Exception("Unable to connect to VDF server")

        writer.write((str(len(str(disc))) + str(disc)).encode())
        await writer.drain()

        ok = await reader.readexactly(2)
        assert(ok.decode() == "OK")

        log.info("Got handshake with VDF server.")

        async with self.lock:
            self.active_discriminants[challenge_start.challenge_hash] = (writer, challenge_start.height, ip)
            self.active_discriminants_start_time[challenge_start.challenge_hash] = time.time()

        async with self.lock:
            if (challenge_start.challenge_hash in self.pending_iters):
                log.info(f"Writing pending iters {challenge_start.challenge_hash}")
                for iter in sorted(self.pending_iters[challenge_start.challenge_hash]):
                    writer.write((str(len(str(iter))) + str(iter)).encode())
                    await writer.drain()

        # Listen to the server until "STOP" is received.
        while True:
            data = await reader.readexactly(4)
            if (data.decode() == "STOP"):
                log.info("Stopped server")
                writer.write(b"ACK")
                await writer.drain()
                await proc.wait()
                # Server is now available.
                async with self.lock:
                    self.free_servers.append((ip, port))
                    len_server = len(self.free_servers)
                    log.info(f"Process ended... Server length {len_server}")
                    del self.discriminant_to_server[challenge_start.challenge_hash]
                break
            elif (data.decode() == "POLL"):
                async with self.lock:
                    # If I have a newer discriminant... Free up the VDF server
                    if (len(self.discriminant_queue) > 0 and challenge_start.height < max([h for _, h in self.discriminant_queue])
                            and challenge_start.challenge_hash in self.active_discriminants):
                        log.info("Got poll, stopping the challenge!")
                        writer.write(b'10')
                        await writer.drain()
                        del self.active_discriminants[challenge_start.challenge_hash]
                        del self.active_discriminants_start_time[challenge_start.challenge_hash]
                        self.done_discriminants.append(challenge_start.challenge_hash)
            else:
                try:
                    # This must be a proof, read the continuation.
                    proof = await reader.readexactly(1860)
                    stdout_bytes_io: io.BytesIO = io.BytesIO(bytes.fromhex(data.decode() + proof.decode()))
                except Exception as e:
                    e_to_str = str(e)
                    log.error(f"Socket error: {e_to_str}")

                iterations_needed = uint64(int.from_bytes(stdout_bytes_io.read(8), "big", signed=True))
                y = ClassgroupElement.parse(stdout_bytes_io)
                proof_bytes: bytes = stdout_bytes_io.read()

                # Verifies our own proof just in case
                proof_blob = ClassGroup.from_ab_discriminant(y.a, y.b, disc).serialize() + proof_bytes
                x = ClassGroup.from_ab_discriminant(2, 1, disc)
                if (not check_proof_of_time_nwesolowski(disc, x, proof_blob, iterations_needed,
                                                        constants["DISCRIMINANT_SIZE_BITS"],
                                                        self.config["n_wesolowski"])):
                    log.error("My proof is incorrect!")

                output = ProofOfTimeOutput(challenge_start.challenge_hash,
                                           iterations_needed,
                                           ClassgroupElement(y.a, y.b))
                proof_of_time = ProofOfTime(output, self.config['n_wesolowski'], [uint8(b) for b in proof_bytes])
                response = timelord_protocol.ProofOfTimeFinished(proof_of_time)

                async with self.lock:
                    if challenge_start.challenge_hash in self.active_discriminants:
                        time_taken = time.time() - self.active_discriminants_start_time[challenge_start.challenge_hash]
                        ips = int(iterations_needed / time_taken * 10)/10
                        log.info(f"Finished PoT, chall:{challenge_start.challenge_hash[:10].hex()}.."
                                 f" {iterations_needed} iters. {int(time_taken*1000)/1000}s, {ips} ips")
                        if ip not in self.avg_ips:
                            self.avg_ips[ip] = (ips, 1)
                        else:
                            prev_avg_ips, trials = self.avg_ips[ip]
                            new_avg_ips = int((prev_avg_ips * trials + ips) / (trials + 1))
                            self.avg_ips[ip] = (new_avg_ips, trials + 1)
                            log.info(f"New estimate: {new_avg_ips}")
                        self.pending_iters[challenge_start.challenge_hash].remove(iterations_needed)
                    else:
                        log.info(f"Finished PoT chall:{challenge_start.challenge_hash[:10].hex()}.. {iterations_needed}"
                                 f" iters. But challenge not active anymore")
                    
                yield OutboundMessage(NodeType.FULL_NODE, Message("proof_of_time_finished", response), Delivery.RESPOND)
                async with self.lock:
                    try:
                        if (challenge_start.height not in self.proof_count):
                            self.proof_count[challenge_start.height] = 1
                        else:
                            self.proof_count[challenge_start.height] += 1
                        if (self.proof_count[challenge_start.height] >= 3):
                            log.info("Cleaning up servers")
                            self.best_height_three_proofs = max(self.best_height_three_proofs, challenge_start.height)
                            for active_disc in list(self.active_discriminants):
                                current_writer, current_height, _ = self.active_discriminants[active_disc]
                                log.info(f"Active height cleanup: {current_height}")
                                log.info(f"Cleanup height: {challenge_start.height}")
                                if (current_height <= challenge_start.height):
                                    current_writer.write(b'10')
                                    await current_writer.drain()
                                    del self.active_discriminants[active_disc]
                                    del self.active_discriminants_start_time[active_disc]
                                    self.done_discriminants.append(active_disc)
                    except Exception as e:
                        log.info(f"Exception caught: {e}")
                            
    @api_request
    async def proof_of_space_info(self, proof_of_space_info: timelord_protocol.ProofOfSpaceInfo):
        """
        Notification from full node about a new proof of space for a challenge. If we already
        have a process for this challenge, we should communicate to the process to tell it how
        many iterations to run for.
        """
        async with self.lock:
            if (proof_of_space_info.challenge_hash in self.active_discriminants):
                writer, _, _ = self.active_discriminants[proof_of_space_info.challenge_hash]
                writer.write(((str(len(str(proof_of_space_info.iterations_needed))) +
                             str(proof_of_space_info.iterations_needed)).encode()))
                await writer.drain()
            elif (proof_of_space_info.challenge_hash in self.done_discriminants):
                return
            if (proof_of_space_info.challenge_hash not in self.pending_iters):
                self.pending_iters[proof_of_space_info.challenge_hash] = []
            self.pending_iters[proof_of_space_info.challenge_hash].append(proof_of_space_info.iterations_needed)
