from blspy import PublicKey, PrependSignature
from ..util.streamable import streamable
from .sized_bytes import bytes32
from ..util.ints import uint8, uint32
from .proof_of_space import ProofOfSpace


@streamable
class CreatePlot:
    size: uint8
    pool_pubkey: PublicKey
    filename: bytes

    @classmethod
    def parse(cls, f):
        return cls(uint8.parse(f), PublicKey.from_bytes(f.read(PublicKey.PUBLIC_KEY_SIZE)), f.read())


@streamable
class PlotterHandshake:
    pool_pk: PublicKey

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
    block_hash: bytes32


@streamable
class ProofOfSpaceResponse:
    proof: ProofOfSpace
    block_hash: bytes32
    block_hash_signature: PrependSignature
    proof_of_possession: PrependSignature
