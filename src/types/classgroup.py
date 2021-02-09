from dataclasses import dataclass

from src.consensus.constants import ConsensusConstants
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class ClassgroupElement(Streamable):
    data: bytes

    @staticmethod
    def get_default_element():
        # Bit 3 in the first byte of serialized compressed form indicates if
        # it's the default generator element.
        return ClassgroupElement(b"\x08")

    @staticmethod
    def get_bad_element(constants: ConsensusConstants):
        # Used by test_blockchain to check that bad VDF outputs and proofs are
        # rejected. Use the default element for simplicity.
        return ClassgroupElement(b"\x08")

    @staticmethod
    def get_size(constants: ConsensusConstants):
        return (constants.DISCRIMINANT_SIZE_BITS + 31) // 32 * 3 + 4
