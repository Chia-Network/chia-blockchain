from dataclasses import dataclass

from src.util.ints import int512
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class ClassgroupElement(Streamable):
    a: int512
    b: int512
