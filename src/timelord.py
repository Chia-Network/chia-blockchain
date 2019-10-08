import logging
import asyncio
import time
import io
import sys
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
from src.consensus.constants import constants
from src.server.outbound_message import OutboundMessage, Delivery, Message, NodeType

class Database:
    lock: Lock = Lock()
    free_servers = []
    solved_discriminants = []
    active_discriminants: Dict = {}
    done_discriminants = []

log = logging.getLogger(__name__)
config = yaml.safe_load(open("src/config/timelord.yaml", "r"))
db = Database()
db.free_servers.append(8889)

@api_request
async def challenge_start(challenge_start: timelord_protocol.ChallengeStart):
    """
    The full node notifies the timelord node that a new challenge is active, and work
    should be started on it. We can generate a classgroup (discriminant), and start
    a new VDF process here. But we don't know how many iterations to run for, so we run
    forever.
    """            

    disc: int = create_discriminant(challenge_start.challenge_hash, constants["DISCRIMINANT_SIZE_BITS"])

    async with db.lock:
        if challenge_start.challenge_hash in db.done_discriminants:
            log.info("This discriminant was already done..")
            return

    #Wait for a server to become free.
    port = None
    while (port is None):
        async with db.lock:
            if (len(db.free_servers) != 0):
                port = db.free_servers[0]
                db.free_servers = db.free_servers[1:]
                log.info(f"Discriminant {disc} attached to port {port}.")
        #Poll until a server becomes free.
        if (port is None):
            await asyncio.sleep(3)
    
    #TODO(Florin): Handle connection failure (attempt another server)
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
    except Exception as e:
        e_to_str = str(e)
        log.error(f"Connection to VDF server error message: {e_to_str}")

    writer.write((str(len(str(disc))) + str(disc)).encode())
    await writer.drain()

    ok = await reader.readexactly(2)
    assert(ok.decode() == "OK")
    
    log.info("Got handshake with VDF server.")

    async with db.lock:
        db.active_discriminants[challenge_start.challenge_hash] = writer

    #Listen to the server until "STOP" is received.
    while(True):
        data = await reader.readexactly(4)
        if (data.decode() == "STOP"):
            #Server is now available.
            async with db.lock:
                writer.write(b"ACK")
                await writer.drain()
                db.free_servers.append(port)
            break
        else:
            try:
                #This must be a proof, read the continuation.
                proof = await reader.readexactly(1860)
                stdout_bytes_io: io.BytesIO = io.BytesIO(bytes.fromhex(data.decode() + proof.decode()))
                iterations_needed = int.from_bytes(stdout_bytes_io.read(8), "big", signed=True)
                y = ClassgroupElement.parse(stdout_bytes_io)
                proof_bytes: bytes = stdout_bytes_io.read()

                # Verifies our own proof just in case
                proof_blob = ClassGroup.from_ab_discriminant(y.a, y.b, disc).serialize() + proof_bytes
                x = ClassGroup.from_ab_discriminant(2, 1, disc)
                assert check_proof_of_time_nwesolowski(disc, x, proof_blob, iterations_needed, 1024, 2)

                output = ProofOfTimeOutput(challenge_start.challenge_hash,
                                iterations_needed,
                                ClassgroupElement(y.a, y.b))
                proof_of_time = ProofOfTime(output, config['n_wesolowski'], [uint8(b) for b in proof_bytes])
                response = timelord_protocol.ProofOfTimeFinished(proof_of_time)

                log.info(f"Got PoT for challenge {challenge_start.challenge_hash}")
                #async with db.lock:
                #    if (challenge_start.challenge_hash in db.solved_discriminants):
                #        log.info("I've already propagated one proof... Ignoring for now...")
                #        continue
                #    db.solved_discriminants.append(challenge_start.challenge_hash)
                yield OutboundMessage(NodeType.FULL_NODE, Message("proof_of_time_finished", response), Delivery.RESPOND)
            except Exception as e:
                e_to_str = str(e)
                log.error(f"Socket error: {e_to_str}")

            
@api_request
async def challenge_end(challenge_end: timelord_protocol.ChallengeEnd):
    """
    A challenge is no longer active, so stop the process for this challenge, if it
    exists.
    """
    async with db.lock:
        if (challenge_end.challenge_hash in db.done_discriminants):
            return 
        if (challenge_end.challenge_hash in db.active_discriminants):
            writer = db.active_discriminants[challenge_end.challenge_hash]
            writer.write(b'10')
            await writer.drain()
            del db.active_discriminants[challenge_end.challenge_hash]
            db.done_discriminants.append(challenge_end.challenge_hash)
    await asyncio.sleep(0.5)

@api_request
async def proof_of_space_info(proof_of_space_info: timelord_protocol.ProofOfSpaceInfo):
    """
    Notification from full node about a new proof of space for a challenge. If we already
    have a process for this challenge, we should communicate to the process to tell it how
    many iterations to run for. TODO: process should be started in challenge_start instead.
    """

    while (True):
        async with db.lock:
            if (proof_of_space_info.challenge_hash in db.active_discriminants):
                writer = db.active_discriminants[proof_of_space_info.challenge_hash]
                writer.write((str(len(str(proof_of_space_info.iterations_needed))) 
                            + str(proof_of_space_info.iterations_needed)).encode())
                await writer.drain()
                return 
            if (proof_of_space_info.challenge_hash in db.done_discriminants):
                log.info("Got iters for a finished challenge")
                return 
        await asyncio.sleep(0.5)
