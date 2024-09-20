from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Type, TypeVar, Union, get_type_hints

from typing_extensions import Concatenate, ParamSpec

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.util.streamable import Streamable

log = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")
S = TypeVar("S", bound=Streamable)
Self = TypeVar("Self")


metadata_attribute_name = "_chia_api_metadata"


@dataclass
class ApiMetadata:
    request_type: ProtocolMessageTypes
    message_class: Type[Streamable]
    peer_required: bool = False
    bytes_required: bool = False
    execute_task: bool = False
    reply_types: List[ProtocolMessageTypes] = field(default_factory=list)


def get_metadata(function: Callable[..., object]) -> Optional[ApiMetadata]:
    return getattr(function, metadata_attribute_name, None)


def _set_metadata(function: Callable[..., object], metadata: ApiMetadata) -> None:
    setattr(function, metadata_attribute_name, metadata)


# TODO: This hinting does not express that the returned callable *_bytes parameter
#       corresponding to the first parameter name will be filled in by the wrapper.
def api_request(
    peer_required: bool = False,
    bytes_required: bool = False,
    execute_task: bool = False,
    reply_types: Optional[List[ProtocolMessageTypes]] = None,
) -> Callable[[Callable[Concatenate[Self, S, P], R]], Callable[Concatenate[Self, Union[bytes, S], P], R]]:
    non_optional_reply_types: List[ProtocolMessageTypes]
    if reply_types is None:
        non_optional_reply_types = []
    else:
        non_optional_reply_types = reply_types

    def inner(f: Callable[Concatenate[Self, S, P], R]) -> Callable[Concatenate[Self, Union[bytes, S], P], R]:
        @functools.wraps(f)
        def wrapper(self: Self, original: Union[bytes, S], *args: P.args, **kwargs: P.kwargs) -> R:
            arg: S
            if isinstance(original, bytes):
                if metadata.bytes_required:
                    kwargs[message_name_bytes] = original
                arg = message_class.from_bytes(original)
            else:
                arg = original
                if metadata.bytes_required:
                    kwargs[message_name_bytes] = bytes(original)

            return f(self, arg, *args, **kwargs)

        message_name, message_class = next(
            (name, hint) for name, hint in get_type_hints(f).items() if name not in {"self", "peer", "return"}
        )
        message_name_bytes = f"{message_name}_bytes"

        metadata = ApiMetadata(
            request_type=getattr(ProtocolMessageTypes, f.__name__),
            peer_required=peer_required,
            bytes_required=bytes_required,
            execute_task=execute_task,
            reply_types=non_optional_reply_types,
            message_class=message_class,
        )

        _set_metadata(function=wrapper, metadata=metadata)

        return wrapper

    return inner
