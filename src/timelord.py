import logging
from asyncio import Lock
from typing import Dict
import time
from src.util.api_decorators import api_request
from src.server.chia_connection import ChiaConnection
from src.server.peer_connections import PeerConnections
from src.protocols import timelord_protocol
from src.types.proof_of_time import ProofOfTimeOutput, ProofOfTime
from src.types.classgroup import ClassgroupElement
from src.util.ints import uint8
from src.consensus import constants
from lib.chiavdf.inkfish.create_discriminant import create_discriminant
from lib.chiavdf.inkfish.classgroup import ClassGroup
from lib.chiavdf.inkfish.proof_of_time import create_proof_of_time_nwesolowski

# TODO: use config file
timelord_port = 8003
full_node_ip = "127.0.0.1"
full_node_port = 8002
iterations_per_sec = 3000
n_wesolowski = 3


class Database:
    lock: Lock = Lock()
    challenges: Dict = {}


log = logging.getLogger(__name__)
db = Database()


@api_request
async def challenge_start(challenge_start: timelord_protocol.ChallengeStart,
                          source_connection: ChiaConnection,
                          all_connections: PeerConnections):
    async with db.lock:
        disc: int = create_discriminant(challenge_start.challenge_hash, constants.DISCRIMINANT_SIZE_BITS)
        db.challenges[challenge_start.challenge_hash] = (time.time(), disc)
        # TODO: Start a VDF process


async def challenge_end(challenge_end: timelord_protocol.ChallengeEnd,
                        source_connection: ChiaConnection,
                        all_connections: PeerConnections):
    # TODO: Stops all running VDF processes for this challenge
    pass


async def proof_of_space_info(proof_of_space_info: timelord_protocol.ProofOfSpaceInfo,
                              source_connection: ChiaConnection,
                              all_connections: PeerConnections):
    async with db.lock:
        if proof_of_space_info.challenge_hash not in db.challenges:
            log.warn(f"Have not seen challenge {proof_of_space_info.challenge_hash} yet.")
            return
        time_recvd, disc = db.challenges[proof_of_space_info.challenge_hash]
        start_x: ClassGroup = ClassGroup.from_ab_discriminant(2, 1, disc)
    y_bytes, proof_bytes = create_proof_of_time_nwesolowski(disc, start_x,
                                                            proof_of_space_info.iterations_needed,
                                                            constants.DISCRIMINANT_SIZE_BITS, n_wesolowski)
    y = ClassGroup.from_bytes(y_bytes, disc)
    output = ProofOfTimeOutput(proof_of_space_info.challenge_hash,
                               proof_of_space_info.iterations_needed,
                               ClassgroupElement(y[0], y[1]))
    proof_of_time = ProofOfTime(output, n_wesolowski, [uint8(b) for b in proof_bytes])
    response = timelord_protocol.ProofOfTimeFinished(proof_of_time)

    await source_connection.send("proof_of_time_finished", response)

    # TODO: tell VDF process how many iterations there are
    # TODO: make this async
