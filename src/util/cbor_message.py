from typing import Any, Type
from src.util.type_checking import strictdataclass


def cbor_message(tag: int):
    """
    Decorator, converts a class into a data class, which checks all arguments to make sure
    they are the right type.
    """
    def apply_cbor_code(cls: Any) -> Type:
        cls1 = strictdataclass(cls=cls)
        return type(cls.__name__, (cls1,), {'__tag__': tag})
    return apply_cbor_code
