from __future__ import annotations

import functools
import logging
from inspect import signature
from typing import Any, Callable, Coroutine, List, Optional, Union, get_type_hints

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message
from chia.server.ws_connection import WSChiaConnection
from chia.util.streamable import Streamable, _T_Streamable

log = logging.getLogger(__name__)

converted_api_f_type = Union[
    Callable[[Union[bytes, _T_Streamable]], Coroutine[Any, Any, Optional[Message]]],
    Callable[[Union[bytes, _T_Streamable], WSChiaConnection], Coroutine[Any, Any, Optional[Message]]],
]

initial_api_f_type = Union[
    Callable[[Any, _T_Streamable], Coroutine[Any, Any, Optional[Message]]],
    Callable[[Any, _T_Streamable, WSChiaConnection], Coroutine[Any, Any, Optional[Message]]],
]


def api_request(f: initial_api_f_type) -> converted_api_f_type:  # type: ignore
    annotations = get_type_hints(f)
    sig = signature(f)

    @functools.wraps(f)
    def f_substitute(*args, **kwargs) -> Any:  # type: ignore
        binding = sig.bind(*args, **kwargs)
        binding.apply_defaults()
        inter = dict(binding.arguments)

        # Converts each parameter from a Python dictionary, into an instance of the object
        # specified by the type annotation (signature) of the function that is being called (f)
        # The method can also be called with the target type instead of a dictionary.
        for param_name, param_class in annotations.items():
            if param_name != "return" and isinstance(inter[param_name], Streamable):
                if param_class.__name__ == "bytes":
                    continue
                if hasattr(f, "bytes_required"):
                    inter[f"{param_name}_bytes"] = bytes(inter[param_name])
                    continue
            if param_name != "return" and isinstance(inter[param_name], bytes):
                if param_class.__name__ == "bytes":
                    continue
                if hasattr(f, "bytes_required"):
                    inter[f"{param_name}_bytes"] = inter[param_name]
                inter[param_name] = param_class.from_bytes(inter[param_name])
        return f(**inter)  # type: ignore

    setattr(f_substitute, "api_function", True)
    return f_substitute


def peer_required(func: Callable[..., Any]) -> Callable[..., Any]:
    def inner() -> Callable[..., Any]:
        setattr(func, "peer_required", True)
        return func

    return inner()


def bytes_required(func: Callable[..., Any]) -> Callable[..., Any]:
    def inner() -> Callable[..., Any]:
        setattr(func, "bytes_required", True)
        return func

    return inner()


def execute_task(func: Callable[..., Any]) -> Callable[..., Any]:
    def inner() -> Callable[..., Any]:
        setattr(func, "execute_task", True)
        return func

    return inner()


def reply_type(prot_type: List[ProtocolMessageTypes]) -> Callable[..., Any]:
    def wrap(func: Callable[..., Any]) -> Callable[..., Any]:
        def inner() -> Callable[..., Any]:
            setattr(func, "reply_type", prot_type)
            return func

        return inner()

    return wrap
