from dataclasses import dataclass

from src.consensus.constants import ConsensusConstants
from src.types.sized_bytes import bytes100
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class ClassgroupElement(Streamable):
    data: bytes100

    @staticmethod
    def from_bytes(data):
        if len(data) < 100:
            data += b"\x00" * (100 - len(data))
        return ClassgroupElement(bytes(data))

    @staticmethod
    def get_default_element():
        # Bit 3 in the first byte of serialized compressed form indicates if
        # it's the default generator element.
        return ClassgroupElement.from_bytes(b"\x08")

    @staticmethod
    def get_bad_element(constants: ConsensusConstants):
        # Used by test_blockchain to check that bad VDF outputs and proofs are
        # rejected. Use the default element for simplicity.
        return ClassgroupElement.get_default_element()

    @staticmethod
    def get_size(constants: ConsensusConstants):
        return 100
