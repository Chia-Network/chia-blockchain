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
    quality: bytes32


@streamable
class RequestProofOfSpace:
    quality: bytes32


@streamable
class RespondProofOfSpace:
    quality: bytes32
    proof: ProofOfSpace


@streamable
class RequestHeaderSignature:
    quality: bytes32
    header_hash: bytes32


@streamable
class HeaderSignature:
    quality: bytes32
    header_hash_signature: PrependSignature


@streamable
class RequestPartialProof:
    quality: bytes32
    farmer_target_hash: bytes32


@streamable
class PartialProof:
    quality: bytes32
    farmer_target_signature: PrependSignature
