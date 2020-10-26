from blspy import G2Element
from src.types.classgroup import ClassgroupElement
from src.types.sized_bytes import bytes32
from src.types.vdf import VDFInfo
from src.types.proof_of_space import ProofOfSpace
from src.types.challenge_slot import ChallengeChainInfusionPoint


def infuse_challenge_chain(infusion_challenge_point: VDFInfo, pos: ProofOfSpace, signature: G2Element) -> bytes32:
    return ChallengeChainInfusionPoint(infusion_challenge_point, pos, signature).get_hash()
