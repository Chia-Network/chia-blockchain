from blspy import PublicKey, PrependSignature
from src.util.streamable import streamable
from src.util.streamable import StreamableList
from src.types.sized_bytes import bytes32
from src.types.proof_of_space import ProofOfSpace


@streamable
class PlotterHandshake:
    pool_pubkeys: StreamableList(PublicKey)


@streamable
class NewChallenge:
    challenge_hash: bytes32


@streamable
class ChallengeResponse:
    challenge_hash: bytes32
    response_id: bytes32
    quality_string: bytes


@streamable
class RequestHeaderSignature:
    response_id: bytes32
    header_hash: bytes32


@streamable
class HeaderSignature:
    response_id: bytes32
    header_hash_signature: PrependSignature
    proof: ProofOfSpace


@streamable
class RequestPartialProof:
    response_id: bytes32
    farmer_target_hash: bytes32


@streamable
class PartialProof:
    response_id: bytes32
    farmer_target_signature: PrependSignature
    proof: ProofOfSpace
