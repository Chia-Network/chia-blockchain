import logging
import asyncio
import time
import io
from asyncio import Lock
from typing import Dict

from lib.chiavdf.inkfish.create_discriminant import create_discriminant
from lib.chiavdf.inkfish.proof_of_time import check_proof_of_time_nwesolowski
from lib.chiavdf.inkfish.classgroup import ClassGroup
from src.util.api_decorators import api_request
from src.protocols import timelord_protocol
from src.types.proof_of_time import ProofOfTimeOutput, ProofOfTime
from src.types.classgroup import ClassgroupElement
from src.util.ints import uint8
from src.consensus import constants
from src.server.outbound_message import OutboundMessage


# TODO: use config file
timelord_port = 8003
full_node_ip = "127.0.0.1"
full_node_port = 8002
iterations_per_sec = 3000
n_wesolowski = 3


class Database:
    lock: Lock = Lock()
    challenges: Dict = {}
    process_running: bool = False


log = logging.getLogger(__name__)
db = Database()


@api_request
async def challenge_start(challenge_start: timelord_protocol.ChallengeStart):
    """
    The full node notifies the timelord node that a new challenge is active, and work
    should be started on it. We can generate a classgroup (discriminant), and start
    a new VDF process here. But we don't know how many iterations to run for, so we run
    forever.
    """
    # TODO: stop previous processes
    async with db.lock:
        disc: int = create_discriminant(challenge_start.challenge_hash, constants.DISCRIMINANT_SIZE_BITS)
        db.challenges[challenge_start.challenge_hash] = (time.time(), disc, None)
        # TODO: Start a VDF process


@api_request
async def challenge_end(challenge_end: timelord_protocol.ChallengeEnd):
    """
    A challenge is no longer active, so stop the process for this challenge, if it
    exists.
    """
    # TODO: Stop VDF process for this challenge
    async with db.lock:
        db.process_running = False


@api_request
async def proof_of_space_info(proof_of_space_info: timelord_protocol.ProofOfSpaceInfo):
    """
    Notification from full node about a new proof of space for a challenge. If we already
    have a process for this challenge, we should communicate to the process to tell it how
    many iterations to run for. TODO: process should be started in challenge_start instead.
    """
    async with db.lock:
        if proof_of_space_info.challenge_hash not in db.challenges:
            log.warn(f"Have not seen challenge {proof_of_space_info.challenge_hash} yet.")
            return
        time_recvd, disc, iters = db.challenges[proof_of_space_info.challenge_hash]
        if iters:
            if proof_of_space_info.iterations_needed == iters:
                log.warn(f"Have already seen this challenge with {proof_of_space_info.iterations_needed}\
                          iterations. Ignoring.")
                return
            elif proof_of_space_info.iterations_needed > iters:
                # TODO: don't ignore, communicate to process
                log.warn(f"Too many iterations required. Already executing {iters} iters")
                return
        if db.process_running:
            # TODO: don't ignore, start a new process
            log.warn("Already have a running process. Ignoring.")
            return
        db.process_running = True

    command = (f"python -m lib.chiavdf.inkfish.cmds -t n-wesolowski -l 1024 -d {n_wesolowski} " +
               f"{proof_of_space_info.challenge_hash.hex()} {proof_of_space_info.iterations_needed}")
    log.info(f"Executing VDF command with new process: {command}")

    process_start = time.time()
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    stdout, stderr = await proc.communicate()

    async with db.lock:
        db.process_running = False

    log.info(f"Finished executing VDF after {int((time.time() - process_start) * 1000)/1000}s")
    if stderr:
        log.error(f'[stderr]\n{stderr.decode()}')
    stdout_bytes_io: io.BytesIO = io.BytesIO(bytes.fromhex(stdout.decode()))

    y = ClassgroupElement.parse(stdout_bytes_io)
    proof_bytes: bytes = stdout_bytes_io.read()

    # Verifies our own proof just in case
    proof_blob = ClassGroup.from_ab_discriminant(y.a, y.b, disc).serialize() + proof_bytes
    x = ClassGroup.from_ab_discriminant(2, 1, disc)
    assert check_proof_of_time_nwesolowski(disc, x, proof_blob, proof_of_space_info.iterations_needed, 1024, 3)

    output = ProofOfTimeOutput(proof_of_space_info.challenge_hash,
                               proof_of_space_info.iterations_needed,
                               ClassgroupElement(y.a, y.b))
    proof_of_time = ProofOfTime(output, n_wesolowski, [uint8(b) for b in proof_bytes])
    response = timelord_protocol.ProofOfTimeFinished(proof_of_time)

    yield OutboundMessage("full_node", "proof_of_time_finished", response, True, True)
