from dataclasses import dataclass

from src.util.ints import int1024
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class ClassgroupElement(Streamable):
    a: int1024
    b: int1024
