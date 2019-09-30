import logging
import asyncio
import time
import io
import yaml
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
from src.server.outbound_message import OutboundMessage, Delivery, Message, NodeType


class Database:
    lock: Lock = Lock()
    challenges: Dict = {}
    finished_challenges = []

config = yaml.safe_load(open("src/config/timelord.yaml", "r"))
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
    async with db.lock:
        assert(challenge_start.challenge_hash not in db.challenges)
        disc: int = create_discriminant(challenge_start.challenge_hash, constants.DISCRIMINANT_SIZE_BITS)
        command = (f"./lib/chiavdf/fast_vdf/vdf {disc}")
        log.info(f"Executing VDF process for discriminant: {disc}")
        
        proc = await asyncio.create_subprocess_shell(
        command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE)

        db.challenges[challenge_start.challenge_hash] = (disc, proc)

    while True:      
        output = await proc.stdout.readline()

        # Signal that process finished all challenges.
        if (output.decode() == "0"*100 + "\n"):
            await proc.wait()
            async with db.lock:
                del db.challenges[challenge_start.challenge_hash]
            log.info(f"The process for challenge {challenge_start.challenge_hash} ended")
            return 

        stdout_bytes_io: io.BytesIO = io.BytesIO(bytes.fromhex(output[:-1].decode()))
        iterations_needed = int.from_bytes(stdout_bytes_io.read(8), "big", signed=True)
        y = ClassgroupElement.parse(stdout_bytes_io)
        proof_bytes: bytes = stdout_bytes_io.read()

        # Verifies our own proof just in case
        proof_blob = ClassGroup.from_ab_discriminant(y.a, y.b, disc).serialize() + proof_bytes
        x = ClassGroup.from_ab_discriminant(2, 1, disc)
        #assert check_proof_of_time_nwesolowski(disc, x, proof_blob, iterations_needed, 1024, 2)

        output = ProofOfTimeOutput(challenge_start.challenge_hash,
                               iterations_needed,
                               ClassgroupElement(y.a, y.b))
        proof_of_time = ProofOfTime(output, config['n_wesolowski'], [uint8(b) for b in proof_bytes])
        response = timelord_protocol.ProofOfTimeFinished(proof_of_time)

        log.info(f"Got PoT for challenge {challenge_start.challenge_hash}")
        yield OutboundMessage(NodeType.FULL_NODE, Message("proof_of_time_finished", response), Delivery.RESPOND)

@api_request
async def challenge_end(challenge_end: timelord_protocol.ChallengeEnd):
    """
    A challenge is no longer active, so stop the process for this challenge, if it
    exists.
    """
    async with db.lock:
        if challenge_end.challenge_hash not in db.finished_challenges:
            _, proc = db.challenges[challenge_end.challenge_hash]
            #I'm no longer accepting new challenges, process will finish everything else smoothly.
            proc.stdin.write(b'0\n')
            await proc.stdin.drain()
            db.finished_challenges.append(challenge_end.challenge_hash)
        else:
            log.info("Trying to close the challenge multiple times..")

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
        assert(proof_of_space_info.challenge_hash not in db.finished_challenges)
        _, proc = db.challenges[proof_of_space_info.challenge_hash]
        proc.stdin.write((str(proof_of_space_info.iterations_needed) + "\n").encode())
        await proc.stdin.drain()