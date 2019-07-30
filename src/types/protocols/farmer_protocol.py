from blspy import PrependSignature
from src.util.streamable import streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32
from src.types.proof_of_space import ProofOfSpace
from src.types.coinbase import CoinbaseInfo


@streamable
class ProofOfSpaceFinalized:
    challenge_hash: bytes32
    height: uint32
    quality: bytes32


@streamable
class ProofOfSpaceArrived:
    height: uint32
    quality: bytes32


@streamable
class DeepReorgNotification:
    pass


@streamable
class RequestHeaderHash:
    challenge_hash: bytes32
    coinbase: CoinbaseInfo
    coinbase_signature: PrependSignature
    fees_target_puzzle_hash: bytes32
    proof_of_space: ProofOfSpace


@streamable
class HeaderHash:
    pos_hash: bytes32
    header_hash: bytes32


@streamable
class HeaderSignature:
    pos_hash: bytes32
    header_hash: bytes32
    header_signature: PrependSignature


@streamable
class ProofOfTimeRate:
    pot_estimate_ips: uint64
