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
        self.free_servers = self.config["vdf_server_ports"]
        self.lock: Lock = Lock()
        self.free_servers: List[int] = self.config["vdf_server_ports"]
        self.active_discriminants: Dict = {}
        self.active_discriminants_start_time: Dict = {}
        self.pending_iters: Dict = {}
        self.done_discriminants: List[bytes32] = []
        self.seen_discriminants: List[bytes32] = []
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

        # Wait for a server to become free.
        port: int = -1
        while port == -1:
            async with self.lock:
                if (challenge_start.height <= max(self.active_heights) - 3):
                    self.done_discriminants.append(challenge_start.challenge_hash)
                    self.active_heights.remove(challenge_start.height)
                    log.info(f"Will not execute challenge at height {challenge_start}, too old")
                    return
                assert(len(self.active_heights) > 0)
                if (challenge_start.height == max(self.active_heights)):
                    if (len(self.free_servers) != 0):
                        port = self.free_servers[0]
                        self.free_servers = self.free_servers[1:]
                        log.info(f"Discriminant {str(disc)[:10]}... attached to port {port}.")
                        log.info(f"Challenge/Height attached is {challenge_start}")
                        self.active_heights.remove(challenge_start.height)

            # Poll until a server becomes free.
            if port == -1:
                await asyncio.sleep(1)

        proc = await asyncio.create_subprocess_shell("./lib/chiavdf/fast_vdf/server " + str(port))

        # TODO(Florin): Handle connection failure (attempt another server)
        writer, reader = None, None
        for _ in range(10):
            try:
                reader, writer = await asyncio.open_connection('127.0.0.1', port)
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
            self.active_discriminants[challenge_start.challenge_hash] = writer
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
                # Server is now available.
                async with self.lock:
                    writer.write(b"ACK")
                    await writer.drain()
                    await proc.wait()
                    self.free_servers.append(port)
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
                    else:
                        log.info(f"Finished PoT chall:{challenge_start.challenge_hash[:10].hex()}.. {iterations_needed}"
                                 f" iters. But challenge not active anymore")

                yield OutboundMessage(NodeType.FULL_NODE, Message("proof_of_time_finished", response), Delivery.RESPOND)

    @api_request
    async def challenge_end(self, challenge_end: timelord_protocol.ChallengeEnd):
        """
        A challenge is no longer active, so stop the process for this challenge, if it
        exists.
        """
        async with self.lock:
            if (challenge_end.challenge_hash in self.done_discriminants):
                return
            if (challenge_end.challenge_hash in self.active_discriminants):
                writer = self.active_discriminants[challenge_end.challenge_hash]
                writer.write(b'10')
                await writer.drain()
                del self.active_discriminants[challenge_end.challenge_hash]
                del self.active_discriminants_start_time[challenge_end.challenge_hash]
                self.done_discriminants.append(challenge_end.challenge_hash)

    @api_request
    async def proof_of_space_info(self, proof_of_space_info: timelord_protocol.ProofOfSpaceInfo):
        """
        Notification from full node about a new proof of space for a challenge. If we already
        have a process for this challenge, we should communicate to the process to tell it how
        many iterations to run for.
        """
        async with self.lock:
            log.info(f"{proof_of_space_info.challenge_hash in self.active_discriminants}")
            log.info(f"{proof_of_space_info.challenge_hash in self.done_discriminants}")
            log.info(f"{proof_of_space_info.challenge_hash in self.pending_iters}")
            if (proof_of_space_info.challenge_hash in self.active_discriminants):
                writer = self.active_discriminants[proof_of_space_info.challenge_hash]
                writer.write(((str(len(str(proof_of_space_info.iterations_needed))) +
                             str(proof_of_space_info.iterations_needed)).encode()))
                await writer.drain()
                return
            elif (proof_of_space_info.challenge_hash in self.done_discriminants):
                return
            elif (proof_of_space_info.challenge_hash not in self.pending_iters):
                self.pending_iters[proof_of_space_info.challenge_hash] = []
            self.pending_iters[proof_of_space_info.challenge_hash].append(proof_of_space_info.iterations_needed)
