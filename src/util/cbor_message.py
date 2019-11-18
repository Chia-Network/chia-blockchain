from typing import Any, Type

from src.util.type_checking import strictdataclass


def cbor_message(cls: Any) -> Type:
    """
    Decorator, converts a class into a strictdataclass, which checks all arguments to make sure
    they are the right type.
    """
    cls1 = strictdataclass(cls=cls)
    return type(cls.__name__, (cls1,), {"__cbor_message__": True})
