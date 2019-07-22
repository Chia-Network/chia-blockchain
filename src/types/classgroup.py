from ..util.streamable import streamable
from ..util.ints import uint1024


@streamable
class ClassgroupElement:
    a: uint1024
    b: uint1024
