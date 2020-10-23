from dataclasses import dataclass

from src.util.ints import int512
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class ClassgroupElement(Streamable):
    a: int512
    b: int512

    @staticmethod
    def get_default_element():
        return ClassgroupElement(int512(2), int512(1))
