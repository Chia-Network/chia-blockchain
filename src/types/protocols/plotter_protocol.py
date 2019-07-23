from blspy import PublicKey, InsecureSignature
from src.util.streamable import streamable
from src.util.ints import uint32
from src.types.sized_bytes import bytes32
from src.types.proof_of_space import ProofOfSpace


@streamable
class PlotterHandshake:
    pool_pubkey: PublicKey

    @classmethod
    def parse(cls, f):
        return cls(PublicKey.from_bytes(f.read(PublicKey.PUBLIC_KEY_SIZE)))


@streamable
class NewChallenge:
    challenge_hash: bytes32


@streamable
class ChallengeResponse:
    challenge_hash: bytes32
    response_id: uint32
    quality: bytes


@streamable
class RequestProofOfSpace:
    challenge_hash: bytes32
    response_id: uint32
    block_hash: bytes32


@streamable
class ProofOfSpaceResponse:
    block_hash: bytes32
    block_hash_signature_share: InsecureSignature
    proof: ProofOfSpace

    @classmethod
    def parse(cls, f):
        return cls(f.read(32),
                   InsecureSignature.from_bytes(f.read(InsecureSignature.SIGNATURE_SIZE)),
                   f.read())
