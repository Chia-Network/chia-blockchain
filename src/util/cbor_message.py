import dataclasses
from typing import Any
from src.util.type_checking import ArgTypeChecker


def cbor_message(tag: int):
    """
    Decorator, converts a class into a data class, which checks all arguments to make sure
    they are the right type.
    """
    def apply_cbor_code(cls: Any):
        cls1 = dataclasses.dataclass(_cls=cls, init=False, frozen=True)
        return type(cls.__name__, (cls1, ArgTypeChecker), {'__tag__': tag})
    return apply_cbor_code

