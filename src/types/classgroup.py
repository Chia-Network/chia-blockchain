from src.util.streamable import streamable, Streamable
from src.util.ints import int1024
from dataclasses import dataclass


@dataclass(frozen=True)
@streamable
class ClassgroupElement(Streamable):
    a: int1024
    b: int1024
