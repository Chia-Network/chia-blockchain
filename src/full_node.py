import logging
from src.util.api_decorators import api_request
from src.types.protocols import farmer_protocol
from src.server.server import ChiaConnection, PeerConnections


# TODO: use config file
full_node_port = 8002
farmer_ip = "127.0.0.1"
farmer_port = 8001


class Database:
    pass


log = logging.getLogger(__name__)
db = Database()


# @streamable
# class RequestBlockHash:
#     challenge: Challenge
#     proof_of_space: ProofOfSpace
#     coinbase_target: CoinbaseInfo
#     coinbase_signature: PrependSignature
#     fees_target: FeeTarget


@api_request(request=farmer_protocol.RequestBlockHash.from_bin)
async def request_block_hash(response: farmer_protocol.RequestBlockHash,
                             source_connection: ChiaConnection,
                             all_connections: PeerConnections):
    p
