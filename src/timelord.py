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
        #self.free_servers = self.config["vdf_server_ports"]
        self.lock: Lock = Lock()
        self.free_servers: List[(str, str)] = [('127.0.0.1', '8889'), ('127.0.0.1', '8890')]
        #self.free_servers: List[(str, str)] = [('18.206.54.21', 8889), ('18.206.54.21', 8890), ('18.206.54.21', 8891), ('18.206.54.21', 8892), ('18.206.54.21', 8893)]
        self.server_count: int = len(self.free_servers)
        self.active_discriminants: Dict = {}
        self.best_height_three_proofs: int = -1
        self.active_discriminants_start_time: Dict = {}
        self.pending_iters: Dict = {}
        self.done_discriminants: List[bytes32] = []
        self.seen_discriminants: List[bytes32] = []
        self.proof_count: Dict = {}
        self.avg_ips: Dict = {}
        self.active_heights: List[uint32] = []

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
                log.info("Already seen this challenge hash {challenge_start.challenge_hash}. Ignoring.")
                return
            self.seen_discriminants.append(challenge_start.challenge_hash)
            self.active_heights.append(challenge_start.height)

        async with self.lock:
            if (challenge_start.height <= self.best_height_three_proofs):
                log.info("Not starting challenge, already three proofs at that height")
                return 
            if (len(self.active_discriminants) == self.server_count):
                worst_height_active = None
                for active_disc in self.active_discriminants:
                    _, current_height, _ = self.active_discriminants[active_disc]
                    if (worst_height_active == None or worst_height_active > current_height):
                        worst_height_active = current_height
                # If I have a better height than what's running, stop the newest process.
                log.info(f"Worst height running {worst_height_active}")
                log.info(f"Challenge start height {challenge_start.height}")
                if (worst_height_active < challenge_start.height):
                    newest_process_time = None
                    latest_finish_time = None
                    stop_writer = None
                    stop_discriminant = None

                    # Firstly find processes without iters and pick the newest one (since it did the least number of iters)
                    for active_disc in self.active_discriminants:
                        writer, current_height, _ = self.active_discriminants[active_disc]
                        if (current_height != worst_height_active):
                            continue
                        process_time = self.active_discriminants_start_time[active_disc]
                        if (active_disc not in self.pending_iters or len(self.pending_iters[active_disc]) == 0):
                            if (newest_process_time == None or process_time > newest_process_time):
                                stop_writer = writer
                                stop_discriminant = active_disc
                                newest_process_time = process_time
                    
                    # If all processes have iters, stop the one that finish one proof the latest.
                    if (stop_writer is None):
                        for active_disc in self.active_discriminants:
                            try:
                                writer, current_height, ip = self.active_discriminants[active_disc]
                                if (current_height != worst_height_active):
                                    continue
                                best_iter = min(self.pending_iters[active_disc])
                                time_taken = time.time() - self.active_discriminants_start_time[active_disc]
                                ips, _ = self.avg_ips[ip]
                                expected_finish = max(0, (best_iter - time_taken * ips) / ips)
                                log.info(f"Expected to finish in: {expected_finish}s")
                                if (latest_finish_time == None or expected_finish > latest_finish_time):
                                    stop_writer = writer
                                    stop_discriminant = active_disc
                                    latest_finish_time = expected_finish
                            except Exception as e:
                                e_to_str = str(e)
                                log.info(f"Exception: {e_to_str}")

                    log.info("Stopping one server as new challenge")
                    stop_writer.write(b'10')
                    await stop_writer.drain()
                    del self.active_discriminants[stop_discriminant]
                    del self.active_discriminants_start_time[stop_discriminant]
                    self.done_discriminants.append(stop_discriminant)
                else:
                    return

        # Wait for a server to become free.
        ip: str = "None"
        port: str = "None"
        while port == "None":
            async with self.lock:
                if (challenge_start.height <= max(self.active_heights) - 3):
                    self.done_discriminants.append(challenge_start.challenge_hash)
                    self.active_heights.remove(challenge_start.height)
                    log.info(f"Will not execute challenge at height {challenge_start}, too old")
                    return
                assert(len(self.active_heights) > 0)
                if (challenge_start.height == max(self.active_heights)):
                    if (len(self.free_servers) != 0):
                        ip, port = self.free_servers[0]
                        self.free_servers = self.free_servers[1:]
                        log.info(f"Discriminant {str(disc)[:10]}... attached to machine {port}.")
                        log.info(f"Challenge/Height attached is {challenge_start}")
                        self.active_heights.remove(challenge_start.height)

            # Poll until a server becomes free.
            if port == "None":
                await asyncio.sleep(1)

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
            await asyncio.sleep(5)
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
                break
            elif (data.decode() == "POLL"):
                async with self.lock:
                    # If I have a newer discriminant... Free up the VDF server
                    if (len(self.active_heights) > 0 and challenge_start.height <= max(self.active_heights)
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
