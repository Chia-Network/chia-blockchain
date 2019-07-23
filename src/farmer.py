import logging
from typing import List
from blspy import PrivateKey
from src.util.api_decorators import api_request
from src.types.protocols import plotter_protocol
from src.server.server import ChiaConnection
import secrets
from hashlib import sha256


log = logging.getLogger(__name__)

farmer_sk = PrivateKey.from_seed(secrets.token_bytes(32))


@api_request(challenge_response=plotter_protocol.ChallengeResponse.from_bin)
async def challenge_response(challenge_response: plotter_protocol.ChallengeResponse,
                             source_connection: ChiaConnection,
                             all_connections: List[ChiaConnection] = []):
    log.info(f"Called challenge_response {challenge_response}")

    quality = int.from_bytes(sha256(challenge_response.quality).digest(), "big")

    # TODO: Calculate the number of iterations using the difficulty, and compare to block time
    if quality < (2 ** 255):
        print("Good quality")
        # TODO: lookup the actual block hash
        block_hash = secrets.token_bytes(32)
        request = plotter_protocol.RequestProofOfSpace(challenge_response.challenge_hash,
                                                       challenge_response.response_id,
                                                       block_hash)
        await source_connection.send("request_proof_of_space", request)
