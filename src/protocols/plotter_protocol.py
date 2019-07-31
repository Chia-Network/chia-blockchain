from blspy import PublicKey, PrependSignature
from src.util.cbor_message import cbor_message
from src.util.streamable import List
from src.types.sized_bytes import bytes32
from src.types.proof_of_space import ProofOfSpace


@cbor_message(tag=1000)
class PlotterHandshake:
    pool_pubkeys: List[PublicKey]


@cbor_message(tag=1001)
class NewChallenge:
    challenge_hash: bytes32


@cbor_message(tag=1002)
class ChallengeResponse:
    challenge_hash: bytes32
    quality: bytes32


@cbor_message(tag=1003)
class RequestProofOfSpace:
    quality: bytes32


@cbor_message(tag=1004)
class RespondProofOfSpace:
    quality: bytes32
    proof: ProofOfSpace


@cbor_message(tag=1005)
class RequestHeaderSignature:
    quality: bytes32
    header_hash: bytes32


@cbor_message(tag=1006)
class RespondHeaderSignature:
    quality: bytes32
    header_hash_signature: PrependSignature


@cbor_message(tag=1007)
class RequestPartialProof:
    quality: bytes32
    farmer_target_hash: bytes32


@cbor_message(tag=1008)
class RespondPartialProof:
    quality: bytes32
    farmer_target_signature: PrependSignature
